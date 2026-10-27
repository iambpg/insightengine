# Sanitized copy of the running stack

This tree is a **reference**, not what `docker compose up` runs. Passwords, API tokens, TLS keys, the Caddy basic-auth hash, and customer addresses were removed before it was committed.

- `10.40.40.222` and `172.29.10.3` were replaced with documentation addresses in `203.0.113.0/24` (TEST-NET-3).
- `prometheus/ie_switches_shard_1.json` is a one-row placeholder. The original site names and hostnames were not copied.
- The Caddy basic-auth hash was replaced with the word `REDACTED`.

See `docs/real-stack-diff.md` for what this bundle kept, changed, or left for the owner.
