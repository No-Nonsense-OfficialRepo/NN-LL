import json, time, pytest
from lantool.trust import signing as s
from lantool.netcore.beacon import make_beacon, parse_beacon
from lantool.manifests import loader as L


def test_sign_verify_and_tamper():
    priv, pub = s.generate_keypair()
    planet = b"planet-bytes"
    pkg = s.sign_planet(priv, planet)
    assert s.verify_planet(pub, planet, pkg)
    assert not s.verify_planet(pub, planet + b"x", pkg)           # tampered file rejected
    _, other_pub = s.generate_keypair()
    assert not s.verify_planet(other_pub, planet, pkg)            # wrong key rejected


def test_beacon_valid_forged_stale():
    priv, pub = s.generate_keypair()
    b = make_beacon(priv, "net1", "192.168.1.5", 47800, "abc", "1.0")
    assert parse_beacon(b, pub)["net_id"] == "net1"
    forged = json.loads(b); forged["host"] = "6.6.6.6"
    assert parse_beacon(json.dumps(forged).encode(), pub) is None
    old = make_beacon(priv, "net1", "h", 1, "a", "1", now=time.time() - 120)
    assert parse_beacon(old, pub) is None
    _, other = s.generate_keypair()
    assert parse_beacon(b, other) is None


def test_manifest_load_and_launch_command(tmp_path):
    lib = L.load_library("games")
    m = lib["bfbc2"]
    assert L.patch_config(m, {"name": "Test Player", "host_ip": "10.0.0.1"}) == \
        {"player_name": "Test Player", "server_ip": "10.0.0.1"}
    bad = dict(m, exe="../../evil.exe")
    with pytest.raises(L.ManifestError):
        L.resolve_exe(bad)
    with pytest.raises(L.ManifestError):
        L.validate({"id": "Bad ID", "name": "x", "exe": "a"})
