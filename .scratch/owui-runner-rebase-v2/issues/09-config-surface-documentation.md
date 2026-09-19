# 09: Config surface documentation

**What to build:** The convention, documented in the repo's existing style. As
an operator, I want every new var documented in the env example and a README
section that explains what a **Policy profile** is, how **Groups (OWUI)** select
one through **GROUP_MAP**, the first-match rule, default-equals-today, and the
group-rename caveat — with a worked two-profile example and the boot-log table it
produces — so that the convention is discoverable without reading the source.
The existing doc-drift guard is extended so the documentation cannot silently
diverge from what the parser actually accepts.

**Blocked by:** 03 (Profile parsing) — content complete after 08 (status surface)

**Status:** ready-for-agent

- [ ] `.env.example` documents `GROUP_MAP` and the full `POLICY_<NAME>_*` block
      in the file's existing one-comment-per-var style.
- [ ] README gains a profiles section: what a profile is, how groups select one,
      first-match priority, default-equals-today, the group-rename caveat, and a
      worked two-profile example with its boot-log output.
- [ ] Glossary terms are used exactly as `CONTEXT.md` defines them: Policy
      profile, GROUP_MAP, Groups (OWUI).
- [ ] The env-documentation drift guard is extended to cover the profile
      convention (prior art: `tests/unit/test_readme_env_docs.py`).
- [ ] `tests/README.md` table lists the new tests and the findings they guard.
- [ ] No changes to `runner/Dockerfile`, `runner/shims/*`, or
      `THIRD-PARTY-NOTICES.md`.
- [ ] Ticket 01 guard still green; full suite green; committed.
