# 01 — D2: opencode CLI source for the rebased runner

Type: task
Status: resolved
Blocked by: —

## Question

Where does the opencode CLI binary come from after the runner rebase onto ZenDiS
bases: (a) the current pinned GitHub installer + a sha256 pin on the release
artifact, or (b) a mirror on gitlab.opencode.de, if one exists?

Recorded decision must state the exact pinning mechanism for the Dockerfile.

## Answer

**Decision: (a) — pinned GitHub installer + sha256 pin on the release artifact.
Not a zends mirror.**

Mechanism, concretely:

- Discover the latest release via `https://github.com/sst/opencode/releases/latest`
  (redirect → tag), or keep a manually-bumped `OPENCODE_VERSION` ARG (currently
  1.18.31; bump = deliberate edit).
- Download `opencode-<version>-linux-x86_64.tar.gz` (name per release assets) from
  `https://github.com/sst/opencode/releases/download/<version>/...` at build time.
- `sha256sum` it against a hash recorded in the Dockerfile; build FAILS on mismatch.
  Record how the hash was obtained (release page / `sha256sum` at bump time) next to
  the ARG so the next bumper can re-verify.
- Installer script `curl https://opencode.ai/install | bash` is dropped; the explicit
  download replaces it (same build-time-egress-only property, now auditable).

Why not (b):

- registry.opencode.de runs **GitLab**, and the thing we'd need mirrored is a
  **GitHub release artifact**; the GitLab generic packages endpoint needs
  authentication, and a mirror project of the CLI would still have to be
  created+populated by someone with credentials. No such mirror was found
  (registry search: no opencode/ project; guide has only docs).
- Even if a mirror existed, a GitHub release URL pinned by tag + sha256 is at least
  as verifiable as a third-party mirror — and the upstream tag is the auditable
  source. A mirror adds a second party to trust, not less.

Verify evidence, this session, on the live registry (all measured):

```
GET https://registry.opencode.de/v2/                                  → 401, realm=GitLab, service=registry, no error token (anonymous challenge)
GET .../v2/oci-community/images/zendis/python3/tags/list              → 401 with error="UNAUTHORIZED" (anonymous; auth works only via docker login)
GET https://gitlab.opencode.de/api/v4/projects?search=opencode        → 200, []        (authenticated-less search finds nothing)
GET https://gitlab.opencode.de/api/v4/groups?search=zendis            → 200, 2 groups  (13 descendants incl. oci-community/images)
GET .../groups/oci-community%2Fimages/projects?search=                → 200, 2 projects: base, guide   (both public; NO opencode CLI mirror)
curl -s https://opencode.ai/install | grep -oP 'github.com/[^"]*releases/download[^"]*' | head -1
  → https://github.com/.../releases/download/v1.18.31/opencode-1.18.31-linux-x86_64.tar.gz
```

So: `D2 = (a) pinned installer + sha256`. The Dockerfile change (replace the
installer-curl with a pinned release download + hash check) happens inside the
Lane A' implementation ticket (which graduates from the fog after D1).

## SUPERSEDED (2026-09-18, later the same session)

D1 landed as R-C **and** the stakeholder dropped the opencode CLI from the
runner entirely (the OWUI chat model is the agent; nothing invokes opencode —
verified by grep: it appears only in `runner/Dockerfile`). With no opencode in
the image there is nothing to pin: **D2 is moot.** The measured GitLab/registry
facts above remain valid record. See ticket 10.
