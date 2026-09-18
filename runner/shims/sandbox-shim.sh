#!/bin/sh
# Sandbox shim (D5/L3, ticket 13). Symlinked as curl, wget and apt-get in
# /usr/local/bin, which is PATH-first and outside the workspace volume, so
# it survives teardown and shadows the real binaries for every session.
#
# HARD RULE: never fake output. An allowlisted internal target always gets
# the real binary's real response, unmodified. Anything else gets a REAL
# failure (or an instant refusal, when SANDBOX_EGRESS says not to bother
# trying) with a short explanation appended to real stderr. Exit 126 on
# every blocked call - never a fake success, never mimicked output.
set -eu

cmd=$(basename "$0")
real="/usr/bin/$cmd"

explain() {
    target=$1
    cat >&2 <<MSG
sandbox: $cmd -> $target blocked (no route outside this runner, by design)
never retry this, never debug DNS, never suggest a proxy/VPN fix
packages: pip/npm work normally via \$PIP_INDEX_URL / \$NPM_CONFIG_REGISTRY
internal services: \$SANDBOX_INTERNAL_SERVICES (env | grep SANDBOX)
MSG
}

if [ ! -x "$real" ]; then
    echo "sandbox: $cmd is not installed in this runner image" >&2
    exit 126
fi

# -- destination extraction (curl/wget only; apt-get has no per-call target
# to gate on at all -- its target IS the outside world, unconditionally) --
target_hostport=""
target_host=""
saw_proxy_flag=0
if [ "$cmd" != "apt-get" ]; then
    for a in "$@"; do
        case "$a" in
            -x | --proxy | -x* | --proxy=*) saw_proxy_flag=1 ;;
        esac
        case "$a" in
            http://* | https://*)
                rest=${a#*://}
                target_hostport=${rest%%/*}
                target_host=${target_hostport%%:*}
                ;;
        esac
    done
fi

# The container talking to ITSELF is not egress at all - this image's own
# HEALTHCHECK calls curl against 127.0.0.1, and that must keep working
# unconditionally, proxy flags included (nothing legitimate proxies a
# loopback call, so this is not an allowlist bypass in practice).
case "$target_host" in
    127.0.0.1 | localhost | ::1 | "[::1]")
        exec "$real" "$@"
        ;;
esac

# -x/--proxy: instant refusal, no attempt, no allowlist exception - routing
# through an arbitrary proxy defeats the whole point of an allowlist.
if [ "$saw_proxy_flag" = "1" ]; then
    explain "${target_hostport:-<proxied target>}"
    exit 126
fi

# An allowlisted internal host:port: the real thing, always, regardless of
# SANDBOX_EGRESS - internal traffic is not egress. Parses the same way the
# env var is documented: cut on `,`, then `=`, keep the `name:port` half.
if [ -n "$target_hostport" ]; then
    old_ifs=$IFS
    IFS=,
    for entry in ${SANDBOX_INTERNAL_SERVICES:-}; do
        if [ "${entry%%=*}" = "$target_hostport" ]; then
            IFS=$old_ifs
            exec "$real" "$@"
        fi
    done
    IFS=$old_ifs
fi

# Everything else is external. Hybrid mode (ticket 04 Q1c):
#   SANDBOX_EGRESS=BLOCKED  -> instant, no network touched.
#   env absent (degraded spawn) -> a real attempt, 2s budget, then wrap a
#                                  real failure. Success passes through
#                                  untouched - honesty in every mode.
if [ "${SANDBOX_EGRESS:-}" = "BLOCKED" ]; then
    explain "${target_hostport:-$*}"
    exit 126
fi

if timeout 2 "$real" "$@"; then
    exit 0
fi
explain "${target_hostport:-$*}"
exit 126
