# Night report — v2.0 group policy profiles

Driven by the night-shift agent chain, one ticket per fresh context, strictly
in order 01→10. Spec: `.scratch/owui-runner-rebase-v2/spec.md`. ADR:
`docs/adr/0012-group-policy-profiles.md`. Tickets:
`.scratch/owui-runner-rebase-v2/issues/`.

Ticket 10 is a STOP POINT — throwaway-stack rehearsal only, no live LXC
(192.168.138.101) cutover. That cutover belongs to Hermes.

**Push note:** GitHub auth (stored credential + `gh` token) is invalid for
Sidiberlin as of this run. Standing rule: push is attempted once per commit;
on failure it is not retried, the commit stays local, and `unpushed: <hash>`
is logged here. Hermes pushes the backlog.

## Log

- **scaffold** `dc995e5` docs(v2): init night report for tickets 01-10 —
  unpushed: dc995e5 (push auth invalid, see note above)
