from pathlib import PurePosixPath, PureWindowsPath

import pytest
import yaml

from colorstats.store import Storage, temporary_path


@pytest.fixture
def storage(tmp_path):
    config = tmp_path / "storage.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "storage": {
                    "raw": [
                        {"host": "ubuntu-1", "path": "/srv/raw-orico", "uuid": "a", "serial": "A"},
                        {
                            "host": "ubuntu-1",
                            "path": "/srv/raw-suneast",
                            "uuid": "b",
                            "serial": "B",
                        },
                    ],
                    "derived": {"host": "ubuntu-2", "path": "/mnt/data/derived"},
                    "models": {"host": "ubuntu-2", "path": "/mnt/data/models"},
                    "work": {"host": "windows", "path": "H:/MCBlueprintColorStats/work"},
                    "backup": {"host": "ubuntu-0", "path": "/srv/backup"},
                }
            }
        ),
        encoding="utf-8",
    )
    return Storage(config)


@pytest.mark.parametrize("last,root", [("0", "raw-orico"), ("1", "raw-suneast")])
def test_rawの内容アドレスを設定配列に振り分ける(storage, last, root):
    sha = "a" * 63 + last
    result = storage.resolve(f"raw/aa/{sha}.png")
    assert result.host == "ubuntu-1"
    assert result.path == PurePosixPath(f"/srv/{root}/aa/{sha}.png")
    with pytest.raises(ValueError, match="ホスト"):
        result.local_path("windows")


def test_各論理保存先とWindowsパスを解決する(storage):
    for name in ("derived", "models", "backup"):
        assert storage.resolve(f"{name}/result/file").path.name == "file"
    result = storage.resolve("work/result.parquet")
    assert result.path == PureWindowsPath("H:/MCBlueprintColorStats/work/result.parquet")


@pytest.mark.parametrize(
    "path",
    [
        "/raw/a",
        "derived/../a",
        "work/C:/a",
        "work/a\\b",
        "raw/ab/" + "a" * 64 + ".png",
        "raw/aa/not-a-sha.png",
    ],
)
def test_保存先を逸脱するパスと不正な内容アドレスを拒否する(storage, path):
    with pytest.raises(ValueError):
        storage.resolve(path)


def test_一時ファイルは同じディレクトリで試行ごとに分かれる(tmp_path):
    target = tmp_path / "new" / "result"
    first = temporary_path(target, "attempt1")
    second = temporary_path(target, "attempt2")
    assert first != second and first.parent == second.parent == target.parent
    first.write_text("result")
    first.replace(target)
    assert target.read_text() == "result" and second.exists()
