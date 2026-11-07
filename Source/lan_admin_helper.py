# LAN Helper: the only program that runs elevated. It does one thing: carry out a single
# allow-listed operation (silent_tunnel.admin_actions) from a request file written by the
# launcher, after the user approves the Windows (UAC) prompt. It has no UI and never
# evaluates a command or script.
if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--lan-admin-action":
        from silent_tunnel.admin_actions import run_admin_child
        raise SystemExit(run_admin_child(sys.argv[2]))
    raise SystemExit(2)
