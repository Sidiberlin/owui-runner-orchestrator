# How to entitle users to the terminal connection

Let regular (non-admin) Open WebUI users actually reach the orchestrator.
This is an Open WebUI **connection permission**, not anything in this repo's
code or config — it's easy to configure everything else correctly and still
have every non-admin user hit a 403 because of this one gap. This exact
failure mode blocked the v2.0 QA pass (see the QA report's finding #2) until
it was fixed the way this how-to describes.

## Prerequisites

- The orchestrator connection already added in Open WebUI (see
  [Getting started](../tutorials/getting-started.md) Step 4).
- Open WebUI admin access.

## Why this is needed

A newly-added Open WebUI terminal connection starts **Private with zero
access grants** — Open WebUI's own phrasing is *"No access grants. Private to
you."* Only the admin who created it can use it; every other user's exec
attempt is refused by Open WebUI's own backend (`{"error":"Access
denied"}`) **before the orchestrator ever sees the request**. This is true no
matter how correctly `GROUP_MAP`, roles, or anything else in this repo is
configured — the connection-level grant is a separate, upstream gate that
sits in front of everything this repo does.

Note the field that actually matters: the connection's
**`config.access_grants`** array. An `access_control` object on the same
connection is a different, unrelated field that this build's authorization
check does not read — setting one and not the other looks like it should
work and doesn't.

## Steps

### 1. Decide the entitlement shape

Two reasonable options, and a blanket "Public" grant is deliberately *not*
one of them for most deployments — it hands every OWUI user a runner with no
group distinction at all:

- **A dedicated entitlement group** (recommended): create an OWUI group
  (e.g. `runner-users`), add everyone who should get a runner to it, and
  grant that group access to the connection. This gives you one clean lever
  for "can this person get a runner at all," separate from `GROUP_MAP`,
  which only tunes *which* profile they get once they're in.
- **Grant to an existing group** you already use for something else, if it
  already has the right membership.

### 2. Create the entitlement group (if using option A)

In Open WebUI: **Admin → Users → Groups → Create Group**. Name it something
that reads clearly in an access-grant list, e.g. `runner-users`. Add every
user who should be able to use the terminal feature.

### 3. Grant the group access on the connection

In Open WebUI: **Admin → Settings → Integrations → Open Terminal**, open the
Runner Orchestrator connection, and add the entitlement group to its access
grants (this writes into `config.access_grants`, not `access_control` — see
above). Save.

This takes effect immediately — no orchestrator restart, no redeploy.

### 4. Layer `GROUP_MAP` on top, if you want per-group resource tuning

Access grants decide *whether* someone can get a runner. `GROUP_MAP`
(configured entirely inside this repo — see
[How to create a policy profile](create-a-policy-profile.md)) decides
*what kind* of runner they get once they're entitled. The two are
independent: a user can be in the entitlement group with no `GROUP_MAP`
mapping (gets the `default` profile) or in a `GROUP_MAP`-mapped group
without also being in a broad entitlement group, as long as *some* access
grant on the connection covers them.

## Verification

Sign in as a non-admin user who is (and, separately, one who is *not*) in the
entitled group, and confirm:

- **Entitled user**: the terminal connection is visible, and a chat exec
  attempt succeeds. Check the orchestrator's own logs for their request:

  ```bash
  docker compose logs orchestrator | grep uid=<their-owui-uid>
  ```

  You should see a line like `POST /execute uid=<uid> role=user
  profile=<their-profile> -> runner-<uid>` — proof the request reached the
  orchestrator and was proxied.

- **Non-entitled user**: the connection either doesn't appear, or an exec
  attempt returns Open WebUI's own `{"error":"Access denied"}` — and,
  correctly, **nothing at all shows up in the orchestrator's logs** for that
  attempt, because Open WebUI never forwarded the request. If you see
  nothing in the orchestrator logs for a user who says they're blocked,
  that's expected, not a bug in this repo — the block happened one layer up.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| A user reports "Access denied" and nothing appears in orchestrator logs | Open WebUI's connection-level access grant doesn't cover them (this is the default state for every new connection) | Add their group to the connection's access grants (Step 3) |
| You set `access_control` on the connection and it still doesn't work | Wrong field — this build reads `config.access_grants`, and ignores `access_control` entirely | Use the access-grants UI/field, not access control |
| A user is entitled but gets the `default` profile instead of the one you expected | Entitlement (access grants) and profile selection (`GROUP_MAP`) are independent; being in the entitlement group doesn't automatically map them to a non-default profile | Add their group to `GROUP_MAP` — see [How to create a policy profile](create-a-policy-profile.md) |
| You want one connection to stay admin-only as a fallback | This is a legitimate, deliberate configuration | Leave that connection's access grants empty (its default state) — an empty grant list is exactly "private to admins," which the QA report's final deployment kept intentionally as an admin-only escape hatch |

## Related

- [Getting started](../tutorials/getting-started.md) Step 4, for adding the connection in the first place.
- [How to create a policy profile](create-a-policy-profile.md) for per-group resource tuning once users are entitled.
- `.scratch/owui-runner-rebase-v2/QA-REPORT.md` for the live incident this how-to documents the fix for (findings #2 and the "Post-QA verification" section).
