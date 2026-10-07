#!/bin/sh
set -eu
# Compose file secrets are bind mounts. Copy the private key into a tmpfs with
# correct Linux ownership, including when the host uses Windows ACLs.
install -d -m 0755 /var/lib/postgresql/tls
install -o postgres -g postgres -m 0600 /run/secrets/postgres-server.key /var/lib/postgresql/tls/server.key
install -o postgres -g postgres -m 0644 /run/secrets/postgres-server.crt /var/lib/postgresql/tls/server.crt
exec /usr/local/bin/docker-entrypoint.sh "$@"
