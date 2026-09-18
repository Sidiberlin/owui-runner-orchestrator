# Upstream report (ready to file): PyPI simple index is served unrewritten

**Repo:** https://github.com/l3montree-dev/devguard
**Affects:** v1.14.0 and `main`
**Status:** filed — [l3montree-dev/devguard#3067](https://github.com/l3montree-dev/devguard/issues/3067) (2026-09-18). Local workaround in the meantime: the `pip-shim` rewrite sidecar (ADR-0010); removal instructions are in `docker-compose.yml` once upstream merges the fix.

---

### Title

Dependency proxy: PyPI simple index is passed through unrewritten, so pip cannot download in an egress-restricted network

### Body

**Summary**

The PyPI dependency proxy serves the upstream simple index verbatim. Every
link in it still points at `files.pythonhosted.org`, so `pip` resolves the
index through DevGuard and then fetches artifacts directly from PyPI's CDN,
bypassing the proxy. In a network where only DevGuard has egress — which is
the deployment the dependency firewall is most useful in — no package can be
installed at all.

npm is unaffected in practice, for a reason worth noting: `dist.tarball` is
likewise served unrewritten and still points at `registry.npmjs.org`, but
npm's own `replace-registry-host` default (`npmjs`) rewrites that host onto
the configured registry, which happens to land exactly on
`/api/v1/dependency-proxy/npm/{package}/-/{path}`. pip has no equivalent
mechanism, so the same passthrough is fatal for Python only.

**Reproduce**

With a self-hosted DevGuard whose dependency proxy is reachable, from a
container that can reach DevGuard but has no other egress:

```
export PIP_INDEX_URL=http://devguard-api:8080/api/v1/dependency-proxy/pypi/simple
export PIP_TRUSTED_HOST=devguard-api
pip install requests
```

Result:

```
Looking in indexes: http://devguard-api:8080/api/v1/dependency-proxy/pypi/simple
Collecting requests
  ERROR: Could not install packages due to an OSError:
  HTTPSConnectionPool(host='files.pythonhosted.org', port=443):
  Max retries exceeded ... Temporary failure in name resolution
```

The index itself is served correctly (HTTP 200), and so is
`/api/v1/dependency-proxy/pypi/packages/...` when requested directly — the
index simply never points at it.

**Cause**

`ProxyPyPISimple` (controllers/dependencyfirewall/python.go) ends with
`pypi.writeResponse(c, data, requestPath, false)`, and `writeResponse` sets
headers only. No URL rewriting happens on either v1.14.0 or `main`.

**Suggested fix**

Rewrite `https://files.pythonhosted.org/packages/` in the simple-index
response to the proxy's own `/api/v1/dependency-proxy/[secret/]pypi/packages/`
prefix, derived from `DEPENDENCY_PROXY_BASE_URL`.

One trap worth building into any fix or its tests: pip content-negotiates
`application/vnd.pypi.simple.v1+json`, not HTML. A rewrite (or a test) that
only handles `text/html` passes a `curl` check and still leaves `pip install`
broken, because the JSON representation goes through unfiltered. That cost us
a debugging cycle when we worked around this locally.

**Workaround, for anyone hitting this**

A reverse proxy in front of the dependency proxy that rewrites that prefix in
both the HTML and JSON representations. Verified working: benign installs
succeed, and flagged packages are still refused with 403 because every request
continues to pass through the dependency proxy.

**Related**

Issue #3022 ("Wrong dependency proxy URLs") is about the documented URLs. This
is a separate problem: the URLs here are correct, and pip still cannot
download.
