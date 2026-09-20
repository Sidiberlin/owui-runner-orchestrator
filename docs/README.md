# Documentation

Organized by what you're trying to do (the [Diataxis](https://diataxis.fr/)
framework): learning, doing a specific task, looking something up, or
understanding why it works this way.

## Tutorial

- [Getting started](tutorials/getting-started.md) — stand up the stack and run your first command, start to finish.

## How-to guides

- [Deploy on a fresh LXC host](how-to/deploy-on-a-fresh-lxc.md)
- [Create a policy profile](how-to/create-a-policy-profile.md)
- [Entitle users via `runner-users` + access grants](how-to/entitle-users.md)
- [Rotate the OWUI admin key safely](how-to/rotate-owui-admin-key-safely.md)

## Reference

- [Environment variables](reference/environment-variables.md)
- [`/_orch/*` endpoints](reference/orch-endpoints.md)
- [Runner environment (`SANDBOX_*`, Open Terminal knobs)](reference/runner-environment.md)

## Explanation

- [Why runners can't reach the internet, spawn-time binding, and the `terminal:true` incident](explanation/sandbox-and-spawn-time-binding.md)

## Decision records and glossary

- [Architecture Decision Records](adr/) — binding design decisions (0001–0012).
- [`CONTEXT.md`](../CONTEXT.md) — project glossary and preferred terminology.
- [`.scratch/owui-runner-rebase-v2/QA-REPORT.md`](../.scratch/owui-runner-rebase-v2/QA-REPORT.md) — the live-verified QA pass several of the above docs are grounded in.
