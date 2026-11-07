Connection check (read-only)

1. Extract both Connection Check files into a folder on the remote Client PC.
2. Keep the Host launcher open, then retry joining from that Client using Room key.
3. Leave the Client open and double-click Connection Check.cmd.
4. Send Connection Report.json back, together with the exact error message.

The check reads VLA status, firewall rules, service listeners and recent join timings.
It sends three small UDP NAT checks to Cloudflare/Google and time-server queries.
It does not change firewall rules, router settings, VLA settings or approvals.
Authentication keys and identity secret files are not included in the report.
The report includes device names, public/network addresses and executable hashes.
