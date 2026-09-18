"""Config parsing. These run on every operator-supplied string in .env."""
import pytest

from app.config import parse_duration, parse_size


@pytest.mark.parametrize("text,expected", [
    ("1g", 1024**3), ("768m", 768 * 1024**2), ("5G", 5 * 1024**3),
    ("512k", 512 * 1024), ("2gb", 2 * 1024**3), ("1024", 1024),
    ("1.5g", int(1.5 * 1024**3)), (" 320m ", 320 * 1024**2),
])
def test_parse_size(text, expected):
    assert parse_size(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("30m", 1800), ("45s", 45), ("2h", 7200), ("1d", 86400), ("90", 90),
])
def test_parse_duration(text, expected):
    assert parse_duration(text) == expected


@pytest.mark.parametrize("bad", ["", "abc", "10x", "g", "1 2 3"])
def test_bad_values_raise_rather_than_defaulting(bad):
    # Silently defaulting a typo'd limit is how a host ends up unprotected.
    with pytest.raises(ValueError):
        parse_size(bad)


# --- Package Seam resolution (ADR-0008, ADR-0010) --------------------------
# The live fleet test (integration/test_package_seam.py) proves packages
# actually arrive. These are the cheap guards on the wiring that decides where
# they are fetched FROM, each one a mistake this stack actually shipped.

from app import config as config_mod


def _seam(monkeypatch, **env) -> dict:
    for key in ("DEVGUARD_ENABLED", "DEVGUARD_BASE_URL", "PIP_SHIM_BASE_URL",
                "PIP_INDEX_URL", "NPM_CONFIG_REGISTRY", "PIP_TRUSTED_HOST"):
        monkeypatch.delenv(key, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return config_mod._package_seam()


def test_the_seam_is_empty_unless_devguard_is_enabled(monkeypatch):
    """Empty by default is the whole point: no forgotten second path to a
    public registry."""
    seam = _seam(monkeypatch)
    assert seam["pip_index_url"] == ""
    assert seam["npm_registry"] == ""
    assert seam["devguard_enabled"] is False


def test_enabling_devguard_derives_both_urls(monkeypatch):
    seam = _seam(monkeypatch, DEVGUARD_ENABLED="true")
    assert seam["pip_index_url"].endswith("/api/v1/dependency-proxy/pypi/simple")
    assert seam["npm_registry"].endswith("/api/v1/dependency-proxy/npm")


def test_pip_goes_through_the_shim_and_npm_does_not(monkeypatch):
    """ADR-0010. DevGuard serves PyPI's index unrewritten, so pip needs the
    rewriting hop and npm does not. Pointing pip straight at DevGuard leaves
    metadata working while every download dies in DNS -- which is exactly how
    this looked before it was measured."""
    seam = _seam(monkeypatch, DEVGUARD_ENABLED="true",
                 DEVGUARD_BASE_URL="http://dg:8080",
                 PIP_SHIM_BASE_URL="http://shim:8080")
    assert seam["pip_index_url"].startswith("http://shim:8080")
    assert seam["npm_registry"].startswith("http://dg:8080")


def test_pip_trusted_host_follows_the_index_not_devguard(monkeypatch):
    """pip refuses a plain-http index unless the host it CONTACTS is trusted.
    Deriving this from DEVGUARD_BASE_URL silently breaks every install."""
    seam = _seam(monkeypatch, DEVGUARD_ENABLED="true",
                 DEVGUARD_BASE_URL="http://dg:8080",
                 PIP_SHIM_BASE_URL="http://shim:8080")
    assert seam["pip_trusted_host"] == "shim"


def test_explicit_values_always_win(monkeypatch):
    """An operator must be able to point at something other than DevGuard
    without editing code."""
    seam = _seam(monkeypatch, DEVGUARD_ENABLED="true",
                 PIP_INDEX_URL="http://mine/simple",
                 NPM_CONFIG_REGISTRY="http://mine/npm")
    assert seam["pip_index_url"] == "http://mine/simple"
    assert seam["npm_registry"] == "http://mine/npm"
