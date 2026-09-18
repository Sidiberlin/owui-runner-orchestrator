#!/bin/bash
# Upstream's initdb.sql hardcodes the kratos password
# ('change-me-definitely-when-not-testing'), which does not match the DSN we
# build from DEVGUARD_DB_PASSWORD -- kratos-migrate then loops forever on
# "password authentication failed for user kratos".
#
# Rather than fork their SQL (and drift from it), run it verbatim with only
# the password substituted.
set -e
sed "s|change-me-definitely-when-not-testing|${KRATOS_DB_PASSWORD}|g" \
    /opt/devguard-initdb.sql \
  | psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"
