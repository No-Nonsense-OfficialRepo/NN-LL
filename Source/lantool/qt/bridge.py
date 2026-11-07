"""Qt Quick bridge over the launcher's shared, existing networking core."""
from __future__ import annotations
import asyncio
import copy
import hashlib
import json
import os
import sys
import shlex
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer, QUrl, Qt
from PySide6.QtWidgets import QFileDialog, QApplication, QMessageBox
from .. import launcher as core
from . import joinpack_ui
from . import diagnostics_ui
from . import networking_ui
from . import cleanup_ui
from ..manifests.loader import resolve_exe
from ..game_directory import scan_game_folders
from ..netcore.timing_log import mark as timing_mark, failure as timing_failure
from ..netcore.errors import Code, JoinBudget, JoinError, Stage, as_join_error


class Value:
    def __init__(self, value=None):
        self.value = value

    def set(self, value):
        self.value = value


class RoomAdapter:
    def __init__(self, owner):
        self.owner = owner

    def set_status(self, text):
        self.owner._status = str(text)
        self.owner.publish()

    def show_room(self, code, role):
        self.owner._room_code = code or ""
        self.owner._room_role = role or ""
        if not code:
            self.owner._roster = []
        self.owner.publish()

    def set_roster(self, roster):
        self.owner._roster = [p for p in roster if p.get('player_id') != self.owner.host_presence_player_id]
        self.owner.publish()


class StatusAdapter:
    def __init__(self, owner):
        self.owner = owner

    def configure(self, **kwargs):
        self.owner._nav_status = kwargs.get("text", self.owner._nav_status)
        self.owner.publish()


class LibraryAdapter:
    def __init__(self, owner):
        self.owner = owner
        self.presence = None
        self.previous_counts = None
        self.previous_players = None

    def set_library(self, library):
        self.owner.library = library
        self.owner._disk_changed()
        self.owner.publish()

    def refresh_install_state(self):
        self.owner.publish()

    def set_presence(self, presence, loop=None):
        if self.presence:
            self.presence.on_counts = self.previous_counts
            self.presence.on_players = self.previous_players
        self.presence = presence
        self.previous_counts = getattr(presence, "on_counts", None)
        self.previous_players = getattr(presence, "on_players", None)
        if presence:
            presence.on_counts = self._counts
            presence.on_players = self._players
            self.owner.runtime.submit(presence.subscribe_players())
        else:
            self.owner._counts = {"games": {}, "players": 0}
            self.owner._roster = []
        self.owner.publish()

    def _counts(self, counts):
        self.owner.after(0, self._apply_counts, counts)
        if self.previous_counts:
            self.previous_counts(counts)

    def _apply_counts(self, counts):
        self.owner._counts = counts
        self.owner.publish()

    def _players(self, roster):
        self.owner.after(0, self.owner.pages["room"].set_roster, roster)
        if self.previous_players:
            self.previous_players(roster)


class LauncherBridge(QObject, core.LauncherCore):
    changed = Signal()
    _disk_done = Signal(object)
    queued = Signal(int, object, tuple)
    quitReady = Signal()
    hostLaunchArgsFinished = Signal(str, bool, str)

    def __init__(self, *, start_services=True, preview=False):
        QObject.__init__(self)
        self._destroyed = False
        self._preview = preview
        self._wiping = False
        self._status = "Starting…" if start_services else "Not connected to a room"
        self._nav_status = "Not in a room"
        self._room_code = ""
        self._room_role = ""
        self._roster = []
        self._counts = {"games": {}, "players": 0}
        self._query = ""
        self._filter = "All games"
        self._selected = ""
        self._dialog = {}
        self._discovered_hosts = {}
        self._host_choice_visible = False
        self._host_choice_epoch = 0
        self._host_choice_switch = False
        self._host_collection_started = False
        self._host_choices_dismissed = False
        self._host_was_chosen = False
        self._upgrade = None
        self._upgrade_beacon = None
        self._upgrade_client = None
        self._upgrade_future = None
        self._upgrade_epoch = 0
        self._share_requests = []
        self._progress = {"active": False, "done": 0, "total": 0, "file": "", "game": ""}
        self._events = []
        self._edit = {}
        self._folders = []
        self._host_index_status = {}
        self._host_index_polling = False
        self._offline_index_jobs = set()
        self._index_record_pending = set()
        self._remembered_index_jobs = set()
        self._index_ready_file = core.APP_DIR / 'host_index_ready.json'
        try:
            self._index_ready_records = json.loads(self._index_ready_file.read_text(encoding='utf-8'))
            if not isinstance(self._index_ready_records, dict):
                self._index_ready_records = {}
        except (OSError, ValueError):
            self._index_ready_records = {}
        self._host_args_saving = False
        self._game_prepare_future = None
        self._download_queue = []
        self._queue_message = ''
        self._close_download_confirm = False
        self._download_preparing = None
        self._download_epoch = 0
        self._cancel_delete = None
        self._download_deleting = False
        self._owned_download_folders = set()
        self._download_was_installed = False
        self._leave_after_download = False
        self._setting_tab = "Game Library"
        self._state = {}
        self._diag = {}
        self._pc = {}
        self._network_profiles = []
        self._network_profile_index = 0
        self._network_profile_busy = False
        self._cleanup_confirm = None
        self.queued.connect(self._schedule, Qt.ConnectionType.QueuedConnection)
        self._init_backend()
        self.game_catalog = (core.load_catalog(self.host_catalog_path, self.game_root, self.host_art_root)
                             if self.role == "host" else {})
        self.library = {gid: m for gid, m in self.game_catalog.items() if m.get("enabled")}
        self.pages = {
            "room": RoomAdapter(self),
            "library": LibraryAdapter(self),
            "profile": SimpleNamespace(name=Value()),
            "options": SimpleNamespace(directory=Value(), keep=Value()),
        }
        self.room_nav_status = StatusAdapter(self)
        # Opens on the Room page; first-run clients still start at setup.
        self._page = ("room" if self.role == "host" or self.config_data.get("setup_completed")
                      else "setup")
        self.publish()
        if self.role == 'host':
            self.manage_game_directory()
            self._restore_index_ready()
        if start_services and self._page != "setup":
            self.after(300, self._recover)
        if start_services and not preview:
            self.after(1500, self._show_startup_problems)

    def _show_startup_problems(self):
        """Only actual startup errors open a dialog; advisory notes stay silent."""
        try:
            from .. import startup_checks
            from .. import appdirs
            problems = startup_checks.run(appdirs.app_root(), appdirs.is_portable())
            problems = [problem for problem in problems if problem.severity == startup_checks.ERROR]
        except Exception:
            return
        if not problems:
            return
        lines = [f"{'Problem' if p.severity == startup_checks.ERROR else 'Note'}: {p.message}"
                 + (f"\nFix: {p.fix_hint}" if p.fix_hint else "") for p in problems]
        box = QMessageBox(QMessageBox.Icon.Warning, "Check this install",
                          "Some things may stop LAN Launcher from working:\n\n" + "\n\n".join(lines))
        box.setModal(False)
        box.setWindowModality(Qt.WindowModality.NonModal)
        box.open()
        self._startup_box = box

    def after(self, milliseconds, callback, *args):
        if self._destroyed:
            return
        if milliseconds <= 0 and getattr(callback, '__name__', '') in ('_update_sync_progress', '_update_index_progress'):
            lock = self.__dict__.setdefault('_progress_mailbox_lock', threading.Lock())
            with lock:
                pending = self.__dict__.setdefault('_progress_mailbox', {})
                pending[callback.__name__] = (callback, args)
                if self.__dict__.get('_progress_mailbox_queued', False):
                    return
                self._progress_mailbox_queued = True
            self.queued.emit(0, self._flush_progress_mailbox, ())
        else:
            self.queued.emit(milliseconds, callback, args)

    def _flush_progress_mailbox(self):
        lock = self._progress_mailbox_lock
        with lock:
            pending = self._progress_mailbox
            self._progress_mailbox = {}
            self._progress_mailbox_queued = False
        for callback, args in pending.values():
            callback(*args)

    @Slot(int, object, tuple)
    def _schedule(self, milliseconds, callback, args):
        def invoke():
            if self._destroyed:
                return
            try:
                callback(*args)
            except Exception as exc:
                self.ui_message("showerror", "Operation failed", str(exc))
            self.publish()
        # Already on the GUI thread inside a queued slot: run zero-delay callbacks now. A zero-ms
        # QTimer armed here was not reliably dispatched, so cross-thread state updates were lost.
        if milliseconds <= 0:
            invoke()
        else:
            QTimer.singleShot(milliseconds, invoke)

    def show_page(self, name):
        if name in ('profile', 'activity'):
            self._setting_tab = 'Player' if name == 'profile' else 'Events'
            name = 'settings'
        if not self.config_data.get("setup_completed") and self.role == "client" and name != "about":
            name = "setup"
        self._page = "settings" if name == "options" else name
        if self._page in ("downloads", "room") and not getattr(self, "_activity_ticking", False):
            self._activity_ticking = True
            self.after(1000, self._activity_tick)
        self.publish()

    def _activity_tick(self):
        """Keep the who-is-sending-to-whom lists fresh (publish runs after every after() callback)."""
        if self._destroyed or self._page not in ("downloads", "room"):
            self._activity_ticking = False
            return
        self.after(1000, self._activity_tick)

    def _transfers(self):
        """Game-level seeders/leechers for the Downloads page."""
        from ..transfer_activity import build_transfers
        downloading = self._progress.get("game_id") if self._progress.get("active") else ""
        uploads = []
        for server in (getattr(self, "peer_file_server", None), getattr(self, "file_sync_server", None)):
            if server is not None and getattr(server, "activity", None) is not None:
                uploads += server.activity.snapshot()
        received = self.received_activity.snapshot()
        if self._cancel_delete:
            received = [row for row in received if row['game'] != self._cancel_delete[0]]
        return build_transfers(
            library=self.library, downloading=downloading, seeded=getattr(self, "seeded_games", set()),
            peer_sources=list(getattr(self, "peer_sources", []) or []), roster=self._roster,
            received=received, uploads=uploads,
            host_ip=str((getattr(self, "last_beacon", None) or {}).get("host_zt", "") or ""),
            my_id=self.config_data.get("player_id", ""))

    def _compass(self):
        """Current room peers and verified local transfer directions."""
        from ..transfer_activity import _ip
        peers = {}
        for player in self._roster:
            ip = str(player.get('ip') or '')
            if ip:
                peers[ip] = str(player.get('name') or ip)
        host_ip = str((getattr(self, 'last_beacon', None) or {}).get('host_zt') or '')
        if self.role != 'host' and host_ip:
            peers.setdefault(host_ip, 'Host')
        for source in getattr(self, 'peer_sources', None) or []:
            ip = str(source.get('host') or '')
            if ip and source.get('player_id') != self.config_data.get('player_id'):
                peers.setdefault(ip, str(source.get('name') or ip))
        links = []
        for row in self.received_activity.snapshot():
            ip = _ip(row['who'])
            if row['active'] and ip in peers:
                links.append({'ip': ip, 'direction': 'download', 'game': row['game']})
        for server in (getattr(self, 'peer_file_server', None), getattr(self, 'file_sync_server', None)):
            if server is not None and getattr(server, 'activity', None) is not None:
                for row in server.activity.snapshot():
                    ip = _ip(row['who'])
                    if row['active'] and ip in peers:
                        links.append({'ip': ip, 'direction': 'seed', 'game': row['game']})
        return {'players': [{'ip': ip, 'name': name} for ip, name in peers.items()], 'links': links}

    def _players_with_activity(self):
        """Host player list: each roster player with the games they seed (up) and the games they download from us (down)."""
        def game_entry(gid, active):
            m = self.library.get(gid, {})
            icon = m.get("icon_path") or ""
            url = QUrl.fromLocalFile(str(Path(icon).resolve())).toString() if icon and Path(icon).is_file() else ""
            return {"id": gid, "name": m.get("name", gid), "icon": url, "active": bool(active)}

        seeding_by_pid = {}
        for peer in getattr(self, "peer_sources", None) or []:
            games = [g for g in peer.get("games", []) if g in self.library]
            if games:
                seeding_by_pid[str(peer.get("player_id"))] = games
        leeching_by_ip = {}
        for server in (getattr(self, "peer_file_server", None), getattr(self, "file_sync_server", None)):
            if server is not None and getattr(server, "activity", None) is not None:
                for row in server.activity.snapshot():
                    per_game = leeching_by_ip.setdefault(str(row["who"]), {})
                    per_game[row["game"]] = per_game.get(row["game"], False) or bool(row["active"])
        out = []
        for p in self._roster:
            seeding = [game_entry(g, True) for g in seeding_by_pid.get(str(p.get("player_id", "")), [])]
            leeching = [game_entry(g, active) for g, active in leeching_by_ip.get(str(p.get("ip", "") or ""), {}).items()]
            out.append({**p, "seeding": seeding, "leeching": leeching,
                        "seedingActive": bool(seeding), "leechingActive": any(g["active"] for g in leeching)})
        return out

    @Slot(str)
    def kickPlayer(self, player_id):
        if (self._preview or self.role != 'host' or not self.room or not self.presence_server
                or not any(p.get('player_id') == player_id for p in self._roster)):
            return
        self.runtime.submit(self.presence_server.kick(player_id))

    @Property("QVariantMap", notify=changed)
    def state(self):
        return self._state

    def _launch_args(self, m):
        if self.role == 'host' or self.room:
            return list(m.get('args', []))
        return list(self.config_data.get('launch_arguments', {}).get(m['id'], m.get('args', [])))

    def _disk_changed(self, game_id=None):
        """Drop cached install state and artwork for one game (or all games) so the next publish re-checks them."""
        if game_id is None:
            self._disk_cache = {}
        else:
            getattr(self, "_disk_cache", {}).pop(game_id, None)
        self._disk_at = -1e9
        self._disk_revision = getattr(self, "_disk_revision", 0) + 1

    def _disk_facts(self, m):
        """Installed state and artwork paths for one game. Touches the disk, so it runs on a worker thread
        (or once, for a game with no cached result yet), never on every publish."""
        try:
            if m.get('exe_required', True) is False:
                from ..install_manifest import shared_matches
                installed = self.role == 'host' or self._local_host_source_matches(m) or shared_matches(m.get('install_dir', ''), m['id'])
            else:
                executable = resolve_exe(m)
                size = m.get("exe_size")
                installed = executable.is_file() and (
                    self.role == "host" or size is None or executable.stat().st_size == size)
        except (ValueError, OSError):
            installed = False
        artwork = m.get("_art_path") or ""
        art = str(Path(artwork).resolve()) if artwork and Path(artwork).is_file() else ""
        icon = str(Path(m["icon_path"]).resolve()) if m.get("icon_path") and Path(m["icon_path"]).is_file() else ""
        from ..install_manifest import is_pending
        folder = m.get("install_dir") or m.get("_dir") or ""
        pending = is_pending(folder)  # a sync started and never finished: not complete, even if the exe is there
        return {"installed": bool(installed) and not pending, "pending": pending, "art": art, "icon": icon}

    def _disk_for(self, m):
        """Cached disk facts for a game. Computed here only the first time a game is seen."""
        cache = getattr(self, "_disk_cache", None)
        if cache is None:
            cache = self._disk_cache = {}
        if m["id"] not in cache:
            cache[m["id"]] = self._disk_facts(m)
        return cache[m["id"]]

    def _maybe_refresh_disk(self):
        """Re-check install state and artwork on a worker thread, at most every 3 seconds."""
        since = time.monotonic() - getattr(self, "_disk_at", -1e9)
        if getattr(self, "_disk_busy", False) or since < 3.0:
            # too soon: retry from a timer, so an install or removal still shows up without another publish
            if not getattr(self, "_disk_pending", False):
                self._disk_pending = True
                QTimer.singleShot(250 if getattr(self, "_disk_busy", False) else 3050, self._run_pending_disk_refresh)
            return
        self._disk_busy = True
        self._disk_at = time.monotonic()
        if not getattr(self, "_disk_connected", False):
            self._disk_done.connect(self._on_disk_done)
            self._disk_connected = True
        games = list(self.library.values())
        revision = getattr(self, "_disk_revision", 0)

        def work():
            facts = {}
            for m in games:
                try:
                    facts[m["id"]] = self._disk_facts(m)
                except Exception:
                    facts[m["id"]] = {"installed": False, "art": "", "icon": ""}
            self._disk_done.emit((revision, facts))

        threading.Thread(target=work, daemon=True, name="disk-facts").start()

    def _run_pending_disk_refresh(self):
        self._disk_pending = False
        self._maybe_refresh_disk()

    @Slot(object)
    def _on_disk_done(self, result):
        self._disk_busy = False
        revision, facts = result
        if revision != getattr(self, "_disk_revision", 0):
            if not self._destroyed:
                self._maybe_refresh_disk()
            return
        if facts != getattr(self, "_disk_cache", None):
            self._disk_cache = facts
            if not self._destroyed:
                self.publish()

    def _game(self, m):
        facts = self._disk_for(m)
        installed = facts["installed"]
        from ..manifests.loader import is_running
        art = QUrl.fromLocalFile(facts["art"]).toString() if facts["art"] else ""
        icon = QUrl.fromLocalFile(facts["icon"]).toString() if facts["icon"] else ""
        counts = self._counts.get("games", {}).get(m["id"], {})
        return {"id": m["id"], "name": m["name"], "installed": installed,
                "exeRequired": m.get('exe_required', True),
                "art": art, "icon": icon, "playing": counts.get("playing", 0), "exe": m.get("exe", ""),
                "args": shlex.join(self._launch_args(m)),
                "argsManagedByHost": self.role == 'client' and bool(self.room),
                "directory": str(m.get("install_dir", "")),
                "enabled": m.get("enabled", True), "running": is_running(m["id"]),
                "seeding": m["id"] in getattr(self, "seeded_games", ()), "incomplete": bool(facts.get("pending", False))}

    def publish(self):
        if self._destroyed:
            return
        if (self.role == 'host' and self.room and self.file_sync_server
                and callable(getattr(self.file_sync_server, 'index_status', None))
                and not self._host_index_polling):
            self._host_index_polling = True
            self.after(500, self._poll_host_index_status)
        self._maybe_refresh_disk()
        games = [self._game(m) for m in sorted(self.library.values(), key=lambda m: m["name"].casefold())]
        visible = [g for g in games if self._query.casefold() in g["name"].casefold()
                   and (self._filter != "Installed" or g["installed"])
                   and (self._filter != "Playing" or g["playing"])]
        selected = next((g for g in games if g["id"] == self._selected), {})
        self._state = {
            "page": self._page, "host": self.role == "host", "version": core.__release__,
            "pcName": self.pc_name, "playerName": self.config_data.get("player_name", "Player"), "avatar": self.config_data.get("avatar", ""),
            "gameDirectory": str(self.game_root), "keepInstalled": not self.tunnel.settings.uninstall_on_exit,
            "games": visible, "allGames": games, "gameCount": len(games), "selected": selected,
            "query": self._query, "filter": self._filter, "connected": bool(self.room),
            "roomCode": self._room_code, "roomRole": self._room_role,
            "hostChoices": sorted(({"id": key, "name": beacon.get("pc_name") or "Host",
                                    "address": beacon.get("host") or "", "room": beacon.get("net_id") or ""}
                                   for key, beacon in self._discovered_hosts.items()),
                                  key=lambda row: (row["name"].casefold(), row["address"])),
            "hostChoiceVisible": self._host_choice_visible,
            "hostLanIp": getattr(self.host_room, 'ip', '') or '',
            "status": self._status, "navStatus": self._nav_status,
            "players": self._players_with_activity(), "playerCount": len(self._roster) if self.role == 'host' else len(self._roster) or self._counts.get("players", 0),
            "busy": bool(self.busy or self.syncing_game), "closing": self._closing,
            "repairing": self._wiping,
            "networkProfiles": self._network_profiles, "networkProfileIndex": self._network_profile_index,
            "networkProfileBusy": self._network_profile_busy,
            "dialog": self._dialog, "progress": self._progress, "events": self._events,
            "launcherUpgrade": self._upgrade, "launcherShareRequests": self._share_requests,
            "downloadQueue": [{"id": gid, "name": self.library[gid]["name"], "position": i + 1}
                              for i, gid in enumerate(self._download_queue) if gid in self.library],
            "downloadActive": bool(self.syncing_game or self._download_preparing),
            "queueMessage": self._queue_message,
            "closeDownloadConfirm": self._close_download_confirm,
            "catalog": [{**row, 'index': self._host_index_status.get(row['id'], {})}
                        for row in self._folders], "edit": self._edit, "settingsTab": self._setting_tab,
            "hostArgsSaving": self._host_args_saving, "diag": self._diag, "pc": getattr(self, "_pc", {}), "cleanupConfirm": getattr(self, "_cleanup_confirm", None),
            "preview": self._preview,
            "roomPasswordPrompt": getattr(self, "_room_password_prompt", None),
            "roomApproval": self._first_room_approval(),
            "roomBlacklist": getattr(self, "_room_admission_snapshot", {}).get("blacklist", []),
            "transfers": self._transfers() if self._page == "downloads" else [], "compass": self._compass() if self._page == "room" else {"players": [], "links": []},
        }
        self.changed.emit()

    def _publish_progress(self):
        """Light update for download progress and transfer ticks. Reuses the last game list, so the UI thread
        does not re-check every game on disk several times a second (that stalled hover and button clicks)."""
        if self._destroyed or not getattr(self, "_state", None):
            return self.publish()
        self._state = {**self._state, "progress": self._progress, "players": self._players_with_activity(),
                       "busy": bool(self.busy or self.syncing_game),
                       "transfers": self._transfers() if self._page == "downloads" else []}
        self.changed.emit()

    def ui_message(self, kind, title, message, stage="", code="", hint=""):
        """stage/code/hint are optional (JoinError details); QML shows them when present."""
        if isinstance(message, JoinError):
            stage, code, hint = stage or message.stage.value, code or message.code, hint or message.hint
        upgrade = getattr(self, '_upgrade', None)
        if (upgrade and upgrade.get('status') == 'mismatch'
                and ('version mismatch' in str(message).lower() or 'connection protocol' in str(message).lower())):
            self.publish()
            return
        detail = {"stage": str(stage or ""), "code": str(code or ""), "hint": str(hint or "")}
        self._dialog = {"title": title, "message": str(message), "error": kind == "showerror", **detail}
        self._events.insert(0, {"title": title, "message": str(message), **detail})
        self._events = self._events[:50]
        self.publish()
        LauncherBridge._maybe_auto_diagnose(self, kind, stage)

    def _maybe_auto_diagnose(self, kind, stage):
        """After a staged join failure, quietly run the read-only check so the report is ready.

        Throttled to once per 2 minutes; the popup's Run diagnostic button opens the result."""
        if kind != "showerror" or not stage or getattr(self, "_preview", False):
            return
        now = time.monotonic()
        if now - getattr(self, "_auto_diag_at", -1e9) < 120:
            return
        start = getattr(self, "_start_diag", None)
        if start is None or (getattr(self, "_diag", None) or {}).get("running"):
            return
        self._auto_diag_at = now
        start(None)

    @Slot()
    def dismissDialog(self):
        self._dialog = {}
        self.publish()

    @Slot()
    def diagnoseFromDialog(self):
        """Join-failure popup 'Run diagnostic': close it, open Settings > Diagnostics, run the check."""
        self._dialog = {}
        self._setting_tab = 'Diagnostics'
        self.show_page('settings')
        self._start_diag(None)
        self.publish()

    def choose_file(self, title="Choose file"):
        return QFileDialog.getOpenFileName(None, title)[0]

    @Slot(str, result=str)
    @Slot(str, str, result=str)
    def chooseFile(self, kind, folder=""):
        filters = {"bundle": "Host bundle (*.json)", "art": "Images (*.png *.jpg *.jpeg *.webp *.ico *.bmp)",
                   "exe": "Windows executable (*.exe)"}
        start = str(Path(folder).resolve()) if folder and Path(folder).is_dir() else ""
        return QFileDialog.getOpenFileName(None, "Choose " + kind, start, filters.get(kind, "All files (*)"))[0]

    @Slot(result=str)
    def chooseDirectory(self):
        return QFileDialog.getExistingDirectory(None, "Choose game directory", str(self.game_root))

    @Slot(str)
    def navigate(self, page):
        if page == "catalog":
            self.manage_game_directory()
            return
        if page == "profile" and self.role == "host":
            page = "room"
        self.show_page(page)

    @Slot(str)
    def search(self, query):
        self._query = query
        self.publish()

    @Slot(str)
    def filterGames(self, value):
        self._filter = value
        self.publish()

    @Slot(str)
    def selectGame(self, gid):
        if gid in self.library:
            self._selected = gid
            self.show_page("details")

    @Slot()
    def play(self):
        self._game_action(False)

    # Library quick-action cubes: act on a game without leaving the library page.
    @Slot(str)
    def playGame(self, gid):
        if gid in self.library:
            self._selected = gid
            self.play()

    @Slot(str)
    def installGame(self, gid):
        if gid in self.library:
            self._game_action(True, game_id=gid, show_downloads=False)

    @Slot(str)
    def stopGame(self, gid):
        from ..manifests.loader import stop
        if stop(gid):
            self.publish()

    @Slot(str)
    def recheckGameIndex(self, gid):
        if self._preview or self.role != 'host':
            return
        manifest = self.library.get(gid)
        if not manifest:
            self.ui_message('showerror', 'Index unavailable', 'Share this game and choose its executable before refreshing its index.')
            return
        if gid in self._offline_index_jobs or self._host_index_status.get(gid, {}).get('state') == 'running':
            return
        self._host_index_status[gid] = {'state': 'running', 'done': 0, 'total': 0,
                                        'files_done': 0, 'files_total': 0}
        self._status = f"Rechecking {manifest['name']} index…"
        self.publish()
        if self.room and self.file_sync_server:
            future = self.runtime.submit(self.file_sync_server.recheck_index(gid))
        else:
            self._offline_index_jobs.add(gid)
            future = self.runtime.submit(self._recheck_offline_index(gid, Path(manifest['_game_dir'])))
        def finished(done):
            try:
                done.result()
                message = f"{manifest['name']} index is ready."
                state = 'ready'
            except Exception as exc:
                message = f"Could not recheck {manifest['name']}: {exc}"
                state = 'error'
            self.after(0, self._set_recheck_status, message, gid, state)
        future.add_done_callback(finished)

    async def _recheck_offline_index(self, gid, folder):
        from ..filesync.index import SqliteHashCache, build_index, run_hash_work
        def hash_game(*, cancelled=None):
            cache = SqliteHashCache(core.APP_DIR / 'file_hash_cache.sqlite3')
            last_update = [0.0]
            def progress(done, total, files_done, files_total, _filename):
                now = time.monotonic()
                if done == total or now - last_update[0] >= .1:
                    last_update[0] = now
                    self.after(0, self._set_offline_index_progress, gid, done, total, files_done, files_total)
            try:
                return build_index(gid, folder, cache, cancelled=cancelled, progress=progress, verify=True)
            finally:
                cache.close()
        return await run_hash_work(hash_game)

    def _set_offline_index_progress(self, gid, done, total, files_done, files_total):
        if gid in self._offline_index_jobs:
            self._host_index_status[gid] = {'state': 'running', 'done': done, 'total': total,
                                            'files_done': files_done, 'files_total': files_total}

    def _set_recheck_status(self, message, gid=None, state=None):
        if gid in self._offline_index_jobs:
            self._offline_index_jobs.remove(gid)
        if gid and state:
            self._host_index_status[gid] = {'state': state, 'done': 1, 'total': 1,
                                            'error': message if state == 'error' else ''}
        self._status = message
        self.publish()
        if gid and state == 'ready':
            self._remember_index_ready(gid)

    @staticmethod
    def _index_folder_fingerprint(folder, *, cancelled=None):
        from ..filesync.server import _tree_fingerprint
        rows = _tree_fingerprint(folder, cancelled=cancelled)
        return hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode('utf-8')).hexdigest()

    @staticmethod
    def _cached_index_fingerprint(folder, cache_path, *, cancelled=None):
        """Recognize a complete older index without trusting partial cache entries."""
        import re
        from ..filesync.server import _tree_fingerprint
        from ..filesync.index import CHUNK, SqliteHashCache
        rows = _tree_fingerprint(folder, cancelled=cancelled)
        if not rows or not Path(cache_path).is_file():
            return ''
        cache = SqliteHashCache(cache_path)
        try:
            for rel, size, mtime in rows:
                if cancelled and cancelled():
                    return ''
                entry = cache._lookup(str(Path(folder) / rel))
                if not entry or entry[0] != size or entry[1] != mtime or len(entry) < 4 or \
                        not isinstance(entry[2], str) or not re.fullmatch(r'[0-9a-f]{64}', entry[2]) or \
                        not isinstance(entry[3], list) or len(entry[3]) != (size + CHUNK - 1) // CHUNK:
                    return ''
        finally:
            cache.close()
        return hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode('utf-8')).hexdigest()

    def _save_index_ready_records(self):
        self._index_ready_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self._index_ready_file.with_suffix('.json.tmp')
        temp.write_text(json.dumps(self._index_ready_records, sort_keys=True), encoding='utf-8')
        os.replace(temp, self._index_ready_file)

    def _remember_index_ready(self, gid):
        game = self.game_catalog.get(gid)
        if not game or gid in self._index_record_pending:
            return
        folder = str(Path(game['_game_dir']).resolve())
        self._index_record_pending.add(gid)
        from ..filesync.index import run_hash_work
        future = self.runtime.submit(run_hash_work(self._index_folder_fingerprint, folder))
        def finished(done):
            try:
                fingerprint = done.result()
            except Exception:
                fingerprint = ''
            self.after(0, self._finish_index_record, gid, folder, fingerprint)
        future.add_done_callback(finished)

    def _finish_index_record(self, gid, folder, fingerprint):
        self._index_record_pending.discard(gid)
        if fingerprint and gid in self.game_catalog and str(Path(self.game_catalog[gid]['_game_dir']).resolve()) == folder:
            record = {'folder': folder, 'fingerprint': fingerprint}
            if self._index_ready_records.get(gid) != record:
                self._index_ready_records[gid] = record
                self._save_index_ready_records()

    def _restore_index_ready(self):
        records = dict(self._index_ready_records)
        cache_path = core.APP_DIR / 'file_hash_cache.sqlite3'
        if not records and not cache_path.is_file():
            return
        from ..filesync.index import run_hash_work
        async def check():
            result = {}
            recovered = {}
            for gid, game in self.game_catalog.items():
                if not game.get('enabled'):
                    continue
                folder = str(Path(game['_game_dir']).resolve())
                record = records.get(gid)
                try:
                    if isinstance(record, dict) and folder == record.get('folder'):
                        fingerprint = await run_hash_work(self._index_folder_fingerprint, folder)
                        if fingerprint == record.get('fingerprint'):
                            result[gid] = {'state': 'ready', 'done': 1, 'total': 1}
                            continue
                    fingerprint = await run_hash_work(self._cached_index_fingerprint, folder, cache_path)
                except (OSError, ValueError):
                    continue
                if fingerprint:
                    result[gid] = {'state': 'ready', 'done': 1, 'total': 1}
                    recovered[gid] = {'folder': folder, 'fingerprint': fingerprint}
            self.after(0, self._apply_restored_index_ready, result, recovered)
        self.runtime.submit(check())

    def _apply_restored_index_ready(self, result, recovered):
        for gid, status in result.items():
            if gid not in self._offline_index_jobs and self._host_index_status.get(gid, {}).get('state') != 'running':
                self._host_index_status[gid] = status
        if recovered:
            self._index_ready_records.update(recovered)
            self._save_index_ready_records()

    def _poll_host_index_status(self):
        server = self.file_sync_server
        if self._destroyed or self.role != 'host' or not self.room or not server:
            self._host_index_polling = False
            self._host_index_status = {gid: status for gid, status in self._host_index_status.items()
                                       if status.get('state') == 'ready'}
            return
        future = self.runtime.submit(server.index_status())
        def finished(done):
            try:
                status = done.result()
            except Exception:
                status = {}
            self.after(0, self._update_host_index_status, server, status)
        future.add_done_callback(finished)

    def _update_host_index_status(self, server, status):
        if server is self.file_sync_server and self.room:
            self._host_index_status.update(status)
            for gid, item in status.items():
                job_id = item.get('job_id')
                if item.get('state') == 'ready' and (gid not in self._index_ready_records or
                                                     job_id and job_id not in self._remembered_index_jobs):
                    if job_id:
                        self._remembered_index_jobs.add(job_id)
                    self._remember_index_ready(gid)
            self.after(500, self._poll_host_index_status)
        else:
            self._host_index_polling = False

    @Slot()
    def refreshRunning(self):
        # Polled by the library while it is open, so Stop turns back into Play when a game exits.
        self.publish()

    @Slot()
    def install(self):
        self._game_action(True)

    @Slot()
    def verifyIntegrity(self):
        """Re-check every file of the selected game against the host's signed index; re-download anything that differs."""
        if self.busy or self.syncing_game:
            return
        self._verify_next_sync = True
        self.install()

    def _game_action(self, install_only, *, game_id=None, show_downloads=True):
        if self._download_deleting:
            return
        gid = game_id if game_id is not None else self._selected
        if self.busy or self.syncing_game:
            if (install_only and not self._preview and self.role == 'client' and self.room
                    and gid in self.library
                    and (self.syncing_game or self._download_preparing is not None)):
                active = self._progress.get('game_id') if self._progress.get('active') else None
                if gid not in (active, self._download_preparing) and gid not in self._download_queue:
                    self._download_queue.append(gid)
                    self.publish()
            return
        if self._preview:
            self.ui_message("showinfo", "Design preview", "Game launching is disabled in preview mode.")
            return
        m = self.library.get(game_id if game_id is not None else self._selected)
        if m:
            m = dict(m)
            m["args"] = self._launch_args(m)
            context = self._launch_context()
            if self.role != 'client':
                if not install_only:
                    self._play_game(m, context)
                return
            if install_only and not self.room:
                self.ui_message('showinfo', 'Join a room', 'Connect to the Host before installing a game.')
                return
            self.busy = True
            self._download_was_installed = bool(self._disk_for(m).get('installed'))
            self._download_preparing = gid
            epoch = self._download_epoch
            self._status = 'Checking local game files…'
            async def prepare():
                from ..filesync.index import run_hash_work
                return await run_hash_work(self._prepare_client_game, m)
            future = core.submit_drained(self.runtime.loop, prepare())
            self._game_prepare_future = future
            def finished(done):
                try:
                    ready, error = done.result(), None
                except Exception as exc:
                    ready, error = False, exc
                self.after(0, self._game_prepared, m, context, install_only, ready, error, show_downloads, epoch)
            future.add_done_callback(finished)
            self.publish()

    def _game_prepared(self, manifest, context, install_only, ready, error, show_downloads=True, epoch=None):
        if epoch is not None and epoch != self._download_epoch:
            if self._download_preparing == manifest['id'] and self._game_prepare_future is None:
                self._download_preparing = None
                self.busy = False
                self.publish()
            return
        self._game_prepare_future = None
        self._download_preparing = None
        self.busy = False
        if self._closing:
            return
        if self._cancel_delete and self._cancel_delete[0] == manifest['id']:
            gid, folder = self._cancel_delete
            self._cancel_delete = None
            self._delete_cancelled_game(folder, gid)
            return
        if self._leave_after_download:
            self._leave_after_download = False
            self.leave_room()
            return
        if error:
            import concurrent.futures
            if not isinstance(error, concurrent.futures.CancelledError):
                self.ui_message('showerror', 'Could not check game files', str(error))
        else:
            if manifest['id'] in self.library:
                self.library[manifest['id']]['install_dir'] = manifest['install_dir']
                if self._local_host_source_matches(manifest):
                    self.library[manifest['id']]['_local_host_source'] = manifest['_local_host_source']
            if install_only:
                if self._local_host_source_matches(manifest):
                    self._status = f"{manifest['name']} is already available in the Host's game directory."
                else:
                    self._sync_then_play(manifest, context, launch_after=False, show_downloads=show_downloads)
            else:
                self._status = 'Ready to play.' if ready else 'Choose Install to download this game.'
                self._play_game(manifest, context, client_ready=ready)
        self.publish()
        self._start_next_download()

    @Slot(str)
    def removeQueuedDownload(self, gid):
        if gid in self._download_queue:
            self._download_queue.remove(gid)
            self._queue_message = f"Removed {self.library[gid]['name']} from the queue."
            self.publish()

    @Slot(str)
    def prioritizeDownload(self, gid):
        if gid not in self._download_queue:
            return
        self._download_queue.remove(gid)
        self._download_queue.insert(0, gid)
        self._queue_message = f"{self.library[gid]['name']} is next to download."
        self._preempt_active_download()
        self._start_next_download()
        self.publish()

    @Slot(str, int)
    def moveQueuedDownload(self, gid, direction):
        if gid not in self._download_queue:
            return
        pos = self._download_queue.index(gid)
        target = max(0, min(len(self._download_queue) - 1, pos + direction))
        self._download_queue.insert(target, self._download_queue.pop(pos))
        shown_position = target + 1 + bool(self.syncing_game or self._download_preparing)
        self._queue_message = f"{self.library[gid]['name']} moved to queue position {shown_position}."
        self.publish()

    @Slot()
    def moveActiveDownloadDown(self):
        if self._download_queue:
            active = self._progress.get('game_id') if self._progress.get('active') else self._download_preparing
            next_game = self._download_queue[0]
            if active in self.library and next_game in self.library:
                self._queue_message = f"Starting {self.library[next_game]['name']} next; {self.library[active]['name']} will resume later."
            self._preempt_active_download()

    def _preempt_active_download(self):
        active = self._progress.get('game_id') if self._progress.get('active') else self._download_preparing
        if not active or active in self._download_queue:
            return
        self._download_queue.append(active)
        if self.syncing_game:
            # The cancelled transfer leaves verified pieces and the pending
            # marker in place; the queued restart uses the normal resume path.
            core.LauncherCore._cancel_sync(self)
        elif self._download_preparing:
            self._download_epoch += 1
            if self._game_prepare_future:
                self._game_prepare_future.cancel()
            self._game_prepare_future = None
            self._download_preparing = None
            self.busy = False
            self._start_next_download()
        self.publish()

    def _start_next_download(self):
        if self._closing or not self.room:
            self._download_queue.clear()
            self._queue_message = ''
            return
        if self.busy or self.syncing_game or self._download_deleting:
            return
        while self._download_queue:
            gid = self._download_queue.pop(0)
            if gid in self.library:
                # Keep the user's current page and selected game intact.
                self._game_action(True, game_id=gid, show_downloads=False)
                break
        if not self._download_queue and not self.syncing_game and not self._download_preparing:
            self._queue_message = ''
        self.publish()

    def _sync_finished(self, manifest, context, result, error, launch_after=True):
        try:
            super()._sync_finished(manifest, context, result, error, launch_after)
        finally:
            if self._cancel_delete and self._cancel_delete[0] == manifest.get('id'):
                cancelled_gid, folder = self._cancel_delete
                self._cancel_delete = None
                self._delete_cancelled_game(folder, cancelled_gid)
            elif self._leave_after_download:
                self._leave_after_download = False
                self.leave_room()
            else:
                self._start_next_download()

    @Slot()
    def cancelDownload(self):
        """Cancel the active transfer and remove only its managed game folder."""
        gid = self._progress.get('game_id') if self._progress.get('active') else self._download_preparing
        manifest = self.library.get(gid)
        if not manifest or not (self.syncing_game or self._download_preparing):
            return
        folder = manifest.get('install_dir')
        if self._download_was_installed:
            self.ui_message('showinfo', 'Installed game kept',
                            'This game was installed before verification began. Pause the transfer or leave the room to keep its files.')
            return
        if not self._safe_download_folder(folder, gid):
            self._status = 'Download cancelled. Preexisting files were kept.'
            if self.syncing_game:
                core.LauncherCore._cancel_sync(self)
            elif self._game_prepare_future:
                self._game_prepare_future.cancel()
            self.publish()
            return
        self._cancel_delete = (gid, folder)
        self._queue_message = ''
        if self.syncing_game:
            core.LauncherCore._cancel_sync(self)
        else:
            if self._game_prepare_future:
                self._game_prepare_future.cancel()
            else:
                self._download_preparing = None
                self.busy = False
                self._cancel_delete = None
                self._delete_cancelled_game(folder, gid)
        self.publish()

    def _safe_download_folder(self, folder, cancelled_gid=None):
        if not folder:
            return False
        path = Path(folder)
        root = Path(self.game_root).resolve()
        cancelled_gid = cancelled_gid or (self._cancel_delete[0] if self._cancel_delete else self._progress.get('game_id') or self._download_preparing)
        return (str(path.resolve()) in getattr(self, '_owned_download_folders', set())
                and path.resolve().parent == root and path != root
                and not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)()
                and all(other.get('install_dir') != str(path) for gid, other in self.library.items()
                        if gid != cancelled_gid))

    def _delete_cancelled_game(self, folder, cancelled_gid=None):
        import shutil
        self._download_deleting = True
        self.busy = True
        def work():
            error = ''
            try:
                peer = self.peer_file_server
                if peer:
                    self.runtime.submit(peer.pause_and_drain()).result()
                if self._safe_download_folder(folder, cancelled_gid):
                    shutil.rmtree(folder) if Path(folder).is_dir() else None
                    self._owned_download_folders.discard(str(Path(folder).resolve()))
                else:
                    error = 'The game folder changed while cancelling. No files were removed.'
            except Exception as exc:
                error = str(exc)
            self.after(0, self._cancel_delete_finished, error, cancelled_gid)
        try:
            threading.Thread(target=work, daemon=True, name='cancel-download-cleanup').start()
        except Exception as exc:
            self._cancel_delete_finished(str(exc) or type(exc).__name__, cancelled_gid)

    def _cancel_delete_finished(self, error, cancelled_gid):
        self._download_deleting = False
        self.busy = False
        if self.peer_file_server:
            self.runtime.loop.call_soon_threadsafe(self.peer_file_server.set_paused, False)
        if not error:
            self.received_activity.clear_game(cancelled_gid)
        if error:
            self.ui_message('showerror', 'Could not remove download', error)
        else:
            self._status = 'Download cancelled and its game folder removed.'
            self._disk_changed(None)
        if self._leave_after_download:
            self._leave_after_download = False
            self.leave_room()
        else:
            self._start_next_download()

    def _clear_download_queue(self):
        # Host loss may call _cancel_sync on the networking thread. Invalidate
        # preparation before its queued completion can start a stale transfer.
        self._download_epoch += 1
        self._download_queue.clear()
        self._queue_message = ''

    def _cancel_sync(self):
        self._clear_download_queue()
        super()._cancel_sync()
        self.after(0, self.publish)

    @Slot(str)
    def saveLaunchArgs(self, arguments):
        if self._selected not in self.library:
            return
        if self.role == 'client' and self.room:
            self.ui_message('showinfo', 'Managed by the Host', 'The Host sets launch parameters for this room. Ask the Host to update this game.')
            return
        try:
            args = shlex.split(arguments)
            self.config_data.setdefault("launch_arguments", {})[self._selected] = args
            core._write_config(self.config_data)
            self.ui_message("showinfo", "Game settings saved", "Your launch arguments have been saved on this PC.")
        except (OSError, ValueError) as exc:
            self.ui_message("showerror", "Couldn't save game settings", str(exc))

    @Slot(str, str, bool, str)
    def finishSetup(self, name, directory, keep, bundle):
        try:
            self.complete_setup(name, directory, keep, bundle)
            if self._preview:
                self._page = "library"
            self.publish()
        except Exception as exc:
            self.ui_message("showerror", "Couldn't save setup", str(exc))

    def _recover(self):
        if not self._preview and not self._wiping:
            super()._recover()

    @Slot()
    def wipeVLA(self):
        cleanup_ui.wipe_vla(self)

    @Slot()
    def wipeZeroTier(self):
        # Compatibility for earlier QML builds: only launcher-owned VLA is removed.
        self.wipeVLA()

    def _wipeFinished(self, result, error):
        cleanup_ui.wipe_finished(self, result, error)

    @Slot(str)
    def saveProfile(self, name):
        try:
            if not name.strip():
                raise ValueError("Enter a player name.")
            self.save_profile(name)
            self.ui_message("showinfo", "Profile saved", "Your player name has been saved.")
        except Exception as exc:
            self.ui_message("showerror", "Couldn't save profile", str(exc))

    @Slot(str)
    def setAvatar(self, path):
        try:
            from PySide6.QtCore import QBuffer, QIODevice, Qt
            from PySide6.QtGui import QImage
            image = QImage(path)
            if image.isNull():
                raise ValueError("That picture could not be read.")
            image = image.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            image = image.copy((image.width() - 64) // 2, (image.height() - 64) // 2, 64, 64)
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "JPG", 80)
            thumb = "data:image/jpeg;base64," + bytes(buffer.data().toBase64()).decode("ascii")
            self.save_avatar(path, thumb)
        except Exception as exc:
            self.ui_message("showerror", "Couldn't set picture", str(exc))
        self.publish()

    @Slot(str, float, float, float)
    def setAvatarCrop(self, path, zoom, horizontal, vertical):
        """Save the square selected in the profile editor and share that same crop."""
        try:
            import tempfile
            from pathlib import Path
            from PySide6.QtCore import QBuffer, QIODevice, Qt
            from PySide6.QtGui import QImage
            image = QImage(path)
            if image.isNull():
                raise ValueError("That picture could not be read.")
            zoom = max(1.0, min(3.0, float(zoom)))
            horizontal = max(0.0, min(1.0, float(horizontal)))
            vertical = max(0.0, min(1.0, float(vertical)))
            side = max(1, int(min(image.width(), image.height()) / zoom))
            left = round((image.width() - side) * horizontal)
            top = round((image.height() - side) * vertical)
            cropped = image.copy(left, top, side, side)
            thumb_image = cropped.scaled(64, 64, Qt.AspectRatioMode.IgnoreAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            thumb_image.save(buffer, "JPG", 80)
            thumb = "data:image/jpeg;base64," + bytes(buffer.data().toBase64()).decode("ascii")
            with tempfile.TemporaryDirectory(prefix="lan-avatar-") as temp:
                cropped_path = Path(temp) / "avatar.jpg"
                if not cropped.save(str(cropped_path), "JPG", 92):
                    raise ValueError("The cropped picture could not be saved.")
                self.save_avatar(str(cropped_path), thumb)
        except Exception as exc:
            self.ui_message("showerror", "Couldn't set picture", str(exc))
        self.publish()

    @Slot(str, bool)
    def saveSettings(self, directory, keep):
        try:
            self.set_game_directory(directory)
            self.save_options(keep)
            if self.role == 'host':
                self.manage_game_directory()
            self.ui_message("showinfo", "Settings saved", "Your launcher preferences have been saved.")
        except Exception as exc:
            self.ui_message("showerror", "Couldn't save settings", str(exc))

    @Slot(str)
    def settingsTab(self, tab):
        self._setting_tab = 'Network' if tab == 'General' else tab
        self.publish()
        if self._setting_tab == 'Network':
            refresh = getattr(self, 'refreshPcStatus', None)
            if refresh:
                refresh()
            self.refreshNetworkProfiles()

    @Slot()
    def refreshNetworkProfiles(self):
        if self._preview or self._network_profile_busy:
            return
        def read():
            try:
                from silent_tunnel.prepare import _powershell_json
                data = _powershell_json(
                    "Get-NetConnectionProfile | Select-Object "
                    "@{n='name';e={[string]$_.InterfaceAlias}},"
                    "@{n='index';e={[int]$_.InterfaceIndex}},"
                    "@{n='category';e={[string]$_.NetworkCategory}} | ConvertTo-Json -Compress")
                rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
                profiles = [r for r in rows if isinstance(r, dict) and isinstance(r.get('index'), int)
                            and r.get('category') in ('Public', 'Private', 'DomainAuthenticated')]
            except Exception:
                profiles = []
            self.after(0, self._network_profiles_loaded, profiles)
        threading.Thread(target=read, name="network-profiles", daemon=True).start()

    def _network_profiles_loaded(self, profiles):
        self._network_profiles = profiles
        if not any(p['index'] == self._network_profile_index for p in profiles):
            self._network_profile_index = profiles[0]['index'] if profiles else 0
        self.publish()

    @Slot(int)
    def selectNetworkProfile(self, index):
        if any(p['index'] == index for p in self._network_profiles):
            self._network_profile_index = index
            self.publish()

    @Slot()
    def toggleNetworkProfile(self):
        if self._preview or self._network_profile_busy:
            return
        profile = next((p for p in self._network_profiles if p['index'] == self._network_profile_index), None)
        if not profile or profile['category'] not in ('Public', 'Private'):
            return
        category = 'Private' if profile['category'] == 'Public' else 'Public'
        self._network_profile_busy = True
        self.publish()
        def change():
            try:
                from silent_tunnel.admin_actions import run_elevated
                run_elevated('set_network_profile', interface_index=profile['index'], category=category)
                self.after(0, self._network_profile_changed, '')
            except Exception as exc:
                self.after(0, self._network_profile_changed, str(exc))
        threading.Thread(target=change, name="network-profile-change", daemon=True).start()

    def _network_profile_changed(self, error):
        self._network_profile_busy = False
        if error:
            self.ui_message('showerror', "Couldn't change network profile", error)
        self.refreshNetworkProfiles()
        self.refreshPcStatus()

    @Slot()
    def refreshPcStatus(self):
        """Read-only check behind the 'PC ready' indicator on Settings > Network."""
        if self._preview or self._pc.get("running") or self._pc.get("checking"):
            return
        self._pc = {**self._pc, "checking": True}

        def work():
            try:
                from silent_tunnel.prepare import pc_status
                self.after(0, self._pc_checked, pc_status(), "")
            except Exception as exc:
                self.after(0, self._pc_checked, None, str(exc) or type(exc).__name__)
        threading.Thread(target=work, name="pc-status", daemon=True).start()

    def _pc_checked(self, status, error):
        if error or not status:
            self._pc = {"ready": False, "text": "Couldn't check this PC.", "error": error, "known": False}
        elif status["ready"]:
            extra = " (network profile is Public)" if not status["network"] else ""
            self._pc = {"ready": True, "text": "PC ready" + extra, "error": "", "known": True}
        else:
            self._pc = {"ready": False, "known": True, "error": "",
                        "text": "Not ready: " + ", ".join(status["missing"])}
        self.publish()

    @Slot()
    def preparePC(self):
        """'Prepare this PC': one Windows permission prompt for VLA, firewall rules and (optionally) Private."""
        if self._preview or self._pc.get("running") or self.busy or self.room or self._beacon_joining:
            return
        self._pc = {**self._pc, "checking": True, "error": ""}

        def look():
            try:
                from silent_tunnel.prepare import pc_status
                self.after(0, self._pc_confirm, pc_status(), "")
            except Exception as exc:
                self.after(0, self._pc_confirm, None, str(exc) or type(exc).__name__)
        threading.Thread(target=look, name="pc-look", daemon=True).start()

    def _pc_confirm(self, status, error):
        self._pc = {**self._pc, "checking": False}
        if error or not status:
            self._pc = {"ready": False, "known": False, "text": "Couldn't check this PC.", "error": error}
            self.publish()
            return
        if status["ready"]:
            self._pc_checked(status, "")
            return
        steps = []
        if not status["vla"]:
            steps.append("install the launcher's VLA service and driver (from the files bundled with this launcher)")
        if status["firewall"] is False:
            steps.append("allow this launcher through the Windows firewall on your LAN only")
        if not steps:
            self._pc_checked(status, "")
            return
        answer = QMessageBox.question(
            None, "Prepare this PC?", "This will " + "; ".join(steps) + ". It works offline. "
            "Windows will ask for permission once.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            self.publish()
            return
        self._pc = {**self._pc, "running": True, "text": "Preparing this PC… approve Windows permission if asked."}
        self.publish()

        def work():
            try:
                from silent_tunnel.prepare import prepare_pc
                result = prepare_pc(core.APP_DIR / "vla-staging", make_private=False)
                self.after(0, self._pc_prepared, result, "")
            except Exception as exc:
                self.after(0, self._pc_prepared, None, str(exc) or type(exc).__name__)
        threading.Thread(target=work, name="pc-prepare", daemon=True).start()

    def _pc_prepared(self, result, error):
        self._pc = {**self._pc, "running": False}
        if error or not result:
            self._pc = {"ready": False, "known": True, "text": "Couldn't prepare this PC.", "error": error}
            self.publish()
            return
        self._pc_checked(result["status"], "")

    @Slot()
    def cleanupPC(self):
        cleanup_ui.cleanup_pc(self)

    @Slot()
    def confirmCleanup(self):
        cleanup_ui.confirm_cleanup(self)

    @Slot()
    def cancelCleanup(self):
        cleanup_ui.cancel_cleanup(self)

    def _cleanup_done(self, result, error):
        cleanup_ui.cleanup_done(self, result, error)

    @Slot()
    def saveJoinPack(self):
        """Host: write a signed join pack file for the open room."""
        joinpack_ui.save_join_pack(self)

    @Slot()
    def openJoinPack(self):
        """Client: read a join pack, check it, then offer to join the room it names."""
        joinpack_ui.open_join_pack(self)

    @Slot(bool)
    def setKeepInstalled(self, keep):
        self.save_options(keep)
        self.publish()

    @Slot()
    def importHost(self):
        if not self._preview:
            self.import_bundle()

    @Slot()
    def exportHost(self):
        if not self._preview:
            self.export_bundle()

    @Slot()
    def findLanHost(self):
        if not self._preview and not self.busy and not self.room and not self._beacon_joining:
            self._paused_version_room = None
            self._paused_admission_room = None
            self._start_discovery(allow_host_switch=True)

    def _start_discovery(self, *, allow_host_switch=False):
        self._host_choice_epoch += 1
        self._discovered_hosts.clear()
        self._host_choice_visible = False
        self._host_choice_switch = allow_host_switch
        self._host_collection_started = False
        self._host_choices_dismissed = False
        self._host_was_chosen = False
        self.publish()
        return super()._start_discovery(allow_host_switch=allow_host_switch)

    def _beacon_seen(self, beacon, *, allow_host_switch=False):
        if (self.role != 'client' or self.busy or self.room or self._beacon_joining
                or time.monotonic() < getattr(self, '_discovery_retry_at', 0)):
            return super()._beacon_seen(beacon, allow_host_switch=allow_host_switch)
        if self._host_choices_dismissed:
            return
        if beacon.get('admission') and beacon.get('net_id') == getattr(self, '_paused_admission_room', None):
            return
        if beacon.get('net_id') == getattr(self, '_paused_version_room', None):
            return
        key = str(beacon.get('host_pub') or '') + ':' + str(beacon.get('net_id') or '')
        if not beacon.get('host_pub') or not beacon.get('net_id'):
            return
        self._discovered_hosts[key] = beacon
        self._host_choice_switch = self._host_choice_switch or allow_host_switch
        if not self._host_collection_started and not self._host_choice_visible:
            self._host_collection_started = True
            epoch = self._host_choice_epoch
            asyncio.create_task(self._finish_host_collection(epoch))
        self.after(0, self.publish)
        return True

    async def _finish_host_collection(self, epoch):
        await asyncio.sleep(2)
        if epoch != self._host_choice_epoch or self.room or self._beacon_joining:
            return
        if len(self._discovered_hosts) == 1:
            beacon = next(iter(self._discovered_hosts.values()))
            core.LauncherCore._beacon_seen(self, beacon, allow_host_switch=self._host_choice_switch)
        elif len(self._discovered_hosts) > 1:
            self._host_choice_visible = True
            self.after(0, self.pages['room'].set_status, 'Choose a LAN host to join.')

    @Slot(str)
    def chooseLanHost(self, host_id):
        if self._preview or self.room or self._beacon_joining:
            return
        self.runtime.submit(self._choose_lan_host(host_id))

    async def _choose_lan_host(self, host_id):
        beacon = self._discovered_hosts.get(host_id)
        if beacon is None or not self._host_choice_visible:
            return
        self._host_choice_visible = False
        self._host_choice_epoch += 1
        self._host_was_chosen = True
        self.after(0, self.publish)
        core.LauncherCore._beacon_seen(self, beacon, allow_host_switch=True)

    @Slot()
    def dismissHostChoices(self):
        self._host_choice_visible = False
        self._host_choice_epoch += 1
        self._discovered_hosts.clear()
        self._host_collection_started = False
        self._host_choices_dismissed = True
        self.publish()

    @Slot()
    def retryConnection(self):
        if not self._preview and not self.busy and not self._beacon_joining:
            self._paused_version_room = None
            self._start_discovery()
            self.pages["room"].set_status("Searching for your saved LAN host…")

    @Slot()
    def prepareVLA(self):
        self.retryZeroTier()

    @Slot()
    def retryZeroTier(self):
        if self._preview or self.role != 'client' or self.busy or self.room or self._beacon_joining:
            return
        def install_or_start():
            self._recover_network_session()
            from silent_tunnel import installer
            from silent_tunnel.admin_actions import run_elevated
            if installer.is_installed():
                run_elevated('restart_service')
            self.tunnel.ensure_ready()
        def ready(result):
            self.pages['room'].set_status('VLA is ready. Looking for your host…')
            if self.config_data.get('setup_completed'):
                self.retryConnection()
        self._run_background(install_or_start, ready, 'Preparing VLA… approve Windows permission if asked.')

    @Slot()
    def repairNetwork(self):
        if self._preview or self.busy or self._beacon_joining:
            return
        from silent_tunnel.firewall import configure_rules
        def ready(result):
            self.pages['room'].set_status('LAN firewall rules repaired.')
            if self.role == 'client' and not self.room:
                self.retryConnection()
        self._run_background(configure_rules, ready, 'Repairing LAN access… approve Windows permission if asked.')

    @Slot(str)
    def joinRoomKey(self, key):
        if self._preview or self.role != 'client' or self.busy or self.room or self._beacon_joining:
            return
        from silent_tunnel.room import parse_room_code
        try:
            network_id = parse_room_code(key)
        except Exception as exc:
            self.ui_message('showerror', 'Invalid room key', str(exc))
            return
        self.busy = True
        self._beacon_joining = True
        self._status = 'Joining the room with your key…'
        future = self.runtime.submit(self._join_room_key(network_id))
        future.add_done_callback(lambda done: self.after(0, self._room_key_finished, done))
        self.publish()

    async def _join_room_key(self, network_id):
        await networking_ui.join_room_key(self, network_id)

    def _room_key_finished(self, future):
        networking_ui.room_key_finished(self, future)

    @Slot(str)
    def connectHostIp(self, address):
        if self._preview or self.role != 'client' or self.busy or self.room or self._beacon_joining:
            return
        networking_ui.connect_host_ip(self, address)

    def _connect_blocked(self, message, hint):
        self._status = 'Could not connect: ' + message
        self.ui_message('showerror', 'Host not compatible', message, hint=hint)
        self.publish()

    @Slot()
    def openHostRoom(self):
        if self.role == 'host' and not self._preview and not self.room and not self.busy:
            self.open_room(self.pc_name)

    @Slot(str)
    def openHostRoomWithPassword(self, password):
        if self.role != 'host' or self._preview or self.room or self.busy:
            return
        if not password.strip() or len(password.encode('utf-8')) > 256:
            self.ui_message('showerror', 'Room password', 'Enter a password of up to 256 UTF-8 bytes.')
            return
        self.open_room(self.pc_name, password=password)

    def _publish_room_admission(self, *_args):
        admission = getattr(self, "room_admission", None)
        self.after(0, self._set_room_admission, admission.snapshot() if admission else {})

    def _first_room_approval(self):
        pending = getattr(self, "_room_admission_snapshot", {}).get("pending")
        return {**pending[0], "requestId": pending[0]["id"]} if pending else None

    def _set_room_admission(self, snapshot):
        previous_error = getattr(self, "_room_admission_snapshot", {}).get("error")
        self._room_admission_snapshot = snapshot
        error = snapshot.get("error")
        if error and error != previous_error:
            self.ui_message('showerror', 'Room access could not be revoked', str(error))
            return
        self.publish()

    @Slot(str, bool)
    def resolveRoomApproval(self, request_id, allow):
        admission = getattr(self, "room_admission", None)
        if admission:
            self.runtime.loop.call_soon_threadsafe(admission.decide, request_id, allow)

    @Slot(str)
    def removeRoomBlacklistEntry(self, entry_id):
        admission = getattr(self, "room_admission", None)
        if admission:
            self.runtime.loop.call_soon_threadsafe(admission.remove, entry_id)

    def _set_room_password_prompt(self, prompt):
        self._room_password_prompt = prompt
        self.publish()

    async def _request_room_admission(self, beacon):
        return await networking_ui.request_room_admission(self, beacon)

    async def _bind_room_admission(self, beacon, access):
        await networking_ui.bind_room_admission(self, beacon, access)

    @Slot(str)
    def submitRoomPassword(self, password):
        prompt = getattr(self, "_room_password_prompt", None)
        queue = getattr(self, "_room_password_input", None)
        if prompt and queue and not prompt["busy"] and not prompt["waiting"]:
            self._set_room_password_prompt({**prompt, "busy": True})
            self.runtime.loop.call_soon_threadsafe(queue.put_nowait, password)

    @Slot()
    def cancelRoomPassword(self):
        queue = getattr(self, "_room_password_input", None)
        if queue:
            self.runtime.loop.call_soon_threadsafe(queue.put_nowait, None)

    def close(self):
        self._close_download_confirm = False
        if self._upgrade:
            self.cancelHostVersionTransfer()
        self._clear_download_queue()
        if self.syncing_game:
            core.LauncherCore._cancel_sync(self)
        self.cancelRoomPassword()
        super().close()

    def _offer_host_version(self, beacon, message, allow_host_switch=False):
        from .upgrade_ui import offer
        offer(self, beacon, message, allow_host_switch)

    def _publish_launcher_share(self, requests):
        self.after(0, self._set_launcher_share, requests)

    def _set_launcher_share(self, requests):
        self._share_requests = requests
        self.publish()

    @Slot()
    def requestHostVersion(self):
        from .upgrade_ui import request
        request(self)

    @Slot(str)
    def submitHostVersionKey(self, pin):
        from .upgrade_ui import unlock
        unlock(self, pin)

    @Slot()
    def chooseHostVersionDestination(self):
        from .upgrade_ui import choose_destination
        choose_destination(self, self._upgrade_epoch)

    @Slot()
    def cancelHostVersionTransfer(self):
        from .upgrade_ui import cancel
        cancel(self)

    @Slot(str, bool)
    def decideHostVersionRequest(self, request_id, allow):
        share = getattr(self, 'launcher_share', None)
        if share and not self._preview:
            self.runtime.submit(share.decide(request_id, allow))

    @Slot()
    def leave(self):
        if not self._preview and self.room:
            if self.syncing_game or self._download_preparing:
                self._leave_after_download = True
                self._download_queue.clear()
                if self.syncing_game:
                    core.LauncherCore._cancel_sync(self)
                else:
                    self._download_epoch += 1
                    if self._game_prepare_future:
                        self._game_prepare_future.cancel()
                    self._game_prepare_future = None
                    self._download_preparing = None
                    self.busy = False
                    self._leave_after_download = False
                    self.leave_room()
            elif not self.busy:
                self.leave_room()
        self.publish()

    @Slot(str)
    def copyText(self, text):
        QApplication.clipboard().setText(text)

    @Slot()
    def copyDiagnosticReport(self):
        diagnostics_ui.copy_report(self)

    @Slot()
    def runDiagnostics(self):
        self._start_diag(None)

    @Slot(str)
    def runLadder(self, address):
        diagnostics_ui.run_ladder(self, address)

    @Slot()
    def runHostCheck(self):
        diagnostics_ui.host_check(self)

    @Slot(str)
    def runFix(self, fix_id):
        diagnostics_ui.run_fix(self, fix_id)

    def _fix_done(self, result, error):
        diagnostics_ui.fix_done(self, result, error)

    def _start_diag(self, make_checks):
        diagnostics_ui.start_diag(self, make_checks)

    def _diag_progress(self, title, i, n):
        diagnostics_ui.diag_progress(self, title, i, n)

    def _diag_done(self, result, error):
        diagnostics_ui.diag_done(self, result, error)

    @Slot()
    def openDiagnosticsFolder(self):
        from PySide6.QtGui import QDesktopServices
        folder = core.APP_DIR / "diagnostics"
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))

    @Slot(str)
    def openWindowsSecurity(self, section):
        """Open Windows Security without modifying any protection settings."""
        urls = {
            'exclusions': 'windowsdefender://threatsettings/',
            'firewall': 'windowsdefender://network/',
        }
        uri = urls.get(section)
        if uri and sys.platform == 'win32':
            try:
                os.startfile(uri)
            except OSError:
                os.startfile('ms-settings:windowsdefender')

    @Slot()
    def copyLauncherFolder(self):
        from ..appdirs import app_root
        QApplication.clipboard().setText(str(app_root()))

    @Slot()
    def openSelectedFolder(self):
        from PySide6.QtGui import QDesktopServices
        m = self.library.get(self._selected)
        if m and Path(m.get("install_dir", "")).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(m["install_dir"]).resolve())))

    def _show_sync_progress(self, game_name, *, game_id=None, show_downloads=True):
        self._progress = {"active": True, "game": game_name, "game_id": game_id, "done": 0,
                          "total": 0, "file": "", "state": "receiving", "index": {}}
        if show_downloads:
            self.show_page("downloads")
        else:
            self.publish()

    def _update_sync_progress(self, game_name, done, total, filename):
        if not self._progress.get('active'):
            return
        self._progress = {**self._progress, "active": True, "game": game_name, "done": done, "total": total,
                          "file": Path(filename).name if filename else "Preparing files…", "index": {}}
        self._publish_progress()

    def _update_index_progress(self, game_name, status):
        if self._progress.get('active') and self._progress.get('game') == game_name and not self._progress.get('total'):
            self._progress = {**self._progress, 'index': status}
            self._publish_progress()

    def _close_sync_progress(self):
        self._progress = {"active": False, "game": "", "game_id": "", "done": 0,
                          "total": 0, "file": "", "state": "idle", "index": {}}
        self.publish()

    def _sync_transfer_state(self, state):
        if not self._progress['active']:
            return
        current = self._progress.get('state')
        # A pause/resume request is in flight: drop controller states that predate it. Queued
        # 'receiving' from the sync start can arrive after the user clicked Pause.
        if current in ('pausing', 'paused') and state == 'receiving':
            return
        if current == 'resuming' and state == 'paused':
            return
        self._progress = {**self._progress, 'state': state}
        super()._sync_transfer_state(state)
        self._publish_progress()

    @Slot()
    def pauseDownload(self):
        if self._progress.get('state') == 'receiving':
            self.toggleDownloadPause()

    @Slot()
    def resumeDownload(self):
        if self._progress.get('state') == 'paused':
            self.toggleDownloadPause()

    @Slot()
    def toggleDownloadPause(self):
        control = getattr(self, '_sync_control', None)
        if self._preview or not control or not self.syncing_game or not self._progress['active']:
            return
        state = self._progress.get('state')
        if state not in ('receiving', 'paused'):
            return
        resume = state == 'paused'
        self._progress = {**self._progress, 'state': 'resuming' if resume else 'pausing'}
        self.publish()
        self.runtime.loop.call_soon_threadsafe(control.resume if resume else control.pause)

    def manage_game_directory(self):
        self._folders = []
        try:
            for folder in scan_game_folders(self.game_root):
                m = self.game_for_folder(folder)
                self._folders.append({"folder": str(folder), "name": m["name"] if m else folder.name,
                                      "exe": (m["exe"] or 'Files only') if m else "Choose a launch executable",
                                      "exeRequired": m.get('exe_required', True) if m else True,
                                      "args": shlex.join(m.get('args', [])) if m else '',
                                      "enabled": bool(m and m.get("enabled")), "id": m["id"] if m else "",
                                      "art": self._game(m)['art'] if m else ''})
        except OSError as exc:
            self.ui_message("showerror", "Couldn't open game directory", str(exc))
        self.show_page("catalog")

    @Slot(str, str, result=bool)
    def saveHostLaunchArgs(self, folder, arguments):
        if self.role != 'host' or self._host_args_saving:
            return False
        try:
            m = self.game_for_folder(folder)
            if not m or m.get('exe_required', True) is False:
                raise ValueError('Select a launch executable for this game first.')
            parsed = shlex.split(arguments)
            snapshot = copy.deepcopy(self.game_catalog)
            snapshot[m['id']]['args'] = parsed
        except (OSError, ValueError) as exc:
            self.hostLaunchArgsFinished.emit(folder, False, str(exc))
            return False
        self._host_args_saving = True
        self.publish()
        async def persist():
            await asyncio.to_thread(core.save_catalog, self.host_catalog_path, snapshot)
        future = self.runtime.submit(persist())
        future.add_done_callback(lambda done: self.after(0, self._host_args_saved, folder, m['id'], parsed, done))
        return True

    def _host_args_saved(self, folder, game_id, parsed, future):
        self._host_args_saving = False
        try:
            future.result()
        except Exception as exc:
            self.publish()
            self.hostLaunchArgsFinished.emit(folder, False, str(exc))
            return
        self.game_catalog[game_id]['args'] = parsed
        if game_id in self.library:
            self.library[game_id]['args'] = parsed
        self._folders = [{**row, 'args': shlex.join(parsed)} if row.get('id') == game_id else row
                         for row in self._folders]
        self.publish()
        self.hostLaunchArgsFinished.emit(folder, True, '')

    @Slot(str, bool)
    def setHostExeRequired(self, folder, required):
        try:
            m = self.game_for_folder(folder)
            exe = str(Path(folder) / m['exe']) if m and m.get('exe') else ''
            if required and not exe:
                exe = self.chooseFile('exe')
                if not exe:
                    self.manage_game_directory()
                    return
            self.register_game(folder, exe, m['name'] if m else Path(folder).name,
                               m.get('args', []) if m else [], exe_required=required)
            self.manage_game_directory()
        except Exception as exc:
            self.ui_message('showerror', 'Could not update folder', str(exc))

    @Slot(str, bool)
    def setHostGameEnabled(self, folder, enabled):
        m = self.game_for_folder(folder)
        if not m:
            self.ui_message('showinfo', 'Choose executable', 'Browse for this game’s .exe first.')
            self.publish()
            return
        if bool(m.get('enabled')) != enabled:
            self.toggle_game_playlist(m['id'])
        self.manage_game_directory()

    @Slot(str, str)
    def browseHostGame(self, folder, kind):
        self._disk_changed()
        path = self.chooseFile(kind, folder)
        if not path:
            return
        try:
            m = self.game_for_folder(folder)
            if kind == 'exe':
                self.register_game(folder, path, m['name'] if m else Path(folder).name,
                                   m.get('args', []) if m else [])
                game = self.game_for_folder(folder)
                if game and not game.get('_art_path'):
                    artwork = self._matching_game_art(Path(folder), Path(path), game['name'])
                    if artwork:
                        self.set_game_art(game['id'], artwork)
            elif m:
                self.set_game_art(m['id'], path)
            else:
                raise ValueError('Choose the game executable before assigning its icon.')
            self.manage_game_directory()
        except Exception as exc:
            self.ui_message('showerror', 'Couldn’t update game', str(exc))

    @staticmethod
    def _matching_game_art(folder, exe, name):
        """Choose a local cover without guessing among unrelated game images."""
        def key(value):
            return ''.join(ch for ch in value.casefold() if ch.isalnum())

        names = [key(name), key(folder.name), key(exe.stem)]
        cover_names = {"cover", "folder", "poster", "boxart", "frontcover", "artwork"}
        fallback = []
        for directory in dict.fromkeys((folder, exe.parent)):
            if not directory.is_dir():
                continue
            images = sorted((p for p in directory.iterdir()
                             if p.is_file() and p.suffix.casefold() in {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}),
                            key=lambda p: p.name.casefold())
            for wanted in names:
                for image in images:
                    if wanted and key(image.stem) == wanted:
                        return str(image)
            for image in images:
                if key(image.stem) in cover_names:
                    return str(image)
            fallback.extend(image for image in images
                            if not any(word in key(image.stem) for word in
                                       ("icon", "logo", "screenshot", "splash", "banner")))
        if len(fallback) == 1:
            return str(fallback[0])
        return ""

    @Slot(str)
    def editFolder(self, folder):
        m = self.game_for_folder(folder)
        self._edit = {"folder": folder, "name": m["name"] if m else Path(folder).name,
                      "exe": str(Path(folder) / m["exe"]) if m and m.get('exe') else "",
                      "exeRequired": m.get('exe_required', True) if m else True,
                      "args": shlex.join(m.get("args", [])) if m else "",
                      "art": "", "enabled": bool(m and m.get("enabled"))}
        self.show_page("editor")

    @Slot(str, str, str, str, bool, str)
    @Slot(str, str, str, str, bool, str, bool)
    def saveGame(self, folder, exe, name, args, enabled, art, exe_required=True):
        try:
            if not name.strip():
                raise ValueError("Enter a game name.")
            self.register_game(folder, exe, name, shlex.split(args) if exe_required else [], exe_required=exe_required)
            m = self.game_for_folder(folder)
            if art:
                self.set_game_art(m["id"], art)
            if bool(m.get("enabled")) != enabled:
                self.toggle_game_playlist(m["id"])
            self.manage_game_directory()
        except Exception as exc:
            self.ui_message("showerror", "Couldn't save game", str(exc))

    @Slot()
    def addGame(self):
        folder = QFileDialog.getExistingDirectory(None, "Choose a folder directly inside Game Directory", str(self.game_root))
        if folder:
            if self.role == 'host':
                if Path(folder).resolve().parent != self.game_root.resolve():
                    self.ui_message('showerror', 'Game folder', 'Choose a folder directly inside Game Directory.')
                else:
                    self.manage_game_directory()
            else:
                self.editFolder(folder)

    @Slot()
    def requestClose(self):
        if self._wiping:
            return
        if self._close_download_confirm:
            return
        if (not self._preview and self.role == 'client'
                and (self.syncing_game or self._download_preparing or self._download_queue)):
            self._close_download_confirm = True
            self.publish()
            return
        self._close_now()

    @Slot(bool)
    def confirmCloseDownloads(self, close_launcher):
        if not self._close_download_confirm:
            return
        self._close_download_confirm = False
        if close_launcher:
            self._close_now()
        else:
            self.publish()

    def _close_now(self):
        if self._game_prepare_future is not None:
            self._game_prepare_future.cancel()
            self._game_prepare_future = None
            self.busy = False
        if self._preview:
            self._finish_close()
        else:
            self.close()
        self.publish()

    def destroy(self):
        self._destroyed = True
        self.quitReady.emit()


