# How to rotate the OWUI admin key safely

`OWUI_ADMIN_TOKEN` is what the orchestrator uses to resolve every user's role
and group membership (`GET /api/v1/users/{uid}` against your Open WebUI
instance). If it expires or is revoked without a replacement in place, **role
resolution fails closed and every user gets a 503** — by design, but it looks
exactly like a total outage. This how-to gets you through a rotation without
that gap.

## Prerequisites

- Admin access to your Open WebUI instance.
- Read/write access to `.env` on the orchestrator host.

## Which kind of credential you have

Check whether Open WebUI has API keys enabled:

```bash
T=<your current OWUI_ADMIN_TOKEN>
O=<your OWUI_BASE_URL>
curl -s -X POST -H "Authorization: Bearer $T" "$O/api/v1/auths/api_key"
```

- **`403 {"detail":"API key creation is not allowed in the environment."}`** —
  API keys are disabled on this instance. Your current `OWUI_ADMIN_TOKEN` is
  a **session JWT** (`HS256`, with `exp`/`iat`/`id`/`jti` claims) obtained
  from a sign-in call, not a durable credential — it **will expire**. Go to
  Option 2 below, or switch to Option 1 to stop this from recurring.
- **Anything else (a created key, or a different error)** — API keys are
  available. If `OWUI_ADMIN_TOKEN` already holds a non-expiring API key,
  you're on the durable path already; rotating it is a straightforward
  swap (Option 1, skip the "enable" sub-step).

## Option 1 (preferred): use a non-expiring API key

This removes the expiry problem permanently, so it's worth doing even as a
one-time migration off a JWT.

1. In Open WebUI, enable API key creation for your admin account (Admin
   Settings, or via `ENABLE_API_KEY` on the OWUI deployment itself — this is
   an Open WebUI setting, not something in this repo).
2. Generate a new API key for the service account the orchestrator should
   act as.
3. Update `.env`:
   ```
   OWUI_ADMIN_TOKEN=<new API key>
   ```
4. Continue at "Apply the rotation" below.

## Option 2: refresh the session JWT before it expires

Use this if API keys are disabled and you can't change that policy right
now. You'll need to repeat this before every expiry — check the `exp` claim
periodically (any JWT decoder, or `python3 -c` with `base64`) and put a
reminder in well before it.

1. Sign in as the service account to get a fresh token:
   ```bash
   curl -s -X POST -H 'Content-Type: application/json' \
     -d '{"email":"<service-account-email>","password":"<password>"}' \
     "$O/api/v1/auths/signin"
   ```
2. Take the `.token` field from the response.
3. Update `.env`:
   ```
   OWUI_ADMIN_TOKEN=<new JWT>
   ```
4. Continue at "Apply the rotation" below.

## Apply the rotation

```bash
docker compose up -d orchestrator
```

This is a config-only restart — it does not touch any live runner. Runners
are adopted back by label on the next boot regardless (see
[Explanation](../explanation/sandbox-and-spawn-time-binding.md)), so
in-flight user sessions survive the restart; only *new* role lookups depend
on the credential you just swapped in.

## Verification

```bash
K=$(grep ^ORCH_API_KEY= .env | cut -d= -f2)
curl -s -H "Authorization: Bearer $K" localhost:8080/_orch/status
```

If this returns cleanly (not a 503, and `runners_live` is a sane number),
the new credential is working. To confirm role resolution specifically
rather than just "the process is up," have any user (or yourself) make a
request through Open WebUI and check the orchestrator logs for a clean
`role=` line rather than an OWUI-rejected-token warning:

```bash
docker compose logs orchestrator --since 2m | grep -i 'admin token\|role='
```

A log line reading `OWUI rejected the orchestrator's admin token (401/403).
Check OWUI_ADMIN_TOKEN.` means the new value is wrong — re-check Step 3 of
whichever option you used.

## Why the timing matters (and how much slack you have)

Role lookups are cached for `ROLE_CACHE_TTL` seconds (default 60) per user.
On a *failed* OWUI lookup — including an expired admin token — the
orchestrator serves a stale cached role for up to `ROLE_CACHE_GRACE` seconds
(default 600 = 10 minutes) before it starts refusing with 503. That grace
window is your real safety margin: if you rotate the credential within 10
minutes of the old one failing, users whose role was already cached won't
notice anything. Past that window, every user — cached or not — gets 503
until the new credential is in place. There is no "fail open" path here by
design (a deleted or demoted OWUI account must never keep a runner just
because Open WebUI was briefly unreachable).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Every user suddenly gets 503 | `OWUI_ADMIN_TOKEN` expired or was revoked, and the 10-minute grace window has passed | Rotate immediately using Option 1 or 2 above |
| `403 {"detail":"API key creation is not allowed..."}` when trying to enable Option 1 | `ENABLE_API_KEY` is off in your OWUI deployment | Enable it in OWUI's own settings, or stay on Option 2 |
| New token in `.env` but `/_orch/status` still errors | The orchestrator wasn't restarted, or `.env` has a typo/stray whitespace | Re-run `docker compose up -d orchestrator`; check the raw file for trailing spaces |
| Users report intermittent 503s right after rotation | The old token failed partway through the grace window for some users but not others (their cache entries have different ages) | This resolves itself once every cached entry either refreshes successfully or ages past `ROLE_CACHE_GRACE`; no action needed once the new token is in place |

## Related

- [Reference: environment variables](../reference/environment-variables.md#role-mapper) for `ROLE_CACHE_TTL`, `ROLE_CACHE_GRACE`, and `OWUI_API_TIMEOUT`.
- README.md's "Ops: the admin token expires" section for the original incident this how-to formalizes.
