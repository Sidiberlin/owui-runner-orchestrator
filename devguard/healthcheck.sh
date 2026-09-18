#!/bin/bash
# Healthy must mean "initdb.sh actually finished", not merely "postgres is
# listening".
#
# History: initdb.sh once aborted outright (it used sed; this image ships no
# sed -- and no grep or awk either, so keep this script to shell builtins +
# psql). The entrypoint carried on, postgres reported healthy, and every
# dependent service started against a database with no kratos role, failing
# much later with an opaque "password authentication failed for user kratos".
#
# The kratos ROLE is checked rather than the kratos DATABASE because upstream's
# initdb.sql creates the database first and the role second -- only the role
# proves the script got past its midpoint.
set -euo pipefail

pg_isready -U "$POSTGRES_USER" >/dev/null

n=$(psql -U "$POSTGRES_USER" -d kratos -tAc "SELECT count(*) FROM pg_roles WHERE rolname='kratos'")
[ "$n" = "1" ]
