"""Room-key join and LAN-IP connect flow. Functions take the bridge instance."""
from __future__ import annotations
import asyncio
import time

from .. import launcher as core
from ..netcore.timing_log import mark as timing_mark, failure as timing_failure
from ..netcore.errors import Code, JoinBudget, JoinError, Stage, as_join_error


async def request_room_admission(bridge, beacon):
    from ..netcore.admission import AdmissionAccess, request_admission

    identity = await asyncio.to_thread(bridge._host_identity, "client_admission_identity.json")
    queue = asyncio.Queue()
    bridge._room_password_input = queue
    name = bridge.config_data.get("player_name", "Player")
    host = beacon.get("pc_name") or "Host"
    player_id = bridge.config_data["player_id"]
    request_id = None
    password = None
    action = "join"
    status = None

    def prompt(status="", waiting=False):
        bridge.after(0, bridge._set_room_password_prompt,
                     {"name": host, "status": status, "waiting": waiting, "busy": False})

    try:
        while not bridge._closing:
            result = await request_admission(beacon, player_id, name, identity=identity,
                                             password=password, request_id=request_id, action=action)
            password = None
            status = result["status"]
            request_id = result.get("request_id") or request_id
            if status == "allowed" and queue.empty() and not bridge._closing:
                return AdmissionAccess.from_result(beacon, result)
            if status == "pending":
                prompt("Waiting for host approval…", waiting=True)
                try:
                    await asyncio.wait_for(queue.get(), timeout=1.5)
                except asyncio.TimeoutError:
                    action = "poll"
                    continue
                break
            messages = {
                "password_required": "",
                "wrong_password": "Incorrect password. Try again.",
                "rate_limited": "Too many attempts too quickly. Wait a moment and try again.",
            }
            if status not in messages:
                if status == "allowed":
                    break
                message = {
                    "denied": "The host denied this PC access to the room.",
                    "version_mismatch": "Launcher version mismatch. Install the same release on both PCs.",
                    "expired": "Host approval expired. Try joining again.",
                    "cancelled": "Room join cancelled.",
                    "busy": "The host is handling too many join requests. Try again shortly.",
                }.get(status, "The host could not verify this join request.")
                raise JoinError(Stage.ROOM_KEY, "E_ADMISSION", message)
            prompt(messages[status])
            try:
                password = await asyncio.wait_for(queue.get(), timeout=120)
            except asyncio.TimeoutError:
                break
            if password is None:
                break
            action = "join"
        raise JoinError(Stage.ROOM_KEY, "E_ADMISSION_CANCELLED", "Room join cancelled.")
    finally:
        bridge._room_password_input = None
        bridge.after(0, bridge._set_room_password_prompt, None)
        if request_id and status == "pending":
            try:
                await request_admission(beacon, player_id, name, identity=identity,
                                        request_id=request_id, action="cancel")
            except (OSError, ValueError, asyncio.TimeoutError):
                pass


async def bind_room_admission(bridge, beacon, access):
    from ..netcore.admission import request_admission

    overlay_beacon = {**beacon, "host": beacon["host_zt"]}
    identity = await asyncio.to_thread(bridge._host_identity, "client_admission_identity.json")
    for attempt in range(4):
        try:
            result = await request_admission(
                overlay_beacon, bridge.config_data["player_id"],
                bridge.config_data.get("player_name", "Player"),
                identity=identity, action="bind", token=access.token)
        except (OSError, asyncio.TimeoutError):
            result = {"status": "busy"}
        if result["status"] == "allowed":
            return
        if result["status"] != "busy":
            break
        if attempt < 3:
            await asyncio.sleep(1)
    raise JoinError(Stage.VLA_JOIN, "E_ADMISSION", "The host could not activate access to the room network.")


async def join_room_key(bridge, network_id):
    from ..netcore.discovery import fetch_room_when_ready
    started = time.monotonic()
    budget = JoinBudget(total=90, floor=15)
    phase = 'vla_approval'
    try:
        await asyncio.to_thread(bridge._recover_network_session)
        await asyncio.to_thread(bridge.tunnel.begin_join, network_id)
        status = await asyncio.to_thread(bridge.tunnel.wait_connected, network_id, budget.slice(60))
        if not status.connected:
            raise JoinError(Stage.VLA_JOIN, Code.VLA_NOT_CONNECTED, status.message,
                            'Ask the Host to approve this PC in VLA, then retry.')
        timing_mark('room_key.vla_ready', started, 'address_assigned')
        phase = 'host_metadata'
        bridge.after(0, bridge.pages['room'].set_status,
                     'VLA connected. Waiting for Host room details… retrying automatically.')
        # An assigned address does not guarantee the internet path is ready.
        # Like BFBC2's lobby reporter, retry without leaving/rejoining VLA.
        beacon = await fetch_room_when_ready(status.host_ip, timeout=budget.slice(60))
        if str(beacon.get('net_id', '')).lower() != network_id:
            raise JoinError(Stage.ROOM_KEY, Code.ROOM_MISMATCH,
                            'The Host returned a different room. Check the room key.',
                            'Re-enter the room key shown on the Host.')
        from ..netcore import compat
        from .._version import __version__ as _my_version, __proto__ as _my_proto
        _ok, level, message, hint = compat.check(str(beacon.get('version', '') or ''),
                                                 compat.proto_of(beacon), _my_version, _my_proto)
        if level == compat.BLOCK:
            offer = getattr(bridge, '_offer_host_version', None)
            if offer:
                bridge.after(0, offer, dict(beacon, host=status.host_ip), message, True)
            raise JoinError(Stage.BEACON, Code.BEACON_INVALID, message, hint)
        if level == compat.WARN:
            bridge.after(0, bridge.pages['room'].set_status, message)
        # A typed key works through VLA, including when the Host's physical
        # LAN address is unreachable. The signed Host identity is retained.
        beacon = {**beacon, 'host': status.host_ip}
        pinned = getattr(bridge, 'trusted_host_pub', None)
        if not pinned or beacon.get('host_pub') == pinned:  # same guard as _beacon_seen (audit A06)
            bridge.last_beacon = beacon
        phase = 'host_setup'
        if beacon.get('admission') or (pinned and beacon.get('host_pub') != pinned):
            await bridge._join_beacon_room(beacon, allow_host_switch=True, report_error=False)
            timing_mark('room_key.join', started, 'connected')
            return
        # Retry only the Host setup step (E_HOST_SETUP). Not the firewall/UAC step,
        # which would prompt the user again on every retry.
        for attempt in range(3):
            await bridge._join_beacon_room(beacon)
            if bridge.room:
                break
            if attempt < 2:
                bridge.after(0, bridge.pages['room'].set_status,
                             f'Host setup did not finish. Retrying ({attempt + 2}/3)…')
                await asyncio.sleep(2 * (attempt + 1))
        if not bridge.room:
            raise JoinError(Stage.HOST_SETUP, Code.HOST_SETUP,
                            'The room network connected, but Host setup did not finish. Retry the room key.',
                            'Retry the room key; keep the Host room open.')
        timing_mark('room_key.join', started, 'connected')
    except Exception as exc:
        timing_mark('room_key.join', started, timing_failure(exc, f'{phase}:'))
        if not await asyncio.to_thread(core._other_launcher_running, bridge.role):
            await asyncio.to_thread(bridge.tunnel._leave_quiet, network_id)
        stage = {'vla_approval': Stage.VLA_JOIN, 'host_metadata': Stage.BEACON,
                 'host_setup': Stage.HOST_SETUP}.get(phase, Stage.UNKNOWN)
        typed = as_join_error(exc, stage)
        if typed is exc:
            raise
        raise typed from exc


def _auto_diagnostic_after_failure():
    """Save a diagnostic report in the background after a failed join, so support
    has it without the user having to press Run diagnostic."""
    import threading
    from pathlib import Path as _Path

    def run():
        try:
            from ..diagnostics.service import run_and_save
            folder = _Path(core.APP_DIR) / 'diagnostics'
            folder.mkdir(parents=True, exist_ok=True)
            result = run_and_save(folder)
            path = result.get('path', '') if isinstance(result, dict) else ''
            with open(_Path(core.APP_DIR) / 'room-errors.log', 'a', encoding='utf-8') as log:
                log.write(f'Diagnostic saved after failed join: {path or folder}\n')
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()


def room_key_finished(bridge, future):
    bridge.busy = False
    bridge._beacon_joining = False
    try:
        future.result()
    except Exception as exc:
        core.LauncherCore._log_room_error(exc)
        _auto_diagnostic_after_failure()
        typed = as_join_error(exc)
        detail = typed.message
        bridge._status = 'Could not join the room: ' + detail
        bridge.ui_message('showerror', 'Room key join failed', detail,
                          stage=typed.stage.value, code=typed.code, hint=typed.hint)
    bridge.publish()


def connect_host_ip(bridge, address):
    from ..netcore.discovery import fetch_room
    async def fetch():
        return await fetch_room(address.strip())
    def work():
        return bridge.runtime.submit(fetch()).result(timeout=7)
    def ready(beacon):
        # Same compatibility gate as the typed-key join path.
        from ..netcore import compat
        from .._version import __version__ as _my_version, __proto__ as _my_proto
        _ok, level, message, hint = compat.check(str(beacon.get('version', '') or ''),
                                                 compat.proto_of(beacon), _my_version, _my_proto)
        if level == compat.BLOCK:
            offer = getattr(bridge, '_offer_host_version', None)
            if offer:
                bridge.after(0, offer, beacon, message, True)
            bridge.after(0, bridge._connect_blocked, message, hint)
            return
        if level == compat.WARN:
            bridge.after(0, bridge.pages['room'].set_status, message)
        bridge._paused_admission_room = None
        bridge.runtime.loop.call_soon_threadsafe(
            lambda: bridge._beacon_seen(beacon, allow_host_switch=True))
    bridge._run_background(work, ready, 'Contacting the host by LAN IP…')
