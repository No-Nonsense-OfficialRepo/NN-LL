"""A safe practice backend for the production Host and Client views."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

from .._version import __release__
from ..single_instance import _existing_window, show_existing
from .main import configure_font_directory, create_engine


ROOM_KEY = "8056-c2e2-1c00-0001"
GAME = {"id": "practice", "name": "Practice Game", "installed": False, "exeRequired": True, "art": ""}
INSTRUCTIONS = {
    "hostOpen": ("Open a practice room", "Optionally tick Require password and type a sample password. Then click Open Room."),
    "hostInvite": ("Invite your players", "Click the sample room key. On your LAN, players can also use Find host automatically."),
    "hostAdd": ("Add a game", "Click + next to Games. In the real Host, put the game folder directly inside Game Directory, then select it."),
    "hostExe": ("Select the executable", "Click the terminal icon in the game row. In the real Host, select the game's .exe."),
    "hostArt": ("Choose game artwork", "Click the image icon to assign a sample cover. In the real Host, choose an image file."),
    "hostShare": ("Share the game", "Tick the checkbox at the left of Practice Game. Clients can now see it in the shared library."),
    "hostPlayers": ("See who joined", "The Players panel lists each connected player, their IP address, and ping. This player is a sample."),
    "hostOptions": ("Open Host options", "Click the Settings gear at the bottom right. Close Settings to finish."),
    "clientFind": ("Find your host", "Click Find host automatically. This example shows what to do if it can't find the room."),
    "clientKey": ("Join by room key", "The practice key is filled in. Click Join room key to continue."),
    "clientPassword": ("Enter a practice password", "Use any sample text. In a real room, enter the password from your host."),
    "clientPlay": ("Try Play", "Click Play on the sample game. No game will launch during practice."),
    "clientInstall": ("Download a game", "Click Install on the game's details page. It downloads the files shared by the host."),
    "clientDownload": ("Check the download", "The Downloads page shows progress. When installation finishes, return to the game and click Play."),
    "clientSettings": ("Open Settings", "Click the Settings gear in the top navigation."),
    "clientPlayerTab": ("Find the Player tab", "Select Player in Settings."),
    "clientProfile": ("Set your player name", "Enter a practice name and click Save profile. This name is only used in this tutorial."),
    "done": ("Practice complete", "Take me there opens the real launcher."),
}


class QuickStart(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.role = ""
        self._terms_acknowledged = False
        self.engine = None
        self.timer = QTimer(self, interval=200)
        self.timer.timeout.connect(self.check_launcher)
        self.download_timer = QTimer(self, interval=50)
        self.download_timer.timeout.connect(self._advance_download)
        self._download_started = 0.0
        self.reset()

    @Property("QVariantMap", notify=changed)
    def state(self):
        return self._state

    def update(self, **values):
        self._state.update(values)
        self.changed.emit()

    def open_window(self):
        self.engine = create_engine(self, startup=True)

    def change_window_shape(self):
        if self.engine is None:
            return
        # The chooser's scene and native surface must leave together. Retire
        # them after the QML button handler returns, then start the new scene.
        self.engine.rootObjects()[0].hide()
        QTimer.singleShot(0, self.replace_window)

    def replace_window(self):
        delete(self.engine)
        self.open_window()
        self.engine.rootObjects()[0].requestActivate()

    def step(self, stage, **values):
        title, instruction = INSTRUCTIONS[stage]
        values.setdefault("tutorialError", "")
        if getattr(self, '_history', None) is not None and self._state.get('tutorialStage') != stage:
            self._history.append((self.role, dict(self._state)))
        self.update(tutorialStage=stage, tutorialTitle=title, tutorialText=instruction, **values)

    @Slot()
    def reset(self):
        self.download_timer.stop()
        self._history = []
        if self.timer.isActive():
            return
        if self.role == "host":
            self.change_window_shape()
        self.role = ""
        self._state = dict(
            tutorial=True, tutorialStage="choose", tutorialTitle="", tutorialText="",
            termsAcknowledged=self._terms_acknowledged,
            tutorialLaunching=False, tutorialError="", tutorialRoomKey=ROOM_KEY, preview=True, host=False, page="room",
            version=__release__, closing=False, connected=False, busy=False,
            dialog={}, progress={}, roomPasswordPrompt=None, cleanupConfirm=None,
            catalog=[], players=[], games=[], allGames=[], selected={}, events=[],
            pcName="Practice PC", playerName="Player", avatar="", status="Ready to practice",
            roomCode="", hostLanIp="", playerCount=0, gameDirectory="Game Directory",
            keepInstalled=True, hostArgsSaving=False, gameCount=0, settingsTab="Game Library",
        )
        self.changed.emit()

    @Slot(str)
    def choose(self, role):
        if self.role or role not in ("host", "client"):
            return
        if role == "host":
            self.change_window_shape()
        self.role = role
        self.step("hostOpen" if role == "host" else "clientFind", host=role == "host")

    @Slot()
    def acknowledgeTerms(self):
        self._terms_acknowledged = True
        self.update(termsAcknowledged=True)

    @Slot()
    def openHostRoom(self):
        if self._state["tutorialStage"] == "hostOpen":
            self.step("hostInvite", connected=True, roomCode=ROOM_KEY, hostLanIp="192.168.1.10")

    @Slot(str)
    def openHostRoomWithPassword(self, _sample):
        self.openHostRoom()

    @Slot(str)
    def copyText(self, _sample):
        if self._state["tutorialStage"] == "hostInvite":
            self.step("hostAdd")
        elif self._state["tutorialStage"] == "clientKey":
            QApplication.clipboard().setText(ROOM_KEY)

    @Slot()
    def addGame(self):
        if self._state["tutorialStage"] == "hostAdd":
            self.step("hostExe", catalog=[{**GAME, "folder": "Practice Game", "exe": "", "enabled": False}])

    @Slot(str, str)
    def browseHostGame(self, _folder, kind):
        stage = self._state["tutorialStage"]
        if stage == "hostExe" and kind == "exe":
            self.step("hostArt", catalog=[{**self._state["catalog"][0], "exe": "PracticeGame.exe"}])
        elif stage == "hostArt" and kind == "art":
            qt = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent)) / "qt"
            art = QUrl.fromLocalFile(str(qt / "assets" / "controls" / "grid.svg")).toString()
            self.step("hostShare", catalog=[{**self._state["catalog"][0], "art": art}])

    @Slot(str, bool)
    def setHostGameEnabled(self, _folder, enabled):
        if self._state["tutorialStage"] == "hostShare" and enabled:
            self.step("hostPlayers", catalog=[{**self._state["catalog"][0], "enabled": True}],
                      players=[{"name": "Practice Player", "ip": "192.168.1.25", "ping_ms": 12}], playerCount=1)

    @Slot()
    def backLesson(self):
        if self._state.get('tutorialLaunching') or not self._history:
            return
        self.download_timer.stop()
        role, previous = self._history.pop()
        if role != self.role:
            self.role = role
            self.change_window_shape()
        self._state = previous
        self.changed.emit()

    @Slot()
    def nextLesson(self):
        stage = self._state['tutorialStage']
        if stage == 'hostOpen': self.openHostRoom()
        elif stage == 'hostInvite': self.copyText(ROOM_KEY)
        elif stage == 'hostAdd': self.addGame()
        elif stage == 'hostExe': self.browseHostGame('', 'exe')
        elif stage == 'hostArt': self.browseHostGame('', 'art')
        elif stage == 'hostShare': self.setHostGameEnabled('', True)
        elif stage == 'hostPlayers': self.step('hostOptions')
        elif stage == 'hostOptions': self.finishHostOptions()
        elif stage == 'clientFind': self.findLanHost()
        elif stage == 'clientKey': self.joinRoomKey(ROOM_KEY)
        elif stage == 'clientPassword': self.submitRoomPassword('Practice password')
        elif stage == 'clientInstall': self.install()
        elif stage == 'clientDownload':
            self.download_timer.stop()
            game = {**GAME, 'installed': True}
            self.step('clientPlay', page='details', selected=game, allGames=[game], progress={})
        elif stage == 'clientPlay': self.play()
        elif stage == 'clientSettings': self.navigate('settings')
        elif stage == 'clientPlayerTab': self.settingsTab('Player')
        elif stage == 'clientProfile': self.saveProfile(self._state.get('playerName') or 'Player')

    @Slot()
    def finishHostOptions(self):
        if self._state["tutorialStage"] == "hostOptions":
            self.step("done")

    @Slot()
    def findLanHost(self):
        if self._state["tutorialStage"] == "clientFind":
            self.step("clientKey", status="Practice result: no host found automatically.")

    @Slot(str)
    def joinRoomKey(self, sample):
        if self._state["tutorialStage"] != "clientKey":
            return
        if sample.strip().casefold() == ROOM_KEY:
            self.step("clientPassword", tutorialError="",
                      roomPasswordPrompt={"name": "Practice Host", "status": INSTRUCTIONS["clientPassword"][1]})
        else:
            self.update(tutorialError="Use the practice room key below.")

    @Slot(str)
    def submitRoomPassword(self, sample):
        if self._state["tutorialStage"] == "clientPassword" and sample:
            self.step("clientInstall", roomPasswordPrompt=None, connected=True, roomCode=ROOM_KEY,
                      selected=GAME, allGames=[GAME], gameCount=1, page="details", tutorialError="")

    @Slot()
    def cancelRoomPassword(self):
        if self._state["tutorialStage"] == "clientPassword":
            self.step("clientKey", roomPasswordPrompt=None, tutorialError="")

    @Slot()
    def install(self):
        if self._state["tutorialStage"] == "clientInstall":
            self.step("clientDownload", page="downloads",
                      progress={"active": True, "game": GAME["name"], "game_id": GAME["id"], "state": "receiving",
                                "done": 0, "total": 1073741824, "file": "PracticeGame.exe"})
            self._download_started = time.monotonic()
            self.download_timer.start()

    def _advance_download(self):
        if self._state["tutorialStage"] != "clientDownload":
            self.download_timer.stop()
            return
        fraction = min(1.0, (time.monotonic() - self._download_started) / 6.0)
        progress = dict(self._state["progress"])
        progress["done"] = round(progress["total"] * fraction)
        if fraction >= 1.0:
            progress["state"] = "complete"
            self.download_timer.stop()
        self.update(progress=progress)

    @Slot()
    def play(self):
        if self._state["tutorialStage"] == "clientPlay":
            self.step("clientSettings")

    @Slot(str)
    def navigate(self, page):
        if page == "settings" and self._state["tutorialStage"] == "clientSettings":
            self.step("clientPlayerTab", page="settings")

    @Slot(str)
    def settingsTab(self, tab):
        if tab == "Player" and self._state["tutorialStage"] == "clientPlayerTab":
            self.step("clientProfile", settingsTab=tab)

    @Slot(str)
    def saveProfile(self, name):
        if self._state["tutorialStage"] == "clientProfile" and name.strip():
            self.step("done", playerName=name.strip())
        elif self._state["tutorialStage"] == "clientProfile":
            self.update(tutorialError="Enter a practice name before saving.")

    @Slot()
    def requestClose(self):
        self.update(closing=True)
        QApplication.instance().quit()

    @Slot()
    def launch(self):
        if self._state["tutorialStage"] != "done" or self.timer.isActive():
            return
        if _existing_window(self.role):
            show_existing(self.role)
            self.requestClose()
            return
        folder = Path(sys.executable).resolve().parent
        executable = folder / f"{self.role.title()}.exe"
        if not executable.is_file():
            self.update(tutorialError=f"Couldn't find {executable.name}. Extract the complete launcher ZIP.")
            return
        try:
            self.process = subprocess.Popen([str(executable)], cwd=folder)
        except OSError as error:
            self.update(tutorialError=f"Couldn't start the launcher. {error}")
            return
        self.update(tutorialLaunching=True, tutorialError="")
        self.deadline = time.monotonic() + 30
        self.timer.start()

    def check_launcher(self):
        if _existing_window(self.role):
            self.timer.stop()
            self.requestClose()
        elif self.process.poll() not in (None, 0) or time.monotonic() >= self.deadline:
            self.timer.stop()
            self.update(tutorialLaunching=False,
                        tutorialError="The launcher window didn't open. Try Take me there again.")


def main():
    configure_font_directory()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("NN LAN Launcher")
    app.setOrganizationName("NN LAN Launcher")
    bridge = QuickStart()
    bridge.open_window()
    code = app.exec()
    delete(bridge.engine)
    return code
