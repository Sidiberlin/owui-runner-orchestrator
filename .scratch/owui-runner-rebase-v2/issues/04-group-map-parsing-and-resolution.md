# 04: GROUP_MAP parsing and resolution (pure, no spawn change)

**What to build:** The mapping. As an operator, I want one env var —
**GROUP_MAP** as an ordered `groupname:profile` list — to decide which group
selects which profile, with left-to-right priority and first match winning, so
that a user in several groups gets a profile I can predict from the config line
alone. A user in no group, an unmapped group, or a renamed group gets the
default profile; a group name Open WebUI does not know warns loudly at boot so a
rename is found in seconds. Profiles tune, they never gate: no path through
resolution can refuse a request. Resolution is attached to the identity and
logged per request in this slice, but not yet applied to containers — so it is
demoable as three users resolving to three expected profiles while every runner
still spawns identically.

**Blocked by:** 03 (Profile parsing, default profile, resolved table at boot)

**Status:** ready-for-agent

- [ ] `GROUP_MAP="group:profile,..."` parses into an ordered structure; order is
      priority, first match wins.
- [ ] Whitespace, empty entries and duplicate group names handled explicitly;
      the duplicate rule is documented.
- [ ] A mapping entry naming an undeclared profile fails startup.
- [ ] A mapping entry naming a group OWUI does not know warns loudly at boot,
      and the user still resolves to the default profile.
- [ ] No group, unmapped group and renamed group all resolve to default; no
      resolution path can deny a request.
- [ ] Resolution is a pure function unit-tested without Docker or OWUI:
      priority order, multi-group users, empty mapping, unknown group.
- [ ] Integration check that admission is unaffected: a pending or unknown-role
      account in a mapped group is still refused (prior art:
      `tests/integration/test_roles.py`).
- [ ] No changes to `runner/Dockerfile`, `runner/shims/*`, or
      `THIRD-PARTY-NOTICES.md`.
- [ ] Ticket 01 guard still green; full suite green; committed.
