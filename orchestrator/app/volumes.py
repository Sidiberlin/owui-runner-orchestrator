"""Per-user workspace volumes.

LANE OWNERSHIP (v1.2 lane correction)
    These are created here, not in docker-compose.yml. Compose cannot
    pre-declare a volume for a user who has not logged in yet — creation is
    lazy and per-user, so it belongs on the spawn path.

MOUNT POINT (N7)
    /home/user, NOT /workspace. The runner entrypoint hardcodes
    HOME=/home/user and would otherwise steer the agent's writes (and
    openCode's own config and auth state) onto the ephemeral layer.

OWNERSHIP (C5/N8)
    A fresh named volume is root:root. We deliberately do NOT chown it here:
    the runner entrypoint does `chown -R user:user $HOME` on every boot, which
    is why the runner needs CAP_CHOWN. Verified by the Lane A persistence test.
"""
from __future__ import annotations

import logging

import aiodocker

from . import labels as L

log = logging.getLogger(__name__)

MOUNT_PATH = "/home/user"


def volume_name(safe_uid: str) -> str:
    return f"runner-ws-{safe_uid}"


async def ensure_volume(
    client: aiodocker.Docker, safe_uid: str, uid: str, version: str,
    network: str = "",
) -> str:
    """Idempotent. Docker's volume create returns the existing volume rather
    than erroring, so this is safe to call on every spawn."""
    name = volume_name(safe_uid)
    await client.volumes.create(
        {
            "Name": name,
            "Labels": {
                L.MANAGED: L.MANAGED_VALUE,
                L.UID: uid,
                L.VERSION: version,
                L.NETWORK: network,
            },
        }
    )
    return name


async def list_workspace_volumes(client: aiodocker.Docker) -> list[dict]:
    data = await client._query_json(
        "volumes", method="GET", params={"filters": f'{{"label":["{L.MANAGED}={L.MANAGED_VALUE}"]}}'}
    )
    return data.get("Volumes") or []


async def remove_volume(client: aiodocker.Docker, name: str) -> None:
    try:
        vol = await client.volumes.get(name)
        await vol.delete()
    except aiodocker.exceptions.DockerError as exc:
        if exc.status not in (404, 409):
            raise
        log.warning("volume %s not removed: %s", name, exc)
