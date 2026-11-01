#!/bin/bash
set -euo pipefail

dump="/var/lib/colorstats-backup/colorstats-$(date -u +%F).dump"
cleanup() {
    sudo -u postgres dropdb --if-exists colorstats_restore_check >/dev/null 2>&1 || true
    sudo -u postgres psql -d colorstats -c 'DROP TABLE IF EXISTS public.issue4_restore_probe' >/dev/null 2>&1 || true
    for artifact in /var/lib/colorstats-backup/*-"$(date -u +%F)".dump; do
        [[ -e "$artifact" ]] && sudo rm -f "$artifact" "${artifact}.sha256"
    done
}
trap cleanup EXIT

sudo -u postgres psql -v ON_ERROR_STOP=1 -d colorstats <<'SQL'
DROP TABLE IF EXISTS public.issue4_restore_probe;
CREATE TABLE public.issue4_restore_probe (id integer PRIMARY KEY, payload text NOT NULL);
INSERT INTO public.issue4_restore_probe VALUES
    (1, 'backup-restore-check-alpha'),
    (2, 'backup-restore-check-beta'),
    (3, 'backup-restore-check-gamma');
SQL

source_signature=$(sudo -u postgres psql -Atqc "SELECT count(*) || ':' || md5(string_agg(id::text || ':' || payload, E'\\n' ORDER BY id)) FROM public.issue4_restore_probe" -d colorstats)
KEEP_LOCAL_BACKUP=1 sudo -u postgres env KEEP_LOCAL_BACKUP=1 /usr/local/sbin/colorstats-backup
sha256=$(sudo -u postgres sha256sum "$dump" | cut -d ' ' -f 1)
sudo -u postgres createdb colorstats_restore_check
sudo -u postgres pg_restore --exit-on-error --no-owner --dbname=colorstats_restore_check "$dump"
restored_signature=$(sudo -u postgres psql -Atqc "SELECT count(*) || ':' || md5(string_agg(id::text || ':' || payload, E'\\n' ORDER BY id)) FROM public.issue4_restore_probe" -d colorstats_restore_check)
test "$source_signature" = "$restored_signature"
printf 'source=%s\nrestored=%s\nsha256=%s\n' "$source_signature" "$restored_signature" "$sha256"
