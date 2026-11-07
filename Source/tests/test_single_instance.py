import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
import uuid

from lantool.single_instance import RoleInstance


@unittest.skipUnless(os.name == 'nt', 'Windows computer-wide instance ownership')
class NativeInstanceTests(unittest.TestCase):
    def setUp(self):
        self.namespace='Global\\LANLauncher.Test.'+uuid.uuid4().hex

    def test_one_of_each_role_and_release_on_close(self):
        with RoleInstance('host',namespace=self.namespace) as host, \
             RoleInstance('client',namespace=self.namespace) as client, \
             RoleInstance('host',namespace=self.namespace) as duplicate:
            self.assertTrue(host.acquire())
            self.assertTrue(client.acquire())
            self.assertFalse(duplicate.acquire())
            host.close()
            self.assertTrue(duplicate.acquire())

    def test_other_process_rejected_and_crash_releases_role(self):
        script='''import sys
from lantool.single_instance import RoleInstance
guard=RoleInstance('host',namespace=sys.argv[1])
print(int(guard.acquire()),flush=True)
sys.stdin.readline()
'''
        source=str(Path(__file__).resolve().parents[1])
        env={**os.environ,'PYTHONPATH':source}
        process=subprocess.Popen([sys.executable,'-u','-c',script,self.namespace],
                                 stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,env=env)
        try:
            self.assertEqual(process.stdout.readline().strip(),'1')
            with RoleInstance('host',namespace=self.namespace) as second:
                self.assertFalse(second.acquire())
                process.terminate();process.wait(timeout=5)
                self.assertTrue(second.acquire())
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=5)
            process.stdin.close();process.stdout.close()


class InstanceStartupTests(unittest.TestCase):
    def test_duplicate_qt_start_does_not_construct_backend_or_run_cleanup(self):
        from lantool.qt import main as startup
        guard=Mock();guard.acquire.return_value=False
        guard.__enter__=Mock(return_value=guard);guard.__exit__=Mock(return_value=False)
        with patch('lantool.single_instance.is_preview',return_value=False), \
             patch('lantool.single_instance.launcher_role',return_value='host'), \
             patch('lantool.single_instance.RoleInstance',return_value=guard), \
             patch('lantool.single_instance.show_existing') as show, \
             patch.object(startup,'_run') as run:
            self.assertEqual(startup.main(),0)
        run.assert_not_called()
        show.assert_called_once_with('host')

    def test_process_check_excludes_self_and_detects_other_host_copies(self):
        from lantool import launcher as core
        pid=os.getpid()
        own=f'"LAN Host V1.1.exe","{pid}","Console","1","5,000 K"\n'
        other='"LAN Host V1.0.exe","900001","Console","1","5,000 K"\n'
        with patch.object(core.subprocess,'run',return_value=Mock(returncode=0,stdout=own)):
            self.assertFalse(core._same_role_launcher_running('host'))
        with patch.object(core.subprocess,'run',return_value=Mock(returncode=0,stdout=own+other)):
            self.assertTrue(core._same_role_launcher_running('host'))
