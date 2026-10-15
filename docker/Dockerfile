# Postgres with the ContractExtraction schema and default configuration baked in.
# The init scripts run only when the data volume is empty (first start, or after `down -v`).
FROM postgres:16.4

COPY schema.sql /docker-entrypoint-initdb.d/01-schema.sql
COPY seed.sql   /docker-entrypoint-initdb.d/02-seed.sql
COPY seed_catalogue.sql /docker-entrypoint-initdb.d/03-seed_catalogue.sql
