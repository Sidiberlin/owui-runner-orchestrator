# 12 — Lane B'': orchestrator image on ZenDiS python3 (gated)

Type: task
Status: resolved
Blocked by: 10

## Question

Move the orchestrator image to `zendis/python3:3.13-main` using the VERIFIED
bootstrap: `python3 -m venv --without-pip` + `get-pip.py` + `pip install -r
requirements.txt` (system pip/ensurepip are broken on the Nix base — M0).
GATE before commit: uvicorn serve-smoke + aiodocker import + the full test
suite green inside the new image. If the gate fails, keep the current base and
record why (R-C full degrades to R-C minimal — stakeholder informed, not silent).

Detail: brief §1.6; M0 evidence incl. the successful open-terminal==0.13.0
venv install on this exact base.

## Answer
Implemented in commit 02b80d9 + review fixup 1eea884; gate passed (serve-smoke + full suite green); re-verified after memory-contention retry on 2026-09-19; pushed (2211d91).
