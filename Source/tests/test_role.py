"""Host/Client role detection: flag beats exe name beats default."""
from lantool.role import detect_role


def test_default_is_client():
    assert detect_role([], "python", False) == "client"


def test_host_flag():
    assert detect_role(["--host"], "python", False) == "host"


def test_client_flag_beats_host_exe_name():
    assert detect_role(["--client"], "LAN Launcher Host", True) == "client"


def test_host_flag_beats_client_exe_name():
    assert detect_role(["--host"], "LAN Launcher Client", True) == "host"


def test_frozen_host_exe_name():
    assert detect_role([], "LAN Launcher Host", True) == "host"


def test_unfrozen_ignores_exe_name():
    assert detect_role([], "host-tool", False) == "client"


def test_both_flags_prefer_client():
    assert detect_role(["--host", "--client"], "x", False) == "client"
