"""Behaviours added during the first live OWUI integration (v1.6)."""
import pytest

from app.config import Config
from app.proxy import denied_prefix, harden_served_content, is_denied

DENY = ("/proxy", "/ports", "/api/terminals")


# --- denylist message (N23 fallout) ---------------------------------------
def test_denied_prefix_names_the_actual_entry():
    # The message used path.split('/')[0], so /api/terminals reported "/api".
    assert denied_prefix("/api/terminals", DENY) == "/api/terminals"
    assert denied_prefix("/api/terminals/ws", DENY) == "/api/terminals"
    assert denied_prefix("/proxy/x", DENY) == "/proxy"


def test_denied_prefix_returns_none_when_allowed():
    assert denied_prefix("/files/read", DENY) is None
    assert is_denied("/files/read", DENY) is False


# --- /files/serve hardening (N25) ------------------------------------------
def test_serve_paths_get_sandboxed():
    h = {}
    harden_served_content("/files/serve/home/user/x.html", h, "sandbox")
    assert h["content-security-policy"] == "sandbox"
    assert h["x-content-type-options"] == "nosniff"


def test_serve_prefix_without_leading_slash_also_hardened():
    h = {}
    harden_served_content("files/serve/home/user/x.html", h, "sandbox")
    assert "content-security-policy" in h


@pytest.mark.parametrize("path", [
    "/files/read", "/files/list", "/execute", "/system",
    # must not over-match a path that merely starts with the same text
    "/files/served-by-someone", "/files/serveX",
])
def test_other_paths_are_untouched(path):
    h = {}
    harden_served_content(path, h, "sandbox")
    assert h == {}


def test_empty_csp_disables_hardening():
    h = {}
    harden_served_content("/files/serve/home/user/x.html", h, "")
    assert h == {}


# --- feature advertisement (N24) -------------------------------------------
def _advert(deny):
    from app.main import _advertisement
    cfg = Config(
        orch_api_key="k", master_secret="m", owui_base_url="http://x",
        owui_admin_token="t", role_cache_ttl=60, role_cache_grace=600,
        owui_api_timeout=5.0, runner_image="img", runners_network="net",
        runner_nano_cpus=1, runner_memory=1, runner_pids=1, max_containers=1,
        idle_timeout=1.0, proxy_deny_prefixes=deny,
    )
    return _advertisement(cfg)["features"]


def test_terminal_always_advertised_true_regardless_of_pty_denylist():
    """v2.0 QA finding (2026-09-20): OWUI gates the model's exec/run_command
    tool call on `features.terminal`, not only the interactive PTY pane the
    original (now-reverted) `not is_denied(...)` derivation assumed. Verified
    live: a connection advertising `terminal:false` made every exec attempt
    fail client-side ("Terminal server '<id>' is unavailable") before any
    request reached this orchestrator, silently breaking all of ADR-0012's
    exec-based checks. `terminal` is therefore always advertised True; the PTY
    itself stays blocked independently by the Q5 proxy denylist on
    /api/terminals in `proxy_to_runner()`, whatever this flag says."""
    assert _advert(("/proxy", "/ports", "/api/terminals"))["terminal"] is True
    assert _advert(("/proxy", "/ports"))["terminal"] is True


def test_advertisement_follows_the_denylist():
    assert _advert(("/notebooks",))["notebooks"] is False
    assert _advert(())["system"] is True


# --- cross-stack ownership -------------------------------------------------
def test_build_stamps_the_owning_network():
    from app import labels as L
    lbls = L.build("u1", "n1", "1", "2026-01-01T00:00:00", role="admin",
                   network="owui-runners-internal")
    assert lbls[L.NETWORK] == "owui-runners-internal"
    assert lbls[L.MANAGED] == L.MANAGED_VALUE


def test_owner_label_defaults_empty_so_legacy_is_detectable():
    from app import labels as L
    assert L.build("u1", "n1", "1", "t")[L.NETWORK] == ""
