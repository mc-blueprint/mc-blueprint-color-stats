"""日次・週次ダンプの保持世代を決める。"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path, PurePosixPath

_DUMP_NAME = re.compile(r"([A-Za-z0-9_-]+)-(\d{4}-\d{2}-\d{2})\.dump\Z")


def dated_dumps(names: list[str]) -> list[tuple[date, str]]:
    """日付形式が正しいダンプ名だけを日付順で返す。"""
    result = []
    for name in names:
        match = _DUMP_NAME.fullmatch(PurePosixPath(name).name)
        if match:
            try:
                result.append((date.fromisoformat(match.group(2)), name))
            except ValueError:
                continue
    return sorted(result)


def retention_plan(
    names: list[str], daily_generations: int = 7, weekly_generations: int = 4
) -> tuple[set[str], set[str]]:
    """日次と週次の各ディレクトリで保持するダンプ名を返す。"""
    dumps = dated_dumps(names)
    by_database: dict[str, list[tuple[date, str]]] = {}
    for day, name in dumps:
        database = _DUMP_NAME.fullmatch(PurePosixPath(name).name).group(1)
        by_database.setdefault(database, []).append((day, name))

    daily = {
        name
        for database_dumps in by_database.values()
        for _, name in database_dumps[-daily_generations:]
    } if daily_generations else set()

    newest_by_week: dict[tuple[str, int, int], str] = {}
    for day, name in dumps:
        iso = day.isocalendar()
        database = _DUMP_NAME.fullmatch(PurePosixPath(name).name).group(1)
        newest_by_week[(database, iso.year, iso.week)] = name
    by_database_weekly: dict[str, list[str]] = {}
    for (database, _, _), name in newest_by_week.items():
        by_database_weekly.setdefault(database, []).append(name)
    weekly = {
        name
        for database_dumps in by_database_weekly.values()
        for name in database_dumps[-weekly_generations:]
    } if weekly_generations else set()
    return daily, weekly


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--generations", type=int, required=True)
    args = parser.parse_args()

    names = [path.name for path in args.directory.glob("*.dump") if path.is_file()]
    keep, _ = retention_plan(names, daily_generations=args.generations, weekly_generations=0)
    for name in names:
        if name not in keep and _DUMP_NAME.fullmatch(name):
            dump = args.directory / name
            dump.unlink()
            dump.with_suffix(".dump.sha256").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
