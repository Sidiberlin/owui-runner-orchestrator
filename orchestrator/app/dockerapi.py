"""aiodocker client factory (Q4) pointed at the socket proxy (Q3).

docker-py is blocking-only and would stall the FastAPI event loop through
image inspect, container create, start and network attach — seconds, not
milliseconds. aiodocker is the asyncio client.

The daemon here reports MinAPIVersion 1.44, so the negotiated version is
pinned explicitly: aiodocker's default is older and gets rejected outright.
"""
from __future__ import annotations

import json
import logging

import aiodocker

log = logging.getLogger(__name__)


def normalise_host(url: str) -> str:
    """aiodocker wants an http:// URL; DOCKER_HOST conventionally says tcp://."""
    if url.startswith("tcp://"):
        return "http://" + url[len("tcp://") :]
    return url


def make_client(docker_host: str, api_version: str) -> aiodocker.Docker:
    return aiodocker.Docker(
        url=normalise_host(docker_host),
        api_version=api_version,
    )


def label_filter(**labels: str) -> str:
    """Docker list filters are a JSON-encoded query param."""
    return json.dumps({"label": [f"{k}={v}" for k, v in labels.items()]})


async def image_exists(client: aiodocker.Docker, ref: str) -> bool:
    """R4: verified at startup so a missing image fails loudly at boot rather
    than inside the first user's request."""
    try:
        await client.images.inspect(ref)
        return True
    except aiodocker.exceptions.DockerError as exc:
        if exc.status == 404:
            return False
        raise
