"""本番DBをREAD ONLYで参照し、固定cohortの権利確認済み入力をprivateへ書く。"""

import argparse
from collections import Counter
from pathlib import Path
from uuid import UUID

from bench.issue73.evaluate import digest, read, write
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from colorstats import retention
from colorstats.schema.models import Asset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-config", type=Path, required=True)
    parser.add_argument("--cohorts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cohorts = read(args.cohorts)
    membership = {identifier: cohort for cohort, ids in cohorts.items() for identifier in ids}
    if len(membership) != sum(len(ids) for ids in cohorts.values()):
        raise ValueError("旧新cohortのIDが重複しています")
    engine = create_engine(read(args.database_config)["url"])
    rows, excluded = [], Counter()
    with Session(engine) as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        assets = session.scalars(select(Asset).where(
            Asset.id.in_([UUID(key) for key in membership]))).all()
        if len(assets) != len(membership):
            raise ValueError("固定cohortに存在しないassetがあります")
        for asset in assets:
            try:
                retention.assert_usable(session, asset.id, images=True)
            except PermissionError:
                excluded[membership[str(asset.id)]] += 1
                continue
            rows.append({"asset_id": str(asset.id), "cohort": membership[str(asset.id)],
                         "sha256": asset.sha256, "input_path": asset.storage_path,
                         "license_class": asset.license_class})
    engine.dispose()
    write(args.output, {"cohorts_sha256": digest(args.cohorts), "read_only": True,
                        "excluded_rights": dict(excluded), "assets": rows})
    args.output.chmod(0o600)
    print({"eligible": dict(Counter(row["cohort"] for row in rows)),
           "excluded_rights": dict(excluded), "read_only": True})


if __name__ == "__main__":
    main()
