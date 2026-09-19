# 03: Profile parsing, default profile, resolved table at boot

**What to build:** The vocabulary. As an operator, I want to declare a named
**Policy profile** through `POLICY_<NAME>_*` env vars — cpus, memory, idle
timeout, exec timeout, image, egress stance — stating only the fields that
differ from the fleet defaults, and I want to read the fully resolved table in
the boot log rather than re-deriving it from env vars in my head. The default
profile is today's global values verbatim, so "default" and "today" cannot drift
apart. No runner behaviour changes in this slice: profiles exist and are
visible.

**Blocked by:** 02 (Prefactor — group names on the resolved policy)

**Status:** ready-for-agent

- [ ] Profile fields parsed: cpus, memory, idle timeout, exec timeout, image,
      egress stance — using the existing size/duration helpers.
- [ ] Every unset field inherits the corresponding global value; the default
      profile equals today's globals with nothing re-specified.
- [ ] A malformed profile value fails startup loudly (prior art:
      `tests/unit/test_config.py`), never silently defaults.
- [ ] Profile names are case-normalised consistently between env var and mapping
      reference; the chosen rule is documented in the parser's docstring.
- [ ] Boot logs the fully resolved profile table, one line per profile, showing
      effective values after inheritance.
- [ ] Unit tests: inheritance, malformed size, malformed duration, unknown field
      ignored vs. rejected (state which, and why), default-profile identity with
      no `POLICY_*` vars set.
- [ ] No changes to `runner/Dockerfile`, `runner/shims/*`, or
      `THIRD-PARTY-NOTICES.md`.
- [ ] Ticket 01 guard still green; full suite green; committed.
