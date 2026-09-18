# The Package Seam is the only way package config reaches runners

PIP_INDEX_URL and NPM_CONFIG_REGISTRY are injected at container create with empty defaults; nothing else about package management is configurable per-runner. This keeps the future swap (no proxy -> DevGuard) a .env change, and guarantees there is no second, forgotten path by which a runner could reach a public registry.
