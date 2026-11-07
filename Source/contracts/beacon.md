# Beacon contract (Workstream A/B)
UDP broadcast on port 47801 every 2 s while a room is open.
Payload: JSON `{"v":1,"net_id":"...","host":"ip","presence_port":47800,"planet_hash":"sha256hex","version":"x.y","proto":1,"ts":unix,"sig":"b64"}`.
`sig` = Ed25519 signature (host private key) over canonical JSON (sorted keys, no spaces) of all fields except `sig`.
Client verifies against baked host public key, rejects if |now-ts| > 30 s (replay window).

Optional fields (added): `host_zt` (host's ZeroTier IP, always .1 of the room subnet), `planet_port` (default 47802), and `sync_port` (default 47803).

Optional field (added): `moon_id` (hex id of the moon whose sha256 is `planet_hash`).

Field `proto` (integer, added in 1.6): the wire protocol number of the sender, from
`lantool/_version.py` `__proto__` (currently 2). It is covered by the signature like every other field.
A beacon WITHOUT `proto` is an older build and counts as proto 1. Old beacons still parse and verify.
The other fields are unchanged.

Compatibility between Host and Client (`lantool/netcore/compat.py`, `compat.check`):
- `proto` differs: `block`. The two builds cannot join. Message says which PC is older.
- `proto` is invalid: `block`.
- same `proto`, same major.minor (patch ignored): `ok`.
- same `proto`, different major.minor, or an unreadable version string: `warn`. Join is still allowed.
Bump `__proto__` when room admission or message formats require incompatible behavior. Ordinary releases increment the `0.9.NN` release counter and keep the room protocol.

Optional field: `sync_port` (file-sync service, default 47803). Clients trust host
beacons only after importing the host's `lantool-client-bundle-v1` JSON package,
which carries the host public key, network id, signed moon and library version.
