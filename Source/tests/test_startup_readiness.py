from unittest.mock import Mock, patch
from silent_tunnel.tunnel import Tunnel
from silent_tunnel.errors import ServiceError
from silent_tunnel.store import Settings


def test_service_started_and_transient_api_failure_retried(tmp_path):
    local = Mock()
    local.status.side_effect = [ServiceError('starting'), {'address': 'abc'}, {'address': 'abc'}]
    installer = Mock()
    installer.is_installed.return_value = True
    progress = Mock()
    tunnel = Tunnel(home=tmp_path, local=local, installer=installer, progress=progress)
    with patch('silent_tunnel.tunnel.time.sleep'):
        tunnel.ensure_ready()
    installer.start_service.assert_called_once()
    installer.install.assert_not_called()
    assert local.status.call_count == 3
    assert 'ready' in progress.call_args.args[0]


def test_install_finishes_before_service_start(tmp_path):
    order = []
    installer = Mock()
    installer.is_installed.return_value = False
    installer.install.side_effect = lambda *args: order.append('install')
    installer.start_service.side_effect = lambda: order.append('start')
    local = Mock()
    local.status.side_effect = lambda: order.append('probe') or {'address': 'abc'}
    tunnel = Tunnel(home=tmp_path, local=local, installer=installer)
    with patch('silent_tunnel.tunnel.time.sleep'):
        tunnel.ensure_ready()
    assert order == ['install', 'start', 'probe', 'probe']
    assert tunnel.state.installed_by_us
    assert Settings().uninstall_on_exit is False


def test_unresponsive_service_gets_one_automatic_restart(tmp_path):
    clock = [0]
    local = Mock()
    installer = Mock()
    installer.is_installed.return_value = True
    local.status.side_effect = lambda: ({'address': 'abc'} if installer.restart_service.called
                                       else {})
    tunnel = Tunnel(home=tmp_path, local=local, installer=installer)
    with patch('silent_tunnel.tunnel.time.monotonic', side_effect=lambda: clock[0]), \
         patch('silent_tunnel.tunnel.time.sleep', side_effect=lambda n: clock.__setitem__(0, clock[0]+n)):
        tunnel.ensure_ready(timeout=30)
    installer.restart_service.assert_called_once()
