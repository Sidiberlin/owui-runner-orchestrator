# =============================================================================
#  OWUI Runner Orchestrator — Lane B/C
#  Base: zendis/python3:3.13-main (ticket 12 / D1). Unlike the runner, this
#  image runs as a non-root USER from the start: it needs no capabilities at
#  all (compose gives it cap_drop: ALL). It never sees the raw Docker socket
#  either — all Docker access goes through the socket proxy over TCP (Q3/N2).
#
#  WHY THIS BASE (ticket 12, gated on M0 evidence)
#    zendis/python3 is Nix-built and ships neither a working system pip nor
#    ensurepip (both MEASURED broken — see m0-zends-probe.md). The verified
#    bootstrap is a venv seeded by get-pip.py, not the base's own pip. The
#    default USER is 53111:53111 and $HOME=/home/nonroot is the only writable
#    place outside the venv target — /tmp is NOT writable under this uid.
#    This swap only shipped after uvicorn serve-smoke + aiodocker import +
#    the full test suite passed green inside this exact image (the gate); a
#    failure there means keep python:3.12-slim, not ship it unproven.
# =============================================================================
FROM registry.opencode.de/oci-community/images/zendis/python3:3.13-main@sha256:bcc27cb47133b3863296808b10ec70417d94364bc6b096279f186d81c786cd2e AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/nonroot \
    PATH=/home/nonroot/venv/bin:/usr/bin:/bin

WORKDIR /srv

COPY requirements.txt .
# System pip / ensurepip are broken on this base (M0). python3 -m venv
# --without-pip + get-pip.py is the verified working route. wget is present;
# curl is not (both measured).
#
# Nix-base /etc fix (measured 2026-09-19, live): the ZenDiS base symlinks
# /etc/passwd and /etc/group into /nix/store, which makes runc's exec path
# validation fail ("openat etc/group: path escapes from parent") — killing
# docker exec AND any Docker healthcheck. Replace the symlinks with real
# files (content dereferenced); nss lookups are unaffected by the swap.
USER root
RUN for f in passwd group; do cp -L "/etc/$f" "/etc/$f.real" && rm "/etc/$f" && mv "/etc/$f.real" "/etc/$f"; done
USER 53111:53111

# get-pip.py is unversioned (bootstrap.pypa.io always serves the current
# bootstrapper, unlike a tagged release) - sha256-verify it the same way D2
# required for the opencode installer: a rebuild fails loudly on a checksum
# mismatch instead of silently trusting whatever the URL serves that day.
# Re-pin deliberately when pypa legitimately rotates it.
ARG GET_PIP_SHA256=fb24e693bab954209a063d90953621412ccad4a500905a726286e038f508ddf6
RUN set -eux; \
    python3 -m venv --without-pip /home/nonroot/venv; \
    wget -q https://bootstrap.pypa.io/get-pip.py -O /home/nonroot/get-pip.py; \
    echo "${GET_PIP_SHA256}  /home/nonroot/get-pip.py" | sha256sum -c -; \
    /home/nonroot/venv/bin/python /home/nonroot/get-pip.py; \
    rm /home/nonroot/get-pip.py; \
    /home/nonroot/venv/bin/pip install -r requirements.txt

COPY app ./app

# /data holds the workspace-size cache (N4); compose mounts a named volume
# over it, which inherits this path's ownership. uid 53111 cannot mkdir at
# the filesystem root (measured), so this one step runs as root and then
# drops straight back — nothing else in this image ever runs as root.
USER root
RUN mkdir -p /data && chown -R 53111:53111 /data
USER 53111:53111

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=4 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/_orch/healthz',timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
