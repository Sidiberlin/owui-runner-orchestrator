# Third-Party Notices

> **DRAFT — not yet reviewed.** Ticket 08 (P0/P1) requires a fresh, independent
> session to re-derive every claim in this file from the tree before it is
> relied upon for a public visibility flip. This draft was produced in the
> same session that built the rebase it documents, which is exactly the
> failure mode that gate exists to catch (see `.scratch/owui-runner-rebase/`
> ticket 02's own retraction of an earlier "file written" overclaim). Sources
> are cited inline; verify them independently before treating this as final.
> The container-image section was fetched live from each upstream repo's
> LICENSE file this session. The Python dependency section (pip-installed
> into the orchestrator image) was spot-checked for the four direct
> dependencies via PyPI metadata; the transitive closure lists SPDX ids from
> public package metadata but was **not** independently re-verified line by
> line this session — flagged below.

This project (MIT, see `LICENSE`) is a self-hosted alternative to Open WebUI's
commercial Terminals orchestrator, built against Open WebUI's documented
integration surface only (clean-room; see the hard constraints below). It
depends on and ships the following third-party software.

## Distribution model

- **"Included as container image"** — an upstream OCI image is pulled and run
  as-is (or as a `FROM` base with our own layers on top); we do not modify or
  redistribute its source.
- **"Vendored"** — a binary or package is fetched at build time and copied
  into an image we build and distribute.
- **"Called over HTTP, not distributed"** — the component (Open WebUI itself)
  is a separate running service this project talks to; nothing of it is
  copied, compiled, or shipped.

## Hard constraints (brief §0, verified 2026-09-18, do not violate)

- **Zero code from `open-webui/terminals`** (the proprietary enterprise fleet
  orchestrator). Never read that repo for implementation reference; this
  project was built from Open WebUI's documented integration surface only.
- **MIT notices preserved** for Open Terminal, the (now-removed) opencode
  CLI, and every ZenDiS image, below.
- Open Web UI itself is called over HTTP only (the admin API, for role
  lookups) — not distributed, no notice obligation beyond attribution.

## Container images

| Component | Image(s) | SPDX | Copyright | Distribution |
|---|---|---|---|---|
| Open Terminal (server) | `ghcr.io/open-webui/open-terminal:slim` | `MIT` | © 2026 Open WebUI Inc. (Timothy Jaeryang Baek) | Included as container image (base for `runner/Dockerfile`) |
| opencode CLI | *(removed, ticket 10 — no longer shipped)* | `MIT` | per `anomalyco/opencode` upstream | Historical only: fetched at build time in prior revisions; kept here for git-history attribution, not current distribution |
| ZenDiS hardened bases | `registry.opencode.de/oci-community/images/zendis/python3:3.13-main` (orchestrator, ticket 12), `registry.opencode.de/oci-community/images/zendis/coreutils:main` (compose helpers, ticket 11) | `MIT` | © 2025 Zentrum für Digitale Souveränität der Öffentlichen Verwaltung (ZenDiS) GmbH | Included as container image. Images carry their own `LICENSE.md` + `cosign.pub`; ZenDiS's own notice: "some files may be provided under a different licence (see file header)" |
| Docker Socket Proxy | `tecnativa/docker-socket-proxy:0.3.0` | `Apache-2.0` | No copyright line in `LICENSE.txt` (stock Apache boilerplate) or a `NOTICE` file upstream; attribute to Tecnativa (github.com/Tecnativa/docker-socket-proxy) | Included as container image |
| DevGuard (API, CLI, web UI) | `ghcr.io/l3montree-dev/devguard:${DEVGUARD_VERSION}`, `ghcr.io/l3montree-dev/devguard-web:${DEVGUARD_VERSION}` | `AGPL-3.0-or-later` | © 2024 l3montree GmbH | Included as container image, **unmodified**. See "DevGuard and AGPL" below. |
| DevGuard's PostgreSQL image | `ghcr.io/l3montree-dev/devguard/postgresql:16.15` | PostgreSQL (permissive) for the database engine itself; the image's init scripts live in l3montree's `AGPL-3.0-or-later` repo | © PostgreSQL Global Development Group (engine); © 2024 l3montree GmbH (init scripts/packaging) | Included as container image, unmodified |
| DevGuard's Kratos image | `ghcr.io/l3montree-dev/devguard/kratos:v26.2.0` | `Apache-2.0` (upstream Ory Kratos) | No explicit copyright line found in Ory's `LICENSE`; attribute to Ory Corp (github.com/ory/kratos) | Included as container image, unmodified |
| nginx (pip-shim, ADR-0010) | `nginx:1.27-alpine` | `BSD-2-Clause`-style ("2-clause" pattern in upstream `LICENSE`) | © 2002-2021 Igor Sysoev; © 2011-2026 Nginx, Inc. | Included as container image; our own `devguard/pip-shim/default.conf` config layered on top, no nginx source modified |

### DevGuard and AGPL

DevGuard is licensed **AGPL-3.0-or-later**, not a permissive license. This
project deploys DevGuard's published container images unmodified, over a
network, as a separate service (the "dependency firewall" / package proxy) —
it is not linked into, forked into, or distributed as part of this
project's own code. Under the standard reading of AGPL's network-copyleft
clause, running someone else's unmodified AGPL program as a service you
depend on does not impose AGPL terms on your own, separately-licensed code;
the clause activates for *modifications to the AGPL program itself* that are
then made available over a network. **This is not legal advice** — flag to
the stakeholder before the public flip: if this project ever forks or
patches DevGuard's own source (as opposed to configuring/deploying the
published image), that changes the analysis and would need AGPL source
disclosure for those modifications.

**Clarification: `pip-shim` is not a DevGuard modification.** ADR-0010's
`pip-shim` sidecar could look, at a glance, like exactly the kind of
DevGuard patch the paragraph above warns about — it is not. `pip-shim` is
this project's own MIT-licensed nginx config (`devguard/pip-shim/default.conf`)
running in an *adjacent* container (`nginx:1.27-alpine`, unmodified — see the
container table above), rewriting the HTTP responses DevGuard serves to pip
clients on their way past. DevGuard itself continues to run as the stock,
unmodified upstream image throughout; no DevGuard source, binary, or config
is patched, forked, or redistributed. The proper fix is upstream:
[l3montree-dev/devguard#3067](https://github.com/l3montree-dev/devguard/issues/3067)
tracks rewriting the simple index natively in DevGuard, and its merge is
what retires `pip-shim` (see `docs/adr/0010-pip-index-rewriter.md` and
`docs/upstream/devguard-pypi-index-passthrough.md`).

**Stakeholder ratified this unmodified-deployment analysis on 2026-09-19.**

## Vendored at build time (not a container image)

| Component | Version pinned | SPDX | Copyright | Distribution |
|---|---|---|---|---|
| Node.js (official prebuilt tarball) | 22.14.0 (`runner/Dockerfile` `NODE_VERSION`) | `MIT` (Node.js's own top-level `LICENSE`); the official binary distribution additionally bundles several third-party components (V8, npm, etc.) each under its own license — see `nodejs/node`'s `LICENSE` file for the full list, not reproduced here | © Node.js contributors | Vendored: official `.tar.gz` fetched from `nodejs.org` at build time, unmodified, copied into `runner/Dockerfile`'s runtime stage |

## Python dependencies (orchestrator image, `orchestrator/requirements.txt`)

Installed via pip into the orchestrator image at build time (ticket 12's
venv+get-pip bootstrap) — vendored, since they end up in a container image
this project distributes.

**Direct dependencies (PyPI metadata spot-checked this session):**

| Package | Pinned | SPDX |
|---|---|---|
| fastapi | 0.115.6 | `MIT` |
| uvicorn\[standard\] | 0.34.0 | `BSD-3-Clause` |
| aiodocker | 0.24.0 | `Apache-2.0` |
| httpx | 0.28.1 | `BSD-3-Clause` |

**Transitive closure** (pulled in by the four above, mostly via
`uvicorn[standard]`'s and `aiodocker`'s own dependencies). SPDX ids below are
from public package metadata known to this session; **not independently
re-verified line-by-line this session** — part of the ticket 08 review gate:

| Package | SPDX (unverified this session) |
|---|---|
| starlette | `BSD-3-Clause` |
| pydantic, pydantic-core | `MIT` |
| typing-extensions | `PSF-2.0` |
| typing-inspection | `MIT` |
| annotated-types | `MIT` |
| click | `BSD-3-Clause` |
| h11 | `MIT` |
| httpcore | `BSD-3-Clause` |
| anyio | `MIT` |
| certifi | `MPL-2.0` |
| idna | `BSD-3-Clause` |
| pyyaml | `MIT` |
| uvloop | `MIT` / `Apache-2.0` (dual) |
| httptools | `MIT` |
| watchfiles | `MIT` |
| websockets | `BSD-3-Clause` |
| python-dotenv | `BSD-3-Clause` |
| aiohttp | `Apache-2.0` |
| multidict, yarl, frozenlist, aiosignal, propcache | `Apache-2.0` |
| attrs | `MIT` |
| aiohappyeyeballs | `PSF-2.0` |

## Called over HTTP, not distributed

- **Open WebUI** (`open-webui/open-webui`) — the orchestrator calls its admin
  API for role lookups (Q1/A8) and is driven by its Open Terminal client
  integration. Nothing of Open WebUI is copied, compiled, or shipped by this
  project. Its own license (BSD-3 + a branding-removal clause, §4) is
  relevant only to someone redistributing Open WebUI itself, which this
  project does not do.
