# Package policy is a maintained blocklist, not a curated allowlist

DevGuard consumes the OpenSSF Malicious Packages feed upstream and continuously — professional policy maintenance we would otherwise have to fake with a hand-curated allowlist. An allowlist is stricter against a fully hostile agent, but on a solo deployment it dies of 403-fatigue and gets bypassed; an always-on maintained blocklist never gets switched off. Curated allowlisting remains a documented v2 escalation layered in front of DevGuard if the threat model ever demands it.
