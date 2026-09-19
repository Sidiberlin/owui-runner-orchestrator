"""Config parsing. These run on every operator-supplied string in .env."""
import pytest

from app.config import (
    DEFAULT_EGRESS_STANCE,
    DEFAULT_PROFILE_NAME,
    build_profiles,
    parse_duration,
    parse_size,
)


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


# --- Policy profiles (ADR-0012, ticket 03) ----------------------------------
# The vocabulary: POLICY_<NAME>_<FIELD> env vars parse into named Profile
# bundles, each field inheriting the matching global default when unset.

_DEFAULTS = dict(
    default_nano_cpus=1_500_000_000,
    default_memory=768 * 1024**2,
    default_idle_timeout=1800.0,
    default_exec_timeout=120.0,
    default_image="owui-agent-runner:dev",
    default_egress=DEFAULT_EGRESS_STANCE,
)


def _profiles(**env):
    return build_profiles(**_DEFAULTS, environ=env)


def test_default_profile_identity_with_no_policy_vars_set():
    """The default profile is today's globals verbatim -- nothing
    re-specified -- so a deployment with no POLICY_* vars at all still gets
    exactly one profile, named "default", equal to the passed-in globals."""
    profiles = _profiles()
    assert set(profiles) == {DEFAULT_PROFILE_NAME}
    p = profiles[DEFAULT_PROFILE_NAME]
    assert p.nano_cpus == _DEFAULTS["default_nano_cpus"]
    assert p.memory == _DEFAULTS["default_memory"]
    assert p.idle_timeout == _DEFAULTS["default_idle_timeout"]
    assert p.exec_timeout == _DEFAULTS["default_exec_timeout"]
    assert p.image == _DEFAULTS["default_image"]
    assert p.egress == DEFAULT_EGRESS_STANCE


def test_unset_fields_inherit_the_global_default():
    """A profile that only overrides one field still gets every other field
    from the global default, not from a Profile-level hardcoded default --
    "default" and "today" cannot drift apart."""
    profiles = _profiles(POLICY_HEAVY_CPUS="4")
    heavy = profiles["heavy"]
    assert heavy.nano_cpus == 4_000_000_000
    assert heavy.memory == _DEFAULTS["default_memory"]
    assert heavy.idle_timeout == _DEFAULTS["default_idle_timeout"]
    assert heavy.exec_timeout == _DEFAULTS["default_exec_timeout"]
    assert heavy.image == _DEFAULTS["default_image"]
    assert heavy.egress == DEFAULT_EGRESS_STANCE


def test_a_profile_can_override_every_field():
    profiles = _profiles(
        POLICY_HEAVY_CPUS="4",
        POLICY_HEAVY_MEMORY="4g",
        POLICY_HEAVY_IDLE_TIMEOUT="2h",
        POLICY_HEAVY_EXEC_TIMEOUT="10m",
        POLICY_HEAVY_IMAGE="owui-agent-runner:heavy",
        POLICY_HEAVY_EGRESS="RELAXED",
    )
    heavy = profiles["heavy"]
    assert heavy.nano_cpus == 4_000_000_000
    assert heavy.memory == 4 * 1024**3
    assert heavy.idle_timeout == 7200.0
    assert heavy.exec_timeout == 600.0
    assert heavy.image == "owui-agent-runner:heavy"
    assert heavy.egress == "RELAXED"


@pytest.mark.parametrize("bad", ["", "abc", "10x", "g"])
def test_malformed_profile_size_fails_startup_loudly(bad):
    with pytest.raises(RuntimeError):
        _profiles(POLICY_HEAVY_MEMORY=bad)


@pytest.mark.parametrize("bad", ["", "abc", "10x"])
def test_malformed_profile_duration_fails_startup_loudly(bad):
    with pytest.raises(RuntimeError):
        _profiles(POLICY_HEAVY_IDLE_TIMEOUT=bad)
    with pytest.raises(RuntimeError):
        _profiles(POLICY_HEAVY_EXEC_TIMEOUT=bad)


def test_malformed_profile_cpus_fails_startup_loudly():
    with pytest.raises(RuntimeError):
        _profiles(POLICY_HEAVY_CPUS="not-a-number")


@pytest.mark.parametrize("field", ["IMAGE", "EGRESS"])
def test_explicit_empty_string_field_fails_rather_than_falling_back(field):
    """An explicitly-set-but-blank POLICY_<NAME>_<FIELD> is a config error,
    same as a malformed size or duration -- not a silent fall-back to the
    global default. Falling back would make `POLICY_HEAVY_IMAGE=` (an empty
    override, likely a template artefact) indistinguishable from never
    having set it at all."""
    with pytest.raises(RuntimeError):
        _profiles(**{f"POLICY_HEAVY_{field}": ""})


def test_unknown_field_suffix_is_rejected_not_ignored():
    """POLICY_* is a reserved namespace: an unrecognised suffix (e.g. a
    typo'd POLICY_HEAVY_CPU instead of CPUS) is far more likely to be a
    mistake than an unrelated var, and silently ignoring it would leave the
    profile on the global default with no warning -- exactly the silent-
    default failure mode this module exists to prevent."""
    with pytest.raises(RuntimeError):
        _profiles(POLICY_HEAVY_CPU="4")


def test_profile_names_are_case_normalised_between_declarations():
    """Two POLICY_* vars for the same profile, declared with different name
    casing, still merge into one profile -- the documented case rule is that
    the <NAME> segment is matched case-insensitively and stored lower-cased."""
    profiles = _profiles(POLICY_Heavy_CPUS="4", POLICY_HEAVY_MEMORY="4g")
    assert set(profiles) == {DEFAULT_PROFILE_NAME, "heavy"}
    heavy = profiles["heavy"]
    assert heavy.nano_cpus == 4_000_000_000
    assert heavy.memory == 4 * 1024**3


def test_profile_named_default_is_rejected():
    """POLICY_DEFAULT_* would let the implicit default profile drift away
    from "today's globals verbatim", which defeats the point of a default --
    it is reserved and always a startup error."""
    with pytest.raises(RuntimeError):
        _profiles(POLICY_DEFAULT_CPUS="4")
