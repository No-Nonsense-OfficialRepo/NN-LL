import json

import pytest

from lantool import joinpack
from lantool._version import __proto__
from lantool.joinpack import JoinPackError, JoinPackProtoError
from lantool.trust.signing import generate_keypair, sha256_hex

EXE = sha256_hex(b"fake exe bytes")
ROOM = {"room_code": "ABCD-2345", "net_id": "net-123", "host_name": "HOST-PC"}


@pytest.fixture()
def keys():
    priv, pub = generate_keypair()
    return priv, pub


def _pack(keys, **over):
    priv, _ = keys
    room = {**ROOM, **over.pop("room", {})}
    return joinpack.build(room, "1.6.0", {"exe": EXE}, priv_b64=priv, now=1000)


def test_round_trip(keys):
    _, pub = keys
    data = _pack(keys)
    pack = joinpack.parse(data)
    assert pack.proto == __proto__
    assert pack.app_version == "1.6.0"
    assert pack.room_code == ROOM["room_code"]
    assert pack.net_id == ROOM["net_id"]
    assert pack.host_name == "HOST-PC"
    assert pack.exe_sha256 == EXE
    assert pack.host_pub == pub
    assert pack.created == 1000
    # Pinned key that matches is accepted too.
    assert joinpack.parse(data, pinned_pub=pub).room_code == ROOM["room_code"]


def test_pack_never_contains_private_key(keys):
    priv, _ = keys
    data = _pack(keys)
    assert priv.encode() not in data
    assert b"private" not in data.lower()


def test_build_refuses_secret_fields(keys):
    priv, _ = keys
    with pytest.raises(ValueError):
        joinpack.build({**ROOM, "planet_secret": "x"}, "1.6.0", {"exe": EXE}, priv_b64=priv)
    with pytest.raises(ValueError):
        joinpack.build(ROOM, "1.6.0", {"exe": EXE, "priv_key": "x"}, priv_b64=priv)


def test_build_requires_fields_and_sha256(keys):
    priv, _ = keys
    with pytest.raises(ValueError):
        joinpack.build({"room_code": "", "net_id": "n", "host_name": "h"},
                       "1.6.0", {"exe": EXE}, priv_b64=priv)
    with pytest.raises(ValueError):
        joinpack.build(ROOM, "1.6.0", {"exe": "not-a-hash"}, priv_b64=priv)


def test_tampered_field_is_rejected(keys):
    data = _pack(keys)
    obj = json.loads(data)
    obj["room_code"] = "ZZZZ-9999"
    with pytest.raises(JoinPackError, match="signature"):
        joinpack.parse(json.dumps(obj).encode())


def test_tampered_exe_hash_is_rejected(keys):
    obj = json.loads(_pack(keys))
    obj["exe_sha256"] = sha256_hex(b"other exe")
    with pytest.raises(JoinPackError, match="signature"):
        joinpack.parse(json.dumps(obj).encode())


def test_tampered_proto_down_is_rejected(keys):
    obj = json.loads(_pack(keys))
    obj["proto"] = 1
    obj["room_code"] = "EVIL"
    with pytest.raises(JoinPackError):
        joinpack.parse(json.dumps(obj).encode())


def test_wrong_signer_pin_is_rejected(keys):
    _, other_pub = generate_keypair()
    with pytest.raises(JoinPackError, match="different Host"):
        joinpack.parse(_pack(keys), pinned_pub=other_pub)


def test_truncated_is_rejected(keys):
    data = _pack(keys)
    for cut in (1, len(data) // 2, len(data) - 1):
        with pytest.raises(JoinPackError):
            joinpack.parse(data[:cut])


def test_newer_proto_is_refused(keys):
    priv, _ = keys
    body = json.loads(_pack(keys))
    body.pop("sig")
    body["proto"] = __proto__ + 1
    from lantool.trust.signing import sign_obj
    newer = json.dumps(sign_obj(priv, body)).encode()
    with pytest.raises(JoinPackProtoError, match=f"protocol {__proto__ + 1}"):
        joinpack.parse(newer)


def test_missing_proto_defaults_to_one(keys):
    priv, _ = keys
    body = json.loads(_pack(keys))
    body.pop("sig")
    body.pop("proto")
    from lantool.trust.signing import sign_obj
    pack = joinpack.parse(json.dumps(sign_obj(priv, body)).encode())
    assert pack.proto == 1


def test_wrong_kind_is_rejected(keys):
    obj = json.loads(_pack(keys))
    obj["kind"] = "something-else"
    with pytest.raises(JoinPackError, match="not a LAN Launcher join pack"):
        joinpack.parse(json.dumps(obj).encode())


def test_empty_and_non_bytes_input():
    for bad in (b"", bytearray(), None, "text"):
        with pytest.raises(JoinPackError):
            joinpack.parse(bad)


def test_oversized_input_is_rejected():
    with pytest.raises(JoinPackError, match="too large"):
        joinpack.parse(b"{" * (joinpack.MAX_BYTES + 1))


def test_non_utf8_and_non_object_are_rejected():
    with pytest.raises(JoinPackError):
        joinpack.parse(b"\xff\xfe\x00")
    with pytest.raises(JoinPackError):
        joinpack.parse(b"[1, 2, 3]")
