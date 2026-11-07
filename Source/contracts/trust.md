# Trust contract (Workstream B)
- Host keypair: Ed25519. Public key (raw 32 bytes, b64) baked into client bundle `bundle.json`.
- `sign_bytes(priv, data)->b64`, `verify_bytes(pub_b64, data, sig_b64)->bool`.
- Planet/moon file served with detached signature + sha256. Client accepts only if signature verifies.
- Bundle: `bundle.json` = {host_pub, planet_sha256, library_version, created}.

## Amendment: moon instead of planet (no prototype exists)
- Host node is the moon root and the network controller. `lantool.trust.moon.build_moon(home, ["<lan ip>/9993"])` runs ZeroTier's `zerotier-idtool initmoon` + `genmoon` and returns `MoonFile(moon_id, data)`. Regenerate when the host's LAN IP changes.
- Served and verified exactly like the old planet file (`PlanetServer` / `fetch_planet`, Ed25519 detached signature + beacon hash). Beacon `planet_hash` = sha256 of the moon file; new optional beacon field `moon_id`.
- Client installs to `<zt home>/moons.d/<16 hex>.moon` and restarts the service (`silent_tunnel/moon.py`, one UAC prompt). The default planet stays; moons are additive.
