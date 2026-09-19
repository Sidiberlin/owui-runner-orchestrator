# 08 — P0/P1: third-party notices package

Type: task
Status: resolved
Blocked by: —

## Question

Complete the §0 inventory into a `THIRD-PARTY-NOTICES.md`: every image/ref in
`docker-compose.yml` + `runner/Dockerfile` with upstream URL, SPDX id
(validated), © line verbatim from the upstream LICENSE, and the
image/vendored/HTTP-call distinction. Independent review gate applies: a fresh
session must re-derive counts/claims before the file is committed.

## Answer
Independent-review gate RAN and PASSED (2026-09-19): 37 rows re-derived; 2 discrepancies (aiohttp dual license, missing pip row) found and fixed same day (2211d91). Draft no longer draft.
