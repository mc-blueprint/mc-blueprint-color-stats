#!/bin/bash
set -euo pipefail

data_dir=/mnt/data/postgres
source_dir=/var/lib/postgresql/16/main
config_dir=/etc/postgresql/16/main

mountpoint -q /mnt/data
test -d "$source_dir"
sudo systemctl stop postgresql
sudo install -d -o postgres -g postgres -m 700 "$data_dir"
if ! sudo test -e "$data_dir/PG_VERSION"; then
    sudo rsync -aHAX --numeric-ids "$source_dir/" "$data_dir/"
fi
sudo pg_conftool 16 main set data_directory "$data_dir"
sudo pg_conftool 16 main set listen_addresses '*'
sudo pg_conftool 16 main set password_encryption scram-sha-256

hba="$config_dir/pg_hba.conf"
rule='host colorstats colorstats 192.168.1.0/24 scram-sha-256'
if ! sudo grep -Fqx "$rule" "$hba"; then
    printf '%s\n' "$rule" | sudo tee -a "$hba" >/dev/null
fi

sudo systemctl start postgresql
sudo -u postgres psql -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'colorstats') THEN
        CREATE ROLE colorstats LOGIN;
    END IF;
END
$$;
SQL

password_file=/var/lib/postgresql/colorstats-password
if ! sudo test -s "$password_file"; then
    sudo -u postgres sh -c 'umask 077; openssl rand -hex 32 > /var/lib/postgresql/colorstats-password'
fi
sudo chown postgres:postgres "$password_file"
sudo chmod 600 "$password_file"
password=$(sudo cat "$password_file")
sql_file=$(mktemp)
trap 'sudo rm -f "$sql_file"' EXIT
chmod 600 "$sql_file"
printf "ALTER ROLE colorstats WITH LOGIN PASSWORD '%s';\n" "$password" >"$sql_file"
sudo chown postgres:postgres "$sql_file"
sudo -u postgres psql -v ON_ERROR_STOP=1 -f "$sql_file"
sudo rm -f "$sql_file"
trap - EXIT

if ! sudo -u postgres psql -Atqc "SELECT 1 FROM pg_database WHERE datname = 'colorstats'" | grep -qx 1; then
    sudo -u postgres createdb --owner=colorstats colorstats
fi
pgpass_tmp=$(mktemp)
trap 'rm -f "$pgpass_tmp"' EXIT
chmod 600 "$pgpass_tmp"
printf '192.168.1.86:5432:colorstats:colorstats:%s\n' "$password" >"$pgpass_tmp"
sudo chown postgres:postgres "$pgpass_tmp"
sudo mv "$pgpass_tmp" /var/lib/postgresql/.pgpass
trap - EXIT
sudo systemctl restart postgresql
sudo -u postgres psql -Atqc 'show data_directory; show listen_addresses;'
pg_isready -h 192.168.1.86
sudo -u postgres env PGPASSFILE=/var/lib/postgresql/.pgpass psql -h 192.168.1.86 -U colorstats -d colorstats -Atqc 'select current_user, current_database();'
