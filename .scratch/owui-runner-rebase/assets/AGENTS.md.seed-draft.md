# This machine

This runner is AIR-GAPPED BY DESIGN. It has no internet access, and that is
not a malfunction. Connection failures to external hosts are EXPECTED:
never retry them, never debug DNS, never suggest VPN/proxy/registry fixes.

Packages are served by an internal, malware-checked mirror that is already
configured. Just run `pip install <pkg>` / `npm install <pkg>` normally —
pip uses $PIP_INDEX_URL, npm uses $NPM_CONFIG_REGISTRY. Never point them
at public registries; it cannot work.

Internal services (machine-readable in $SANDBOX_INTERNAL_SERVICES):
- devguard-api:8080 — package proxy (pip/npm), blocks known-malicious packages

curl, wget and apt-get work ONLY for internal services. Pointed at the
outside world they print an explanation and fail fast (exit 126).
Never use them against external URLs; never run `apt-get update`/`install`.

git works locally (init, commit, diff). Cloning from external hosts is
impossible — if you need external code, say so in your reply instead of
trying to fetch it.

Check `env | grep SANDBOX` for the machine-readable facts about this machine.
