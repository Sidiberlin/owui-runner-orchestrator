# 07 — Research: ZenDiS registry shape + open-terminal vendoring facts

Type: research
Status: resolved
Blocked by: —

## Question

What EXACTLY is on the ZenDiS registry for agent-runner bases: the published
tag list per image (python3 / debian / nodejs / base / coreutils / nginx /
postgresql), and — from the open-terminal side — the vendoring facts (package
name/version/Requires-Python) needed to vendor the Open Terminal server onto a
ZenDiS python3 base?

## Answer

**Resolved 2026-09-18 with live measurements** (subagent probes 19:14–19:33 +
this session's own probes; full evidence: `/root/.planning/user-briefs/m0-zends-probe.md`;
an earlier draft of this answer contained unverified claims and was retracted —
everything below is measured).

Registry: anonymous pulls work; confirmed tags include `base:main`,
`coreutils:main`, `debian:13-main-minimal`, `python3:3.13-main`,
`python3:3.13-main-minimal`, `nodejs:24-main`, `nodejs:26-main`.
nginx/postgresql presence: UNMEASURED (needs a tag-list check before any
"move auxiliary images" work).

Capability highlights (uid 53111 everywhere measured; images are NIX-BUILT —
stdlib under /nix/store):

- `python3:3.13-main`: sh, wget, python 3.13.15; NO bash/git/curl/apt/pip;
  `ensurepip` FAILS; **venv + get-pip WORKS** (pip 26.2.1 in venv).
- `python3:3.13-main-minimal`: NO shell at all — unusable as runtime.
- `debian:13-main-minimal`: busybox + sh + wget only; no apt-get.
- `nodejs:24/26-main`: sh, wget, node 24.21.0/26.9.0, npm 11.19.x, corepack;
  no bash/git/curl/pip/python; no /etc/os-release, no ldd.
- `coreutils:main`: BusyBox v1.37.0 multi-call image → direct replacement for
  the `busybox:1.36` compose helpers.

open-terminal vendoring: PyPI package **`open-terminal==0.13.0`**,
`requires_python >=3.11`, top-level module `open-terminal`; **installed
successfully into a venv on zends python 3.13** (get-pip route). Serve-command
shape inside a Nix image: not yet exercised (impl-lane check).
