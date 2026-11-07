"""Game-level view of who we download from and who downloads from us (Downloads page). No Qt, no I/O."""
from __future__ import annotations


def _name(roster):
    by_id = {str(p.get("player_id")): p.get("name") for p in roster if p.get("player_id") and p.get("name")}
    by_ip = {str(p.get("ip")): p.get("name") for p in roster if p.get("ip") and p.get("name")}
    return by_id, by_ip


def _ip(who):
    """'10.1.2.3:47805' -> '10.1.2.3'; a bare ip stays as is."""
    return str(who).rsplit(":", 1)[0] if str(who).count(":") == 1 else str(who)


def _rank(rows):
    return sorted(rows, key=lambda r: (not r["active"], r["name"].casefold()))


def build_transfers(*, library, downloading, seeded, peer_sources, roster, received, uploads, host_ip="", my_id=""):
    """Rows for the Downloads page, one per game that is downloading, seeding or has recent transfers.

    received/uploads are ActivityTracker snapshots; received.who is 'ip:port' of the source, uploads.who is the
    leecher's ip. Each result row: {id, name, downloading, seeding, from: [...], to: [...]} with list items
    {name, kind: host|peer, active, bytes}."""
    by_id, by_ip = _name(roster)
    got, sent, out = {}, {}, []
    for row in received:
        got.setdefault(row["game"], []).append(row)
    for row in uploads:
        sent.setdefault(row["game"], []).append(row)
    for gid, manifest in library.items():
        is_downloading = gid == downloading
        sources = []
        used = set()
        if is_downloading or gid in got:
            rows_by_ip = {}
            for row in got.get(gid, []):
                ip = _ip(row["who"])
                prev = rows_by_ip.get(ip)
                rows_by_ip[ip] = {"bytes": row["bytes"] + (prev["bytes"] if prev else 0),
                                  "active": row["active"] or bool(prev and prev["active"])}
            if host_ip and (is_downloading or host_ip in rows_by_ip):
                info = rows_by_ip.get(host_ip, {"bytes": 0, "active": False})
                sources.append({"name": "Host", "kind": "host", **info})
                used.add(host_ip)
            for peer in peer_sources:
                if gid not in peer.get("games", ()) or peer.get("player_id") == my_id:
                    continue
                ip = str(peer.get("host", ""))
                if ip in used:
                    continue
                used.add(ip)
                info = rows_by_ip.get(ip, {"bytes": 0, "active": False})
                name = by_id.get(str(peer.get("player_id"))) or by_ip.get(ip) or ip or "Unknown player"
                sources.append({"name": name, "kind": "peer", **info})
            for ip, info in rows_by_ip.items():  # a source that served us but is no longer announced
                if ip not in used:
                    sources.append({"name": by_ip.get(ip) or f"Unknown ({ip})", "kind": "peer", **info})
        targets = []
        merged = {}
        for row in sent.get(gid, []):
            prev = merged.get(row["who"])
            merged[row["who"]] = {"bytes": row["bytes"] + (prev["bytes"] if prev else 0),
                                  "active": row["active"] or bool(prev and prev["active"])}
        for ip, info in merged.items():
            targets.append({"name": by_ip.get(ip) or f"Unknown ({ip})", "kind": "peer", **info})
        seeding = gid in seeded or bool(targets)
        if not (is_downloading or seeding or sources):
            continue
        out.append({"id": gid, "name": manifest.get("name", gid), "downloading": is_downloading,
                    "seeding": seeding, "from": _rank(sources), "to": _rank(targets)})
    out.sort(key=lambda r: (not r["downloading"], r["name"].casefold()))
    return out
