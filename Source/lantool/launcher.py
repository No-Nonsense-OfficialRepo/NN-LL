"""LAN Tool desktop shell and integration entry point.

Start from the project directory with ``python -m lantool.launcher`` for the
Client or add ``--host`` for the Host. Hosts broadcast signed room beacons and
serve moons, game manifests, and game files. Clients discover the host, join
ZeroTier, switch adapter metrics, and sync games from its repository.
"""
from __future__ import annotations

import asyncio
import base64
import csv
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import Future
import concurrent.futures
from concurrent.futures.thread import ThreadPoolExecutor

# Python 3.15 exports this through a lazy import. In frozen builds the
# unresolved proxy can escape module lookup and asyncio cannot call it.
# Bind the concrete class before asyncio creates its default worker pool.
# Scoped to frozen builds (audit A18) so a normal run does not patch the stdlib.
if getattr(sys, "frozen", False):
    concurrent.futures.ThreadPoolExecutor = ThreadPoolExecutor

from pathlib import Path
from types import SimpleNamespace
from .ui.dialogs import filedialog, messagebox

from silent_tunnel import Tunnel, CONNECTED, format_room_code
from silent_tunnel.moon import install_moon
from silent_tunnel.store import data_dir as tunnel_data_dir

from .manifests.loader import validate
from .game_directory import game_id_for, load_catalog, save_catalog, find_game_folder, assign_client_folders
from .trust.freshness import SESSION as FRESHNESS, StaleError
from .presence.client import PresenceClient
from .presence.server import PresenceServer
from .filesync.client import sync_game
from .filesync.server import FileSyncServer
from .filesync.client import fetch_art
from .filesync.peer import PeerFileServer
from .filesync.activity import ActivityTracker
from .netcore.adapter import AdapterSwitcher
from .netcore.beacon import BeaconListener
from .netcore.controller import RoomController
from .netcore.errors import Code, JoinError, Stage, as_join_error
from .netcore.host_room import HostRoom
from .netcore.zt_adapter import SilentTunnelZT
from .trust import signing as signing
from .trust.bundle import create_bundle, load_bundle
from .netcore.moon_sync import MoonSync
from .netcore.timing_log import mark as timing_mark, failure as timing_failure
from ._version import __version__, __release__


from .appdirs import default_app_dir as _default_app_dir
APP_DIR = _default_app_dir()
CONFIG_PATH = APP_DIR / "launcher.json"
ZT_OWNERSHIP_FILE = APP_DIR / "vla-installed-by-lantool"
from .role import detect_role as _detect_role
HOST_ROLE = _detect_role()


def _resource_path(relative: str) -> Path:
    """Resolve immutable files from source or from a PyInstaller bundle."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / relative


LIBRARY_ROOT = _resource_path("games")
GAME_FILES_ROOT = (Path(sys.executable).resolve().parent / "Game Directory"
                   if getattr(sys, "frozen", False)
                   else Path(__file__).resolve().parents[1] / "game_files")


def _lan_ip():
    """Ask Windows routing which local IPv4 address it would use on the LAN."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def _format_room(network_id):
    return format_room_code(network_id)


def _other_launcher_running(role: str) -> bool:
    """Check whether the other packaged role is running on this Windows PC.

    If Windows won't let us inspect the process list, preserve ZeroTier rather
    than risk uninstalling it while the other role may still need it.
    """
    from .single_instance import already_running
    other_role = "client" if role == "host" else "host"
    # Older releases can still be using the shared driver without the role lock.
    return already_running(other_role) or _launcher_process_running(f"lan {other_role} ")


def _launcher_process_running(prefix: str, *, exclude_self: bool = False) -> bool:
    """True when a ``<prefix>*.exe`` process is running on this Windows PC (audit A19).

    A process list that cannot be read counts as running, so callers preserve shared state.
    ``exclude_self`` ignores this process's own pid.
    """
    if os.name != "nt":
        return False
    own_pid = str(os.getpid())
    try:
        result = subprocess.run(["tasklist.exe", "/FO", "CSV", "/NH"],
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0:
            return True
        for row in csv.reader(result.stdout.splitlines()):
            if not row:
                continue
            name = row[0].casefold()
            if not (name.startswith(prefix) and name.endswith(".exe")):
                continue
            if exclude_self and len(row) > 1 and row[1].strip() == own_pid:
                continue
            return True
        return False
    except (OSError, subprocess.SubprocessError, csv.Error):
        return True


def _same_role_launcher_running(role):
    """Preserve a room still owned by an older duplicate without the new lock."""
    return _launcher_process_running('lan ' + role + ' ', exclude_self=True)


ROOM_ERROR_LOG_LIMIT = 1024 * 1024  # bytes; room-errors.log is rotated to room-errors.log.1 past this

# Shutdown limits (seconds): per step, for the slower network cleanup, and for the whole close.
from . import timeouts as _timeouts
SHUTDOWN_STEP_TIMEOUT = _timeouts.load(APP_DIR)['shutdown_step']
CLEANUP_STEP_TIMEOUT = _timeouts.load(APP_DIR)['cleanup_step']
CLOSE_DEADLINE = _timeouts.load(APP_DIR)['close_deadline']
NETWORK_WAIT = _timeouts.load(APP_DIR)['network_wait']


def submit_drained(loop, coroutine):
    """Request task cancellation without announcing completion before cleanup."""
    class DrainedFuture(Future):
        def cancel(self):
            if self.done():
                return False
            loop.call_soon_threadsafe(request_cancel)
            return True

    future = DrainedFuture()
    task = None
    cancel_requested = False

    def request_cancel():
        nonlocal cancel_requested
        if cancel_requested:
            return  # repeated cancellation must not interrupt finally cleanup
        cancel_requested = True
        if task is not None:
            task.cancel()

    def finished(done):
        if done.cancelled():
            Future.cancel(future)
        else:
            error = done.exception()
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(done.result())

    def start():
        nonlocal task
        task = loop.create_task(coroutine)
        task.add_done_callback(finished)
        if cancel_requested:
            task.cancel()

    loop.call_soon_threadsafe(start)
    return future


class AsyncLoopThread:
    """Own the asyncio networking clients while the Qt UI owns the main thread."""
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="lantool-asyncio", daemon=True)
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            # All cooperative disk jobs have released their files. Join the
            # executor too: its non-daemon threads otherwise outlive the UI.
            self.loop.run_until_complete(self.loop.shutdown_default_executor())
            self.loop.close()

    def submit(self, coro) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self, timeout=2):
        if not self.loop.is_closed():
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except RuntimeError:
                if not self.loop.is_closed():
                    raise
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=timeout)


def _read_config() -> dict:
    from .config_store import read
    return read(CONFIG_PATH)


def _write_config(value: dict):
    from .config_store import write
    write(CONFIG_PATH, value)


class LauncherCore:
    """Shared room, trust, sync and process logic; presentation is supplied by a UI adapter."""

    def _init_backend(self):
        self.role = HOST_ROLE
        timing_mark("app.started", outcome=self.role)
        self.game_root = GAME_FILES_ROOT
        self.host_catalog_path = APP_DIR / "host_games.json"
        self.host_art_root = APP_DIR / "host_art"
        self.client_art_root = APP_DIR / "client_art"
        self.seeded_games: set[str] = set()
        self.seeded_files: dict[str, list[str]] = {}
        self.received_activity = ActivityTracker()  # bytes received per (source host:port, game), for the Downloads page
        self.peer_sources: list[dict] = []
        self.peer_file_server = None
        self.pc_name = socket.gethostname()
        self.config_data = {"player_name": "Player", "uninstall_on_exit": False, **_read_config()}
        if self.role == "client" and self.config_data.get("game_directory"):
            self.game_root = Path(self.config_data["game_directory"])
        if not self.config_data.get("player_id"):
            self.config_data["player_id"] = uuid.uuid4().hex
            _write_config(self.config_data)
        tunnel_state = APP_DIR / "vla-state" / self.role
        self.tunnel = Tunnel(home=tunnel_state, ownership_file=ZT_OWNERSHIP_FILE,
                             settings_file=tunnel_data_dir() / "settings.json",
                             progress=lambda message: self.after(0, self.pages["room"].set_status, message),
                             authorizer_interval=1.0, poll_interval=0.4)
        self.runtime = AsyncLoopThread()
        self.room = None
        self.presence_server = None
        self.host_presence_player_id = None
        self.presence_client = None
        self.process_watcher = None
        self.host_room = None
        self.file_sync_server = None
        self.file_sync_prewarm_task = None
        self.beacon_transport = None
        self.host_conflict_transport = None
        self._reported_hosts = set()
        self.room_controller = None
        self.discovery_task = None
        self.library_refresh_task = None
        self.trusted_host_pub = self.config_data.get("trusted_host_pub")
        self.client_moon_sync = None
        self.last_beacon = None
        self.client_bundle = None
        self._beacon_joining = False
        self._discovery_listening_since = None
        sidecar_bundle = (Path(sys.executable).resolve().parent / "client_bundle.json"
                          if getattr(sys, "frozen", False) else None)
        embedded_bundle = _resource_path("client_bundle.json")
        auto_bundle = (sidecar_bundle if sidecar_bundle and sidecar_bundle.is_file()
                       else embedded_bundle if getattr(sys, "frozen", False) and embedded_bundle.is_file()
                       else None)
        self._load_trusted_bundle(auto_bundle)
        FRESHNESS.bind(APP_DIR / "freshness.json", self.trusted_host_pub)
        self.busy = False
        self.syncing_game = False
        self._sync_future = None
        self._network_session_recovered = False
        self._firewall_ready = False
        self._firewall_lock = threading.Lock()
        self._sync_dialog = None
        self._sync_dialog_status = None
        self._sync_dialog_progress = None
        # The Qt bridge replaces both right after this method; the defaults keep early readers safe (audit A26).
        self.library = {}
        self.game_catalog = {}
        self._closing = False
        self._close_finished = False
        self._close_step = None


    def _checked_game_directory(self, value):
        """Validate a game directory choice and make sure it exists, without recording it."""
        if not value.strip():
            raise ValueError("Choose a game directory.")
        directory = Path(value).expanduser().resolve()
        if directory != self.game_root.resolve() and (self.room or self.busy or self.syncing_game):
            raise ValueError("Leave your room and wait for downloads to finish before changing the directory.")
        directory.mkdir(parents=True, exist_ok=True)
        return directory


    def set_game_directory(self, value):
        directory = self._checked_game_directory(value)
        self.game_root = directory
        self.config_data["game_directory"] = str(directory)
        _write_config(self.config_data)


    def complete_setup(self, name, directory, keep_installed, bundle_path=""):
        if self.config_data.get("setup_completed"):
            return
        if not name.strip():
            raise ValueError("Enter a player name.")
        # Validate the name, folder and bundle first, then commit them together (audit A10), so a bad folder
        # can never leave a trusted host key behind with setup unfinished.
        self._checked_game_directory(directory)
        bundle = None
        if bundle_path.strip():
            bundle = self._read_bundle(bundle_path.strip())
            if bundle is None:
                return
            if not self._commit_bundle(bundle):
                return
            self.pages["room"].set_status("Host trusted. Waiting for its signed room beacon…")
        self.set_game_directory(directory)
        self.save_profile(name)
        self.save_options(keep_installed)
        self.config_data["setup_completed"] = True
        _write_config(self.config_data)
        self.pages["profile"].name.set(name.strip())
        self.pages["options"].directory.set(str(self.game_root))
        self.pages["options"].keep.set(keep_installed)
        self.show_page("room")
        self.after(100, self._recover)


    def game_for_folder(self, folder):
        if folder is None:
            return None
        resolved = Path(folder).resolve()
        return next((m for m in self.game_catalog.values()
                     if Path(m["_game_dir"]).resolve() == resolved), None)


    def register_game(self, folder, exe, name, args=None, exe_required=True):
        folder = Path(folder).resolve()
        exe = Path(exe).resolve() if exe_required else None
        root = self.game_root.resolve()
        if folder.parent != root or not folder.is_dir():
            raise ValueError("Choose a game folder directly inside Game Directory.")
        if exe_required and (folder not in exe.parents or exe.suffix.casefold() != ".exe" or not exe.is_file()):
            raise ValueError("Choose a launch .exe inside that game folder.")
        previous = self.game_for_folder(folder)
        game_id = previous["id"] if previous else game_id_for(folder)
        if game_id in self.game_catalog and Path(self.game_catalog[game_id]["_game_dir"]).resolve() != folder:
            raise ValueError("Another game has the same internal game ID.")
        manifest = dict(previous or {})
        manifest.update({"id": game_id, "name": name.strip(),
                         "exe": exe.relative_to(folder).as_posix() if exe_required else '',
                         "exe_required": exe_required, "args": list(args or []) if exe_required else [],
                         "_game_dir": str(folder), "_dir": str(folder),
                         "install_dir": str(folder), "enabled": bool(previous and previous.get("enabled"))})
        self.game_catalog[game_id] = manifest
        try:
            self._update_game_icon(game_id)
        except Exception:
            # The game is still registered without its icon (audit A24: one save, after the icon step).
            logging.getLogger(__name__).exception("Could not read the game's icon: %s", game_id)
        self._save_host_catalog()
        self._refresh_host_playlist()


    def refresh_game_icon(self, game_id):
        """Extract the launch exe's own icon (the sidebar image) and save. False when none exists."""
        ok = self._update_game_icon(game_id)
        self._save_host_catalog()
        self._refresh_host_playlist()
        return ok


    def _update_game_icon(self, game_id):
        """Update the catalog entry's icon fields in memory only; the caller saves and refreshes."""
        from .exe_icon import extract_exe_icon
        import hashlib
        manifest = self.game_catalog[game_id]
        ok = False
        if manifest.get("exe_required", True) and manifest.get("exe"):
            self.host_art_root.mkdir(parents=True, exist_ok=True)
            dest = self.host_art_root / f"{game_id}_icon.png"
            ok = extract_exe_icon(Path(manifest["_game_dir"]) / manifest["exe"], dest)
            if ok:
                manifest["_icon_path"] = str(dest)
                manifest["icon_sha256"] = hashlib.sha256(dest.read_bytes()).hexdigest()
        if not ok and manifest.pop("_icon_path", None) is not None:
            # The exe changed or lost its icon. Old clients get the cover again.
            manifest["icon_sha256"] = manifest.get("art_sha256", "")
        return ok


    def set_game_art(self, game_id, source):
        from PIL import Image, ImageOps
        manifest = self.game_catalog[game_id]
        source = Path(source)
        if source.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("Choose an image smaller than 20 MB.")
        self.host_art_root.mkdir(parents=True, exist_ok=True)
        dest = self.host_art_root / f"{game_id}.png"
        with Image.open(source) as image:
            if image.width > 8192 or image.height > 8192:
                raise ValueError("Artwork dimensions must be 8192 pixels or less.")
            image = ImageOps.fit(image.convert("RGB"), (600, 900))
            image.save(dest, format="PNG", optimize=True)
        manifest["_art_path"] = str(dest)
        import hashlib
        manifest["art_sha256"] = hashlib.sha256(dest.read_bytes()).hexdigest()
        # Older clients only read icon_sha256. Without an exe icon it stays the cover.
        if not manifest.get("_icon_path"):
            manifest["icon_sha256"] = manifest["art_sha256"]
        self._save_host_catalog()
        self._refresh_host_playlist()


    def toggle_game_playlist(self, game_id):
        manifest = self.game_catalog[game_id]
        manifest["enabled"] = not manifest.get("enabled", False)
        self._save_host_catalog()
        self._refresh_host_playlist()


    def _save_host_catalog(self):
        save_catalog(self.host_catalog_path, self.game_catalog)


    def _refresh_host_playlist(self):
        self.library = {gid: item for gid, item in self.game_catalog.items()
                        if item.get("enabled") and Path(item["_game_dir"]).is_dir()}
        if self.process_watcher:
            watcher = self.process_watcher
            self.process_watcher = None
            # ProcessWatcher owns an asyncio task. Playlist edits come from the UI
            # thread, so cancel and recreate that task on its event loop.
            def restart_watcher():
                watcher.stop()
                if not self._closing and self.role == "host" and self.presence_client:
                    self._start_watcher()
            self.runtime.loop.call_soon_threadsafe(restart_watcher)


    def _launch_context(self):
        host_ip = self.room.host_ip if self.room else ""
        return {"name": self.config_data.get("player_name", "Player"), "host_ip": host_ip}


    @staticmethod
    def _local_host_source_matches(manifest):
        """Only locally attested Host source paths bypass a Client install receipt."""
        source = manifest.get('_local_host_source')
        if not source or not manifest.get('install_dir'):
            return False
        try:
            return Path(source).resolve() == Path(manifest['install_dir']).resolve() and Path(source).is_dir()
        except (OSError, ValueError, TypeError):
            return False

    def _local_host_library(self, host_pub):
        """Read an existing same-PC Host catalog without creating a Host identity.

        Folder names alone are not sufficient to trust file-only collections.
        The signed publisher must be this PC's stored Host before source folders
        can be reused, including when the Client has its own download directory.
        """
        if not isinstance(host_pub, str) or not host_pub:
            return {}
        try:
            identity = json.loads((APP_DIR / 'host_identity.json').read_text(encoding='utf-8'))
            if identity.get('public') != host_pub:
                return {}
            return load_catalog(getattr(self, 'host_catalog_path', APP_DIR / 'host_games.json'),
                                GAME_FILES_ROOT, getattr(self, 'host_art_root', APP_DIR / 'host_art'))
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    @staticmethod
    def _reuse_local_host_source(manifest, catalog, *, cancelled=None):
        source = catalog.get(manifest['id'])
        if not source or not source.get('enabled') or source.get('exe_required', True) != manifest.get('exe_required', True):
            return
        if str(source.get('exe', '')).replace('\\', '/').casefold() != str(manifest.get('exe', '')).replace('\\', '/').casefold():
            return
        folder = Path(source['_game_dir'])
        if not folder.is_dir():
            return
        if manifest.get('exe_required', True):
            candidate = {**manifest, 'install_dir': str(folder)}
            try:
                from .manifests.loader import resolve_exe
                if not LauncherCore._client_executable_matches(candidate, resolve_exe(candidate), cancelled=cancelled):
                    return
            except (OSError, ValueError):
                return
        manifest['install_dir'] = str(folder)
        manifest['_local_host_source'] = str(folder)
        if source.get('_icon_path') and source.get('icon_sha256') == manifest.get('icon_sha256'):
            manifest['icon_path'] = source['_icon_path']
        elif source.get('_art_path') and source.get('art_sha256') == manifest.get('icon_sha256'):
            manifest['icon_path'] = source['_art_path']  # Host has no exe icon; the cover is the icon
        if source.get('_art_path') and manifest.get('art_sha256') and source.get('art_sha256') == manifest['art_sha256']:
            manifest['_art_path'] = source['_art_path']

    def _prepare_client_game(self, manifest, *, cancelled=None):
        from .install_manifest import is_pending
        assigned = getattr(self, "_client_download_folders", {})
        gid = manifest["id"]
        preferred = assigned.get(gid)
        current = manifest.get("install_dir") or manifest.get("_dir")
        # Keep another title's files out of both discovery and repair.
        reserved = {Path(folder).resolve() for other, folder in assigned.items() if other != gid}
        root = Path(self.game_root).resolve()
        for other, game in getattr(self, "library", {}).items():
            if other != gid and game.get("install_dir"):
                folder = Path(game["install_dir"]).resolve()
                if folder == root or root in folder.parents:
                    reserved.add(folder)
        if preferred and current:
            path = Path(current).resolve()
            if any(owner == path or (owner != root and owner in path.parents) for owner in reserved):
                manifest["install_dir"] = str(preferred)
        if getattr(self, '_verify_next_sync', False) or is_pending(manifest.get('install_dir') or manifest.get('_dir') or ''):
            return False  # verify, or an unfinished download: always sync, never launch on the exe alone
        if manifest.get('exe_required', True) is False:
            from .install_manifest import shared_matches
            if not LauncherCore._local_host_source_matches(manifest):
                catalog = LauncherCore._local_host_library(self, getattr(self, 'trusted_host_pub', None))
                LauncherCore._reuse_local_host_source(manifest, catalog, cancelled=cancelled)
            return LauncherCore._local_host_source_matches(manifest) or shared_matches(manifest['install_dir'], manifest['id'])
        if LauncherCore._local_host_source_matches(manifest):
            from .manifests.loader import resolve_exe
            return LauncherCore._client_executable_matches(manifest, resolve_exe(manifest), cancelled=cancelled)
        local_dir = find_game_folder(self.game_root, manifest.get("exe", ""),
                                     manifest.get("exe_size", -1),
                                     preferred=Path(manifest.get("install_dir") or self.game_root),
                                     exe_sha256=manifest.get("exe_sha256"), cancelled=cancelled, reserved=reserved)
        if local_dir:
            manifest["install_dir"] = str(local_dir)
        from .manifests.loader import resolve_exe
        return self._client_executable_matches(manifest, resolve_exe(manifest), cancelled=cancelled)

    def _play_game(self, manifest, context, client_ready=None):
        if manifest.get('exe_required', True) is False:
            messagebox.showinfo('Shared folder', 'This entry contains files only. Use Install or Open Folder.', parent=self)
            return
        if self.busy or self.syncing_game or (self.room_controller and self.room_controller.launch_blocked):
            messagebox.showinfo("Please wait", "Room setup is still in progress.", parent=self)
            return
        from .manifests.loader import launch, resolve_exe
        if self.role == "client":
            # Recheck at play time: the user may have copied a game into the
            # destination after the host library was first received.
            if client_ready is None:
                client_ready = self._prepare_client_game(manifest)
        try:
            exe = resolve_exe(manifest)
        except Exception as exc:
            messagebox.showerror("Invalid game manifest", str(exc), parent=self)
            return
        can_sync = bool(self.room and (self.host_room and self.file_sync_server or
                                       self.last_beacon and self.trusted_host_pub))
        if self.role == "client" and not client_ready:
            messagebox.showinfo("Game not installed", "Choose Install to download this game. Then choose Play when you are ready.", parent=self)
            return
        if self.role == "client" and client_ready:
            try:
                launch(manifest, context)
            except Exception as exc:
                messagebox.showerror("Couldn't launch game", str(exc), parent=self)
            return
        if can_sync or not exe.is_file():
            self._sync_then_play(manifest, context)
            return
        try:
            launch(manifest, context)
        except Exception as exc:
            messagebox.showerror("Couldn't launch game", str(exc), parent=self)


    @staticmethod
    def _client_executable_matches(manifest, exe, *, cancelled=None):
        """Check only the Host-selected exe metadata before deciding to sync."""
        if manifest.get("exe_sha256"):
            from .install_manifest import matches
            return matches(manifest.get("install_dir") or manifest.get("_dir", ""), manifest, cancelled=cancelled)
        expected_size = manifest.get("exe_size")
        if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
            return False
        game_root = Path(manifest.get("install_dir") or manifest.get("_dir", "")).resolve()
        exe = exe.resolve()
        try:
            relative_path = exe.relative_to(game_root).as_posix()
        except ValueError:
            return False
        host_path = str(manifest.get("exe", "")).replace("\\", "/")
        if relative_path.casefold() != host_path.casefold() or not exe.is_file():
            return False
        try:
            return exe.stat().st_size == expected_size
        except OSError:
            return False


    def _sync_then_play(self, manifest, context, launch_after=True, *, show_downloads=True):
        if LauncherCore._local_host_source_matches(manifest):
            # Never index or download a second copy of the Host's source on
            # this PC merely to create a Client-side installation receipt.
            if launch_after and manifest.get('exe_required', True):
                from .manifests.loader import launch
                launch(manifest, context)
            else:
                self.pages['room'].set_status(f"{manifest['name']} is already available on this PC. Use Open Folder to view the files.")
            return
        if not self.room:
            messagebox.showinfo("Game not installed", "Join a room with an available game library first.", parent=self)
            return
        if self.host_room and self.file_sync_server:
            host, port, pub = self.room.host_ip, self.file_sync_server.port, self._host_identity()[1]
        elif self.last_beacon and self.trusted_host_pub:
            host = self.last_beacon.get("host_zt")
            port = self.last_beacon.get("sync_port", 47803)
            pub = self.trusted_host_pub
        else:
            messagebox.showinfo("Import host bundle", "Import the host's join bundle before syncing games.", parent=self)
            return
        dest = manifest.get("install_dir") or manifest.get("_dir")
        if dest:
            folder = Path(dest)
            try:
                folder.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                pass
            else:
                owned = getattr(self, '_owned_download_folders', None)
                if owned is None:
                    owned = self._owned_download_folders = set()
                owned.add(str(folder.resolve()))
        self.syncing_game = True
        from .filesync.control import TransferControl
        def transfer_state(state):
            if self.peer_file_server:
                self.peer_file_server.set_paused(state in ('pausing', 'paused'))
            self.after(0, self._sync_transfer_state, state)
        self._sync_control = TransferControl(transfer_state)
        self.pages["room"].set_status(f"Preparing {manifest['name']}…")
        self._show_sync_progress(manifest["name"], game_id=manifest["id"], show_downloads=show_downloads)
        import time as _time
        last_progress_sent = [0.0]
        def progress(done, total, filename):
            # Throttle: every 1 MiB piece used to queue a full UI publish, which backed up the GUI
            # event queue so Pause could not run until the transfer ended.
            now = _time.monotonic()
            if done < total and now - last_progress_sent[0] < 0.25:
                return
            last_progress_sent[0] = now
            self.after(0, self._update_sync_progress, manifest["name"], done, total, filename)
        def index_progress(status):
            self.after(0, self._update_index_progress, manifest["name"], status)
        verify_now = bool(getattr(self, "_verify_next_sync", False))
        self._verify_next_sync = False
        if dest:
            try:
                from .install_manifest import mark_pending
                mark_pending(dest, manifest["id"])
            except OSError:
                pass
        self._disk_changed(manifest["id"])
        async def run_sync():
            started = time.monotonic()
            retries = 0
            held_index = {}
            while True:
                result = await sync_game(
                    host, port, pub, manifest["id"], dest, progress=progress,
                    peers=lambda: list(self.peer_sources), verify=verify_now,
                    on_index=self._register_transfer_index, on_piece=self._share_transfer_piece,
                    control=self._sync_control, received=self.received_activity,
                    index_progress=index_progress, held_index=held_index,
                    **({"access": self.room_access} if getattr(self, "room_access", None) else {}))
                if result.ok:
                    return result
                reasons = [reason for _, reason in result.failed] if result.failed else [result.error or ""]
                transient = bool(reasons) and all(any(word in reason.lower() for word in (
                    "lost contact", "timed out", "timeout", "connection", "no source available",
                    "network is unreachable", "host is unreachable", "refused", "reset by peer"))
                    for reason in reasons)
                if not transient or time.monotonic() - started >= 90 or not self.room_controller:
                    return result
                retries += 1
                self.after(0, self.pages["room"].set_status,
                           f"Connection interrupted. Retrying download (attempt {retries + 1})…")
                await asyncio.sleep(min(2 * retries, 10))
        future = submit_drained(self.runtime.loop, run_sync())
        self._sync_future = future
        def finished(done):
            try:
                result, error = done.result(), None
            except BaseException as exc:
                # A cancelled sync raises CancelledError (a BaseException); `except Exception` skipped it,
                # so _sync_finished never ran and the UI stayed in the sync state.
                result, error = None, exc
            self.after(0, self._sync_finished, manifest, context, result, error, launch_after)
        future.add_done_callback(finished)

    def _cancel_sync(self):
        """Stop a running or paused game sync (room left, host lost). Safe from any thread and when none is running."""
        future = getattr(self, "_sync_future", None)
        if future is not None and not future.done():
            future.cancel()

    def _sync_transfer_state(self, state):
        """Frontend hook; the Qt bridge overrides it and calls this default, which shows the state as room status."""
        self.pages['room'].set_status({'pausing':'Pausing download…',
            'paused':'Download paused', 'receiving':'Receiving game files'}.get(state,state))


    async def _register_transfer_index(self, gid, dest, files):
        if self.peer_file_server:
            self.peer_file_server.register_index(gid, dest, files)

    def _shared_file_map(self, games=None):
        """Files to advertise per game; games with no verified file yet (empty list) are left out."""
        games = self.seeded_files.keys() if games is None else games
        return {g: self.seeded_files[g] for g in games if self.seeded_files.get(g)}

    async def _share_transfer_piece(self, gid, dest, entry, piece_index):
        if not self.peer_file_server:
            return
        paths = self.seeded_files.setdefault(gid, [])
        if entry["path"] in paths:
            return
        # Announce after the first verified piece. Peers check the requested
        # range against the signed piece hash, so missing pieces safely return 404.
        paths.append(entry["path"])
        self.seeded_games.add(gid)
        self.peer_file_server.set_shared_files(self._shared_file_map())
        if self.presence_client:
            await self.presence_client.publish_seeds(self.peer_file_server.shared_games,
                                                     self.peer_file_server.port)

    async def _seed_existing_games(self, beacon):
        from .filesync.client import fetch_index, _HttpError
        from .filesync.index import HashCache, CACHE_NAME, diff_index, run_hash_work, finish_disk_work
        # Bind the first index fetch to the joined room key: the beacon must
        # match the pinned Host key and the room this PC actually joined.
        pinned_pub = getattr(self, "trusted_host_pub", None)
        joined_net = str(getattr(getattr(self, "room", None), "network_id", "") or "").lower()
        if (not pinned_pub or beacon.get("host_pub") != pinned_pub
                or not joined_net or str(beacon.get("net_id", "")).lower() != joined_net):
            return
        for gid, manifest in list(self.library.items()):
            if self.syncing_game or not self.peer_file_server:
                return
            if LauncherCore._local_host_source_matches(manifest):
                # The Host already serves these exact files from this disk.
                # A colocated Client must not index/hash them again as a peer.
                continue
            dest = Path(manifest["install_dir"])
            if not dest.is_dir():
                continue
            try:
                endpoints = list(dict.fromkeys(filter(None, (beacon.get('host'), beacon.get('host_zt')))))
                if not endpoints:
                    continue
                for position, endpoint in enumerate(endpoints):
                    try:
                        files = await fetch_index(endpoint, beacon.get('sync_port', 47803), pinned_pub, gid,
                                                  **({'access': self.room_access}
                                                     if getattr(self, 'room_access', None) else {}))
                        break
                    except (OSError, asyncio.TimeoutError, _HttpError):
                        if position == len(endpoints) - 1:
                            raise
                if self.syncing_game or not self.peer_file_server:
                    return
                cache = HashCache(dest / CACHE_NAME)
                _, same = await run_hash_work(diff_index, files, dest, cache)
                await finish_disk_work(cache.save)
                if not self.peer_file_server or self.syncing_game:
                    return
                self.peer_file_server.register_index(gid, dest, files)
                self.seeded_files[gid] = [entry["path"] for entry in same]
                if same:
                    self.seeded_games.add(gid)
                else:
                    self.seeded_games.discard(gid)
                self.peer_file_server.set_shared_files(self._shared_file_map(self.seeded_games))
                if self.presence_client:
                    await self.presence_client.publish_seeds(self.peer_file_server.shared_games,
                                                             self.peer_file_server.port)
            except (OSError, ValueError, RuntimeError, _HttpError):
                logging.getLogger(__name__).exception("Could not verify existing game for sharing: %s", gid)

    def _disk_changed(self, game_id):
        """Hook: a game's install state or artwork changed. The Qt bridge drops its cached disk facts here."""

    def _sync_finished(self, manifest, context, result, error, launch_after=True):
        self._disk_changed(manifest.get('id'))
        self.syncing_game = False
        self._sync_control = None
        self._sync_future = None
        if self.peer_file_server:
            self.runtime.loop.call_soon_threadsafe(self.peer_file_server.set_paused, False)
        self._close_sync_progress()
        if isinstance(error, (asyncio.CancelledError, concurrent.futures.CancelledError)):
            # Cancelled on purpose (room left or host lost): no error popup, just release the UI.
            self.pages["room"].set_status("Download stopped.")
            return
        if error or not result or not result.ok:
            message = str(error) if error else (result.error or "Game sync failed")
            if result and result.failed:
                details = "\n".join(f"{path}: {reason}" for path, reason in result.failed[:3])
                message = f"{message}\n{details}"
            messagebox.showerror("Game sync failed", message, parent=self)
            self.pages["room"].set_status(message)
            return
        from .install_manifest import clear_pending
        completed_folder = manifest.get('install_dir') or manifest.get('_dir')
        clear_pending(completed_folder)  # finished with every file verified
        if completed_folder:
            getattr(self, '_owned_download_folders', set()).discard(str(Path(completed_folder).resolve()))
        self._disk_changed(manifest.get('id'))
        if self.role == "client":
            if manifest.get('exe_required', True) is False:
                from .install_manifest import mark_shared_installed
                mark_shared_installed(manifest['install_dir'], manifest['id'])
                self._disk_changed(manifest['id'])  # the install record now exists; re-check it            self.seeded_games.add(manifest["id"])
            self.seeded_files[manifest["id"]] = result.verified_files.get(manifest["id"], [])
            self.pages["library"].refresh_install_state()
            async def publish():
                if self.peer_file_server:
                    self.peer_file_server.set_shared_files(self._shared_file_map(self.seeded_games & set(self.library)))
                    if self.presence_client:
                        await self.presence_client.publish_seeds(self.peer_file_server.shared_games,
                                                                 self.peer_file_server.port)
            asyncio.run_coroutine_threadsafe(publish(), self.runtime.loop)
        if not launch_after or manifest.get('exe_required', True) is False:
            next_action = 'Use Open Folder to view the files.' if manifest.get('exe_required', True) is False else 'Choose Play when you are ready.'
            self.pages["room"].set_status(f"{manifest['name']} is installed. {next_action}")
            return
        from .manifests.loader import launch
        try:
            launch(manifest, context)
        except Exception as exc:
            messagebox.showerror("Couldn't launch game", str(exc), parent=self)


    def _run_background(self, function, on_success, label="Working…"):
        if self.busy:
            self.pages["room"].set_status("Room setup is still running, so that action was ignored. Try again when it finishes.")
            return
        self.busy = True
        self.pages["room"].set_status(label)

        async def run():
            return await asyncio.get_running_loop().run_in_executor(None, function)
        future = self.runtime.submit(run())
        def finished(done):
            try:
                result, error = done.result(), None
            except Exception as exc:
                result, error = None, exc
            self.after(0, self._background_done, result, error, on_success)
        future.add_done_callback(finished)


    def _background_done(self, result, error, callback):
        self.busy = False
        if error:
            self._log_room_error(error)
            typed = as_join_error(error)
            self.pages["room"].set_status(typed.message)
            messagebox.showerror("Room setup failed", typed.message, parent=self,
                                 stage=typed.stage.value, code=typed.code, hint=typed.hint)
            return
        callback(result)

    @staticmethod
    def _log_room_error(error):
        """Keep the original worker traceback for room startup failures."""
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            import traceback
            log_path = APP_DIR / 'room-errors.log'
            try:
                if log_path.stat().st_size > ROOM_ERROR_LOG_LIMIT:
                    # Keep one previous log so the total stays bounded (audit A23).
                    os.replace(log_path, log_path.with_name(log_path.name + '.1'))
            except FileNotFoundError:
                pass
            with log_path.open('a', encoding='utf-8') as log:
                log.write(time.strftime('\n%Y-%m-%d %H:%M:%S Room setup failed\n'))
                traceback.print_exception(type(error), error, error.__traceback__, file=log)
        except OSError:
            logging.getLogger(__name__).exception('Could not save room error details')


    def open_room(self, room_name, *, password=""):
        def work():
            self._recover_network_session()
            room = self.tunnel.open_room(room_name or None, **({"protected": True} if password else {}))
            status = self.tunnel.wait_connected(room.network_id, timeout=NETWORK_WAIT)
            if status.state != CONNECTED:
                self.tunnel.close_room()
                raise JoinError(Stage.HOST_SETUP, Code.HOST_SETUP, status.message)
            return room
        opened = (lambda room: self._room_opened(room, password=password)) if password else self._room_opened
        self._run_background(work, opened,
                             "Preparing LAN access and room… approve Windows permission if asked.")


    def _room_opened(self, room, *, password=""):
        self.room = room
        self.busy = True
        async def start_presence():
            try:
                self.game_root.mkdir(parents=True, exist_ok=True)
                admission = None
                if password:
                    from .netcore.admission import RoomAdmission
                    admission = RoomAdmission(password, on_change=self._publish_room_admission,
                                              overlay=self.tunnel.room_overlay)
                    self.room_admission = admission
                    await admission.start()
                admission_options = {"admission": admission} if admission else {}
                self.presence_server = PresenceServer(
                    on_change=lambda _counts, roster: self.after(
                        0, self.pages["room"].set_roster, roster), **admission_options)
                await self.presence_server.start()
                private, public = self._host_identity()
                from .netcore.launcher_share import LauncherShare, build_package
                from .appdirs import app_root
                package_path = APP_DIR / 'launcher-share' / f'LAN Launcher V{__version__}.zip'
                share = LauncherShare(lambda: build_package(app_root(), package_path),
                                      on_change=getattr(self, '_publish_launcher_share', None))
                try:
                    await share.start()
                    self.launcher_share = share
                except OSError:
                    logging.getLogger(__name__).exception('Launcher sharing is unavailable; room hosting continues.')
                    self.launcher_share = None
                self.host_room = HostRoom(
                    private, self.tunnel.local.home, APP_DIR / "host", room.network_id,
                    _lan_ip, __version__, presence_port=self.presence_server.port,
                    host_zt=room.host_ip, host_pub=public, pc_name=self.pc_name,
                    launcher_share=share.metadata if self.launcher_share else None, **admission_options)
                await self.host_room.start()
                self.host_conflict_transport = await BeaconListener.listen_discovered(
                    self._host_conflict_seen, port=47804)
                self.file_sync_server = FileSyncServer(
                    private, self.game_root, cache_path=APP_DIR / "file_hash_cache.sqlite3",
                    library_provider=lambda: self.library, **admission_options)
                await self.file_sync_server.start()
                # Hash a requested game on demand. Prewarming every game kept
                # the Host disk busy for tens of minutes in real rooms and made
                # index requests wait behind the background scan.
                # Host.exe serves the room; only Client.exe registers a player.
            except Exception:
                await self._stop_room_admission()
                await self._stop_file_sync_prewarm()
                if self.host_room:
                    await self.host_room.stop()
                    self.host_room = None
                if self.file_sync_server:
                    await self.file_sync_server.stop()
                    self.file_sync_server = None
                if self.host_conflict_transport:
                    self.host_conflict_transport.close()
                    self.host_conflict_transport = None
                if self.presence_client:
                    await self.presence_client.stop()
                    self.presence_client = None
                if self.presence_server:
                    await self.presence_server.stop()
                    self.presence_server = None
                raise
        future = self.runtime.submit(start_presence())
        future.add_done_callback(lambda done: self.after(0, self._host_ready, room, done))

    async def _stop_room_admission(self):
        share = getattr(self, 'launcher_share', None)
        if share:
            self.launcher_share = None
            await share.stop()
        admission = getattr(self, "room_admission", None)
        if admission:
            self.room_admission = None
            await admission.stop()
            self._publish_room_admission()


    @staticmethod
    def _file_sync_prewarm_done(task, started):
        if task.cancelled():
            timing_mark("host.file_index_prewarm", started, "cancelled")
            return
        try:
            task.result()
        except Exception as exc:
            timing_mark("host.file_index_prewarm", started, type(exc).__name__)
        else:
            timing_mark("host.file_index_prewarm", started, "complete")


    async def _stop_file_sync_prewarm(self):
        task, self.file_sync_prewarm_task = self.file_sync_prewarm_task, None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


    def _host_ready(self, room, future):
        self.busy = False
        try:
            future.result()
        except Exception as exc:
            self._log_room_error(exc)
            self.room = None
            self._run_background(self.tunnel.close_room, lambda _r: None, "Cleaning up failed room setup…")
            messagebox.showerror("Room setup failed", str(exc), parent=self)
            return
        if self.role == "client":
            self.pages["library"].set_presence(self.presence_client, self.runtime.loop)
        self.pages["room"].show_room(room.code, "Hosting")
        self.pages["room"].set_status(f"Hosting as {self.pc_name}. Looking for LAN clients…")
        self.room_nav_status.configure(text=f"Hosting · {room.code}")


    def _host_identity(self, filename="host_identity.json"):
        identity_path = APP_DIR / filename
        try:
            raw = identity_path.read_bytes()
        except FileNotFoundError:
            raw = None  # first run: no identity yet
        except OSError as exc:
            # A transient read problem must not replace a good key. Every client that imported it would lose this host.
            raise RuntimeError(f"Could not read the host identity file {identity_path}: {exc}. "
                               "The host key was left unchanged; try again.") from exc
        if raw is not None:
            try:
                data = json.loads(raw)
                private, public = data["private"], data["public"]
                proof = signing.sign_bytes(private, b"lantool-host-key")
                if signing.verify_bytes(public, b"lantool-host-key", proof):
                    return private, public
            except (ValueError, KeyError, TypeError):
                pass
            # The file is unusable. Keep a copy before replacing it (audit A13); if that fails, stop instead of
            # destroying the only record of the old key.
            backup = identity_path.with_name(f"{identity_path.name}.invalid-{int(time.time())}")
            try:
                backup.write_bytes(raw)
            except OSError as exc:
                raise RuntimeError(f"The host identity file {identity_path} is invalid and could not be backed up: "
                                   f"{exc}. No new host key was created.") from exc
            logging.getLogger(__name__).error(
                "Host identity file %s is invalid. It was backed up to %s and a new host key was generated; "
                "clients that imported the old join bundle must import a new one.", identity_path, backup)
        private, public = signing.generate_keypair()
        APP_DIR.mkdir(parents=True, exist_ok=True)
        temp = identity_path.with_name(identity_path.name + ".tmp")
        temp.write_text(json.dumps({"private": private, "public": public}), encoding="utf-8")
        temp.replace(identity_path)
        return private, public


    def _host_presence_identity(self):
        """Return a persistent ID distinct from this installation's client ID."""
        host_id = self.config_data.get("host_player_id")
        if not isinstance(host_id, str) or not host_id.startswith("host-"):
            host_id = f"host-{uuid.uuid4().hex}"
            self.config_data["host_player_id"] = host_id
            _write_config(self.config_data)
        return host_id


    def export_bundle(self):
        if not self.host_room or not self.room:
            messagebox.showinfo("No hosted room", "Open a room before exporting its join bundle.", parent=self)
            return
        messagebox.showinfo("Local room ready",
                            f"Room code: {self.room.code}\n\nClients on this LAN discover the host automatically. No join bundle is required.",
                            parent=self)


    def import_bundle(self, path=None, *, start_discovery=True):
        path = path or filedialog.askopenfilename(parent=self, title="Import host join bundle",
                                         filetypes=[("LAN Tool bundle", "*.json"), ("JSON files", "*.json")])
        if not path:
            return False
        # Switching the trusted host mid-session would leave a joined room on the wrong key (audit A11).
        if getattr(self, "room", None) or getattr(self, "room_controller", None):
            messagebox.showinfo("Leave the room first",
                                "Leave the current room before importing a different host's join bundle.", parent=self)
            return False
        bundle = self._read_bundle(path)
        if bundle is None or not self._commit_bundle(bundle):
            return False
        if start_discovery:
            self._start_discovery()
        self.pages["room"].set_status("Host trusted. Waiting for its signed room beacon…")
        return True


    def _load_trusted_bundle(self, auto_bundle):
        """Load imported trust or seed it from a bundled file. Keep a host saved by LAN discovery."""
        log = logging.getLogger(__name__)
        stored_path = self.config_data.get("trusted_bundle_path")
        if stored_path:
            try:
                self.client_bundle, _data = load_bundle(stored_path)
                self.trusted_host_pub = self.client_bundle["host_pub"]
            except Exception:
                log.exception("Could not load the imported join bundle %s", stored_path)
                self.client_bundle = None
        if self.client_bundle is None and auto_bundle and (stored_path or not self.trusted_host_pub):
            try:
                bundle, _data = load_bundle(auto_bundle)
                APP_DIR.mkdir(parents=True, exist_ok=True)
                stored_bundle = APP_DIR / "trusted_host_bundle.json"
                temp = stored_bundle.with_name(stored_bundle.name + ".tmp")
                temp.write_text(json.dumps(bundle), encoding="utf-8")
                temp.replace(stored_bundle)
                self.config_data.update({
                    "trusted_host_pub": bundle["host_pub"],
                    "trusted_net_id": bundle["net_id"],
                    "trusted_moon_id": bundle["moon_id"],
                    "trusted_bundle_path": str(stored_bundle),
                })
                _write_config(self.config_data)
                self.client_bundle = bundle
                self.trusted_host_pub = bundle["host_pub"]
            except Exception:
                log.exception("Could not load the bundled join bundle %s", auto_bundle)
                self.client_bundle = None


    def _read_bundle(self, path):
        """Load and verify a join bundle without recording it. Shows the error and returns None if invalid."""
        try:
            bundle, _moon = load_bundle(path)
        except Exception as exc:
            messagebox.showerror("Invalid join bundle", str(exc), parent=self)
            return None
        return bundle


    def _commit_bundle(self, bundle):
        """Store a verified bundle. The file is written first, so a failed write leaves the old trust unchanged."""
        stored_bundle = APP_DIR / "trusted_host_bundle.json"
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            temp = stored_bundle.with_name(stored_bundle.name + ".tmp")
            # Store the verified content itself, not a second read of the user's file.
            temp.write_text(json.dumps(bundle), encoding="utf-8")
            temp.replace(stored_bundle)
        except OSError as exc:
            messagebox.showerror("Could not save join bundle", str(exc), parent=self)
            return False
        self.client_bundle = bundle
        self.trusted_host_pub = bundle["host_pub"]
        self.config_data["trusted_host_pub"] = self.trusted_host_pub
        self.config_data["trusted_net_id"] = bundle["net_id"]
        self.config_data["trusted_moon_id"] = bundle["moon_id"]
        self.config_data["trusted_bundle_path"] = str(stored_bundle)
        _write_config(self.config_data)
        return True


    def _start_discovery(self, *, allow_host_switch=False):
        if self.beacon_transport:
            self.beacon_transport.close()
        listen_started = time.monotonic()
        self._discovery_listening_since = None
        timing_mark("discovery.listen_start")
        async def listen():
            self.after(0, self.pages['room'].set_status,
                       'Checking LAN access… approve Windows permission if asked.')
            await asyncio.to_thread(self._prepare_firewall)
            self.after(0, self.pages['room'].set_status, 'Searching for a LAN Host…')
            def on_beacon(beacon):
                nonlocal allow_host_switch
                if self._beacon_seen(beacon, allow_host_switch=allow_host_switch):
                    allow_host_switch = False

            self.beacon_transport = await BeaconListener.listen_discovered(
                on_beacon if allow_host_switch else self._beacon_seen)
            transport = self.beacon_transport
            asyncio.create_task(self._discovery_fallback(transport))
        future = self.runtime.submit(listen())
        future.add_done_callback(lambda done: self.after(0, self._discovery_started, done, listen_started))


    async def _discovery_fallback(self, transport):
        """Retry the last working host over TCP while UDP searches in parallel."""
        from .netcore.discovery import fetch_room
        started = time.monotonic()
        while not self._closing and not transport.is_closing():
            if not self.room and not self._beacon_joining and not self.busy:
                address = self.config_data.get("last_host_address")
                if address:
                    try:
                        beacon = await fetch_room(address, timeout=1)
                        if not transport.is_closing():
                            self._beacon_seen(beacon)
                    except (OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                        pass
                if not self.room and not self._beacon_joining and time.monotonic() - started >= 8:
                    self.after(0, self.pages["room"].set_status,
                               "Still searching. Open a room on the Host. If it is already open, use Connect by IP or Repair LAN access. Retrying automatically…")
                    started = time.monotonic()
            await asyncio.sleep(2)


    def _discovery_started(self, future, listen_started=None):
        try:
            future.result()
            self._discovery_listening_since = time.monotonic()
            timing_mark("discovery.listener_ready", listen_started, "ok")
        except Exception as exc:
            timing_mark("discovery.listener_ready", listen_started, type(exc).__name__)
            self.pages["room"].set_status(f"Room discovery couldn't start: {exc}")


    def _beacon_seen(self, beacon, *, allow_host_switch=False):
        if self.role != "client" or self.busy:
            return
        if time.monotonic() < getattr(self, "_discovery_retry_at", 0):
            return
        if beacon.get("admission") and beacon.get("net_id") == getattr(self, "_paused_admission_room", None):
            return
        paused_version = getattr(self, '_paused_version_room', None)
        if paused_version and beacon.get('net_id') == paused_version and not allow_host_switch:
            return
        if self.room_controller is None and not self._beacon_joining and not self.room:
            timing_mark("discovery.matching_beacon", self._discovery_listening_since, "matched")
        # With a pinned host key, only that host's beacon may become last_beacon, because _sync_then_play and the
        # library loop pair its addresses with the trusted key (audit A06). A foreign beacon still reaches the join
        # path below, which refuses it with a visible error.
        pinned = self.trusted_host_pub
        if not pinned or beacon.get("host_pub") == pinned:
            self.last_beacon = beacon
        controller = self.room_controller
        if (controller and beacon.get("host_pub") == self.trusted_host_pub and
                str(beacon.get("net_id", "")).lower() == str(controller.net_id or "").lower()):
            controller.observe_beacon(beacon)
        if self.room_controller is None and not self._beacon_joining and not self.room:
            self._beacon_joining = True
            if allow_host_switch:
                asyncio.create_task(self._join_beacon_room(beacon, allow_host_switch=True))
            else:
                asyncio.create_task(self._join_beacon_room(beacon))
            return True


    async def _join_beacon_room(self, beacon, *, allow_host_switch=False, report_error=True):
        join_started = time.monotonic()
        timing_mark("join.started", join_started, "beacon")
        try:
            # All wire beacons carry a signature. Keep internal callers which supply
            # already-checked room data on the same join path.
            if "sig" in beacon:
                from .netcore import compat
                proto = compat.proto_of(beacon)
                _, level, message, hint = compat.check(
                    beacon.get("version"), proto, __version__, compat.PROTO_VERSION)
                if proto is None or level == compat.BLOCK:
                    offer = getattr(self, '_offer_host_version', None)
                    if offer:
                        self.after(0, offer, beacon, message, allow_host_switch)
                    raise JoinError(Stage.BEACON, Code.BEACON_INVALID, f"{message} {hint}")
            await asyncio.to_thread(self._recover_network_session)
            discovered_pub = beacon.get("host_pub")
            if not discovered_pub:
                raise JoinError(Stage.BEACON, Code.BEACON_INVALID, "room announcement is missing the host identity")
            pinned_pub = self.trusted_host_pub
            switching_host = bool(pinned_pub and discovered_pub != pinned_pub)
            if switching_host and not allow_host_switch:
                raise JoinError(Stage.BEACON, Code.BEACON_INVALID, "room host does not match the trusted host bundle")
            if not beacon.get("host_zt"):
                raise JoinError(Stage.BEACON, Code.BEACON_INVALID, "room beacon is missing the host's VLA address")
            access = None
            if beacon.get("admission"):
                access = await self._request_room_admission(beacon)
            phase_started = time.monotonic()
            try:
                await asyncio.get_running_loop().run_in_executor(None, self.tunnel.ensure_ready)
            except Exception as exc:
                timing_mark("zerotier.ensure_ready", phase_started, type(exc).__name__)
                raise
            timing_mark("zerotier.ensure_ready", phase_started, "ready")
            self.presence_client = PresenceClient(
                self.config_data["player_id"], self.config_data.get("player_name", "Player"), beacon["host"],
                port=beacon.get("presence_port", 47800), on_seeds=self._seeds_received,
                avatar=self.config_data.get("avatar_thumb", ""),
                on_kicked=lambda: self.after(0, self._host_kicked_me),
                **({"access": access} if access else {}))
            if not access:
                self.presence_client.start()
            async def no_room_file(_beacon):
                return True
            self.room_controller = RoomController(
                SilentTunnelZT(self.tunnel),
                AdapterSwitcher(APP_DIR / "vla-adapter-state.json"),
                self.presence_client,
                lambda: "",
                no_room_file,
                lambda b: b["host_zt"],
                **({"admit_overlay": lambda: self._bind_room_admission(beacon, access)} if access else {}),
            )
            await self.room_controller.on_beacon(beacon)
            if self.room_controller.state.value != "zerotier":
                raise (self.room_controller.join_error or
                       JoinError(Stage.HOST_SETUP, Code.HOST_SETUP, "couldn't join room"))
            if access:
                self.presence_client.start()
            self.room = SimpleNamespace(network_id=beacon["net_id"], code=_format_room(beacon["net_id"]),
                                        host_ip=beacon["host_zt"], discovered=True)
            # Only the joined room's overlay interface may accept peer requests.
            room_ip = self.room_controller.room_ip
            if room_ip:
                self.peer_file_server = PeerFileServer(self.game_root, host=room_ip)
                try:
                    await self.peer_file_server.start()
                    await self.presence_client.publish_seeds([], self.peer_file_server.port)
                except OSError:
                    # Peer sharing is optional: the Client still downloads from the Host.
                    logging.getLogger(__name__).exception("Peer sharing unavailable; downloads will use the Host only")
                    self.peer_file_server = None
            else:
                logging.getLogger(__name__).warning("No IPv4 room address; peer sharing is unavailable")
            updated_config = dict(self.config_data, last_host_address=beacon["host"],
                                  trusted_host_pub=discovered_pub, trusted_net_id=beacon["net_id"],
                                  trusted_moon_id=beacon.get("moon_id"))
            if switching_host:
                updated_config.pop("trusted_bundle_path", None)
            _write_config(updated_config)
            self.config_data.clear()
            self.config_data.update(updated_config)
            self.trusted_host_pub = discovered_pub
            self.room_access = access
            if switching_host:
                self.client_bundle = None
                self.last_beacon = beacon
            self.library_refresh_task = asyncio.create_task(self._watch_host_library(beacon))
            self._start_watcher()
            self.after(0, self._discovered_room_joined, beacon)
            self.discovery_task = asyncio.create_task(self._watch_host())
            timing_mark("join.complete", join_started, "connected")
        except Exception as exc:
            timing_mark("join.complete", join_started, timing_failure(exc))
            if self.room_controller:
                try:
                    await self.room_controller.leave()
                except Exception as cleanup_error:
                    self._log_room_error(cleanup_error)
            if self.peer_file_server:
                await self.peer_file_server.stop()
                self.peer_file_server = None
            if self.presence_client:
                await self.presence_client.publish_seeds([], 0)
                await self.presence_client.stop()
                self.presence_client = None
            self.room_controller = None
            self.room = None
            self.room_access = None
            if beacon.get("admission"):
                self._paused_admission_room = beacon.get("net_id")
            self._beacon_joining = False
            if not report_error:
                raise
            self.after(0, self._discovery_failed, str(exc))


    def _pinned_host_pub(self, beacon):
        """Host key a library fetch may trust. With an imported join bundle, the beacon must carry that bundle's key.

        Without a bundle (discovery-only join), the signed beacon's key is trusted as before.
        """
        beacon_pub = beacon.get("host_pub")
        bundle = getattr(self, "client_bundle", None)
        if bundle and bundle.get("host_pub") != beacon_pub:
            raise RuntimeError("room beacon's host key does not match the imported join bundle")
        return beacon_pub

    async def _fetch_host_library(self, host, port, host_pub):
        fetch_started = time.monotonic()
        access = getattr(self, "room_access", None)
        connect = access.connect if access else asyncio.open_connection
        reader, writer = await asyncio.wait_for(connect(host, port), 5)
        try:
            header = access.authorization_header if access else b""
            writer.write(b"GET /library HTTP/1.0\r\n" + header + b"\r\n")
            await writer.drain()
            headers = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 8)
            status_line = headers.split(b"\r\n", 1)[0].decode("latin-1", "replace")
            status = status_line.split(None, 2)
            if len(status) < 2 or not status[0].startswith("HTTP/") or status[1] != "200":
                # An error page must not be parsed as the signed library.
                raise RuntimeError(f"Host game list request failed: {status_line[:80] or 'no status line'}")
            length = next((int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n")
                           if line.lower().startswith(b"content-length:")), 0)
            if not 0 < length <= 8 * 1024 * 1024:
                raise RuntimeError("Invalid host library response size")
            raw = headers + await asyncio.wait_for(reader.readexactly(length), 8)
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 2)
            except (OSError, asyncio.TimeoutError):
                pass  # the connection is already finished with; a slow or reset close is not an error
        _headers, separator, body = raw.partition(b"\r\n\r\n")
        if not separator:
            raise RuntimeError("host game list response was incomplete")
        envelope = json.loads(body)
        if not signing.verify_obj(host_pub, envelope) or envelope.get("type") != "library":
            raise RuntimeError("host game list signature is invalid")
        try:
            FRESHNESS.check(host_pub, "library", envelope)
        except StaleError as exc:
            raise RuntimeError(f"host game list rejected: {exc}") from None
        manifests = [validate(dict(raw_manifest)) for raw_manifest in envelope.get("games", [])]
        for manifest in manifests:
            # A remote manifest must never supply the local-source attestation.
            manifest.pop('_local_host_source', None)
        # Publish the complete verified playlist before disk scans or artwork
        # requests. A slow drive or missing cover must not hide every game.
        # Each game downloads into a folder named after the game, chosen once and remembered. It touches the disk,
        # so it runs off the event loop (audit A03); the playlist is still published before any slow scan.
        client_folders = await asyncio.to_thread(assign_client_folders, self.game_root, APP_DIR / "client_game_dirs.json",
                                                 [(m["id"], m.get("name", "")) for m in manifests])
        self._client_download_folders = client_folders
        assigned_paths = {gid: folder.resolve() for gid, folder in client_folders.items()}
        def reserved_by_other(gid, path):
            path = Path(path).resolve()
            return any(other != gid and (folder == path or folder in path.parents)
                       for other, folder in assigned_paths.items())
        initial_library = {}
        local_source_cache = getattr(self, '_local_host_source_cache', {})
        def source_fingerprint(manifest):
            return (manifest.get('exe_required', True), manifest.get('exe'), manifest.get('exe_size'), manifest.get('exe_sha256'))
        for manifest in manifests:
            gid = manifest["id"]
            previous = self.library.get(gid, {})
            initial = dict(manifest)
            same_exe = all(previous.get(k) == manifest.get(k) for k in ('exe', 'exe_size', 'exe_sha256'))
            previous_folder = previous.get('install_dir') if same_exe else None
            initial['install_dir'] = (previous_folder if previous_folder and not reserved_by_other(gid, previous_folder)
                                      else str(client_folders[gid]))
            cached = local_source_cache.get((host_pub, gid))
            if cached and cached['fingerprint'] == source_fingerprint(manifest):
                initial.update({'install_dir': cached['source'], '_local_host_source': cached['source']})
                if not LauncherCore._local_host_source_matches(initial):
                    initial.pop('_local_host_source', None)
            if previous.get('icon_path') and previous.get('icon_sha256') == manifest.get('icon_sha256'):
                initial['icon_path'] = previous['icon_path']
            if previous.get('_art_path') and previous.get('art_sha256') == manifest.get('art_sha256'):
                initial['_art_path'] = previous['_art_path']
            initial_library[gid] = initial
        self._publish_host_library(initial_library)
        timing_mark('library.playlist_visible', fetch_started, f'games={len(initial_library)}')
        local_catalog = await asyncio.to_thread(LauncherCore._local_host_library, self, host_pub) or {}
        new_library = {}
        new_local_source_cache = {}
        claimed_folders = set()
        from .filesync.index import run_hash_work
        for manifest in manifests:
            gid = manifest["id"]
            await run_hash_work(LauncherCore._reuse_local_host_source, manifest, local_catalog)
            if LauncherCore._local_host_source_matches(manifest):
                new_local_source_cache[(host_pub, gid)] = {'source': manifest['_local_host_source'],
                                                         'fingerprint': source_fingerprint(manifest)}
                previous = self.library.get(gid, {})
                if previous.get('icon_path') and previous.get('icon_sha256') == manifest.get('icon_sha256'):
                    manifest['icon_path'] = previous['icon_path']
                if previous.get('_art_path') and previous.get('art_sha256') == manifest.get('art_sha256'):
                    manifest['_art_path'] = previous['_art_path']
                new_library[gid] = manifest
                continue
            synced_dir = client_folders[gid]
            # Cache the folder scan per game until its exe fingerprint changes (audit A03). A hit is reused while the
            # folder still exists; a miss is retried after a short delay so a finished download is still noticed.
            folder_cache = self.__dict__.setdefault('_game_folder_cache', {})
            entry = folder_cache.get((host_pub, gid))
            fresh_key = source_fingerprint(manifest)
            if not manifest.get('exe_required', True):
                local_dir = None
            elif (entry and entry['fingerprint'] == fresh_key and
                  ((entry['dir'] and Path(entry['dir']).is_dir() and not reserved_by_other(gid, entry['dir'])
                    and Path(entry['dir']).resolve() not in claimed_folders) or
                   (not entry['dir'] and time.monotonic() - entry['at'] < LauncherCore.GAME_FOLDER_MISS_RETRY))):
                local_dir = entry['dir']
            else:
                local_dir = await run_hash_work(find_game_folder, self.game_root, manifest.get("exe", ""),
                                                manifest.get("exe_size", -1), preferred=synced_dir,
                                                exe_sha256=manifest.get("exe_sha256"),
                                                reserved=({path for other, path in assigned_paths.items() if other != gid}
                                                          | claimed_folders))
                folder_cache[(host_pub, gid)] = {'fingerprint': fresh_key, 'dir': str(local_dir) if local_dir else None,
                                                 'at': time.monotonic()}
            manifest["install_dir"] = str(local_dir or synced_dir)
            if local_dir:
                claimed_folders.add(Path(local_dir).resolve())
            previous = self.library.get(gid, {})
            if (previous.get("install_dir"), previous.get("exe"), previous.get("exe_size")) != (
                    manifest["install_dir"], manifest.get("exe"), manifest.get("exe_size")):
                try:
                    APP_DIR.mkdir(parents=True, exist_ok=True)
                    with (APP_DIR / "game-detection.log").open("a", encoding="utf-8") as log:
                        log.write(json.dumps({"game": gid, "library_root": str(self.game_root),
                                              "host_exe": manifest.get("exe"),
                                              "host_exe_size": manifest.get("exe_size"),
                                              "matched_folder": str(local_dir) if local_dir else None,
                                              "selected_folder": manifest["install_dir"]}) + "\n")
                except OSError:
                    logging.getLogger(__name__).exception("Could not record game detection")
            if manifest.get("icon_sha256"):
                art_path = self.client_art_root / f"{gid}.png"
                try:
                    access = getattr(self, "room_access", None)
                    if await fetch_art(host, port, gid, manifest["icon_sha256"], art_path,
                                       **({"access": access} if access else {})):
                        manifest["icon_path"] = str(art_path)
                except Exception:
                    pass
            if manifest.get("art_sha256"):
                portrait_path = self.client_art_root / f"{gid}_portrait.png"
                try:
                    if manifest["art_sha256"] == manifest.get("icon_sha256") and manifest.get("icon_path"):
                        manifest["_art_path"] = manifest["icon_path"]  # one image serves both
                    elif await fetch_art(host, port, gid, manifest["art_sha256"], portrait_path, kind="portrait",
                                         **({"access": self.room_access} if getattr(self, "room_access", None) else {})):
                        manifest["_art_path"] = str(portrait_path)
                except Exception:
                    pass
            new_library[gid] = manifest
        self._local_host_source_cache = new_local_source_cache
        return self._publish_host_library(new_library)

    GAME_FOLDER_MISS_RETRY = 30  # seconds before a game folder scan that found nothing is repeated

    def _publish_host_library(self, new_library):
        changed = self.library != new_library
        self.library = new_library
        if self.peer_file_server:
            self.peer_file_server.set_shared_files(self._shared_file_map(self.seeded_games & set(self.library)))
        if changed and self.role == "client":
            self.after(0, self._client_library_updated)
        return changed


    def _clear_received_activity(self):
        tracker = getattr(self, "received_activity", None)  # absent on bare cores built without __init__ (tests)
        if tracker is not None:
            tracker.clear()

    def _seeds_received(self, peers):
        self.peer_sources = [peer for peer in peers if isinstance(peer, dict) and
                             peer.get("player_id") != self.config_data.get("player_id") and peer.get("host") and
                             isinstance(peer.get("port"), int) and
                             1 <= peer["port"] <= 65535 and isinstance(peer.get("games"), list)]


    async def _watch_host_library(self, beacon):
        seed_checked = 0
        last_error = None
        delay = 3
        while self.room_controller:
            # Follow the host's latest beacon, but only one for the same host key and room (audit A07).
            current = self.last_beacon
            if (current and current.get("host_pub") == beacon.get("host_pub")
                    and str(current.get("net_id", "")).lower() == str(beacon.get("net_id", "")).lower()):
                beacon = current
            try:
                # Discovery gives us the physical LAN endpoint. Use it while
                # the new overlay path warms up, retaining signature checks.
                changed = True
                for host in dict.fromkeys(filter(None, (beacon.get("host"), beacon["host_zt"]))):
                    started = time.monotonic()
                    try:
                        changed = await self._fetch_host_library(host, beacon.get("sync_port", 47803), LauncherCore._pinned_host_pub(self, beacon))
                    except (OSError, asyncio.TimeoutError, ValueError, RuntimeError) as exc:
                        timing_mark('library.fetch', started, type(exc).__name__)
                        if host == beacon["host_zt"]:
                            raise
                    else:
                        timing_mark('library.fetch', started, 'complete')
                        break
                last_error = None
                # Back off while the library is unchanged, snap back to 3s on any change (audit A03).
                delay = 3 if changed else min(delay * 2, 15)
                if self.peer_file_server and self.presence_client:
                    await self.presence_client.publish_seeds(self.peer_file_server.shared_games,
                                                             self.peer_file_server.port)
                if not self.syncing_game and time.monotonic() - seed_checked >= 60:
                    seed_checked = time.monotonic()
                    await self._seed_existing_games(beacon)
            except (OSError, asyncio.TimeoutError, ValueError, RuntimeError) as exc:
                # Log each new failure once, so a stuck host does not flood the log every 3 seconds.
                message = str(exc) or type(exc).__name__
                if message != last_error:
                    last_error = message
                    logging.getLogger(__name__).warning("Host library refresh failed: %s", message)
                if "host key does not match" in message:
                    self.after(0, self.pages["room"].set_status,
                               "Host key mismatch: this room's host doesn't match your join bundle, so its games are blocked.")
                delay = 3
            await asyncio.sleep(delay)


    def _client_library_updated(self):
        page = self.pages.get("library")
        if page:
            page.set_library(self.library)
        if self.process_watcher:
            watcher = self.process_watcher
            self.process_watcher = None
            def restart_watcher():
                watcher.stop()
                if not self._closing and self.room_controller:
                    self._start_watcher()
            self.runtime.loop.call_soon_threadsafe(restart_watcher)
        elif self.room_controller:
            self._start_watcher()


    async def _watch_host(self):
        transfer_loss_since = None
        while self.room_controller:
            await asyncio.sleep(1)
            if self.room_controller.host_lost():
                # Keep the overlay and partial download available while a brief
                # Host interruption clears. Presence reconnects independently.
                if self.syncing_game and self._sync_future and not self._sync_future.done():
                    if transfer_loss_since is None:
                        transfer_loss_since = time.monotonic()
                        self.after(0, self.pages["room"].set_status,
                                   "Host connection interrupted. Waiting for the room to reconnect…")
                    if time.monotonic() - transfer_loss_since < 90:
                        continue
                self._cancel_sync()
                try:
                    await self.room_controller.leave()
                except Exception as cleanup_error:
                    self._log_room_error(cleanup_error)
                self.room_controller = None
                if self.peer_file_server:
                    await self.peer_file_server.stop()
                    self.peer_file_server = None
                if self.process_watcher:
                    self.process_watcher.stop()
                    self.process_watcher = None
                if self.presence_client:
                    await self.presence_client.stop()
                    self.presence_client = None
                self.library = {}
                self.seeded_games.clear()
                self.seeded_files.clear()
                self._clear_received_activity()
                self.peer_sources = []
                self.after(0, self._client_library_updated)
                self.room = None
                self.discovery_task = None
                self.after(0, self._room_left, None)
                self.after(0, self.pages["room"].set_status, "Host lost. Returned to Ethernet.")
                break
            elif transfer_loss_since is not None:
                transfer_loss_since = None
                self.after(0, self.pages["room"].set_status, "Room connection restored.")


    def _discovered_room_joined(self, beacon):
        self._beacon_joining = False
        if self.role == "client":
            self.pages["library"].set_presence(self.presence_client, self.runtime.loop)
        self.pages["room"].show_room(self.room.code, "Joined")
        joined_status = (f"Joined {beacon.get('pc_name', 'host')}." if getattr(self, '_host_was_chosen', False)
                         else f"Joined {beacon.get('pc_name', 'host')} automatically.")
        if self.room_controller and self.room_controller.adapter_warning:
            joined_status += (" The room connection is active, but Windows couldn't change the network "
                              f"adapter priority: {self.room_controller.adapter_warning}")
        self.pages["room"].set_status(joined_status)
        self.room_nav_status.configure(text=f"In room · {self.room.code}")


    def _discovery_failed(self, error):
        self._discovery_retry_at = time.monotonic() + 3
        self.pages["room"].set_status(f"Couldn't join room: {error}")


    def _host_kicked_me(self):
        if self.role == 'client' and self.room:
            self.leave_room()
            notify = getattr(self, 'ui_message', None)
            if notify:
                notify('showinfo', 'Removed from room', 'The Host removed you from the room.')
            else:
                messagebox.showinfo('Removed from room', 'The Host removed you from the room.', parent=self)

    def leave_room(self, timeout=20):
        async def stop_services():
            self._cancel_sync()
            if self.discovery_task:
                self.discovery_task.cancel()
                self.discovery_task = None
            if self.library_refresh_task:
                self.library_refresh_task.cancel()
                self.library_refresh_task = None
            if self.beacon_transport:
                self.beacon_transport.close()
                self.beacon_transport = None
            if self.host_conflict_transport:
                self.host_conflict_transport.close()
                self.host_conflict_transport = None
            if self.process_watcher:
                self.process_watcher.stop()
                self.process_watcher = None
            async def stop(name, action):
                try:
                    await asyncio.wait_for(action(), max(.1, timeout - 1))
                except Exception as exc:
                    return RuntimeError(f'{name}: {exc or type(exc).__name__}')
            actions = [('file sync prewarm', self._stop_file_sync_prewarm)]
            if getattr(self, 'room_admission', None):
                actions.append(('room admission', self._stop_room_admission))
            for attr in ('room_controller', 'peer_file_server', 'presence_client',
                         'presence_server', 'host_room', 'file_sync_server'):
                member = getattr(self, attr, None)
                if member:
                    async def stop_member(attr=attr, member=member):
                        await (member.leave() if attr == 'room_controller' else member.stop())
                        setattr(self, attr, None)
                    actions.append((attr, stop_member))
            errors = [result for result in await asyncio.gather(*(stop(name, action) for name, action in actions))
                      if result is not None]
            if errors:
                raise RuntimeError('; '.join(str(error) for error in errors))
        def stop_and_report():
            # A hung or failing service stop must not keep busy set or skip the network teardown.
            future = asyncio.run_coroutine_threadsafe(stop_services(), self.runtime.loop)
            try:
                future.result(timeout=timeout)
                return None
            except Exception as exc:  # includes the timeout
                future.cancel()
                self._log_room_error(exc)
                return exc
        self._run_background(stop_and_report, self._leave_network, "Leaving room…")


    def _leave_network(self, stop_error=None):
        def leave():
            errors = [stop_error] if stop_error else []
            for action in (AdapterSwitcher(APP_DIR / 'vla-adapter-state.json').restore,
                           self.tunnel.close_room if self.role == 'host' else self.tunnel.leave):
                try:
                    action()
                except Exception as exc:
                    self._log_room_error(exc)
                    errors.append(exc)
            return RuntimeError('; '.join(str(e) for e in errors)) if errors else None
        self._run_background(leave, lambda error: self._room_left(None, error), "Leaving VLA room…")


    def _room_left(self, _result, stop_error=None):
        self.room = None
        self.room_access = None
        self.last_beacon = None
        self._beacon_joining = False
        if self.role == "client":
            self.pages["library"].set_presence(None)
            self.library = {}
            self.seeded_games.clear()
            self.seeded_files.clear()
            self._clear_received_activity()
            self.peer_sources = []
            self.pages["library"].set_library(self.library)
        self.pages["room"].show_room(None, None)
        self.room_nav_status.configure(text="Not in a room")
        if stop_error:
            self.pages["room"].set_status("Left the room, but some services didn't stop cleanly. See room-errors.log.")


    def save_profile(self, name):
        self.config_data["player_name"] = name.strip() or "Player"
        if not self.config_data.get("player_id"):
            self.config_data["player_id"] = uuid.uuid4().hex
        _write_config(self.config_data)
        if self.presence_client:
            self.presence_client.name = self.config_data["player_name"]
            asyncio.run_coroutine_threadsafe(self.presence_client.push_profile(), self.runtime.loop)

    def save_avatar(self, source, thumb=""):
        """Copy the chosen picture into the launcher's own folder, so it survives the original being moved."""
        import shutil
        src = Path(source)
        if not src.is_file():
            raise ValueError("That picture could not be found.")
        folder = APP_DIR / "profile"
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"avatar-{int(time.time())}-{uuid.uuid4().hex}{src.suffix.lower()}"
        shutil.copyfile(src, dest)
        old = self.config_data.get("avatar")
        self.config_data["avatar"] = str(dest)
        self.config_data["avatar_thumb"] = thumb
        _write_config(self.config_data)
        if old and Path(old) != dest and Path(old).parent == folder and Path(old).is_file():
            Path(old).unlink()
        if self.presence_client:
            self.presence_client.avatar = thumb
            asyncio.run_coroutine_threadsafe(self.presence_client.push_profile(), self.runtime.loop)


    def _start_watcher(self):
        from .presence.watcher import ProcessWatcher
        watch = {}
        for game_id, manifest in self.library.items():
            try:
                from .manifests.loader import resolve_exe
                watch[game_id] = resolve_exe(manifest).name
            except Exception:
                continue
        self.process_watcher = ProcessWatcher(
            watch,
            lambda game: self.presence_client.launch(game) if self.presence_client else None,
            lambda game: self.presence_client.exit(game) if self.presence_client else None,
        )
        self.runtime.loop.call_soon_threadsafe(self.process_watcher.start)


    def save_options(self, keep_installed):
        self.config_data["uninstall_on_exit"] = not keep_installed
        self.tunnel.settings.uninstall_on_exit = not keep_installed
        self.tunnel.save_settings()
        _write_config(self.config_data)


    def _recover(self):
        """Opening the UI never installs networking or changes Windows settings."""
        if self._closing:
            return
        self.pages['room'].set_status(
            'Choose Open Room to start hosting.' if self.role == 'host' else
            'Choose Find host or enter a room key to connect.')

    def _prepare_firewall(self):
        """Check app-scoped rules; elevate only the firewall helper when needed."""
        if not getattr(sys, 'frozen', False):
            return  # Never add firewall rules for a development Python runtime.
        with self._firewall_lock:
            if self._firewall_ready:
                return
            from silent_tunnel.firewall import ensure_rules
            ensure_rules()
            self._firewall_ready = True

    def _recover_network_session(self):
        """Recover stale networking only when a room action was requested."""
        if self._network_session_recovered:
            return
        self._prepare_firewall()
        # Another role owns the same machine-wide VLA membership.
        if not _other_launcher_running(self.role):
            AdapterSwitcher(APP_DIR / 'vla-adapter-state.json').recover_after_crash()
            self.tunnel.recover()
            # Only a recovery that really ran ends the checks. If the other role was running, recovery was skipped,
            # so it must be tried again on the next room action once that role has exited (audit A09).
            self._network_session_recovered = True
        # Remember that a room action used the network, so close() still cleans up after a skipped recovery.
        self._network_session_requested = True


    def _host_conflict_seen(self, beacon):
        if self.role != "host" or not self.host_room:
            return
        foreign_key = beacon.get("host_pub")
        if not foreign_key or foreign_key == self.host_room.host_pub or foreign_key in self._reported_hosts:
            return
        self._reported_hosts.add(foreign_key)
        other_name = beacon.get("pc_name") or "Unknown PC"
        self.after(0, lambda: messagebox.showwarning(
            "Another LAN Host Found",
            f"Another host was found: {other_name}\n\nThis PC is currently hosting as {self.pc_name}.",
            parent=self))


    def add_game_to_repo(self):
        self.manage_game_directory()


    def close(self):
        if self._closing:
            return
        if self.busy:
            messagebox.showinfo("Please wait", "Room setup is still in progress.", parent=self)
            return
        self._closing = True
        self.config_data["uninstall_on_exit"] = self.tunnel.settings.uninstall_on_exit
        try:
            _write_config(self.config_data)
        except (OSError, ValueError):
            logging.getLogger(__name__).exception('Could not save settings while closing; continuing cleanup')
        peer_running = _other_launcher_running(self.role)
        preserve_host_network = _same_role_launcher_running(self.role) or (self.role == 'client' and peer_running)
        network_used = bool(self._network_session_recovered or getattr(self, '_network_session_requested', False)
                            or self.room_controller or self.room or self.host_room)
        self._close_step = 'starting'
        async def step(name, awaitable, timeout=SHUTDOWN_STEP_TIMEOUT):
            # One stuck or failing step must not keep the window open or skip the rest.
            self._close_step = name
            try:
                return await asyncio.wait_for(awaitable, timeout)
            except asyncio.TimeoutError:
                logging.getLogger(__name__).error('Shutdown step timed out after %ss: %s', timeout, name)
            except Exception:
                logging.getLogger(__name__).exception('Shutdown step failed: %s', name)
        async def shutdown():
            if getattr(self, "room_admission", None):
                await step('room admission', self._stop_room_admission())
            await step('file sync prewarm', self._stop_file_sync_prewarm())
            if self.discovery_task:
                self.discovery_task.cancel()
                self.discovery_task = None
            if self.library_refresh_task:
                self.library_refresh_task.cancel()
                self.library_refresh_task = None
            if self.beacon_transport:
                self.beacon_transport.close()
                self.beacon_transport = None
            if self.host_conflict_transport:
                self.host_conflict_transport.close()
                self.host_conflict_transport = None
            if self.room_controller:
                if not preserve_host_network:
                    await step('leave room', self.room_controller.leave())
                self.room_controller = None
            if self.peer_file_server:
                await step('peer file server', self.peer_file_server.stop())
                self.peer_file_server = None
            if self.process_watcher:
                self.process_watcher.stop()
                self.process_watcher = None
            if self.presence_client:
                await step('presence client', self.presence_client.stop())
            if self.presence_server:
                await step('presence server', self.presence_server.stop())
            if self.host_room:
                await step('host room', self.host_room.stop())
            if self.file_sync_server:
                await step('file sync server', self.file_sync_server.stop())
        async def full_shutdown():
            await shutdown()
            if preserve_host_network or not network_used:
                # Stop this Client's own services, but keep the shared adapter,
                # membership, route priority and VLA service used by the Host.
                return []
            uninstall = False if peer_running else None
            return await step('network cleanup', asyncio.get_running_loop().run_in_executor(
                None, lambda: self.tunnel.cleanup(uninstall=uninstall)), timeout=CLEANUP_STEP_TIMEOUT)
        future = self.runtime.submit(full_shutdown())
        future.add_done_callback(lambda _done: self.after(0, self._finish_close))
        # Last resort: if the steps above still hang, close anyway after the deadline.
        self.after(int(CLOSE_DEADLINE * 1000), self._close_deadline)


    def _close_deadline(self):
        if getattr(self, '_close_finished', False):
            return
        logging.getLogger(__name__).error(
            'Shutdown did not finish within %ss; stuck at: %s', CLOSE_DEADLINE, getattr(self, '_close_step', 'unknown'))
        self._finish_close(force=True)

    def _finish_close(self, force=False):
        if getattr(self, '_close_finished', False):
            return
        self.runtime.stop(timeout=0)
        if self.runtime.thread.is_alive():
            if not force:
                # Keep the window/closing indicator alive until executor workers
                # have released their game files instead of hiding a live process.
                self.after(50, self._finish_close)
                return
            logging.getLogger(__name__).error('Closing with background work still running; last step: %s',
                                              getattr(self, '_close_step', 'unknown'))
        self._close_finished = True
        # Hard stop: if anything (e.g. a stuck tunnel cleanup thread) keeps the
        # process alive, force exit 30 seconds after the window is destroyed.
        import os as _os
        import sys as _sys
        import threading as _threading
        if 'pytest' not in _sys.modules:  # never kill the test runner mid-suite
            _killer = _threading.Timer(30.0, _os._exit, args=(0,))
            _killer.daemon = True
            _killer.start()
        self.destroy()



def main():
    local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
    if not getattr(sys, "frozen", False) and local_qt.is_dir():
        sys.path.insert(0, str(local_qt))
    from .qt.main import main as qt_main
    raise SystemExit(qt_main())


if __name__ == "__main__":
    main()
