# File sync contract (Workstream G, F8)

Transport: plain HTTP/1.0 over TCP, default port 47803 (`SYNC_PORT`). Host serves `<library_root>/<game_id>/`.
Ports so far: presence TCP 47800, beacon UDP 47801, planet TCP 47802, sync TCP 47803.

## Trust
The index is signed by the host's Ed25519 key (`sign_obj`). Clients verify it against the baked public key
BEFORE downloading anything, then verify each file's sha256 against the signed index. File bytes themselves are
never trusted on their own (games are executables). A tampered file, a forged index, or an index for another
game id is rejected.

## Routes (GET only)
| route | response |
|---|---|
| `/index/<game_id>` | 200 JSON `{"game_id","files":[{"path","size","sha256"}],"total_bytes","sig"}` |
| `/file/<game_id>/<url-quoted relpath>` | 200 full body, or 206 when `Range: bytes=N-` (optionally `N-M`) is sent |
| anything else / bad id / path escape | 404 (416 for unsatisfiable range) |

`path` is a forward-slash relative path. Rejected on both sides: empty, absolute, backslash, `..`/`.` segments,
`:` (drive letters, NTFS streams), trailing dot or space, Windows device names (CON, NUL, COM1...).

## Client behaviour
1. Fetch + verify index. Check free disk space against bytes still to download (F10 pre-flight).
2. Diff: a local file is unchanged when size and sha256 match. Local hashes are cached in
   `<dest>/.lantool-hashcache.json` keyed by (size, mtime_ns); `verify=True` ignores the cache.
3. Download changed files to `<file>.lantool-part`, resuming with `Range` from the part's size. If the server
   answers 200 to a ranged request the part restarts from 0.
4. Verify sha256 after each file; only then atomic-rename into place. Mismatch deletes the part and records a failure.
5. `prune=True` removes local files that are not in the index. Default is off.
6. Up to `concurrency` (default 4) files in parallel. Progress callback gets (bytes_done, bytes_total, current_path).

Host-only files never served or indexed: `*.lantool-part`, `.lantool-hashcache.json`, symlinks.
