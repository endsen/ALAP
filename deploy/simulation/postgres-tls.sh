#!/bin/sh
set -eu
cp /run/secrets/postgres.crt "$PGDATA/server.crt"
cp /run/secrets/postgres.key "$PGDATA/server.key"
chmod 600 "$PGDATA/server.key"
cat >> "$PGDATA/postgresql.conf" <<'CONFIG'
ssl = on
ssl_cert_file = 'server.crt'
ssl_key_file = 'server.key'
CONFIG
# The bootstrap local socket remains usable by the image entrypoint. All network
# connections require encrypted transport and SCRAM, including private networks.
cat > "$PGDATA/pg_hba.conf" <<'HBA'
local all all trust
hostssl all all all scram-sha-256
hostnossl all all all reject
HBA
