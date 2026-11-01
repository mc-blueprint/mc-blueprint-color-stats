from datetime import date, timedelta

from colorstats.backup_retention import dated_dumps, main, retention_plan


def names(start: date, count: int) -> list[str]:
    return [f"colorstats-{start + timedelta(days=offset)}.dump" for offset in range(count)]


def test_retains_seven_daily_and_four_latest_weekly_generations() -> None:
    daily, weekly = retention_plan(names(date(2026, 1, 1), 35))

    assert len(daily) == 7
    assert len(weekly) == 4
    assert "colorstats-2026-02-04.dump" in daily


def test_retains_generations_independently_for_each_database() -> None:
    database_names = names(date(2026, 1, 1), 10)
    postgres_names = names(date(2026, 1, 1), 10)
    database_names.extend(name.replace("colorstats-", "postgres-") for name in postgres_names)

    daily, weekly = retention_plan(database_names)

    assert len(daily) == 14
    assert len(weekly) == 4


def test_ignores_invalid_names_and_dates() -> None:
    assert dated_dumps(["notes.txt", "colorstats-2026-02-30.dump"]) == []


def test_zero_generations_keeps_none() -> None:
    assert retention_plan(names(date(2026, 1, 1), 10), 0, 0) == (set(), set())


def test_cli_removes_expired_dumps_and_sidecars_only(tmp_path, monkeypatch) -> None:
    database_names = names(date(2026, 1, 1), 10)
    postgres_names = names(date(2026, 1, 1), 10)
    database_names.extend(name.replace("colorstats-", "postgres-") for name in postgres_names)
    for name in database_names:
        (tmp_path / name).touch()
        (tmp_path / f"{name}.sha256").touch()
    (tmp_path / "notes.txt").touch()
    monkeypatch.setattr("sys.argv", ["retention", str(tmp_path), "--generations", "7"])

    main()

    assert len(list(tmp_path.glob("colorstats-*.dump"))) == 7
    assert len(list(tmp_path.glob("colorstats-*.dump.sha256"))) == 7
    assert len(list(tmp_path.glob("postgres-*.dump"))) == 7
    assert len(list(tmp_path.glob("postgres-*.dump.sha256"))) == 7
    assert (tmp_path / "notes.txt").exists()


def test_archives_and_dumps_retain_independent_generations(tmp_path, monkeypatch) -> None:
    artifacts = names(date(2026, 1, 1), 35)
    artifacts += [name.replace(".dump", ".tar.gz") for name in artifacts]
    for name in artifacts:
        (tmp_path / name).touch()
        (tmp_path / f"{name}.sha256").touch()
    daily, weekly = retention_plan(artifacts)
    assert len(daily) == 14
    assert len(weekly) == 8
    monkeypatch.setattr("sys.argv", ["retention", str(tmp_path), "--generations", "7"])

    main()

    assert {p.name for p in tmp_path.iterdir()} == daily | {f"{n}.sha256" for n in daily}
