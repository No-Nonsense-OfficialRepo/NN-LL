"""Version/protocol compatibility (WP-D): compat.check, beacon 'proto' field, old-beacon parsing."""
import json
import time

import pytest

from lantool._version import __proto__ as PROTO
from lantool.netcore import compat
from lantool.netcore.beacon import make_beacon, parse_beacon
from lantool.trust.signing import generate_keypair, sign_obj


def _signed_without_proto(priv, now=None):
    """A beacon as an older build (before the 'proto' field) would have sent it."""
    body = {"v": 1, "net_id": "abcdef0123456789", "host": "192.168.1.5", "presence_port": 47800,
            "planet_hash": "hash", "version": "1.5.0", "ts": int(now or time.time()),
            "host_pub": None}
    body.pop("host_pub")
    return json.dumps(sign_obj(priv, body)).encode()


# --- compat.check -----------------------------------------------------------

def test_same_version_and_proto_is_ok():
    ok, level, message, hint = compat.check("1.6.0", 1, "1.6.0", 1)
    assert (ok, level) == (True, "ok")
    assert "same version" in message.lower()


@pytest.mark.parametrize('other', ['0.9.24', '0.9.26', None, '', '0.9', '0.9.25-beta'])
def test_every_different_or_missing_release_is_blocked(other):
    assert compat.check(other, PROTO, '0.9.25', PROTO)[:2] == (False, 'block')


def test_patch_difference_is_blocked():
    ok, level, _, _ = compat.check("1.6.3", 1, "1.6.0", 1)
    assert (ok, level) == (False, "block")


def test_minor_difference_blocks_join():
    ok, level, message, hint = compat.check("1.5.0", 1, "1.6.0", 1)
    assert (ok, level) == (False, "block")
    assert "1.5.0" in message and "1.6.0" in message
    assert hint


def test_major_difference_blocks():
    ok, level, _, _ = compat.check("2.0.0", 1, "1.6.0", 1)
    assert (ok, level) == (False, "block")


def test_newer_host_protocol_blocks_and_says_this_pc_is_older():
    ok, level, message, hint = compat.check("2.0.0", 2, "1.6.0", 1)
    assert (ok, level) == (False, "block")
    assert "older LAN Launcher" in message
    assert "This PC is running an older" in message
    assert hint


def test_older_host_protocol_blocks_and_says_host_is_older():
    ok, level, message, hint = compat.check("1.0.0", 1, "1.6.0", 2)
    assert (ok, level) == (False, "block")
    assert "The Host is running an older" in message


@pytest.mark.parametrize("bad", ["", "abc", "1", "v", "x.y.z", None, 1.6])
def test_malformed_host_version_blocks_instead_of_crashing(bad):
    ok, level, message, hint = compat.check(bad, 1, "1.6.0", 1)
    assert (ok, level) == (False, "block")
    assert message and hint


def test_malformed_local_version_blocks():
    ok, level, _, _ = compat.check("1.6.0", 1, "not-a-version", 1)
    assert (ok, level) == (False, "block")


def test_unknown_protocol_blocks():
    ok, level, _, _ = compat.check("1.6.0", None, "1.6.0", 1)
    assert (ok, level) == (False, "block")


def test_parse_version_accepts_common_forms():
    assert compat.parse_version("1.6.0") == (1, 6)
    assert compat.parse_version("V1.6") == (1, 6)
    assert compat.parse_version("v10.2.1-beta") == (10, 2)
    assert compat.parse_version("0.0.1-other") == (0, 0)
    assert compat.parse_version(None) is None


# --- proto_of ----------------------------------------------------------------

def test_missing_proto_counts_as_one():
    assert compat.proto_of({"version": "1.5.0"}) == 1


@pytest.mark.parametrize("value", [0, -1, True, "2", 1.5, None])
def test_unusable_proto_values_are_unknown(value):
    assert compat.proto_of({"proto": value}) is None


def test_integer_proto_is_read():
    assert compat.proto_of({"proto": 3}) == 3


# --- beacon format and signatures ------------------------------------------

def test_new_beacon_carries_proto_and_verifies():
    priv, pub = generate_keypair()
    raw = make_beacon(priv, "abcdef0123456789", "192.168.1.5", 47800, "hash", "1.6.0", host_pub=pub)
    beacon = parse_beacon(raw, pub)
    assert beacon is not None
    assert beacon["proto"] == PROTO == 3


def test_explicit_proto_is_signed_and_read_back():
    priv, pub = generate_keypair()
    raw = make_beacon(priv, "abcdef0123456789", "192.168.1.5", 47800, "hash", "2.0.0", proto=2)
    assert parse_beacon(raw, pub)["proto"] == 2


def test_old_beacon_without_proto_still_parses_and_verifies():
    priv, pub = generate_keypair()
    raw = _signed_without_proto(priv)
    beacon = parse_beacon(raw, pub)
    assert beacon is not None
    assert "proto" not in beacon
    assert compat.proto_of(beacon) == 1


def test_old_beacon_against_new_build_is_blocked_even_when_versions_match_major_minor():
    priv, pub = generate_keypair()
    beacon = parse_beacon(_signed_without_proto(priv), pub)
    ok, level, _, _ = compat.check(beacon["version"], compat.proto_of(beacon), "1.5.0", PROTO)
    assert (ok, level) == (False, "block")


def test_newer_host_beacon_read_as_higher_proto_is_blocked_by_this_build():
    priv, pub = generate_keypair()
    beacon = parse_beacon(make_beacon(priv, "abcdef0123456789", "192.168.1.5", 47800, "hash",
                                      "2.0.0", proto=PROTO + 1), pub)
    ok, level, _, _ = compat.check(beacon["version"], compat.proto_of(beacon), "1.6.0", PROTO)
    assert (ok, level) == (False, "block")


def test_tampered_proto_breaks_the_signature():
    priv, pub = generate_keypair()
    raw = make_beacon(priv, "abcdef0123456789", "192.168.1.5", 47800, "hash", "1.6.0", proto=1)
    tampered = json.loads(raw)
    tampered["proto"] = 2
    assert parse_beacon(json.dumps(tampered).encode(), pub) is None


def test_stripping_proto_from_a_signed_beacon_breaks_the_signature():
    priv, pub = generate_keypair()
    raw = make_beacon(priv, "abcdef0123456789", "192.168.1.5", 47800, "hash", "1.6.0", proto=1)
    stripped = json.loads(raw)
    stripped.pop("proto")
    assert parse_beacon(json.dumps(stripped).encode(), pub) is None


def test_wrong_key_still_rejected_for_new_beacons():
    priv, _ = generate_keypair()
    _, other_pub = generate_keypair()
    raw = make_beacon(priv, "abcdef0123456789", "192.168.1.5", 47800, "hash", "1.6.0")
    assert parse_beacon(raw, other_pub) is None


def test_stale_beacon_rejected_even_without_proto():
    priv, pub = generate_keypair()
    raw = _signed_without_proto(priv, now=time.time() - 600)
    assert parse_beacon(raw, pub) is None
