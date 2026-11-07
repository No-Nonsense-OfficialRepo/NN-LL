# Release reliability validation

Build environment: Windows x64 CPython 3.15.0. Install with `python -m pip install --require-hashes -r build-requirements.lock`. The build verifies installed versions and records the lock digest in version.json. Hashes apply to the captured Windows wheels; regenerate the lock deliberately for another interpreter or architecture.

Publisher signing already exists in scripts/sign_release.ps1 and build_windows.ps1. Supply a trusted CurrentUser\My certificate with a private key and a timestamp service. The build signs before hashing and verifies signatures. No suitable certificate was available during this work; no signed release has been produced.

## Two-PC fault exercise (pending hardware execution)

Use disposable destination folders. Record versions, adapter type, disk type, logs, elapsed recovery time and final file hashes for each case.

1. Start a large transfer, terminate Host, restart it, then resume. Expect verified pieces reused and every final hash matching Host.
2. Disconnect Client network for 30 seconds and reconnect. Expect bounded retries, a useful error/status, and successful resume without restarting the app.
3. Sleep/resume each PC during a transfer. Expect discovery/presence recovery and no duplicate transfer owners.
4. Fill a disposable destination volume during transfer. Expect a visible disk error, no completed installation receipt, and resumable data after space is freed.
5. Hold a destination or journal file open briefly without delete sharing. Expect bounded retry; a longer lock must produce a useful error and allow later retry.
6. Kill the launcher after joining/hosting; restart. Expect recorded memberships/rooms cleaned up. Corrupt primary state and repeat: backup must restore recovery information. If both records are damaged startup must report failure.
7. Connect multiple clients, including one stalled request. Expect normal clients to continue transferring and idle/stalled sockets to expire.
8. Verify signed executable identities, package manifest hashes and actual launch on a clean Windows PC before publishing.

These cases have not been executed across two PCs in this session.
