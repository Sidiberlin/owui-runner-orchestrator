# pip gets a rewriting shim; npm does not need one

DevGuard serves PyPI's simple index exactly as PyPI returns it. Every link in
it points at `files.pythonhosted.org`, which a runner on an `internal: true`
network cannot resolve, and pip follows those links literally. Measured: the
index resolves, then every download dies in DNS. This is not a URL mistake --
it is true of the documented URL, of both trailing-slash spellings, and of
DevGuard's `main` branch, which still has no rewriting in `ProxyPyPISimple`.

npm has the same unrewritten-metadata problem (`dist.tarball` still points at
`registry.npmjs.org`) and works anyway, because npm's own
`replace-registry-host` default rewrites that host onto the configured
registry and lands exactly on DevGuard's tarball route. pip has no equivalent.
So the asymmetry is a client-behaviour difference, not a configuration one,
and only pip needs help.

`pip-shim` is an nginx service on `runners` that proxies to devguard-api and
rewrites index links onto DevGuard's own `pypi/packages/*` route -- a route
that already works and already runs the malicious-package check. It rewrites
both content types pip negotiates: a filter covering only HTML passes a curl
test and still fails pip, because pip asks for
`application/vnd.pypi.simple.v1+json`. That trap cost a debugging cycle and is
why the config names both.

Alternatives rejected: opening egress to `files.pythonhosted.org` destroys the
zero-egress invariant for the one ecosystem most targeted by typosquatting;
forking DevGuard to rewrite the index contradicts ADR-0007, which put policy
authority with the upstream product.

ADR-0006's objection to extra components was that each one's failure could
silently reopen egress. This one cannot: it sits only on `runners`, which is
`internal: true`, so it has no upstream route to leak through, and every
request it serves still passes through devguard-api and its firewall
(verified: a flagged package returns 403 through the shim). If it dies, pip
stops working -- it fails closed, loudly.

This is temporary. It is deleted, along with `PIP_SHIM_BASE_URL` and the pip
default that points at it, as soon as DevGuard rewrites the simple index
itself.
