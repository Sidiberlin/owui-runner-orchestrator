# Orchestrator moves to zendis/python3:3.13-main, gated on a proven bootstrap

The orchestrator image (ticket 12) moves from `python:3.12-slim` to
`zendis/python3:3.13-main`, digest-pinned, to trace as much of the stack as
feasible to the opencode.de hardened catalog. This is the gated half of D1:
the runner runtime itself stays on `open-terminal:slim` (M0 ruled out the
zends bases there — no pip, no toolchain), but the orchestrator is a plain
Python service with no OS-level dependencies of its own, which is exactly
the shape M0 found workable.

The base is Nix-built and ships neither a working system pip nor a working
`ensurepip` (`python3 -m ensurepip` throws inside the bundled wheel's own
self-install, measured live). The verified bootstrap is `python3 -m venv
--without-pip` followed by `get-pip.py` into that venv — proven first for
`open-terminal==0.13.0` in M0, and here for the orchestrator's own
dependency set (fastapi, uvicorn[standard], aiodocker, httpx, and their
transitive closure including compiled extensions — uvloop, httptools,
pydantic-core — all of which resolved to prebuilt manylinux wheels with no
compiler on the image). `/tmp` is not writable under the base's default uid
53111; the venv and its bootstrap script live under `$HOME=/home/nonroot`
instead. A fresh top-level directory (`/data`, for the workspace-size cache,
N4) is not writable by uid 53111 either — the Dockerfile's one `USER root`
step creates and chowns it, then drops straight back; nothing else in the
image ever runs as root.

This shipped only after the ticket's hard gate passed inside the built
image: `import aiodocker, fastapi, uvicorn, httpx` plus the orchestrator's
own `app.main`, then the full test suite (162 passed, 12 skipped
live-DevGuard-gated, 7 deselected slow) against a stack running this exact
image. A gate failure here was an accepted outcome (keep `python:3.12-slim`
and record why) — it did not come to that.
