# 08: Observability — profile on the status surface

**What to build:** The operator's answer to "did my mapping take effect?" As an
operator, I want the status surface to report the resolved profile table and the
profile name of each live runner — adopted runners included — so that I can
confirm a mapping change without exec-ing into anything, and so that incident
analysis checks the strictness a runner actually had rather than assuming global
env. Unknown mapped group names show up here too, not only in the boot log, so a
rename is visible to whoever is looking at the fleet right now.

**Blocked by:** 05 (Spawn integration — resources, image and exec timeout)

**Status:** ready-for-agent

- [ ] Status reports the resolved profile table with effective values.
- [ ] Status reports the profile name per live runner, including
      restart-adopted runners.
- [ ] Unknown mapped group names are surfaced in status, not only in the boot
      log.
- [ ] No secret or token is added to the status payload.
- [ ] With no mapping configured, the added fields report the default profile
      and nothing else changes in the payload's existing fields.
- [ ] Tests assert the response body, never internals.
- [ ] No changes to `runner/Dockerfile`, `runner/shims/*`, or
      `THIRD-PARTY-NOTICES.md`.
- [ ] Ticket 01 guard still green; full suite green; committed.
