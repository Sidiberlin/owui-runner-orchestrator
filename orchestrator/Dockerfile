# =============================================================================
#  OWUI Runner Orchestrator — Lane B/C
# =============================================================================
#  Unlike the runner, this image runs as a non-root USER from the start: it
#  needs no capabilities at all (compose gives it cap_drop: ALL). It never sees
#  the raw Docker socket either — all Docker access goes through the socket
#  proxy over TCP (Q3/N2).
# =============================================================================
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# /data holds the workspace-size cache (N4). Compose bind-mounts over it; the
# uid must match so the mount is writable.
RUN useradd --system --uid 10001 --create-home --home-dir /home/orch orch \
 && mkdir -p /data \
 && chown -R orch:orch /srv /data
USER orch

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=4 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/_orch/healthz',timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
