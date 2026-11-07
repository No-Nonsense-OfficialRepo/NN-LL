"""Qt frontend integration checks with all network/elevated actions isolated."""
import os
import asyncio
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
if local_qt.is_dir():
    sys.path.insert(0, str(local_qt))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import lantool.qt  # Apply the same eager Qt initialization as production.
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QObject, QThread
from PySide6.QtWidgets import QApplication
from lantool import launcher as core
from lantool._version import __proto__ as ROOM_PROTOCOL
from lantool.qt.bridge import LauncherBridge
from lantool.qt.main import create_engine


_WAIT_FLAGS = QEventLoop.ProcessEventsFlag.AllEvents | QEventLoop.ProcessEventsFlag.WaitForMoreEvents


def _wait_for_events(remaining):
    """Block until a Qt event arrives (queued signals, bridge.changed, worker results) or `remaining` seconds pass."""
    QCoreApplication.processEvents(_WAIT_FLAGS, max(1, int(remaining * 1000)))
    QCoreApplication.sendPostedEvents()


def pump(seconds=.12):
    """Deliver queued events for up to `seconds`, waking on each event rather than sleeping."""
    deadline = time.monotonic() + seconds
    QApplication.processEvents()
    QCoreApplication.sendPostedEvents()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        _wait_for_events(remaining)


def pump_until(predicate, timeout=2):
    """Run the Qt event loop until predicate() holds; wakes on posted events instead of fixed sleeps."""
    deadline = time.monotonic() + timeout
    while not predicate():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        _wait_for_events(remaining)


def wait_for_worker(event, timeout=2):
    """Block on a threading.Event set by a worker thread, then deliver events it queued."""
    ok = event.wait(timeout)
    pump(0)
    return ok


class QtLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.saved = []
        self.recoveries = []
        self.tunnel = SimpleNamespace(settings=SimpleNamespace(uninstall_on_exit=True),
                                      save_settings=Mock(), cleanup=Mock(), recover=Mock(return_value=[]))
        self.patches = [
            patch.object(core, "APP_DIR", self.root),
            patch.object(core, "GAME_FILES_ROOT", self.root/"games"),
            patch.object(core, "_read_config", return_value={}),
            patch.object(core, "_write_config", side_effect=lambda value:self.saved.append(dict(value))),
            patch.object(core, "_same_role_launcher_running", return_value=False),
            patch.object(core, "Tunnel", return_value=self.tunnel),
            patch.object(LauncherBridge, "_recover", lambda obj:self.recoveries.append(True)),
        ]
        for p in self.patches:
            p.start()
        self.bridge = LauncherBridge(start_services=False)
        self.engine = None

    def tearDown(self):
        self.bridge._destroyed = True
        if self.engine:
            for root in self.engine.rootObjects():
                root.setVisible(False)
            self.engine.deleteLater()
            # processEvents() does not run DeferredDelete outside an event loop. Destroy the window now, while the
            # bridge still exists, so QML bindings never see backend == null during teardown.
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.engine = None
        self.bridge.runtime.stop()
        pump(.02)
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_multiple_discovered_hosts_wait_for_explicit_choice(self):
        hosts = [dict(host_pub=key * 64, net_id=key * 16, host=f'192.168.1.{i}',
                      pc_name=f'Host {i}') for i, key in enumerate(('a', 'b'), 1)]
        async def discover():
            for beacon in hosts:
                self.bridge._beacon_seen(beacon, allow_host_switch=True)
            await asyncio.sleep(2.1)
        with patch.object(core.LauncherCore, '_beacon_seen') as join:
            self.bridge.runtime.submit(discover()).result(4)
            pump(.05)
            self.assertFalse(join.called)
            self.assertTrue(self.bridge.state['hostChoiceVisible'])
            self.assertEqual(len(self.bridge.state['hostChoices']), 2)
            self.bridge.chooseLanHost('b' * 64 + ':' + 'b' * 16)
            pump_until(lambda: join.called)
            join.assert_called_once_with(self.bridge, hosts[1], allow_host_switch=True)
            self.assertFalse(self.bridge.state['hostChoiceVisible'])

    def test_network_security_shortcuts_and_folder_copy(self):
        self.library()
        self.bridge.settingsTab('Network')
        self.bridge.show_page('settings')
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        for name in ('openDefenderExclusionsButton', 'copyLauncherFolderButton',
                     'openFirewallSettingsButton'):
            button = window.findChild(QObject, name)
            self.assertIsNotNone(button)
            self.assertLessEqual(button.property('width'), 300)
            self.assertEqual(button.property('height'), 36)
        with patch('lantool.qt.bridge.os.startfile') as start:
            self.bridge.openWindowsSecurity('exclusions')
            self.bridge.openWindowsSecurity('firewall')
            self.bridge.openWindowsSecurity('unknown')
        self.assertEqual([call.args[0] for call in start.call_args_list],
                         ['windowsdefender://threatsettings/', 'windowsdefender://network/'])
        with patch('lantool.appdirs.app_root', return_value=self.root):
            self.bridge.copyLauncherFolder()
        self.assertEqual(QApplication.clipboard().text(), str(self.root))

    def library(self):
        self.bridge.config_data["setup_completed"] = True
        self.bridge.library = {}
        for i in range(16):
            folder = self.root/"games"/str(i)
            folder.mkdir(parents=True)
            if i%2==0:
                (folder/"game.exe").write_bytes(b"")
            self.bridge.library[f"g{i}"] = {"id":f"g{i}","name":f"Game {i:02}",
                "exe":"game.exe","install_dir":str(folder),"exe_size":0}
        self.bridge.show_page("library")

    def test_setup_is_one_form_and_saved_once(self):
        self.assertEqual(self.bridge.state["page"],"setup")
        self.assertEqual(self.recoveries,[])
        self.bridge.finishSetup("",str(self.root/"downloads"),True,"")
        self.assertTrue(self.bridge.state["dialog"]["error"])
        self.assertNotIn("setup_completed",self.bridge.config_data)
        self.bridge.finishSetup("Test Player",str(self.root/"downloads"),True,"")
        pump()
        self.assertTrue(self.saved[-1]["setup_completed"])
        self.assertFalse(self.saved[-1]["uninstall_on_exit"])
        self.assertEqual(self.bridge.state["page"],"room")
        self.bridge.finishSetup("Test Player",str(self.root/"downloads"),True,"")
        pump()
        self.assertEqual(len(self.recoveries),1)

    def test_16_games_filter_search_and_real_launch_callback(self):
        self.library()
        self.assertEqual(len(self.bridge.state["games"]),16)
        self.bridge.filterGames("Installed")
        self.assertEqual(len(self.bridge.state["games"]),8)
        self.bridge.search("Game 02")
        self.assertEqual(self.bridge.state["games"][0]["id"],"g2")
        self.bridge.selectGame("g2")
        self.assertEqual(self.bridge.state["page"],"details")
        self.bridge.saveLaunchArgs('+connect "{host_ip}"')
        with patch.object(self.bridge,"_play_game") as launch:
            self.bridge.play()
            pump_until(lambda: launch.called)
        m,context=launch.call_args.args
        self.assertEqual(m["id"],"g2")
        self.assertEqual(m["args"],["+connect","{host_ip}"])
        self.assertEqual(context["name"],"Player")
        self.bridge.pages["library"].set_library({})
        self.assertEqual(self.bridge.state["selected"],{})

    def test_worker_callbacks_are_delivered_on_qt_thread(self):
        seen=[]
        t=threading.Thread(target=lambda:self.bridge.after(0,lambda:seen.append(QThread.currentThread())))
        t.start();t.join();pump()
        self.assertEqual(seen,[self.app.thread()])

    def test_manual_zerotier_retry_uses_worker_and_resumes_discovery(self):
        self.bridge.role='client'
        self.bridge.config_data['setup_completed']=True
        self.tunnel.ensure_ready=Mock()
        with patch('silent_tunnel.installer.is_installed',return_value=False), \
             patch.object(self.bridge,'retryConnection') as resume:
            self.bridge.retryZeroTier()
            pump_until(lambda: not self.bridge.busy, timeout=3)
            self.tunnel.ensure_ready.assert_called_once()
            resume.assert_called_once()

    def test_message_opens_only_one_popup_for_each_role(self):
        self.engine=create_engine(self.bridge)
        window=self.engine.rootObjects()[0]
        message=window.findChild(QObject,'applicationMessagePopup')
        self.assertIsNone(window.findChild(QObject,'hostMessagePopup'))
        self.assertIsNone(window.findChild(QObject,'clientMessagePopup'))
        for role in ['client','host']:
            self.bridge.role=role
            self.bridge.ui_message('showinfo','Profile saved','Your player name has been saved.')
            pump(.03)
            self.assertTrue(message.property('visible'))
            self.bridge.dismissDialog();pump(.03)
            self.assertFalse(message.property('visible'))

    def test_borderless_window_keeps_aspect_ratio(self):
        from PySide6.QtCore import Qt
        self.engine=create_engine(self.bridge)
        window=self.engine.rootObjects()[0]
        # The client stage fits the screen at 16:9 (fitToScreen), so the starting size varies by display.
        self.assertAlmostEqual(window.width()/window.height(),16/9,places=2)
        self.assertTrue(window.flags() & Qt.FramelessWindowHint)
        for role,ratio in [('client',16/9),('host',9/21)]:
            self.bridge.role=role;self.bridge.publish();pump(.03)
            window.setWidth(463 if role=='host' else 1260);pump(.03)
            self.assertLessEqual(abs(window.height()-window.width()/ratio),1)
            window.setHeight(1080 if role=='host' else 720);pump(.03)
            self.assertLessEqual(abs(window.width()-window.height()*ratio),1)

    def test_corner_snap_moves_window_without_resizing(self):
        from PySide6.QtCore import QMetaObject
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        area = window.screen().availableGeometry()
        original = window.size()
        window.setX(area.x() + 18)
        window.setY(area.y() + 21)
        self.assertTrue(QMetaObject.invokeMethod(window, 'snapToDesktopCorner'))
        self.assertEqual((window.x(), window.y()), (area.x(), area.y()))
        self.assertEqual(window.size(), original)

    def test_fill_screen_covers_usable_desktop_and_restores_windowed_ratio(self):
        import json
        from PySide6.QtCore import QMetaObject, QSettings, QUrl, Q_ARG
        from PySide6.QtQml import QQmlComponent
        self.library()
        self.bridge.settingsTab('Appearance')
        self.bridge.show_page('settings')
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        path = self.root / 'fill-screen.ini'
        location = json.dumps(QUrl.fromLocalFile(str(path)).toString())
        component = QQmlComponent(self.engine)
        component.setData(('import QtQuick\nimport "."\nItem {\n'
            'Component.onCompleted: { WindowPreferences.store.location='+location+'; WindowPreferences.reload(); }\n'
            'function setFill(enabled: bool) { WindowPreferences.setFillScreen(enabled); }\n'
            '}').encode(), QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'lantool/qt/qml/FillHarness.qml')))
        harness = component.create()
        self.assertIsNotNone(harness, [e.toString() for e in component.errors()])
        checkbox = window.findChild(QObject, 'fillScreenCheckbox')
        self.assertIsNotNone(checkbox)
        QMetaObject.invokeMethod(harness, 'setFill', Q_ARG(bool, True))
        pump(.05)
        area = window.screen().availableGeometry()
        self.assertEqual(window.geometry(), area)
        self.assertTrue(checkbox.property('checked'))
        self.assertFalse(window.findChild(QObject, 'clientResolutionSelector').property('enabled'))
        sidebar = window.findChild(QObject, 'launcherSidebar')
        self.assertAlmostEqual(sidebar.width(), 182 * 1.2)
        stage = sidebar.parentItem()
        # Uniformly scaled stage covers the usable window in both axes.
        self.assertAlmostEqual(stage.width() * stage.scale(), area.width())
        self.assertAlmostEqual(stage.height() * stage.scale(), area.height())
        page = window.findChild(QObject, 'pageLoader')
        self.assertGreater(page.x(), sidebar.width())
        self.assertLessEqual(page.x() + page.width(), stage.width())
        saved = QSettings(str(path), QSettings.IniFormat)
        self.assertEqual(str(saved.value('Window/fillScreen')).lower(), 'true')
        # Host's independent portrait window stays at its existing ratio.
        self.bridge.role = 'host'; self.bridge.publish(); pump(.03)
        self.assertFalse(window.property('fillScreen'))
        self.assertAlmostEqual(window.width()/window.height(), 9/21, places=2)
        self.bridge.role = 'client'; self.bridge.publish(); pump(.03)
        self.assertEqual(window.geometry(), area)
        QMetaObject.invokeMethod(harness, 'setFill', Q_ARG(bool, False))
        pump(.05)
        self.assertFalse(checkbox.property('checked'))
        self.assertAlmostEqual(window.width()/window.height(), 16/9, places=2)
        self.assertTrue(window.findChild(QObject, 'clientResolutionSelector').property('enabled'))
        link = window.findChild(QObject, 'bottomDownloadsLink')
        self.assertEqual(link.property('text'), 'Downloads')
        # Qt rounds anchor positions to physical pixels, including odd widths.
        self.assertAlmostEqual(link.x() + link.width()/2, window.width()/2, delta=.5)
        QMetaObject.invokeMethod(link, 'activate')
        self.assertEqual(self.bridge.state['page'], 'downloads')
        harness.deleteLater()

    def test_desktop_bounds_include_monitor_offset_and_taskbar_inset(self):
        from PySide6.QtCore import QRect
        from lantool.qt.desktop import DesktopArea
        for area in (QRect(-1600, 40, 1600, 860), QRect(80, 0, 1840, 1080)):
            screen = SimpleNamespace(availableGeometry=lambda: area)
            result = DesktopArea.availableGeometry(None, SimpleNamespace(screen=lambda: screen))
            self.assertEqual(result, dict(x=area.x(), y=area.y(), width=area.width(), height=area.height()))

    def test_sidebar_navigation_spacing_room_shortcut_and_about_contents(self):
        from PySide6.QtCore import QMetaObject, QPointF
        self.library()
        self.bridge._room_code = '1234-5678-9abc-def0'
        self.bridge.publish()
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        sidebar = window.findChild(QObject, 'launcherSidebar')
        def items(item):
            yield item
            for child in item.childItems():
                yield from items(child)
        for width in (1280, 1920):
            window.setWidth(width); pump(.05)
            objects = list(items(window.contentItem()))
            buttons = [next(i for i in objects if i.objectName() == 'nav-'+key) for key in ('library','room','downloads','settings')]
            centers = [b.mapToScene(QPointF(b.width()/2,b.height()/2)).x() for b in buttons]
            left = sidebar.mapToScene(QPointF(0,0)).x()
            right = sidebar.mapToScene(QPointF(sidebar.width(),0)).x()
            step = (right-left)/4
            for i, center in enumerate(centers):
                self.assertAlmostEqual(center, left+step*(i+.5), places=3)
        self.assertEqual(window.findChild(QObject, 'sidebarRoomCode').property('text'), self.bridge._room_code)
        QMetaObject.invokeMethod(window.findChild(QObject, 'sidebarRoomPlayersAction'), 'clicked')
        self.assertEqual(self.bridge.state['page'], 'room')
        logo = window.findChild(QObject, 'sidebarAboutAction')
        self.assertEqual((logo.width(),logo.height()), (50,34))
        QMetaObject.invokeMethod(logo, 'clicked'); pump(.05)
        self.assertEqual(self.bridge.state['page'], 'about')
        self.assertIn(self.bridge.state['version'], window.findChild(QObject, 'aboutVersion').property('text'))
        objects = list(items(window.contentItem()))
        urls = {'YouTube': 'https://www.youtube.com/@NoNonsenseLAN',
                'Discord': 'https://discord.com/invite/a9NgtcnH5r',
                'GitHub': 'https://github.com/No-Nonsense-OfficialRepo'}
        for label,url in urls.items():
            link = next(i for i in objects if i.objectName() == 'aboutLink'+label)
            self.assertEqual(link.property('modelData')['url'], url)
        texts = [i.property('text') for i in objects if i.metaObject().indexOfProperty('text') >= 0]
        for name in ('Dante47','LegionZA','Mango','Zeloth'):
            self.assertIn(name, texts)
        self.assertIn('Find our LAN Ready Repository on your Favorite Torrent Site under No-NonsenseLAN', texts)
        self.bridge.config_data['setup_completed'] = False
        self.bridge.navigate('about')
        self.assertEqual(self.bridge.state['page'], 'about')
        self.bridge.navigate('library')
        self.assertEqual(self.bridge.state['page'], 'setup')

    def test_quickstart_terms_appear_once_per_run_and_acknowledgment_survives_reset(self):
        from PySide6.QtCore import QMetaObject
        from lantool.qt.quickstart import QuickStart
        practice = QuickStart()
        self.engine = create_engine(practice)
        window = self.engine.rootObjects()[0]
        popup = window.findChild(QObject, 'termsOfServicePopup')
        pump(.05)
        self.assertTrue(popup.property('visible'))
        self.assertTrue(popup.property('startupAcknowledgment'))
        supplied = self.engine.rootContext().contextProperty('termsOfService')
        self.assertIn('Terms of Service, Software Disclaimer & End-User Liability Notice', supplied)
        self.assertIn('5 November 2026', supplied)
        self.assertIn('END OF DOCUMENT', supplied)
        QMetaObject.invokeMethod(window.findChild(QObject, 'acknowledgeTermsButton'), 'clicked')
        pump(.03)
        self.assertTrue(practice.state['termsAcknowledged'])
        self.assertFalse(popup.property('visible'))
        practice.choose('client')
        practice.reset()
        self.assertTrue(practice.state['termsAcknowledged'])
        self.assertFalse(popup.property('visible'))
        self.assertFalse(QuickStart().state['termsAcknowledged'])

    def test_quickstart_hint_follows_the_current_action(self):
        from PySide6.QtCore import QPointF
        from lantool.qt.quickstart import QuickStart
        practice = QuickStart()
        practice.acknowledgeTerms()
        practice.step('clientFind', host=False)
        self.engine = create_engine(practice)
        window = self.engine.rootObjects()[0]
        window.setWidth(1280)
        hint = window.findChild(QObject, 'tutorialHintPanel')
        target = window.findChild(QObject, 'findHostAction')
        pump(.35)
        self.assertIsNotNone(hint)
        self.assertIsNotNone(target)
        self.assertGreater(hint.width(), 410)
        center = target.mapToScene(QPointF(target.width()/2, target.height()/2))
        left = hint.mapToScene(QPointF(0, 0))
        self.assertLess(abs(left.x() - center.x()), 650)
        def separated(a, b):
            a0, a1 = a.mapToScene(QPointF(0, 0)), a.mapToScene(QPointF(a.width(), a.height()))
            b0, b1 = b.mapToScene(QPointF(0, 0)), b.mapToScene(QPointF(b.width(), b.height()))
            return (a1.x() <= b0.x() or b1.x() <= a0.x()
                    or a1.y() <= b0.y() or b1.y() <= a0.y())
        self.assertTrue(separated(hint, target))
        from lantool.qt.quickstart import GAME
        practice.step('clientPlay', host=False, page='details', selected={**GAME, 'installed': True},
                      allGames=[GAME], gameCount=1)
        pump(.35)
        self.assertTrue(separated(hint, window.findChild(QObject, 'gameActionButton')))
        practice.step('hostOpen', host=True)
        window.setWidth(463)
        window.setHeight(1080)
        pump(.35)
        self.assertTrue(separated(hint, window.findChild(QObject, 'hostStartAction')))

    def test_quickstart_download_fills_over_six_seconds(self):
        from lantool.qt.quickstart import QuickStart
        practice = QuickStart()
        practice.step('clientInstall')
        practice.install()
        self.assertEqual(practice.state['progress']['done'], 0)
        practice._download_started = time.monotonic() - 3
        practice._advance_download()
        halfway = practice.state['progress']['done'] / practice.state['progress']['total']
        self.assertAlmostEqual(halfway, .5, delta=.03)
        practice._download_started = time.monotonic() - 6
        practice._advance_download()
        self.assertEqual(practice.state['progress']['done'], practice.state['progress']['total'])
        self.assertEqual(practice.state['progress']['state'], 'complete')
        self.assertFalse(practice.download_timer.isActive())

    def test_quickstart_can_be_cancelled_from_chooser_and_lessons(self):
        from lantool.qt.quickstart import QuickStart
        practice = QuickStart()
        practice.acknowledgeTerms()
        self.engine = create_engine(practice)
        window = self.engine.rootObjects()[0]
        chooser_close = window.findChild(QObject, 'tutorialChooserClose')
        self.assertIsNotNone(chooser_close)
        self.assertTrue(chooser_close.property('visible'))
        practice.step('clientFind', host=False)
        pump(.05)
        cancel = window.findChild(QObject, 'tutorialCancelAction')
        self.assertEqual(cancel.property('text'), 'Back')
        self.assertTrue(cancel.property('visible'))

    def test_about_shortcuts_terms_and_header_font(self):
        from PySide6.QtCore import QMetaObject
        self.library()
        self.bridge.settingsTab('Diagnostics')
        self.bridge.show_page('settings')
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        QMetaObject.invokeMethod(window.findChild(QObject, 'diagnosticsAboutButton'), 'clicked')
        pump(.04)
        self.assertEqual(self.bridge.state['page'], 'about')
        buttons = window.findChildren(QObject, 'aboutTermsButton')
        visible = [b for b in buttons if b.property('visible')]
        self.assertEqual(len(visible), 1)
        QMetaObject.invokeMethod(visible[0], 'clicked')
        popup = window.findChild(QObject, 'termsOfServicePopup')
        pump(.03)
        self.assertTrue(popup.property('visible'))
        self.assertFalse(popup.property('startupAcknowledgment'))
        QMetaObject.invokeMethod(popup, 'close')
        self.bridge.navigate('library')
        QMetaObject.invokeMethod(window.findChild(QObject, 'versionAboutLink'), 'activate')
        self.assertEqual(self.bridge.state['page'], 'about')
        self.bridge.role = 'host'; self.bridge.publish(); pump(.03)
        QMetaObject.invokeMethod(window.findChild(QObject, 'versionAboutLink'), 'activate')
        self.assertTrue(window.findChild(QObject, 'hostAboutPopup').property('visible'))

    def test_diagnostics_rows_show_aligned_status_marks(self):
        self.engine=create_engine(self.bridge)
        window=self.engine.rootObjects()[0]
        self.bridge.config_data['setup_completed']=True
        self.bridge._setting_tab='Diagnostics'
        self.bridge._diag={'running':False,'step':'','done':0,'total':0,'error':'','lines':[],'path':'','worst':'fail',
                           'rows':[{'title':'VLA service','status':'ok','detail':'Running'},
                                   {'title':'Peers','status':'fail','detail':'none'},
                                   {'title':'Firewall rules','status':'warn','detail':'check'}]}
        self.bridge.show_page('settings');pump(.1)
        results=window.findChild(QObject,'diagResults')
        self.assertIsNotNone(results)
        self.assertTrue(results.property('visible'))
        def walk(item):
            for child in item.childItems():
                yield child
                yield from walk(child)
        marks=[c for c in walk(results) if c.property('text') in ('OK','X','!')]
        self.assertEqual([m.property('text') for m in marks],['OK','X','!'])
        self.assertEqual(len({round(m.mapToItem(results,0,0).x()) for m in marks}),1)  # one aligned column

    def test_room_setup_runs_on_worker_and_returns_to_gui(self):
        room=SimpleNamespace(network_id='8056c2e21c000001')
        seen=[]
        self.tunnel.open_room=Mock(side_effect=lambda name:(seen.append(threading.get_ident()),room)[1])
        self.tunnel.wait_connected=Mock(return_value=SimpleNamespace(state=core.CONNECTED))
        self.bridge._room_opened=lambda value:seen.append((value,QThread.currentThread()))
        self.bridge.open_room('Test room')
        pump_until(lambda: not self.bridge.busy, timeout=3)
        self.assertFalse(self.bridge.busy)
        self.assertNotEqual(seen[0],threading.get_ident())
        self.assertEqual(seen[1],(room,self.app.thread()))
        self.assertEqual(self.bridge.state['dialog'],{})

    def test_room_failure_records_worker_traceback(self):
        def fail():
            raise TypeError("'lazy_import' object is not callable")
        self.bridge._run_background(fail,lambda value:self.fail('Unexpected success'))
        pump_until(lambda: not self.bridge.busy, timeout=3)
        self.assertFalse(self.bridge.busy)
        self.assertIn('lazy_import',self.bridge.state['dialog']['message'])
        log=(self.root/'room-errors.log').read_text(encoding='utf-8')
        self.assertIn('Traceback',log)
        self.assertIn('in fail',log)

    def test_live_presence_and_sync_updates(self):
        self.library()
        presence=SimpleNamespace(on_counts=None,on_players=None,subscribe_players=lambda:async_nothing())
        self.bridge.pages["library"].set_presence(presence)
        t=threading.Thread(target=lambda:presence.on_counts({"games":{"g3":{"playing":2}},"players":2}))
        t.start();t.join();pump()
        self.bridge.filterGames("Playing")
        self.assertEqual(self.bridge.state["games"][0]["id"],"g3")
        self.bridge._show_sync_progress("Game 03")
        self.bridge._update_sync_progress("Game 03",50,100,"files/main.dat")
        self.assertEqual(self.bridge.state["page"],"downloads")
        self.assertEqual(self.bridge.state["progress"]["done"],50)
        self.bridge._close_sync_progress()
        self.assertFalse(self.bridge.state["progress"]["active"])
        self.bridge.pages["library"].set_presence(None)
        self.assertIsNone(presence.on_counts)

    def test_catalog_editor_preserves_playlist_behavior(self):
        self.bridge.role="host"
        folder=self.bridge.game_root/"Example"
        folder.mkdir(parents=True)
        exe=folder/"game.exe";exe.write_bytes(b"data")
        self.bridge.manage_game_directory()
        self.assertEqual(self.bridge.state["catalog"][0]["name"],"Example")
        self.bridge.editFolder(str(folder))
        self.bridge.saveGame(str(folder),str(exe),"Example game","-lan",True,"")
        self.assertEqual(self.bridge.state["page"],"catalog")
        self.assertEqual(self.bridge.state["gameCount"],1)
        self.assertTrue(self.bridge.state["catalog"][0]["enabled"])

    def test_host_parameters_saved_and_invalid_input_keeps_previous_value(self):
        self.bridge.role='host'
        folder=self.bridge.game_root/'Example'
        folder.mkdir(parents=True)
        exe=folder/'game.exe';exe.write_bytes(b'game')
        self.bridge.register_game(folder,exe,'Example')
        self.bridge.setHostGameEnabled(str(folder),True)
        self.assertTrue(self.bridge.saveHostLaunchArgs(str(folder), '+connect {host_ip} +name "{name}" -lan'))
        pump_until(lambda:not self.bridge.state['hostArgsSaving'])
        expected=['+connect','{host_ip}','+name','{name}','-lan']
        manifest=self.bridge.game_for_folder(folder)
        self.assertEqual(manifest['args'],expected)
        self.assertEqual(self.bridge.library[manifest['id']]['args'],expected)
        from lantool.game_directory import load_catalog
        persisted=load_catalog(self.bridge.host_catalog_path,self.bridge.game_root,self.bridge.host_art_root)
        self.assertEqual(persisted[manifest['id']]['args'],expected)
        results=[]
        self.bridge.hostLaunchArgsFinished.connect(lambda *result:results.append(result))
        self.assertFalse(self.bridge.saveHostLaunchArgs(str(folder),'"unterminated'))
        self.assertEqual(manifest['args'],expected)
        self.assertFalse(results[-1][1])
        self.assertIn('quotation',results[-1][2])
        self.assertTrue(self.bridge.saveHostLaunchArgs(str(folder),''))
        pump_until(lambda:not self.bridge.state['hostArgsSaving'])
        self.assertEqual(self.bridge.library[manifest['id']]['args'],[])
        self.bridge.dismissDialog()
        self.engine=create_engine(self.bridge)
        window=self.engine.rootObjects()[0]
        pump(.1)
        def items(item):
            yield item
            for child in item.childItems():
                yield from items(child)
        action=next(item for item in items(window.contentItem())
                    if item.property('text')=='Launch parameters' and item.metaObject().indexOfSignal('clicked()')>=0)
        from PySide6.QtCore import QMetaObject
        QMetaObject.invokeMethod(action,'click');pump(.05)
        popup=window.findChild(QObject,'hostLaunchParametersPopup')
        self.assertTrue(popup.property('visible'))
        window.findChild(QObject,'hostLaunchArgumentsField').setProperty('text','-lan')
        QMetaObject.invokeMethod(window.findChild(QObject,'hostSaveLaunchArgumentsAction'),'click')
        pump_until(lambda:not popup.property('visible'))
        self.assertFalse(popup.property('visible'))
        self.assertEqual(self.bridge.library[manifest['id']]['args'],['-lan'])

    def test_host_parameter_editor_survives_refresh_and_slow_or_failed_save(self):
        from PySide6.QtCore import QMetaObject, QTimer, QPointF, Qt
        from PySide6.QtTest import QTest
        from shiboken6 import isValid
        self.bridge.role='host'
        folder=self.bridge.game_root/'Example';folder.mkdir(parents=True)
        exe=folder/'game.exe';exe.write_bytes(b'game')
        self.bridge.register_game(folder,exe,'Example',['-before'])
        self.bridge.setHostGameEnabled(str(folder),True)
        self.engine=create_engine(self.bridge)
        window=self.engine.rootObjects()[0];pump(.1)
        def items(item):
            yield item
            for child in item.childItems():yield from items(child)
        action=next(item for item in items(window.contentItem())
                    if item.property('text')=='Launch parameters' and item.metaObject().indexOfSignal('clicked()')>=0)
        point=action.mapToScene(QPointF(action.width()/2,action.height()/2)).toPoint()
        QTest.mousePress(window,Qt.LeftButton,Qt.NoModifier,point)
        for i in range(3):
            self.bridge.publish();pump(.01)
            self.assertTrue(isValid(action),'Presence refresh destroyed a pressed game action')
        QTest.mouseRelease(window,Qt.LeftButton,Qt.NoModifier,point);pump(.05)
        popup=window.findChild(QObject,'hostLaunchParametersPopup')
        field=window.findChild(QObject,'hostLaunchArgumentsField')
        save=window.findChild(QObject,'hostSaveLaunchArgumentsAction')
        self.assertTrue(popup.property('visible'))
        self.assertTrue(field.hasActiveFocus())
        entered,release=threading.Event(),threading.Event()
        original=core.save_catalog
        def slow_save(*args):
            entered.set()
            if not release.wait(3):raise TimeoutError('Test save not released')
            original(*args)
        with patch.object(core,'save_catalog',side_effect=slow_save) as writer, \
             patch.object(self.bridge,'manage_game_directory',side_effect=AssertionError('Parameter save rescanned games')):
            try:
                field.setProperty('text','-after')
                QMetaObject.invokeMethod(save,'click')
                wait_for_worker(entered)
                self.assertTrue(self.bridge.state['hostArgsSaving'])
                self.assertTrue(popup.property('visible'))
                self.assertFalse(save.property('enabled'))
                self.assertFalse(self.bridge.saveHostLaunchArgs(str(folder),'-duplicate'))
                ticks=[];QTimer.singleShot(0,lambda:ticks.append(True));pump(.03)
                self.assertEqual(ticks,[True],'GUI stalled while catalog was being saved')
            finally:
                release.set()
                pump_until(lambda:not self.bridge.state['hostArgsSaving'])
            self.assertEqual(writer.call_count,1)
        self.assertFalse(popup.property('visible'))
        manifest=self.bridge.game_for_folder(folder)
        self.assertEqual(manifest['args'],['-after'])
        QMetaObject.invokeMethod(action,'click');pump(.03)
        self.assertEqual(field.property('text'),'-after')
        with patch.object(core,'save_catalog',side_effect=OSError('Disk temporarily unavailable')):
            field.setProperty('text','-failed')
            QMetaObject.invokeMethod(save,'click')
            pump_until(lambda:not self.bridge.state['hostArgsSaving'])
        self.assertTrue(popup.property('visible'))
        self.assertIn('Disk temporarily unavailable',popup.property('saveError'))
        self.assertEqual(field.property('text'),'-failed')
        self.assertEqual(manifest['args'],['-after'])

    def test_host_setup_popup_never_covers_client_downloads(self):
        self.library()
        self.engine=create_engine(self.bridge)
        window=self.engine.rootObjects()[0]
        popup=window.findChild(QObject,'hostPreparationPopup')
        self.bridge.busy=True
        self.bridge._progress['active']=True
        self.bridge._page='downloads'
        self.bridge.publish();pump(.03)
        self.assertFalse(popup.property('visible'))
        self.bridge._progress['active']=False
        self.bridge.publish();pump(.03)
        self.assertFalse(popup.property('visible'))
        self.bridge.role='host';self.bridge.publish();pump(.03)
        self.assertTrue(popup.property('visible'))
        self.bridge._progress['active']=True
        self.bridge.publish();pump(.03)
        self.assertFalse(popup.property('visible'))

    def test_same_pc_host_shared_folder_needs_no_client_install(self):
        self.library()
        self.bridge._selected='g0'
        manifest=self.bridge.library['g0']
        manifest['exe_required']=False
        manifest['_local_host_source']=manifest['install_dir']
        self.bridge.room=SimpleNamespace(host_ip='127.0.0.1')
        self.bridge.publish()
        self.assertTrue(self.bridge.state['selected']['installed'])
        with patch.object(self.bridge,'_sync_then_play') as sync:
            self.bridge.install()
            pump_until(lambda:not self.bridge.busy)
        sync.assert_not_called()
        self.assertIn('already available',self.bridge.state['status'])

    def test_connected_client_launch_uses_host_parameters_over_local_override(self):
        self.library()
        self.bridge._selected='g2'
        self.bridge.config_data['launch_arguments']={'g2':['-local-stale']}
        self.bridge.library['g2']['args']=['+connect','{host_ip}','+name','{name}']
        self.bridge.room=SimpleNamespace(host_ip='10.1.2.3')
        self.bridge.publish()
        self.assertTrue(self.bridge.state['selected']['argsManagedByHost'])
        self.assertNotIn('local-stale',self.bridge.state['selected']['args'])
        self.bridge.saveLaunchArgs('-client-change')
        self.assertEqual(self.bridge.config_data['launch_arguments']['g2'],['-local-stale'])
        with patch.object(self.bridge,'_play_game') as launch:
            self.bridge.play()
            pump_until(lambda:launch.called)
        manifest,context=launch.call_args.args
        from lantool.manifests.loader import build_command
        self.assertEqual(build_command(manifest,context)[1:],['+connect','10.1.2.3','+name','Player'])

    def test_condensed_host_renders_and_icon_browse_updates_catalog(self):
        from PIL import Image
        self.bridge.role='host'
        folder=self.bridge.game_root/'Example'
        folder.mkdir(parents=True)
        exe=folder/'game.exe';exe.write_bytes(b'game')
        art=self.root/'cover.png';Image.new('RGB',(20,20),'red').save(art)
        with patch.object(self.bridge,'chooseFile',return_value=str(exe)):
            self.bridge.browseHostGame(str(folder),'exe')
        with patch.object(self.bridge,'chooseFile',return_value=str(art)):
            self.bridge.browseHostGame(str(folder),'art')
        self.assertTrue(self.bridge.state['catalog'][0]['art'].startswith('file:'))
        self.bridge.setHostGameEnabled(str(folder),True)
        self.assertTrue(self.bridge.state['catalog'][0]['enabled'])
        self.bridge.pages['room'].set_roster([{'player_id':'client-1','name':'Player','ip':'10.1.2.3'}])
        self.assertEqual(self.bridge.state['playerCount'],1)
        self.assertEqual(self.bridge.state['players'][0]['ip'],'10.1.2.3')
        self.engine=create_engine(self.bridge)
        warnings=[]
        self.engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
        pump()
        shot=self.engine.rootObjects()[0].grabWindow()
        self.assertFalse(shot.isNull())
        self.assertEqual((self.engine.rootObjects()[0].width(),self.engine.rootObjects()[0].height()),(463,1080))
        preview=Path(__file__).resolve().parents[1]/'build'/'qt-preview'/'host-zones.png'
        preview.parent.mkdir(parents=True,exist_ok=True)
        shot.save(str(preview))
        self.assertEqual(warnings,[])

    def test_host_game_picker_starts_in_game_folder_and_matches_artwork(self):
        from PIL import Image
        folder = self.bridge.game_root / 'Example Game'
        folder.mkdir(parents=True)
        exe = folder / 'launcher.exe'
        exe.write_bytes(b'game')
        art = folder / 'Example Game.png'
        Image.new('RGB', (20, 20), 'red').save(art)
        with patch.object(self.bridge, 'chooseFile', return_value=str(exe)) as picker:
            self.bridge.browseHostGame(str(folder), 'exe')
        picker.assert_called_once_with('exe', str(folder))
        game = self.bridge.game_for_folder(str(folder))
        self.assertTrue(game['_art_path'])
        with patch.object(self.bridge, 'chooseFile', return_value='') as picker:
            self.bridge.browseHostGame(str(folder), 'art')
        picker.assert_called_once_with('art', str(folder))

    def test_host_auto_art_uses_local_cover_and_keeps_manual_choice(self):
        from PIL import Image
        folder = self.bridge.game_root / 'Example Game'
        folder.mkdir(parents=True)
        exe = folder / 'launcher.exe'
        exe.write_bytes(b'game')
        cover = folder / 'cover.jpg'
        Image.new('RGB', (20, 30), 'red').save(cover)
        Image.new('RGB', (20, 30), 'blue').save(folder / 'screenshot.png')

        with patch.object(self.bridge, 'chooseFile', return_value=str(exe)):
            self.bridge.browseHostGame(str(folder), 'exe')
        game = self.bridge.game_for_folder(str(folder))
        self.assertTrue(game['_art_path'])
        self.assertTrue(self.bridge.state['catalog'][0]['art'].startswith('file:'))

        manual = self.root / 'manual.png'
        Image.new('RGB', (20, 30), 'green').save(manual)
        with patch.object(self.bridge, 'chooseFile', return_value=str(manual)):
            self.bridge.browseHostGame(str(folder), 'art')
        chosen_hash = game['art_sha256']
        with patch.object(self.bridge, 'chooseFile', return_value=str(exe)):
            self.bridge.browseHostGame(str(folder), 'exe')
        self.assertEqual(game['art_sha256'], chosen_hash)

    def test_host_auto_art_skips_ambiguous_images(self):
        from PIL import Image
        folder = self.bridge.game_root / 'Example Game'
        folder.mkdir(parents=True)
        exe = folder / 'launcher.exe'
        exe.write_bytes(b'game')
        for name in ('scene-one.png', 'scene-two.png'):
            Image.new('RGB', (20, 30), 'red').save(folder / name)
        with patch.object(self.bridge, 'chooseFile', return_value=str(exe)):
            self.bridge.browseHostGame(str(folder), 'exe')
        self.assertNotIn('_art_path', self.bridge.game_for_folder(str(folder)))

    def test_host_recheck_is_clickable_and_hashes_with_room_closed(self):
        self.bridge.role = 'host'
        folder = self.bridge.game_root / 'Offline Game'
        folder.mkdir(parents=True)
        exe = folder / 'game.exe'
        exe.write_bytes(b'game')
        self.bridge.register_game(str(folder), str(exe), 'Offline Game')
        game = self.bridge.game_for_folder(str(folder))
        self.bridge.toggle_game_playlist(game['id'])
        self.bridge.manage_game_directory()
        self.assertEqual(len(self.bridge.state['catalog']), 1)
        self.bridge.recheckGameIndex(game['id'])
        self.assertEqual(self.bridge._host_index_status[game['id']]['state'], 'running')
        pump_until(lambda: self.bridge._host_index_status.get(game['id'], {}).get('state') == 'ready', 5)
        self.assertEqual(self.bridge._host_index_status[game['id']]['state'], 'ready', self.bridge._status)
        pump_until(lambda: self.bridge._index_ready_file.is_file(), 5)
        self.assertTrue(self.bridge._index_ready_file.is_file())
        with patch.object(core, 'HOST_ROLE', 'host'):
            reopened = LauncherBridge(start_services=False)
        try:
            pump_until(lambda: reopened._host_index_status.get(game['id'], {}).get('state') == 'ready', 5)
            self.assertEqual(reopened._host_index_status[game['id']]['state'], 'ready')
        finally:
            reopened._destroyed = True
            reopened.runtime.stop()
        self.bridge._index_ready_file.unlink()
        with patch.object(core, 'HOST_ROLE', 'host'):
            migrated = LauncherBridge(start_services=False)
        try:
            pump_until(lambda: migrated._host_index_status.get(game['id'], {}).get('state') == 'ready', 5)
            self.assertEqual(migrated._host_index_status[game['id']]['state'], 'ready')
            self.assertTrue(migrated._index_ready_file.is_file())
        finally:
            migrated._destroyed = True
            migrated.runtime.stop()
        exe.write_bytes(b'changed game')
        self.bridge._host_index_status.clear()
        self.bridge._restore_index_ready()
        pump(.3)
        self.assertNotIn(game['id'], self.bridge._host_index_status)

    def test_qml_pages_render_and_grid_scrolls(self):
        self.library()
        self.bridge._selected="g2"
        self.engine=create_engine(self.bridge)
        warnings=[]
        self.engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
        window=self.engine.rootObjects()[0]
        for page in ["library","details","room","settings","profile","downloads","gameSettings","activity","setup"]:
            self.bridge._page=page;self.bridge.publish();pump(.2)
            self.assertFalse(window.grabWindow().isNull(),page)
        self.bridge._page="library";self.bridge.publish();pump()
        grid=window.findChild(QObject,"gameGrid")
        self.assertIsNotNone(grid)
        self.assertEqual(grid.property("count"),16)
        grid.setProperty("contentY",400)
        self.assertGreater(grid.property("contentY"),0)
        self.assertEqual(warnings,[])

    def test_host_close_room_requires_confirmation(self):
        from PySide6.QtCore import QMetaObject
        self.bridge.role = 'host'
        self.bridge.room = SimpleNamespace(network_id='8056c2e21c000001')
        self.bridge.publish()
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        action = window.findChild(QObject, 'hostStartAction')
        confirmation = window.findChild(QObject, 'hostCloseConfirmation')
        self.assertIsNotNone(action)
        with patch.object(self.bridge, 'leave') as leave:
            QMetaObject.invokeMethod(action, 'click')
            pump(.03)
            self.assertTrue(confirmation.property('visible'))
            leave.assert_not_called()
            QMetaObject.invokeMethod(window.findChild(QObject, 'hostCloseCancelAction'), 'click')
            pump(.03)
            leave.assert_not_called()
            QMetaObject.invokeMethod(action, 'click')
            pump(.03)
            QMetaObject.invokeMethod(window.findChild(QObject, 'hostCloseAcceptAction'), 'click')
            pump(.03)
            leave.assert_called_once()
        self.bridge.room = None

    def test_hover_description_waits_point_eight_seconds_and_clears(self):
        from PySide6.QtCore import QMetaObject, QUrl
        from PySide6.QtQml import QQmlComponent
        self.library()
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        # Isolate the dwell service from the desktop cursor hovering another item.
        window.contentItem().setEnabled(False)
        pump(.15)
        component = QQmlComponent(self.engine)
        qml = b'''import QtQuick
import "."
Item {
    id: owner
    function startHint() { HoverHelp.begin(owner, "Hover timing regression description."); }
    function stopHint() { HoverHelp.end(owner); }
}
'''
        base = Path(__file__).resolve().parents[1] / 'lantool/qt/qml/HoverHelpHarness.qml'
        component.setData(qml, QUrl.fromLocalFile(str(base)))
        harness = component.create()
        self.assertIsNotNone(harness, [e.toString() for e in component.errors()])
        panel = window.findChild(QObject, 'hoverDescriptionPanel')
        label = window.findChild(QObject, 'hoverDescriptionText')
        QMetaObject.invokeMethod(harness, 'startHint')
        pump(.55)
        self.assertFalse(panel.property('visible'))
        pump(.60)
        self.assertTrue(panel.property('visible'))
        self.assertEqual(label.property('text'), 'Hover timing regression description.')
        self.assertGreater(panel.property('x'), window.width() / 2)
        self.assertGreater(panel.property('y'), window.height() / 2)
        QMetaObject.invokeMethod(harness, 'stopHint')
        pump(.03)
        self.assertFalse(panel.property('visible'))
        QMetaObject.invokeMethod(harness, 'startHint')
        pump(.03)
        QMetaObject.invokeMethod(harness, 'stopHint')
        pump(.95)
        self.assertFalse(panel.property('visible'))
        harness.deleteLater()
        pump(.03)

    def test_supplied_themes_apply_persist_and_keep_preview_isolated(self):
        import json
        from PySide6.QtCore import QMetaObject, QSettings, QUrl
        from PySide6.QtQml import QQmlComponent, QQmlEngine
        self.library()
        self.bridge.settingsTab('Appearance')
        self.bridge.show_page('settings')
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        settings_path = self.root / 'appearance.ini'
        location = json.dumps(QUrl.fromLocalFile(str(settings_path)).toString())
        qml = ('import QtQuick\nimport "."\nItem {\n'
               'property string chosen: Theme.currentName\n'
               'property string foreground: String(Theme.paper)\n'
               'property string uiFamily: Theme.ui\n'
               'property string headingFamily: Theme.heading\n'
               'Component.onCompleted: { Theme.preferences.location = '+location+'; Theme.reload(); }\n'
               'function invalidTheme() { Theme.apply("Unknown"); }\n'
               'ThemePicker { id: picker; width: 747 }\n'
               'function chooseDark() { for(let child of picker.children) if(child.themeName === "Dark") { child.click(); return; } }\n'
               'function chooseNeon() { for(let child of picker.children) if(child.themeName === "Neon") { child.click(); return; } }\n'
               'function choosePearl() { Theme.apply("Pearl"); }\n'
               '}').encode()
        base = Path(__file__).resolve().parents[1] / 'lantool/qt/qml/ThemeHarness.qml'
        component = QQmlComponent(self.engine)
        component.setData(qml, QUrl.fromLocalFile(str(base)))
        harness = component.create()
        self.assertIsNotNone(harness, [e.toString() for e in component.errors()])
        self.assertEqual(harness.property('chosen'), 'No-Nonsense')
        self.assertEqual(harness.property('foreground').lower(), '#ede9e1')
        pump(.12)
        warnings = []
        self.engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
        for name, color in [('Dark', '#e4e5e7'), ('Neon', '#f3e9ff')]:
            QMetaObject.invokeMethod(harness, 'choose'+name)
            pump(.12)
            self.assertEqual(harness.property('chosen'), name)
            self.assertEqual(harness.property('foreground').lower(), color)
            self.assertEqual(harness.property('uiFamily'), 'Inter')
            self.assertEqual(harness.property('headingFamily'), 'Cinzel')
        saved = QSettings(str(settings_path), QSettings.IniFormat)
        self.assertEqual(saved.value('Appearance/theme'), 'Neon')
        QMetaObject.invokeMethod(harness, 'invalidTheme')
        self.assertEqual(harness.property('chosen'), 'Neon')
        # A new QML engine reloads the same saved appearance preference.
        fresh_engine = QQmlEngine()
        fresh_engine.rootContext().setContextProperty('backend', self.bridge)
        fresh_component = QQmlComponent(fresh_engine)
        fresh_component.setData(qml, QUrl.fromLocalFile(str(base)))
        fresh = fresh_component.create()
        self.assertIsNotNone(fresh, [e.toString() for e in fresh_component.errors()])
        self.assertEqual(fresh.property('chosen'), 'Neon')
        fresh.deleteLater(); fresh_engine.deleteLater(); pump(.03)
        # Preview can change its own appearance but cannot overwrite the preference.
        self.bridge._preview = True
        self.bridge.publish()
        QMetaObject.invokeMethod(harness, 'chooseDark')
        pump(.05)
        saved.sync()
        self.assertEqual(saved.value('Appearance/theme'), 'Neon')
        self.assertEqual(harness.property('chosen'), 'Dark')
        QMetaObject.invokeMethod(harness, 'choosePearl')
        for name in ['Dark', 'Neon', 'Pearl']:
            self.bridge._preview = False
            self.bridge.publish()
            if name == 'Dark':
                QMetaObject.invokeMethod(harness, 'chooseDark')
            elif name == 'Neon':
                QMetaObject.invokeMethod(harness, 'chooseNeon')
            else:
                QMetaObject.invokeMethod(harness, 'choosePearl')
            pump(.08)
            for page in ['library','details','room','settings','profile','downloads','gameSettings','activity','setup']:
                self.bridge._page = page; self.bridge.publish(); pump(.2)
                self.assertFalse(window.grabWindow().isNull(), name+' '+page)
            self.bridge._page = 'settings'; self.bridge.publish(); pump(.03)
        self.assertEqual(warnings, [], "\n".join(warnings))
        harness.deleteLater(); pump(.03)

    def test_window_resolutions_save_independently_and_fit_each_role(self):
        import json
        from PySide6.QtCore import QMetaObject, QSettings, QUrl, Q_ARG
        from PySide6.QtQml import QQmlComponent, QQmlEngine
        self.library()
        self.bridge.settingsTab('Appearance')
        self.bridge.show_page('settings')
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        path = self.root / 'window.ini'
        location = json.dumps(QUrl.fromLocalFile(str(path)).toString())
        qml = ('import QtQuick\nimport "."\nItem {\n'
               'property string client: WindowPreferences.clientResolution\n'
               'property string host: WindowPreferences.hostResolution\n'
               'property var clients: WindowPreferences.choices\n'
               'property var hosts: WindowPreferences.hostChoices\n'
               'Component.onCompleted: { WindowPreferences.store.location='+location+'; WindowPreferences.reload(); }\n'
               'function invalid() { WindowPreferences.apply("9000x9000",false); WindowPreferences.apply("9000",true); }\n'
               '}').encode()
        base = Path(__file__).resolve().parents[1] / 'lantool/qt/qml/ResolutionHarness.qml'
        component = QQmlComponent(self.engine)
        component.setData(qml, QUrl.fromLocalFile(str(base)))
        harness = component.create()
        self.assertIsNotNone(harness, [e.toString() for e in component.errors()])
        pump(.15)
        warnings = []
        self.engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
        client_picker = window.findChild(QObject, 'clientResolutionSelector')
        host_picker = window.findChild(QObject, 'hostResolutionSelector')
        self.assertIsNotNone(client_picker)
        self.assertIsNotNone(host_picker)
        clients = harness.property('clients').toVariant()
        hosts = harness.property('hosts').toVariant()
        self.assertEqual([c['height'] for c in clients], [720,768,900,1080,1440,1800,2160])
        self.assertEqual([c['height'] for c in clients], [c['height'] for c in hosts])
        self.assertEqual((hosts[-1]['width'],hosts[-1]['height']), (926,2160))
        for index, choice in enumerate(clients):
            QMetaObject.invokeMethod(client_picker, 'activated', Q_ARG(int,index))
            pump(.04)
            self.assertEqual(harness.property('client'), choice['key'])
            self.assertLessEqual(abs(window.width()/window.height()-16/9),.003)
            self.assertLessEqual(window.width(),choice['width'])
            self.assertLessEqual(window.height(),choice['height'])
        client_size = (window.width(),window.height())
        QMetaObject.invokeMethod(host_picker, 'activated', Q_ARG(int,6))
        self.assertEqual((window.width(),window.height()),client_size)
        saved = QSettings(str(path), QSettings.IniFormat)
        self.assertEqual(saved.value('Window/resolution'),'3840x2160')
        self.assertEqual(saved.value('Window/hostResolution'),'2160')
        QMetaObject.invokeMethod(harness,'invalid')
        self.assertEqual(harness.property('client'),'3840x2160')
        self.assertEqual(harness.property('host'),'2160')
        # A new engine reads both preferences, independently of the current role.
        fresh_engine = QQmlEngine()
        fresh_engine.rootContext().setContextProperty('backend',self.bridge)
        fresh_component = QQmlComponent(fresh_engine)
        fresh_component.setData(qml,QUrl.fromLocalFile(str(base)))
        fresh = fresh_component.create()
        self.assertIsNotNone(fresh,[e.toString() for e in fresh_component.errors()])
        self.assertEqual(fresh.property('client'),'3840x2160')
        self.assertEqual(fresh.property('host'),'2160')
        fresh.deleteLater(); fresh_engine.deleteLater(); pump(.03)
        # Host offers its own live selector; client choices cannot resize it.
        self.bridge.role='host'; self.bridge.publish(); pump(.12)
        host_view = window.findChild(QObject,'hostView')
        host_picker = host_view.findChild(QObject,'hostResolutionSelector')
        QMetaObject.invokeMethod(host_view.findChild(QObject,'hostAppearanceAction'),'clicked')
        pump(.05)
        self.assertTrue(host_view.findChild(QObject,'hostAppearancePopup').property('visible'))
        for index,choice in enumerate(hosts):
            QMetaObject.invokeMethod(host_picker,'activated',Q_ARG(int,index)); pump(.04)
            self.assertLessEqual(abs(window.width()-window.height()*9/21),1)
            self.assertLessEqual(window.height(),choice['height'])
            self.assertLessEqual(window.height(),max(window.minimumHeight(),window.screen().availableGeometry().height()))
        self.assertTrue(window.findChild(QObject,'hostFlatBackground').property('visible'))
        self.assertEqual(window.findChild(QObject,'hostFlatBackground').property('opacity'),1.0)
        self.assertEqual(window.grabWindow().pixelColor(1,window.height()//2).alpha(),255)
        self.assertFalse(window.findChild(QObject,'launcherGlassBackground').property('visible'))
        self.assertFalse(window.grabWindow().isNull())
        # Preview changes stay local and never overwrite the saved choice.
        self.bridge._preview=True; self.bridge.publish()
        QMetaObject.invokeMethod(host_picker,'activated',Q_ARG(int,0)); pump(.04)
        self.assertEqual(harness.property('host'),'720')
        saved.sync()
        self.assertEqual(saved.value('Window/hostResolution'),'2160')
        self.assertEqual(warnings,[], '\n'.join(warnings))
        harness.deleteLater(); pump(.03)

    def test_download_button_pauses_resumes_and_launches_only_after_completion(self):
        import asyncio
        from PySide6.QtCore import QMetaObject
        self.library()
        self.bridge._selected='g0'
        self.bridge.room=SimpleNamespace(host_ip='127.0.0.1')
        self.bridge.host_room=None
        self.bridge.last_beacon={'host_zt':'127.0.0.1','sync_port':1}
        self.bridge.trusted_host_pub='fixture'
        finish=threading.Event()
        async def transfer(*args,progress,control,**kwargs):
            async def operation():
                progress(4,12,'game.exe')
                while not finish.is_set():
                    await asyncio.sleep(.01)
                return SimpleNamespace(ok=True,verified_files={'g0':['game.exe']})
            return await control.run(operation)
        self.engine=create_engine(self.bridge)
        window=self.engine.rootObjects()[0]
        with patch.object(core,'sync_game',transfer), patch('lantool.manifests.loader.launch') as launch:
            self.bridge._sync_then_play(self.bridge.library['g0'],{})
            pump(.15)
            button=window.findChild(QObject,'downloadPauseAction')
            self.assertTrue(button.property('visible'))
            QMetaObject.invokeMethod(button,'clicked')
            pump_until(lambda: self.bridge.state['progress']['state']=='paused')
            self.assertEqual(self.bridge.state['progress']['state'],'paused')
            self.assertEqual(self.bridge.state['progress']['done'],4)
            self.assertEqual(button.property('text'),'Pause download')
            self.assertFalse(button.property('enabled'))
            self.assertTrue(self.bridge.syncing_game)
            launch.assert_not_called()
            # Queued progress must not silently clear the pause state.
            self.bridge._update_sync_progress('Game 00',4,12,'game.exe')
            self.assertEqual(self.bridge.state['progress']['state'],'paused')
            resume = window.findChild(QObject, 'downloadResumeAction')
            self.assertTrue(resume.property('enabled'))
            self.assertNotEqual(resume.property('iconName'), button.property('iconName'))
            QMetaObject.invokeMethod(resume,'clicked')
            pump_until(lambda: self.bridge.state['progress']['state']=='receiving')
            self.assertEqual(self.bridge.state['progress']['state'],'receiving')
            finish.set()
            pump_until(lambda: not self.bridge.syncing_game)
            launch.assert_called_once()
            self.assertFalse(self.bridge.syncing_game)
            self.assertFalse(self.bridge.state['progress']['active'])
            self.assertFalse(button.property('visible'))

    def test_portrait_install_stays_in_library_and_only_updates_its_game(self):
        import asyncio
        self.library()
        self.bridge.library = {gid: self.bridge.library[gid] for gid in ('g1', 'g3')}
        self.bridge.library['g3']['name'] = self.bridge.library['g1']['name']
        self.bridge._selected = 'g3'
        self.bridge.room = SimpleNamespace(host_ip='127.0.0.1')
        self.bridge.last_beacon = {'host_zt': '127.0.0.1', 'sync_port': 1}
        self.bridge.trusted_host_pub = 'fixture'
        finish = threading.Event()

        async def transfer(_host, _port, _pub, gid, dest, **_options):
            while not finish.is_set():
                await asyncio.sleep(.01)
            (Path(dest) / 'game.exe').touch()
            return SimpleNamespace(ok=True, verified_files={gid: ['game.exe']})

        def items(item):
            yield item
            for child in item.childItems():
                yield from items(child)

        self.bridge.publish()
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        with patch.object(self.bridge, '_prepare_client_game', return_value=False), \
             patch.object(core, 'sync_game', transfer):
            self.bridge.installGame('g1')
            try:
                pump_until(lambda: self.bridge.state['progress']['active'])
                self.assertEqual(self.bridge.state['page'], 'library')
                self.assertEqual(self.bridge.state['progress']['game_id'], 'g1')
                self.assertEqual(self.bridge.state['selected']['id'], 'g3')
                cards = {item.objectName(): item for item in items(window.contentItem())}
                self.assertTrue(cards['libraryPortrait-g1'].property('downloading'))
                self.assertFalse(cards['libraryPortrait-g3'].property('downloading'))
            finally:
                finish.set()
                pump_until(lambda: not self.bridge.syncing_game)
        self.assertEqual(self.bridge.state['page'], 'library')
        self.assertEqual({game['id']: game['installed'] for game in self.bridge.state['games']},
                         {'g1': True, 'g3': False})

    def test_download_queue_is_fifo_deduplicated_and_stays_in_library(self):
        import asyncio
        self.library()
        self.bridge.room = SimpleNamespace(host_ip='127.0.0.1')
        self.bridge.last_beacon = {'host_zt': '127.0.0.1', 'sync_port': 1}
        self.bridge.trusted_host_pub = 'fixture'
        started = []
        release = {gid: threading.Event() for gid in ('g1', 'g3', 'g5')}

        async def transfer(_host, _port, _pub, gid, dest, **_options):
            started.append(gid)
            while not release[gid].is_set():
                await asyncio.sleep(.01)
            (Path(dest) / 'game.exe').touch()
            return SimpleNamespace(ok=True, verified_files={gid: ['game.exe']})

        with patch.object(self.bridge, '_prepare_client_game', return_value=False), \
             patch.object(core, 'sync_game', transfer):
            self.bridge.installGame('g1')
            # Queue during the local-file check too, before transfer starts.
            self.bridge.installGame('g3')
            self.bridge.installGame('g3')
            self.bridge.installGame('g1')
            self.bridge.installGame('g5')
            self.assertEqual(self.bridge._download_queue, ['g3', 'g5'])
            try:
                pump_until(lambda: started == ['g1'])
                self.bridge._sync_transfer_state('paused')
                pump(.05)
                self.assertEqual(started, ['g1'])
                self.assertEqual([r['position'] for r in self.bridge.state['downloadQueue']], [1, 2])
                for gid, expected in [('g1', ['g1', 'g3']), ('g3', ['g1', 'g3', 'g5'])]:
                    release[gid].set()
                    pump_until(lambda: started == expected)
                    self.assertEqual(started, expected)
                release['g5'].set()
                pump_until(lambda: not self.bridge.syncing_game and not self.bridge.busy)
                self.assertEqual(self.bridge.state['downloadQueue'], [])
                self.assertEqual(self.bridge.state['page'], 'library')
            finally:
                for event in release.values():
                    event.set()
                pump_until(lambda: not self.bridge.syncing_game and not self.bridge.busy)

    def test_queued_download_can_be_removed_and_queue_advances_after_failure(self):
        self.library()
        self.bridge.room = SimpleNamespace(host_ip='127.0.0.1')
        self.bridge.syncing_game = True
        self.bridge._progress = {'active': True, 'game_id': 'g1'}
        self.bridge.installGame('g3')
        self.bridge.installGame('g5')
        self.bridge.removeQueuedDownload('g3')
        self.assertEqual(self.bridge.state['downloadQueue'], [{'id': 'g5', 'name': 'Game 05', 'position': 1}])
        with patch.object(self.bridge, '_game_action') as start:
            self.bridge._sync_finished(self.bridge.library['g1'], {}, None, RuntimeError('offline'), False)
        start.assert_called_once_with(True, game_id='g5', show_downloads=False)
        self.assertIn('offline', self.bridge.state['dialog']['message'])

    def test_reordering_preempts_active_download_and_keeps_it_queued(self):
        self.library()
        self.bridge.room = SimpleNamespace(host_ip='127.0.0.1')
        self.bridge.syncing_game = True
        self.bridge._progress = {'active': True, 'game_id': 'g1', 'game': 'Game 01', 'state': 'receiving'}
        self.bridge._download_queue = ['g3', 'g5']
        with patch.object(core.LauncherCore, '_cancel_sync') as cancel:
            self.bridge.prioritizeDownload('g5')
            self.assertEqual(self.bridge._download_queue, ['g5', 'g3', 'g1'])
            cancel.assert_called_once()
        self.bridge.syncing_game = False
        self.bridge._download_queue = ['g3', 'g5']
        self.bridge.moveQueuedDownload('g5', -1)
        self.assertEqual(self.bridge._download_queue, ['g5', 'g3'])
        self.assertIn('Game 05', self.bridge.state['queueMessage'])

    def test_queue_rows_pair_game_names_with_icon_actions(self):
        from PySide6.QtQml import QQmlExpression
        self.library()
        self.bridge._page = 'downloads'
        self.bridge.syncing_game = True
        self.bridge._progress = {'active': True, 'game_id': 'g1', 'game': 'Game 01',
                                 'state': 'receiving', 'done': 4, 'total': 12, 'index': {}}
        self.bridge._download_queue = ['g3', 'g5']
        self.bridge.publish()
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        pump(.05)
        self.assertEqual(len(self.bridge.state['downloadQueue']), 2)
        self.assertIsNotNone(window.findChild(QObject, 'activeQueueRow'))
        rep = window.findChild(QObject, 'downloadQueueRepeater')
        first, undefined = QQmlExpression(self.engine.rootContext(), rep, 'itemAt(0)').evaluate()
        self.assertFalse(undefined)
        self.assertEqual(first.objectName(), 'queuedGameRow-g3')
        for name, icon in [('queueTop-g3', 'queue-top'), ('queueUp-g3', 'queue-up'),
                           ('queueDown-g3', 'queue-down'), ('queueRemove-g3', 'cancel'),
                           ('activeQueueNextAction', 'queue-next')]:
            button = (window if name == 'activeQueueNextAction' else first).findChild(QObject, name)
            self.assertIsNotNone(button)
            self.assertEqual(button.property('iconName'), icon)
            self.assertTrue(button.property('iconOnly'))

    def test_cancel_download_removes_only_managed_partial_game(self):
        import concurrent.futures
        self.library()
        self.bridge.room = SimpleNamespace(host_ip='127.0.0.1')
        folder = Path(self.bridge.library['g3']['install_dir'])
        (folder / 'game.exe.lanpart').write_bytes(b'partial')
        # This fixture represents a folder created by this launcher operation.
        self.bridge._owned_download_folders.add(str(folder.resolve()))
        self.bridge.syncing_game = True
        self.bridge._progress = {'active': True, 'game_id': 'g3', 'game': 'Game 03', 'state': 'receiving'}
        self.bridge._queue_message = 'Starting another game next'
        self.bridge.received_activity.record('127.0.0.1:47803', 'g3', 1024)
        self.bridge._page = 'downloads'
        self.bridge.publish()
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        progress_bar = window.findChild(QObject, 'downloadProgressBar')
        self.assertTrue(progress_bar.property('visible'))
        with patch.object(core.LauncherCore, '_cancel_sync') as cancel:
            self.bridge.cancelDownload()
            cancel.assert_called_once()
        self.assertEqual(self.bridge.state['queueMessage'], '')
        self.bridge._sync_finished(self.bridge.library['g3'], {}, None,
                                   concurrent.futures.CancelledError(), False)
        pump_until(lambda: not folder.exists())
        self.assertFalse(folder.exists())
        self.assertTrue(Path(self.bridge.library['g5']['install_dir']).exists())
        self.assertFalse(self.bridge.state['progress']['active'])
        self.assertEqual(self.bridge.state['progress']['done'], 0)
        self.assertEqual(self.bridge.state['progress']['index'], {})
        self.assertFalse(progress_bar.property('visible'))
        self.assertFalse(any(row['id'] == 'g3' for row in self.bridge.state['transfers']))

    def test_cancel_preserves_preexisting_incomplete_folder(self):
        self.library()
        folder = Path(self.bridge.library['g3']['install_dir'])
        saved = folder / 'save.dat'
        saved.write_bytes(b'keep')
        self.bridge.syncing_game = True
        self.bridge._progress = {'active': True, 'game_id': 'g3'}
        with patch.object(core.LauncherCore, '_cancel_sync') as cancel, \
                patch.object(self.bridge, '_delete_cancelled_game') as delete:
            self.bridge.cancelDownload()
        cancel.assert_called_once()
        delete.assert_not_called()
        self.assertEqual(saved.read_bytes(), b'keep')

    def test_deletion_blocks_new_game_actions_and_queue_advancement(self):
        self.library()
        self.bridge.room = SimpleNamespace(host_ip='127.0.0.1')
        self.bridge._download_deleting = True
        self.bridge._download_queue = ['g3']
        with patch.object(self.bridge, '_prepare_client_game') as prepare:
            self.bridge._game_action(True, game_id='g3')
            self.bridge._start_next_download()
        prepare.assert_not_called()
        self.assertEqual(self.bridge._download_queue, ['g3'])

    def test_close_with_downloads_requires_explicit_choice(self):
        self.library()
        self.bridge.syncing_game = True
        self.bridge._download_queue = ['g3']
        self.bridge._progress = {'active': True, 'game_id': 'g1', 'game': 'Game 01',
                                 'state': 'receiving'}
        self.bridge.publish()
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        popup = window.findChild(QObject, 'closeDownloadsPopup')
        with patch.object(self.bridge, 'close') as close:
            self.bridge.requestClose()
            pump(.03)
            self.assertTrue(popup.property('visible'))
            close.assert_not_called()
            self.bridge.requestClose()  # Repeated window-close clicks do not bypass the choice.
            close.assert_not_called()
            self.bridge.confirmCloseDownloads(False)
            self.assertFalse(self.bridge.state['closeDownloadConfirm'])
            self.assertEqual(self.bridge._download_queue, ['g3'])
            self.bridge.requestClose()
            self.bridge.confirmCloseDownloads(True)
            close.assert_called_once()

    def test_confirmed_close_cancels_active_transfer_and_queue(self):
        self.library()
        self.bridge.syncing_game = True
        self.bridge._download_queue = ['g3']
        with patch.object(core.LauncherCore, '_cancel_sync') as cancel, \
             patch.object(core.LauncherCore, 'close') as finish:
            self.bridge.close()
        cancel.assert_called_once()
        finish.assert_called_once()
        self.assertEqual(self.bridge._download_queue, [])

    def test_room_loss_clears_queue_and_invalidates_inflight_preparation(self):
        self.library()
        self.bridge.room = SimpleNamespace(host_ip='127.0.0.1')
        self.bridge.busy = True
        self.bridge._download_preparing = 'g1'
        self.bridge.installGame('g3')
        epoch = self.bridge._download_epoch
        self.bridge._cancel_sync()
        with patch.object(self.bridge, '_sync_then_play') as sync:
            self.bridge._game_prepared(self.bridge.library['g1'], {}, True, False, None, False, epoch)
        sync.assert_not_called()
        self.assertFalse(self.bridge.busy)
        self.assertEqual(self.bridge.state['downloadQueue'], [])

    def test_portrait_controls_keep_spacing_icons_and_queue_action_independent(self):
        from PySide6.QtCore import QMetaObject, QPoint, QPointF
        from PySide6.QtTest import QTest
        from lantool.install_manifest import mark_pending
        self.library()
        mark_pending(self.bridge.library['g1']['install_dir'], 'g1')
        self.bridge.seeded_games.add('g2')
        self.bridge._download_queue = ['g5']
        self.bridge._disk_changed()
        self.bridge.publish()
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        def items(item):
            yield item
            for child in item.childItems():
                yield from items(child)
        def card(gid):
            return next(i for i in objects if i.objectName() == 'libraryPortrait-'+gid)
        for width in (1280, 1920):
            window.setWidth(width); pump(.12)
            objects = list(items(window.contentItem()))
            for gid in ('g0', 'g1', 'g2', 'g5'):
                row = card(gid).findChild(QObject, 'portraitControls')
                controls = [i for i in row.childItems() if i.objectName().startswith('portrait')]
                self.assertEqual(len(controls), 3)
                self.assertTrue(all(abs(i.width()-31*.85) < .001 for i in controls))
                self.assertAlmostEqual(controls[1].x()-controls[0].x()-controls[0].width(), 4)
                self.assertAlmostEqual(controls[2].x()-controls[1].x()-controls[1].width(), 4)
                status = card(gid).findChild(QObject, 'portraitInstallStatus')
                action = card(gid).findChild(QObject, 'portraitGameAction')
                self.assertNotEqual(status.property('portraitIcon'), action.property('portraitIcon'))
        self.assertEqual(card('g1').findChild(QObject, 'portraitInstallStatus').property('portraitIcon'), 'incomplete')
        self.assertEqual(card('g2').findChild(QObject, 'portraitInstallStatus').property('portraitIcon'), 'seeding')
        action = card('g5').findChild(QObject, 'portraitGameAction')
        QMetaObject.invokeMethod(action, 'clicked')
        self.assertEqual(self.bridge.state['downloadQueue'], [])
        # A real hover lifts and lightens the cached shadow.
        shadow = card('g1').findChild(QObject, 'portraitShadow')
        point = card('g1').mapToScene(QPointF(40, 60))
        QTest.mouseMove(window, QPoint(round(point.x()), round(point.y())))
        pump(.22)
        self.assertTrue(card('g1').property('hot'))
        self.assertLess(shadow.opacity(), .5)

    def test_navigation_and_visible_actions_have_distinct_icons(self):
        self.library()
        self.bridge._selected = 'g2'
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        def items(item):
            yield item
            for child in item.childItems():
                yield from items(child)
        for page, tab in [('library', None), ('room', None), ('details', None),
                          ('downloads', None), ('profile', None), ('gameSettings', None),
                          ('settings', 'Game Library'), ('settings', 'Network'),
                          ('settings', 'Appearance'), ('settings', 'Player'),
                          ('settings', 'Events'), ('settings', 'Diagnostics')]:
            if tab:
                self.bridge._setting_tab = tab
            self.bridge._page = page
            self.bridge.publish()
            pump(.1)
            actions = [item for item in items(window.contentItem())
                       if item.isVisible() and item.metaObject().indexOfSignal('clicked()') >= 0
                       and item.property('iconName')]
            pairs = [(str(item.property('text')), str(item.property('iconName'))) for item in actions]
            icons = [icon for label, icon in pairs]
            self.assertEqual(len(icons), len(set(icons)), (page, tab, pairs))
            for label, icon in pairs:
                for directory in ['controls', 'themes/dark/controls', 'themes/neon/controls']:
                    self.assertTrue((local_qt.parent.parent / 'lantool/qt/assets' / directory / (icon+'.svg')).is_file(),
                                    (label, icon, directory))
        nav = [item.objectName() for item in items(window.contentItem()) if item.objectName().startswith('nav-')]
        self.assertEqual(set(nav), {'nav-library', 'nav-room', 'nav-downloads', 'nav-settings'})
        self.assertEqual(len(nav), 4)

    def test_details_has_only_fitted_cover_and_no_banner(self):
        self.library()
        self.bridge._selected = 'g2'
        self.bridge._page = 'details'
        self.bridge.publish()
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        pump(.08)
        cover = window.findChild(QObject, 'selectedGameCover')
        self.assertIsNotNone(cover)
        # Details is a fixed 432x647 portrait panel by design; the cover fills it.
        self.assertLessEqual(cover.property('width'), 432)
        from PySide6.QtQml import QQmlExpression
        from PySide6.QtQml import QQmlEngine
        expression = QQmlExpression(QQmlEngine.contextForObject(cover), cover, 'fillMode === 1')
        fitted = expression.evaluate()
        self.assertTrue(fitted[0] if isinstance(fitted, tuple) else fitted)
        # The game title was removed from the Details page by design; the cover is the only identity.
        self.assertIsNone(window.findChild(QObject, 'selectedGameTitle'))
        install = window.findChild(QObject, 'gameActionButton')
        # g2 has its exe on disk, so the single action button reads Play (it reads Install only for missing games).
        self.assertEqual(install.property('text'), 'Play')
        self.bridge.syncing_game = True
        self.bridge._progress['active'] = True
        self.bridge.publish()
        pump(.03)
        self.assertEqual(install.property('text'), 'Play')
        self.assertFalse(install.property('enabled'))

    def test_client_room_key_field_submits_normalized_key(self):
        from unittest.mock import AsyncMock
        from PySide6.QtCore import QMetaObject
        self.library()
        self.bridge._page = 'room'
        self.bridge.publish()
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        pump(.05)
        field = window.findChild(QObject, 'roomKeyField')
        action = window.findChild(QObject, 'joinRoomKeyAction')
        self.assertIsNotNone(field)
        self.assertFalse(action.property('enabled'))
        with patch.object(self.bridge, '_join_room_key', new=AsyncMock()) as join:
            field.setProperty('text', '8056-C2E2-1C00-0001')
            pump(.03)
            self.assertTrue(action.property('enabled'))
            QMetaObject.invokeMethod(action, 'clicked')
            pump_until(lambda: not self.bridge.busy)
            join.assert_awaited_once_with('8056c2e21c000001')

    def test_mismatched_signed_beacon_is_rejected_before_network_setup(self):
        from lantool.netcore.errors import JoinError
        with patch.object(self.bridge, '_recover_network_session') as recover:
            future = self.bridge.runtime.submit(self.bridge._join_beacon_room(
                {'sig': 'fixture', 'version': '0.9.24', 'proto': ROOM_PROTOCOL}, report_error=False))
            with self.assertRaisesRegex(JoinError, 'version mismatch'):
                future.result(timeout=2)
        recover.assert_not_called()
        self.assertIsNone(self.bridge.room)

    def test_launcher_offer_respects_pinned_host_and_does_not_interrupt_key_entry(self):
        self.bridge.trusted_host_pub = 'saved-host'
        beacon = dict(net_id='fixture-room', host='192.168.1.5', host_pub='different-host', version='0.9.27',
                      launcher_share=dict(protocol=1,port=47808,fingerprint='0'*64))
        self.bridge._offer_host_version(beacon, 'Mismatch')
        self.assertFalse(self.bridge.state['launcherUpgrade']['supported'])
        self.bridge._offer_host_version(beacon, 'Mismatch', True)
        self.assertTrue(self.bridge.state['launcherUpgrade']['supported'])
        self.bridge._upgrade['status'] = 'pin'
        self.bridge._offer_host_version(beacon, 'Repeated discovery')
        self.assertEqual(self.bridge._upgrade['status'], 'pin')

    def test_host_version_request_approval_pin_destination_and_direct_download(self):
        from lantool.netcore.launcher_share import LauncherShare
        from lantool._version import __version__
        self.library()
        host = LauncherBridge(start_services=False)
        host.role = 'host'
        host.publish()
        host_engine = create_engine(host)
        host_window = host_engine.rootObjects()[0]
        package = self.root / 'fixture-host.zip'
        package.write_bytes(b'fixture launcher package' * 20000)
        server = LauncherShare(lambda: package, host='127.0.0.1', port=0, on_change=host._publish_launcher_share)
        host.runtime.submit(server.start()).result(timeout=5)
        host.launcher_share = server
        saved_folder = tempfile.TemporaryDirectory(dir=self.root.parent)
        self.addCleanup(saved_folder.cleanup)
        destination = Path(saved_folder.name) / 'downloaded-host.zip'
        self.engine = create_engine(self.bridge)
        try:
            beacon = dict(host='127.0.0.1', net_id='fixture-room', version=__version__, launcher_share=server.metadata)
            self.bridge._offer_host_version(beacon, 'Launcher version mismatch fixture')
            self.bridge.requestHostVersion()
            pump_until(lambda: bool(host.state['launcherShareRequests']))
            request = host.state['launcherShareRequests'][0]
            self.assertEqual(request['status'], 'pending')
            self.assertFalse(destination.exists())
            host.decideHostVersionRequest(request['id'], True)
            pump_until(lambda: self.bridge.state['launcherUpgrade']['status'] == 'pin')
            self.assertEqual(self.bridge.state['launcherUpgrade']['status'], 'pin')
            key = host.state['launcherShareRequests'][0]['pin']
            self.assertEqual(len(key), 3)
            key_item = host_window.findChild(QObject, 'hostLauncherShareKey')
            self.assertEqual(key_item.property('text'), key)
            self.assertFalse(destination.exists())
            pump_until(lambda: self.bridge._upgrade_future.done())
            with patch('lantool.qt.upgrade_ui.QFileDialog.getSaveFileName', return_value=(str(destination), 'ZIP')) as choose:
                self.bridge.submitHostVersionKey(key)
                pump_until(lambda: self.bridge.state['launcherUpgrade']['status'] in ('complete', 'error'), timeout=5)
            choose.assert_called_once()
            self.assertEqual(self.bridge.state['launcherUpgrade']['status'], 'complete', self.bridge.state['launcherUpgrade'])
            self.assertEqual(destination.read_bytes(), package.read_bytes())
            self.assertIn('Repair Network/Wipe VLA', self.bridge.state['launcherUpgrade']['message'])
            self.assertIn('Close this Client', self.bridge.state['launcherUpgrade']['message'])
            self.assertEqual(self.bridge._launcher_upgrade_download, str(destination))
            self.assertIsNone(self.bridge.room)
        finally:
            self.bridge.cancelHostVersionTransfer()
            host.runtime.submit(server.stop()).result(timeout=5)
            host._destroyed = True
            for window in host_engine.rootObjects():
                window.setVisible(False)
            host_engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            host.runtime.stop()

    def test_invalid_room_key_does_not_start_network_join(self):
        from unittest.mock import AsyncMock
        self.library()
        with patch.object(self.bridge, '_join_room_key', new=AsyncMock()) as join:
            self.bridge.joinRoomKey('not-a-room-key')
        join.assert_not_called()
        self.assertEqual(self.bridge.state['dialog']['title'], 'Invalid room key')
        self.assertFalse(self.bridge.busy)

    def test_room_key_uses_verified_host_metadata_and_full_join_flow(self):
        from unittest.mock import AsyncMock
        key = '8056c2e21c000001'
        self.tunnel.begin_join = Mock(return_value=key)
        self.tunnel.wait_connected = Mock(return_value=SimpleNamespace(connected=True, host_ip='10.147.20.1'))
        self.tunnel._leave_quiet = Mock()
        async def connected(beacon):
            self.bridge.room = SimpleNamespace(network_id=key)
        with patch('lantool.netcore.discovery.fetch_room', new=AsyncMock(return_value={
                'net_id': key, 'host_pub': 'verified-key', 'host': '192.168.1.10', 'proto': ROOM_PROTOCOL, 'version': core.__version__})) as fetch, \
             patch.object(self.bridge, '_join_beacon_room', new=AsyncMock(side_effect=connected)) as join:
            self.bridge.runtime.submit(self.bridge._join_room_key(key)).result(timeout=2)
        fetch.assert_awaited_once()
        self.assertEqual(fetch.await_args.args, ('10.147.20.1',))
        self.assertEqual(join.await_args.args[0]['host'], '10.147.20.1')
        self.assertEqual(join.await_args.args[0]['host_pub'], 'verified-key')
        self.tunnel._leave_quiet.assert_not_called()

    def test_room_key_rejects_other_room_and_cleans_up_attempt(self):
        from unittest.mock import AsyncMock
        key = '8056c2e21c000001'
        self.tunnel.begin_join = Mock(return_value=key)
        self.tunnel.wait_connected = Mock(return_value=SimpleNamespace(connected=True, host_ip='10.147.20.1'))
        self.tunnel._leave_quiet = Mock()
        with patch('lantool.netcore.discovery.fetch_room', new=AsyncMock(return_value={'net_id': '0000000000000001'})), \
             patch.object(core, '_other_launcher_running', return_value=False), \
             patch.object(self.bridge, '_join_beacon_room', new=AsyncMock()) as join:
            with self.assertRaisesRegex(RuntimeError, 'different room'):
                self.bridge.runtime.submit(self.bridge._join_room_key(key)).result(timeout=2)
        join.assert_not_called()
        self.tunnel._leave_quiet.assert_called_once_with(key)

    def test_room_key_retries_metadata_without_leaving_or_rejoining_vla(self):
        from unittest.mock import AsyncMock
        key = '8056c2e21c000001'
        self.tunnel.begin_join = Mock(return_value=key)
        self.tunnel.wait_connected = Mock(return_value=SimpleNamespace(connected=True, host_ip='10.147.20.1'))
        self.tunnel._leave_quiet = Mock()
        async def connected(beacon):
            self.bridge.room = SimpleNamespace(network_id=key)
        async def retry_now(_delay):
            self.tunnel._leave_quiet.assert_not_called()
        with patch('lantool.netcore.discovery.fetch_room', new=AsyncMock(side_effect=[
                TimeoutError(), ConnectionRefusedError(), {'net_id': key, 'host_pub': 'verified-key', 'proto': ROOM_PROTOCOL, 'version': core.__version__}])) as fetch, \
             patch('lantool.netcore.discovery.asyncio.sleep', new=AsyncMock(side_effect=retry_now)), \
             patch.object(self.bridge, '_join_beacon_room', new=AsyncMock(side_effect=connected)):
            self.bridge.runtime.submit(self.bridge._join_room_key(key)).result(timeout=2)
        self.assertEqual(fetch.await_count, 3)
        self.tunnel.begin_join.assert_called_once_with(key)
        self.tunnel.wait_connected.assert_called_once_with(key, 60)
        self.tunnel._leave_quiet.assert_not_called()

    def test_room_key_timeout_popup_contains_useful_detail(self):
        from concurrent.futures import Future
        future = Future()
        future.set_exception(TimeoutError())
        with patch.object(core.LauncherCore, '_log_room_error') as log:
            self.bridge._room_key_finished(future)
        self.assertIn('timed out', self.bridge.state['dialog']['message'])
        log.assert_called_once()
        self.assertFalse(self.bridge.busy)

    def test_host_checkbox_registers_shared_folder_without_executable(self):
        from lantool.game_directory import load_catalog
        self.bridge.role = 'host'
        folder = self.bridge.game_root / 'Map files'
        folder.mkdir(parents=True)
        (folder / 'map.txt').write_text('Map data')
        self.bridge.setHostExeRequired(str(folder), False)
        manifest = self.bridge.game_for_folder(folder)
        self.assertFalse(manifest['exe_required'])
        self.assertEqual(manifest['exe'], '')
        self.bridge.setHostGameEnabled(str(folder), True)
        self.assertIn(manifest['id'], self.bridge.library)
        self.assertFalse(self.bridge.state['catalog'][0]['exeRequired'])
        self.engine = create_engine(self.bridge)
        pump(.05)
        window = self.engine.rootObjects()[0]
        def find_visual(item, name):
            if item.objectName() == name:
                return item
            for child in item.childItems():
                found = find_visual(child, name)
                if found is not None:
                    return found
        checkbox = find_visual(window.contentItem(), 'hostExeRequiredCheck')
        self.assertIsNotNone(checkbox)
        self.assertFalse(checkbox.property('checked'))

    def test_shared_folder_install_marks_installed_without_launching(self):
        self.library()
        folder = self.root / 'shared-files'
        folder.mkdir()
        manifest = {'id': 'files', 'name': 'Map files', 'exe': '', 'exe_required': False,
                    'install_dir': str(folder)}
        self.bridge.library = {'files': manifest}
        self.bridge._selected = 'files'
        self.bridge.syncing_game = True
        result = SimpleNamespace(ok=True, verified_files={'files': ['map.txt']})
        with patch('lantool.manifests.loader.launch') as launch:
            self.bridge._sync_finished(manifest, {}, result, None, launch_after=False)
        launch.assert_not_called()
        self.assertTrue(self.bridge._game(manifest)['installed'])
        self.bridge._page = 'details'
        self.bridge.publish()
        self.engine = create_engine(self.bridge)
        pump(.05)
        window = self.engine.rootObjects()[0]
        play = window.findChild(QObject, 'gameActionButton')
        self.assertEqual(play.property('text'), 'Play')
        self.assertFalse(play.property('enabled'))

    def test_install_does_not_launch_and_play_remains_separate(self):
        self.library()
        self.bridge._selected = 'g0'
        self.bridge.room = SimpleNamespace(host_ip='127.0.0.1')
        with patch.object(self.bridge, '_sync_then_play') as install, \
             patch.object(self.bridge, '_play_game') as play:
            self.bridge.install()
            pump_until(lambda: install.called)
            install.assert_called_once()
            self.assertFalse(install.call_args.kwargs['launch_after'])
            play.assert_not_called()

    def test_install_completion_never_launches(self):
        self.library()
        self.bridge.syncing_game = True
        result = SimpleNamespace(ok=True, verified_files={'g0': ['game.exe']})
        with patch('lantool.manifests.loader.launch') as launch:
            self.bridge._sync_finished(self.bridge.library['g0'], {}, result, None, launch_after=False)
            pump(.05)
        launch.assert_not_called()
        self.assertFalse(self.bridge.syncing_game)

    def test_game_checks_do_not_block_navigation(self):
        self.library()
        self.bridge._selected = 'g0'
        entered, release = threading.Event(), threading.Event()
        def slow_check(manifest, *, cancelled=None):
            entered.set()
            release.wait(3)
            return True
        with patch.object(self.bridge, '_prepare_client_game', side_effect=slow_check), \
             patch.object(self.bridge, '_play_game') as play:
            try:
                self.bridge.play()
                wait_for_worker(entered)
                self.assertTrue(self.bridge.busy)
                self.bridge.navigate('activity')
                self.assertEqual(self.bridge.state['page'], 'settings')
                self.assertEqual(self.bridge.state['settingsTab'], 'Events')
                release.set()
                pump_until(lambda: play.called)
                play.assert_called_once()
            finally:
                release.set()

    def test_close_during_local_game_check_cancels_disk_worker(self):
        self.library()
        self.bridge._selected='g0'
        entered,exited=threading.Event(),threading.Event()
        def check(manifest, *, cancelled=None):
            entered.set()
            while not cancelled():time.sleep(.005)
            exited.set()
            return False
        def closing():
            self.assertFalse(self.bridge.busy)
            self.bridge._closing=True
        with patch.object(self.bridge,'_prepare_client_game',side_effect=check), \
             patch.object(self.bridge,'close',side_effect=closing) as close:
            self.bridge.play()
            wait_for_worker(entered)
            self.assertTrue(self.bridge.busy)
            self.bridge.requestClose()
            close.assert_not_called()
            self.assertTrue(self.bridge.state['closeDownloadConfirm'])
            self.bridge.confirmCloseDownloads(True)
            close.assert_called_once()
            wait_for_worker(exited)
            self.assertTrue(exited.is_set())
            self.assertIsNone(self.bridge._game_prepare_future)

    def test_closing_local_client_preserves_running_hosts_membership(self):
        self.bridge.role = 'client'
        controller = SimpleNamespace(leave=Mock(side_effect=AssertionError('Host network was disconnected')))
        self.bridge.room_controller = controller
        with patch.object(core, '_other_launcher_running', return_value=True):
            self.bridge.requestClose()
            pump_until(lambda: self.bridge._destroyed)
        controller.leave.assert_not_called()
        self.tunnel.cleanup.assert_not_called()
        self.assertTrue(self.bridge._destroyed)

    def test_closing_older_duplicate_host_preserves_active_hosts_membership(self):
        self.bridge.role='host'
        controller=SimpleNamespace(leave=Mock(side_effect=AssertionError('Active Host network was disconnected')))
        self.bridge.room_controller=controller
        with patch.object(core,'_same_role_launcher_running',return_value=True), \
             patch.object(core,'_other_launcher_running',return_value=True):
            self.bridge.requestClose()
            pump_until(lambda:self.bridge._destroyed)
        controller.leave.assert_not_called()
        self.tunnel.cleanup.assert_not_called()
        self.assertTrue(self.bridge._destroyed)

    def test_client_recovery_does_not_touch_running_hosts_adapter(self):
        self.bridge.role = 'client'
        self.tunnel.recover = Mock()
        with patch.object(core, '_other_launcher_running', return_value=True), \
             patch.object(core, 'AdapterSwitcher') as adapter, \
             patch.object(self.bridge, '_start_discovery'):
            core.LauncherCore._recover(self.bridge)
            pump_until(lambda: not self.bridge.busy)
        self.tunnel.recover.assert_not_called()
        adapter.assert_not_called()

    def test_message_popup_can_be_hidden_without_blocking_window(self):
        from PySide6.QtCore import QMetaObject
        self.library()
        self.engine = create_engine(self.bridge)
        self.bridge.ui_message('showinfo', 'Download information', 'Transfer continues in the background.')
        pump(.05)
        window = self.engine.rootObjects()[0]
        popup = window.findChild(QObject, 'applicationMessagePopup')
        self.assertFalse(popup.property('modal'))
        self.bridge.dismissDialog()
        pump(.05)
        self.assertFalse(popup.property('visible'))
        self.assertEqual(self.bridge.state['events'][0]['title'], 'Download information')

    def test_close_finishes_cleanup_before_quit(self):
        self.bridge._network_session_recovered = True
        closed=[]
        self.bridge.quitReady.connect(lambda:closed.append(True))
        with patch.object(core,"_other_launcher_running",return_value=False):
            self.bridge.requestClose()
            pump(.4)
        self.assertTrue(self.tunnel.cleanup.called)
        self.assertTrue(closed)
        self.assertTrue(self.bridge._destroyed)

    def test_closing_unused_launcher_does_not_change_existing_networking(self):
        with patch.object(core, '_other_launcher_running', return_value=False), \
             patch.object(core, '_same_role_launcher_running', return_value=False):
            self.bridge.requestClose()
            pump_until(lambda: self.bridge._destroyed)
        self.tunnel.cleanup.assert_not_called()
        self.assertTrue(self.bridge._destroyed)

    def test_vla_wipe_actions_are_named_and_cancel_safely_in_both_views(self):
        from PySide6.QtCore import QMetaObject
        from PySide6.QtWidgets import QMessageBox
        self.library()
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        with patch.object(core, '_other_launcher_running', return_value=False), \
                patch('lantool.qt.bridge.QMessageBox.warning', return_value=QMessageBox.StandardButton.Cancel) as confirm, \
                patch('silent_tunnel.admin_actions.run_elevated') as elevated:
            for role in ('client', 'host'):
                self.bridge.role = role
                self.bridge._page = 'settings'
                self.bridge._setting_tab = 'Network'
                self.bridge.publish()
                pump(.06)
                if role == 'host':
                    QMetaObject.invokeMethod(window.findChild(QObject, 'hostAppearancePopup'), 'open')
                    pump(.06)
                actions = window.findChildren(QObject, 'wipeVLAButton')
                visible = [button for button in actions if button.property('visible')]
                self.assertEqual(len(visible), 1, role)
                self.assertEqual(visible[0].property('text'), 'Repair Network/Wipe VLA')
                QMetaObject.invokeMethod(visible[0], 'clicked')
                pump(.03)
            self.assertEqual(confirm.call_count, 2)
        elevated.assert_not_called()
        self.assertTrue(self.bridge.runtime.thread.is_alive())

    def test_host_diagnostic_popup_publishes_progress_results_and_fix_links(self):
        from PySide6.QtCore import QMetaObject
        self.bridge.role = 'host'
        self.bridge.publish()
        self.engine = create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        with patch.object(self.bridge, '_start_diag') as start:
            QMetaObject.invokeMethod(window.findChild(QObject, 'hostAppearancePopup'), 'open')
            QMetaObject.invokeMethod(window.findChild(QObject, 'hostNetworkDiagnosticAction'), 'clicked')
        start.assert_called_once_with(None)
        popup = window.findChild(QObject, 'hostNetworkDiagnosticPopup')
        self.assertTrue(popup.property('visible'))
        self.bridge._diag = {'running': True, 'rows': []}
        self.bridge._diag_progress('Checking firewall', 1, 2)
        self.assertEqual(self.bridge.state['diag']['step'], 'Checking firewall')
        self.bridge._diag_done({'lines': ['Firewall blocked'], 'path': '', 'worst': 'warn',
            'rows': [{'title': 'Firewall', 'detail': 'Rules need updating', 'status': 'warn',
                      'fix': 'repairLan', 'fixLabel': 'Repair rules'}]}, '')
        pump(.05)
        self.assertFalse(self.bridge.state['diag']['running'])
        def items(item):
            yield item
            for child in item.childItems():
                yield from items(child)
        objects = list(items(window.contentItem()))
        link = next((i for i in objects if i.objectName() == 'hostDiagFix_repairLan'), None)
        self.assertIsNotNone(link)
        self.assertTrue(link.property('visible'))
        self.assertEqual(link.property('text'), 'Repair rules')
        self.bridge._diag_done(None, 'Fixture failure')
        self.assertEqual(self.bridge.state['diag']['error'], 'Fixture failure')
        self.assertAlmostEqual(window.findChild(QObject, 'hoverDescriptionPanel').scale(), .7)
        self.bridge.ui_message('showerror', 'Room failed', 'Fixture error', stage='bootstrap')
        pump(.03)
        repair = window.findChild(QObject, 'dialogDiagnoseButton')
        self.assertEqual(repair.property('text'), 'Repair Network/Wipe VLA')
        with patch.object(self.bridge, 'wipeVLA') as wipe:
            QMetaObject.invokeMethod(repair, 'clicked')
        wipe.assert_called_once_with()

    def test_legacy_wipe_slot_delegates_to_vla(self):
        with patch.object(self.bridge, 'wipeVLA') as wipe:
            self.bridge.wipeZeroTier()
        wipe.assert_called_once_with()

    def test_wipe_cancel_does_not_stop_runtime_or_remove_anything(self):
        from PySide6.QtWidgets import QMessageBox
        with patch.object(core, '_other_launcher_running', return_value=False), \
                patch('lantool.qt.bridge.QMessageBox.warning', return_value=QMessageBox.StandardButton.Cancel), \
                patch('silent_tunnel.admin_actions.run_elevated') as elevated:
            self.bridge.wipeVLA()
        elevated.assert_not_called()
        self.assertFalse(self.bridge._wiping)
        self.assertTrue(self.bridge.runtime.thread.is_alive())

    def test_wipe_blocks_while_other_launcher_is_running(self):
        with patch.object(core, '_other_launcher_running', return_value=True), \
                patch('lantool.qt.bridge.QMessageBox.warning') as confirm:
            self.bridge.wipeVLA()
        confirm.assert_not_called()
        self.assertIn('close the other launcher', self.bridge.state['dialog']['message'])

    def test_confirmed_wipe_stops_runtime_reports_result_and_closes(self):
        from PySide6.QtWidgets import QMessageBox
        profile = self.root / 'launcher.json'
        profile.write_text('{"player_name":"Reset me"}')
        games = self.root / 'games'
        games.mkdir()
        (games / 'keep.exe').write_bytes(b'game')
        # A broken/stale room must not prevent the forced-removal escape hatch.
        self.bridge.room_controller = Mock()
        with patch.object(core, '_other_launcher_running', return_value=False), \
                patch.object(core, 'AdapterSwitcher') as switcher, \
                patch('lantool.qt.bridge.QMessageBox.warning', return_value=QMessageBox.StandardButton.Yes) as confirm, \
                patch('lantool.qt.bridge.QMessageBox.information') as information, \
                patch('lantool.reset_data.reset_preferences'), \
                patch('silent_tunnel.admin_actions.run_elevated', return_value={
                    'report': {'issues': [], 'reboot': True}}) as elevated:
            self.bridge.wipeVLA()
            pump(.5)
        confirmation = confirm.call_args.args[2]
        self.assertIn('launcher-owned', confirmation)
        for scope in ('launcher data', 'theme', 'resolution', 'game directories'):
            self.assertIn(scope, confirmation)
        self.assertIn('Other applications', confirmation)
        self.assertIn('launcher closes', confirmation)
        elevated.assert_called_once_with('wipe_vla')
        switcher.assert_called_once_with(core.APP_DIR / "vla-adapter-state.json")
        switcher.return_value.restore.assert_called_once()
        self.assertFalse(self.bridge.runtime.thread.is_alive())
        self.assertTrue(self.bridge._destroyed)
        self.assertFalse(profile.exists())
        self.assertEqual((games / 'keep.exe').read_bytes(), b'game')
        self.assertIn('Restart Windows', information.call_args.args[-1])

    def test_incomplete_vla_removal_keeps_launcher_state_for_retry(self):
        from PySide6.QtWidgets import QMessageBox
        profile = self.root / 'launcher.json'
        profile.write_text('keep until VLA cleanup succeeds')
        with patch.object(core, '_other_launcher_running', return_value=False), \
             patch.object(core, 'AdapterSwitcher'), \
             patch('lantool.qt.bridge.QMessageBox.warning', return_value=QMessageBox.StandardButton.Yes), \
             patch('silent_tunnel.admin_actions.run_elevated', return_value={'report': {'issues': ['Adapter locked'], 'reboot': True}}), \
             patch('lantool.reset_data.reset_data') as reset, \
             patch('lantool.reset_data.reset_preferences') as preferences:
            self.bridge.wipeVLA()
            pump_until(lambda: self.bridge._destroyed)
        reset.assert_not_called()
        preferences.assert_not_called()
        self.assertTrue(profile.exists())

    def test_reset_drains_diagnostic_writer_before_deleting_state(self):
        from PySide6.QtWidgets import QMessageBox
        release = threading.Event()
        report = self.root / 'diagnostics' / 'late.json'
        def write_report():
            release.wait()
            report.parent.mkdir(exist_ok=True)
            report.write_text('late diagnostic result')
        worker = threading.Thread(target=write_report)
        self.bridge._diag_thread = worker
        worker.start()
        try:
            with patch.object(core, '_other_launcher_running', return_value=False), \
                 patch.object(core, 'AdapterSwitcher'), \
                 patch('lantool.qt.bridge.QMessageBox.warning', return_value=QMessageBox.StandardButton.Yes), \
                 patch('lantool.qt.bridge.QMessageBox.information'), \
                 patch('silent_tunnel.admin_actions.run_elevated', return_value={'report': {'issues': [], 'reboot': False}}) as elevated, \
                 patch('lantool.reset_data.reset_preferences'):
                self.bridge.wipeVLA()
                pump(.05)
                elevated.assert_not_called()
                release.set()
                pump_until(lambda: self.bridge._destroyed)
                self.assertTrue(self.bridge._destroyed)
            self.assertFalse(report.exists())
            self.assertFalse(worker.is_alive())
        finally:
            release.set()
            worker.join(timeout=2)


async def async_nothing():
    return None


if __name__=="__main__":
    unittest.main()

