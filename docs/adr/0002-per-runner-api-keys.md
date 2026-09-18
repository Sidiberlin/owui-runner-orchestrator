# Every runner gets its own random API key

Runners can read their own environment (proven by a test), so a shared secret would be readable by every runner. Per-runner random keys mean a compromised runner's credentials are worth nothing outside itself, and DevGuard/orchestrator logs attribute every package pull and request to exactly one runner.
