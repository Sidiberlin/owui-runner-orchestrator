# =============================================================================
#  OWUI Agent Runner — per-user ephemeral coding-agent container
#  Lane A.  See REVIEW OUTCOMES v1.2 (N6, N7, N8, N9) in the brief.
# =============================================================================
#
#  LAYERING — inverted from the original brief (N6)
#
#    The brief said "multi-stage build on the openCode base image".  Measured:
#      ghcr.io/anomalyco/opencode  = Alpine 3.24, NO python3/pip/uv/node/git/curl,
#                                    and the binary is musl-linked.
#      Open Terminal               = a Python service.
#    So openCode cannot host it, and the musl binary cannot be copied into a
#    glibc image.  We therefore base on Open Terminal and fetch openCode's
#    glibc build at BUILD time (build-time egress is fine; runtime egress is
#    zero via the `internal: true` network).
#
#      ghcr.io/open-webui/open-terminal:slim   Debian 13 · py3.12 · uid1000 `user`
#        │                                     tini · hardened entrypoint · :8000
#        ├─ stage `opencode`  fetch pinned openCode release (installer needs bash)
#        └─ stage `runtime`   COPY just the binary — nothing else from the builder
#
#  RUNTIME SHAPE — why there is no `USER` line below (N8)
#
#    root  (entrypoint-slim.sh)          ← MUST start as root
#      │   file_env OPEN_TERMINAL_API_KEY[_FILE]
#      │   chown -R user:user $HOME      ← this is what fixes a fresh, root-owned
#      │                                   named volume.  It is the real answer
#      │                                   to C5, and it needs CAP_CHOWN.
#      └── gosu user ──► open-terminal run --host 0.0.0.0 --port 8000
#                          │
#                          └─ POST /execute ──► opencode, cwd under $HOME
#
#    Setting `USER 1000` here would break both the chown and the gosu drop.
#    Compose must pair this with:
#        cap_drop: [ALL]
#        cap_add:  [CHOWN, DAC_OVERRIDE, FOWNER, SETUID, SETGID]
#
#  HOME (N7)
#    entrypoint-slim.sh:199 hardcodes `export HOME=/home/user`, which silently
#    overrides any HOME we set.  The per-user volume therefore mounts at
#    /home/user — NOT /workspace.  That is also upstream's documented layout and
#    it keeps openCode's own config/auth on the persistent volume.
# =============================================================================

ARG OPEN_TERMINAL_REF=ghcr.io/open-webui/open-terminal:slim
# Pinned to the version shipped in ghcr.io/anomalyco/opencode at review time.
# Bump deliberately; never float to latest (R4: explicit pinned tag).
ARG OPENCODE_VERSION=1.18.31
# Node is fetched as the official tarball, for the same reason openCode is:
# Debian's `npm` package drags in 377 packages even with
# --no-install-recommends -- including X11 (x11-utils, zutty, libegl1) and a
# SECOND interpreter, python3.13, which Debian's python3-pip would then target
# instead of this image's own 3.12. MEASURED, not assumed.
ARG NODE_VERSION=22.14.0

# ---------------------------------------------------------------- stage 1 ---
FROM ${OPEN_TERMINAL_REF} AS opencode
ARG OPENCODE_VERSION
USER root
ENV HOME=/root
# The installer is bash (uses [[ ]]); under sh/dash its arch detection fails
# with "Unsupported OS/Arch: linux/x86_64".  It honours VERSION= and hardcodes
# INSTALL_DIR=$HOME/.opencode/bin.
RUN set -eux; \
    curl -fsSL https://opencode.ai/install -o /tmp/install.sh; \
    VERSION="${OPENCODE_VERSION}" bash /tmp/install.sh; \
    test -x /root/.opencode/bin/opencode; \
    /root/.opencode/bin/opencode --version

# ---------------------------------------------------------------- stage 1b --
# Node + npm, so the Package Seam (ADR-0008) has an npm to configure. Without
# this NPM_CONFIG_REGISTRY is injected into a runner that has no npm at all.
FROM ${OPEN_TERMINAL_REF} AS node
ARG NODE_VERSION
USER root
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) node_arch=x64 ;; \
      arm64) node_arch=arm64 ;; \
      *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    # .tar.gz, not .tar.xz: this image ships no xz, and tar then fails with
    # "xz: Cannot exec". gzip costs a slightly larger download and no apt.
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.gz" \
      -o /tmp/node.tar.gz; \
    mkdir -p /opt/node; \
    tar -xzf /tmp/node.tar.gz -C /opt/node --strip-components=1; \
    rm /tmp/node.tar.gz; \
    # Drop what a runner never needs: headers, docs, and npm's own man pages.
    rm -rf /opt/node/include /opt/node/share; \
    # npm's shebang is `#!/usr/bin/env node`, so node must be on PATH here or
    # this check dies with "env: 'node': No such file or directory".
    /opt/node/bin/node --version; \
    PATH="/opt/node/bin:$PATH" npm --version

# ---------------------------------------------------------------- stage 2 ---
FROM ${OPEN_TERMINAL_REF} AS runtime
ARG OPENCODE_VERSION
ARG NODE_VERSION

LABEL org.opencontainers.image.title="owui-agent-runner" \
      org.opencontainers.image.description="Per-user ephemeral coding-agent runner (Open Terminal + openCode)" \
      io.owui.runner.opencode-version="${OPENCODE_VERSION}" \
      io.owui.runner.node-version="${NODE_VERSION}"

COPY --from=opencode /root/.opencode/bin/opencode /usr/local/bin/opencode
COPY --from=node /opt/node /opt/node

# pip for the image's OWN python3.12. ensurepip ships in the stdlib, so this
# costs no apt packages and cannot introduce a second interpreter the way
# Debian's python3-pip does. Without it PIP_INDEX_URL is injected into a
# runner whose python has no pip module at all.
RUN set -eux; \
    ln -s /opt/node/bin/node /usr/local/bin/node; \
    ln -s /opt/node/bin/npm  /usr/local/bin/npm; \
    ln -s /opt/node/bin/npx  /usr/local/bin/npx; \
    python3 -m ensurepip --upgrade; \
    python3 -m pip --version; \
    node --version; \
    npm --version

# Q2 / N7 — one user per container, so Open Terminal's own multi-user account
# provisioning is redundant AND impossible here (it shells out to sudo, which
# this image deliberately does not ship).  File browser root stays at `home`,
# which the entrypoint pins to /home/user, which is where the volume mounts.
ENV OPEN_TERMINAL_MULTI_USER=false \
    OPEN_TERMINAL_FILE_BROWSER_ROOT=home
# C6 — containment knobs that already exist upstream.  Defaults only; the
# orchestrator overrides these per-runner at create time from .env.
ENV OPEN_TERMINAL_MAX_SESSIONS=8 \
    OPEN_TERMINAL_EXECUTE_TIMEOUT=120 \
    OPEN_TERMINAL_SESSION_CWD_TTL=604800
# N9 — OPEN_TERMINAL_ALLOWED_DOMAINS is deliberately LEFT UNSET.  Setting it
# (even to "") activates the entrypoint's iptables+dnsmasq firewall, which
# needs CAP_NET_ADMIN that we do not grant.  The `internal: true` network is
# the stronger, capability-free control.
# OPEN_TERMINAL_API_KEY is deliberately NOT set: it is per-runner, derived by
# the orchestrator (N1) and injected at create time.

RUN set -eux; \
    install -d -o user -g user -m 0755 /home/user; \
    opencode --version; \
    node --version; \
    npm --version; \
    python3 -m pip --version

# The base image sets WorkingDir=/app (root-owned).  Without this the agent's
# cwd is /app, so every RELATIVE-path write through /files/write fails with
# "Permission denied: '/app/...'" while absolute paths work — a silent,
# confusing half-broken state.  Caught by the Lane A functional test.
WORKDIR /home/user

# Any HTTP response proves the ASGI app is serving; /system answers 401
# without credentials, which is a perfectly good liveness signal.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/system \
      | grep -qE '^(200|401|403)$' || exit 1

EXPOSE 8000
# Inherit the base entrypoint (tini -> entrypoint-slim.sh) and its `run` cmd.
