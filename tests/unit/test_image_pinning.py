"""R4: every image reference in the stack is pinned - a tag at minimum, a
digest for the zends refs (tickets 11/12). No `latest` anywhere: floating
refs are exactly what let a rebuild drift under an operator without warning.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_IMAGE_LINE = re.compile(r"^\s*image:\s*(\S+)", re.MULTILINE)
_FROM_LINE = re.compile(r"^\s*FROM\s+(\S+)", re.MULTILINE | re.IGNORECASE)


def _refs_from(path: str, pattern: re.Pattern) -> list[str]:
    with open(os.path.join(ROOT, path)) as fh:
        text = fh.read()
    return pattern.findall(text)


def _is_build_stage_alias(ref: str, known_stages: set[str]) -> bool:
    """`FROM base AS runtime` / `FROM ${OPEN_TERMINAL_REF} AS opencode` later
    referenced as `FROM opencode` is a build-stage name, not an image ref."""
    return ref in known_stages


def test_compose_image_refs_are_pinned_and_not_latest():
    refs = _refs_from("docker-compose.yml", _IMAGE_LINE)
    assert refs, "expected at least one image: line in docker-compose.yml"
    for ref in refs:
        assert not ref.endswith(":latest"), f"{ref} floats to :latest"
        assert ":" in ref or "@" in ref, f"{ref} has no tag or digest at all"


def test_zends_refs_are_digest_pinned():
    """The new hardened-base refs (tickets 11/12) are digest-pinned, not
    just tag-pinned - a tag can be repointed upstream, a digest cannot."""
    refs = _refs_from("docker-compose.yml", _IMAGE_LINE)
    zends = [r for r in refs if "oci-community/images/zendis" in r]
    assert zends, "expected the zends coreutils ref introduced by ticket 11"
    for ref in zends:
        assert "@sha256:" in ref, f"{ref} is not digest-pinned"

    orch_from_refs = _refs_from("orchestrator/Dockerfile", _FROM_LINE)
    orch_zends = [r for r in orch_from_refs if "zendis/python3" in r]
    assert orch_zends, "expected the zends python3 FROM line introduced by ticket 12"
    assert "@sha256:" in orch_zends[0]


def test_dockerfile_from_refs_are_pinned_and_not_latest():
    for path, stages in (
        ("runner/Dockerfile", {"node", "runtime"}),
        ("orchestrator/Dockerfile", {"base"}),
    ):
        refs = _refs_from(path, _FROM_LINE)
        assert refs, f"expected at least one FROM line in {path}"
        for ref in refs:
            if _is_build_stage_alias(ref, stages):
                continue
            # ARG-based refs (${OPEN_TERMINAL_REF}) are resolved from their
            # own ARG default line, checked below instead of here.
            if ref.startswith("${"):
                continue
            assert not ref.endswith(":latest"), f"{ref} floats to :latest"
            assert ":" in ref or "@" in ref, f"{ref} has no tag or digest at all"

    with open(os.path.join(ROOT, "runner/Dockerfile")) as fh:
        runner_dockerfile = fh.read()
    m = re.search(r"OPEN_TERMINAL_REF=(\S+)", runner_dockerfile)
    assert m, "expected an OPEN_TERMINAL_REF default ARG"
    assert not m.group(1).endswith(":latest")
    assert ":" in m.group(1)
