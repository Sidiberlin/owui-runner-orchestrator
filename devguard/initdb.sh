#!/bin/bash
# Upstream's initdb.sql hardcodes the kratos password
# ('change-me-definitely-when-not-testing'), which does not match the DSN we
# build from DEVGUARD_DB_PASSWORD -- kratos-migrate then loops forever on
# "password authentication failed for user kratos".
#
# Rather than fork their SQL (and drift from it), run it verbatim with only
# the password substituted.
#
# Substitution is bash parameter expansion, NOT sed: this postgres image is
# minimal and ships no sed. The earlier sed version died with
# "sed: command not found", the entrypoint carried on regardless, and postgres
# went healthy with no kratos database at all. Hence the assertions below AND
# the kratos-database check in this service's compose healthcheck -- a silent
# init failure must never again present as a healthy database.
set -euo pipefail

PLACEHOLDER='change-me-definitely-when-not-testing'
SRC=/opt/devguard-initdb.sql

: "${KRATOS_DB_PASSWORD:?initdb: KRATOS_DB_PASSWORD is empty; refusing to create the kratos role with the upstream default password}"

sql=$(<"$SRC")

# If upstream ever renames the placeholder, fail here rather than shipping
# their default password into a live role.
case $sql in
  *"$PLACEHOLDER"*) ;;
  *) echo "initdb: placeholder '$PLACEHOLDER' not found in $SRC -- upstream SQL changed, refusing to guess" >&2
     exit 1 ;;
esac

# printf '%s', not echo: the SQL contains psql backslash commands (\c kratos).
printf '%s' "${sql//"$PLACEHOLDER"/$KRATOS_DB_PASSWORD}" \
  | psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"

echo "initdb: kratos database and role created"
