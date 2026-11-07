"""Join pack: a small signed file a Host can hand to a Client offline (WP-F).

The pack carries what a Client needs to join a room by file instead of by
discovery: the room code, the Host name, the app version and the SHA-256 of
the exe. It is signed with the Host's existing Ed25519 key (trust/signing.py)
and embeds the Host's public key, so it verifies the same way a beacon does.

It never carries private keys, planet/moon secrets or anything beyond what
the signed beacon already shares.
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ._version import __proto__ as PROTO_VERSION
from .trust.signing import canonical, sign_obj, verify_obj

KIND = "lanlauncher-joinpack"
MAX_BYTES = 16 * 1024
_SECRET_MARKERS = ("priv", "secret", "password", "token", "key_file", "planet", "moon_secret")
_ROOM_FIELDS = ("room_code", "net_id")


class JoinPackError(ValueError):
    """Pack is empty, truncated, malformed or fails verification."""


class JoinPackProtoError(JoinPackError):
    """Pack was written by a newer protocol than this build understands."""


@dataclass(frozen=True)
class JoinPack:
    proto: int
    app_version: str
    room_code: str
    net_id: str
    host_name: str
    host_pub: str
    exe_sha256: str
    created: int = 0
    extra: dict = field(default_factory=dict, compare=False)


def _pub_from_priv(priv_b64: str) -> str:
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(priv_b64))
    pub = key.public_key().public_bytes(encoding=serialization.Encoding.Raw,
                                        format=serialization.PublicFormat.Raw)
    return base64.b64encode(pub).decode()


def _check_no_secrets(room_info: dict) -> None:
    for key in room_info:
        low = str(key).lower()
        if any(marker in low for marker in _SECRET_MARKERS):
            raise ValueError(f"join pack refuses secret-looking field: {key!r}")


def build(room_info: dict, app_version: str, hashes: dict, *, priv_b64: str,
          now: int | None = None) -> bytes:
    """Return a signed join pack as bytes.

    room_info needs 'room_code', 'net_id' and 'host_name'. hashes needs 'exe'
    (the SHA-256 hex of the exe). priv_b64 is the Host's signing key, used only
    to sign and never written to the pack.
    """
    _check_no_secrets(room_info)
    _check_no_secrets(hashes)
    for name in ("room_code", "net_id", "host_name"):
        if not isinstance(room_info.get(name), str) or not room_info[name]:
            raise ValueError(f"room_info.{name} is required")
    exe = hashes.get("exe")
    if not isinstance(exe, str) or len(exe) != 64:
        raise ValueError("hashes['exe'] must be a SHA-256 hex digest")
    body = {
        "kind": KIND,
        "proto": PROTO_VERSION,
        "app_version": str(app_version),
        "room_code": room_info["room_code"],
        "net_id": room_info["net_id"],
        "host_name": str(room_info["host_name"])[:64],
        "host_pub": _pub_from_priv(priv_b64),
        "exe_sha256": exe.lower(),
        "created": int(now if now is not None else time.time()),
    }
    return canonical(sign_obj(priv_b64, body))


def parse(data: bytes, *, pinned_pub: str | None = None,
          max_proto: int = PROTO_VERSION) -> JoinPack:
    """Verify and decode a join pack. Raises JoinPackError on any problem.

    If pinned_pub is given the signature must match it; otherwise the embedded
    host_pub is used (self-authenticating, like discovered beacons).
    """
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise JoinPackError("join pack is empty")
    if len(data) > MAX_BYTES:
        raise JoinPackError("join pack is too large")
    try:
        obj = json.loads(bytes(data).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise JoinPackError("join pack is truncated or not valid JSON") from exc
    if not isinstance(obj, dict) or obj.get("kind") != KIND:
        raise JoinPackError("not a LAN Launcher join pack")

    proto = obj.get("proto", 1)
    if not isinstance(proto, int) or isinstance(proto, bool) or proto < 1:
        raise JoinPackError("join pack has an invalid proto")
    if proto > max_proto:
        raise JoinPackProtoError(
            f"join pack needs protocol {proto}; this build supports {max_proto}. "
            "Update LAN Launcher on this PC.")

    for name in ("app_version", "room_code", "net_id", "host_name",
                 "host_pub", "exe_sha256", "sig"):
        if not isinstance(obj.get(name), str) or not obj[name]:
            raise JoinPackError(f"join pack is missing {name}")

    signer = pinned_pub or obj["host_pub"]
    if pinned_pub and obj["host_pub"] != pinned_pub:
        raise JoinPackError("join pack was signed by a different Host")
    if not verify_obj(signer, obj):
        raise JoinPackError("join pack signature does not match (tampered or damaged)")

    exe = obj["exe_sha256"]
    if len(exe) != 64 or any(c not in "0123456789abcdef" for c in exe):
        raise JoinPackError("join pack has a malformed exe hash")

    known = {"kind", "proto", "app_version", "room_code", "net_id", "host_name",
             "host_pub", "exe_sha256", "created", "sig"}
    return JoinPack(
        proto=proto,
        app_version=obj["app_version"],
        room_code=obj["room_code"],
        net_id=obj["net_id"],
        host_name=obj["host_name"],
        host_pub=obj["host_pub"],
        exe_sha256=exe,
        created=int(obj.get("created", 0) or 0),
        extra={k: v for k, v in obj.items() if k not in known},
    )
