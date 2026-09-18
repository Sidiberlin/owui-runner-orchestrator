# We deploy the full DevGuard platform, not a proxy-only clone

A self-built "DevGuard-lite" proxy consuming the same feed was considered and rejected: it would re-implement registry protocols DevGuard has already solved, and drift from the upstream product. The platform costs ~2 GB RAM and carries auth/UI we barely use — accepted, because the target host has the RAM and policy authority staying with the upstream product is worth it. Self-hosting keeps the dependency proxy inside our network topology; the SaaS would force egress.
