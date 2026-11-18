"""SAM3専用環境の固定参照と、既存の回収契約への接続を検証する。"""

import copy
import io
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from colorstats import trial_native, trial_native_common, trial_sam3
from colorstats.api_budget import digest
from colorstats.trial_fake import synthetic_plan
from colorstats.trial_inputs import sha
from colorstats.trial_native_common import code_files, environment_reference
from tests.test_trial_runner import drive, runner_for
from tests.test_trial_runner import trial as trial


@pytest.fixture
def worker(tmp_path, monkeypatch):
    directory = tmp_path / "worker"
    directory.mkdir()
    image = Image.new("RGB", (32, 24), "silver")
    image.save(directory / "input.png")
    plan = synthetic_plan(tmp_path / "unused")
    deployment = copy.deepcopy(plan["deployments"]["E"])
    model = directory / "model"
    model.mkdir()
    (model / "synthetic.bin").write_bytes(b"synthetic")
    deployment["model"]["files"] = [{"file": "synthetic.bin", "sha256": sha(b"synthetic")}]
    for key in ("model", "segmenter"):
        deployment[key]["license_confirmed"] = True
    lock = directory / "sam3.lock"
    lock.write_bytes(b"locked")
    deployment["runtime"]["sam3"]["lock"] = {"file": str(lock), "sha256": sha(b"locked")}
    versions = dict(deployment["runtime"]["sam3"]["versions"])
    monkeypatch.setattr(trial_native_common.importlib.metadata, "version", versions.__getitem__)
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            cuda=SimpleNamespace(device_count=lambda: 1, max_memory_reserved=lambda _: 1024 * 1024)
        ),
    )
    mask = np.zeros((24, 32), dtype=bool)
    mask[4:20, 6:26] = True
    monkeypatch.setattr(
        trial_sam3, "sam3", lambda spec, image: ("unsupported", [("wall", [0, 0, 1, 1], mask)])
    )
    spec = {
        **deployment,
        "configuration_id": "E",
        "model_path": str(model),
        "input_sha256": sha((directory / "input.png").read_bytes()),
        "external_deadline": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    return directory, spec


def test_専用workerは同寸法二値PNGと既存phase形式を返す(worker):
    directory, spec = worker
    trial_sam3.run(spec, directory)
    value = json.loads((directory / "sam3-output.json").read_text())
    assert value["scene"] == "unsupported" and value["input_tokens"] == 0
    assert value["peak_vram_mib"] == 1
    record = value["regions"][0]["mask"]
    raw = (directory / record["file"]).read_bytes()
    assert sha(raw) == record["sha256"]
    with Image.open(io.BytesIO(raw)) as image:
        assert image.size == (32, 24)
        assert image.mode == "L" and set(np.unique(image)) == {0, 255}


@pytest.mark.parametrize("kind", ["input", "model", "worker", "lock", "version", "deadline"])
def test_入力重みworker_lock版期限の不一致を推論前に拒否する(worker, kind):
    directory, spec = worker
    if kind == "input":
        spec["input_sha256"] = "0" * 64
    elif kind == "model":
        spec["model"]["files"][0]["sha256"] = "0" * 64
    elif kind == "worker":
        spec["runtime"]["code_files"]["trial_sam3.py"] = "0" * 64
    elif kind == "lock":
        spec["runtime"]["sam3"]["lock"]["sha256"] = "0" * 64
    elif kind == "version":
        spec["runtime"]["sam3"]["versions"]["numpy"] = "2.0.0"
    else:
        spec["external_deadline"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError):
        trial_sam3.run(spec, directory)
    assert not (directory / "sam3-output.json").exists()
    assert not list(directory.glob("mask-*.png"))


def test_推論中に短縮された期限を保存前に再確認する(worker, monkeypatch):
    directory, spec = worker
    original = trial_sam3.sam3

    def shorten(spec, image):
        (directory / "deadline.json").write_text(
            json.dumps(
                {"external_deadline": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}
            )
        )
        return original(spec, image)

    monkeypatch.setattr(trial_sam3, "sam3", shorten)
    with pytest.raises(ValueError, match="期限"):
        trial_sam3.run(spec, directory)
    assert not list(directory.glob("mask-*.png"))


@pytest.mark.parametrize("code", ["oom", "invalid_output"])
def test_worker例外は既存分類だけを残して成功出力を作らない(worker, monkeypatch, code):
    directory, spec = worker
    (directory / "request.json").write_text(json.dumps(spec))
    error = type("OutOfMemoryError", (RuntimeError,), {}) if code == "oom" else RuntimeError

    def fail(*args):
        raise error("private detail")

    monkeypatch.setattr(trial_sam3, "sam3", fail)
    monkeypatch.setattr(sys, "argv", ["worker", "--directory", str(directory)])
    with pytest.raises(SystemExit) as result:
        trial_sam3.main()
    assert result.value.code == 1
    assert json.loads((directory / "failure.json").read_text()) == {"reason_code": code}
    assert not (directory / "sam3-output.json").exists()


def test_workerのimportは通常アプリやDB依存を要求しない():
    script = """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.startswith(('sqlalchemy', 'colour', 'cv2', 'vllm', 'colorstats.trial_inputs')):
        raise AssertionError(name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import colorstats.trial_sam3
"""
    subprocess.run([sys.executable, "-c", script], check=True)


@pytest.mark.parametrize("field", ["code", "lock", "versions"])
def test_E環境の変更を再開時に拒否する(trial, field):
    runner = runner_for(trial)
    runner.tick()
    plan = trial[1]
    runtime = plan["deployments"]["E"]["runtime"]
    if field == "code":
        runtime["code_files"]["trial_sam3.py"] = "0" * 64
    elif field == "lock":
        runtime["sam3"]["lock"]["sha256"] = "0" * 64
    else:
        runtime["sam3"]["versions"]["Pillow"] = "12.0.0"
    plan["configurations"]["E"]["environment_sha256"] = digest(
        environment_reference(plan["deployments"]["E"]["versions"], runtime)
    )
    with pytest.raises(ValueError):
        runner_for(trial)


def test_E専用workerの実出力が150結果の受領と比較ページへ接続する(trial, worker):
    directory, spec = worker
    backend = trial[2]
    original = backend.submit

    def submit(pod, resource, image, content, request):
        original(pod, resource, image, content, request)
        if resource["configuration_id"] != "E":
            return
        # 同じworkerを合成画像で通し、推論部分だけをfixtureで差し替える。
        work = directory / image["trial_id"]
        work.mkdir()
        (work / "input.png").write_bytes(content)
        current = {**spec, "input_sha256": sha(content)}
        with Image.open(io.BytesIO(content)) as photo:
            mask = np.ones((photo.height, photo.width), dtype=bool)
        original_inference = trial_sam3.sam3
        try:
            trial_sam3.sam3 = lambda s, p: ("unsupported", [("wall", [0, 0, 1, 1], mask)])
            trial_sam3.run(current, work)
        finally:
            trial_sam3.sam3 = original_inference
        phase = json.loads((work / "sam3-output.json").read_text())
        value, _ = backend.jobs[(resource["attempt"], image["trial_id"])]
        value.update(
            {k: phase[k] for k in ["scene", "regions", "peak_vram_mib", "elapsed_seconds"]}
        )
        blobs = {
            r["mask"]["file"]: (work / r["mask"]["file"]).read_bytes() for r in phase["regions"]
        }
        backend.jobs[(resource["attempt"], image["trial_id"])] = value, blobs
        assert request["runtime"]["code_files"] == code_files()
        assert request["runtime"]["sam3"]["python"] == trial_native_common.SAM3_PYTHON

    backend.submit = submit
    runner = runner_for(trial)
    assert drive(runner) == "complete"
    assert len(runner.state["results"]) == 150
    assert len(json.loads((trial[0] / "number-map.json").read_text())["rows"]) == 30
    assert not backend.pods


@pytest.mark.parametrize("name,configuration", [("sam3", "E"), ("qwen", "A")])
def test_両環境は絶対Pythonとコードパスで同じプロセス群に起動する(
    monkeypatch, tmp_path, name, configuration
):
    calls = []

    def execute(argv, **kwargs):
        if argv[0] == "nvidia-smi":
            return SimpleNamespace(stdout=b"1000,48000\n")
        calls.append((argv, kwargs))
        return SimpleNamespace()

    monkeypatch.setattr(trial_native.subprocess, "run", execute)
    spec = {
        "gpu_count": 1,
        "configuration_id": configuration,
        "image_timeout_seconds": 120,
        "external_deadline": (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
    }
    trial_native.run_phases(spec, tmp_path, [name])
    argv, options = calls[0]
    executable = (
        trial_native_common.SAM3_PYTHON if name == "sam3" else trial_native_common.CONTROLLER_PYTHON
    )
    module = "colorstats.trial_sam3" if name == "sam3" else "colorstats.trial_native"
    assert argv[:5] == [
        "/usr/bin/env",
        f"PYTHONPATH={trial_native_common.CODE_PATH}",
        executable,
        "-m",
        module,
    ]
    assert 0 < options["timeout"] <= 30
    assert not options.get("start_new_session", False)


@pytest.mark.parametrize("reason", ["oom", "invalid_output", "timeout", "expired"])
def test_E失敗時は並列Dを含む全新設Podを終了する(trial, reason):
    trial[1]["concurrency"] = 2
    backend = trial[2]
    original = backend.collect

    def collect(pod, resource, trial_id):
        response = original(pod, resource, trial_id)
        if resource["configuration_id"] == "E" and response is not None:
            value, _ = response
            value.update(status="failed", reason_code=reason, regions=[])
            return value, {}
        return response

    backend.collect = collect
    runner = runner_for(trial)
    assert drive(runner) == "stopped"
    assert runner.state["stop_reason"] == "native_failed"
    assert all(r["status"] == "closed" for r in runner.state["resources"])
    assert not backend.pods
    assert any(
        r["configuration_id"] == "E" and r["status"] == "failed" for r in runner.state["results"]
    )


def test_Dockerの環境作成と検査も共通パスを使用する(tmp_path, monkeypatch):
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    docker = (root / "ops/vlm-trial/Dockerfile").read_text()
    paths_text = (root / "src/colorstats/trial_paths.json").read_text()
    paths = json.loads(paths_text)
    config = tmp_path / "src/colorstats/trial_paths.json"
    config.parent.mkdir(parents=True)
    config.write_text(paths_text)
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subprocess, "run", run)
    scripts = re.findall(r"RUN python3.12 - <<'PY'\n(.*?)\nPY", docker, re.S)
    assert len(scripts) == 2
    for script in scripts:
        exec(compile(script, "Dockerfile", "exec"), {})
    for key in ("CONTROLLER_PYTHON", "SAM3_PYTHON"):
        executable = paths[key]
        assert Path(executable).is_absolute()
        assert any(
            argv[:3] == ["python3.12", "-m", "venv"]
            and argv[3] == str(Path(executable).parent.parent)
            for argv, _ in calls
        )
        assert any(
            "--python" in argv and executable in argv and argv[1:3] == ["pip", "install"]
            for argv, _ in calls
        )
        assert any(
            argv[-2:] == ["--python", executable]
            and kwargs["env"]["PYTHONPATH"] == paths["PYTHONPATH"]
            for argv, kwargs in calls
            if argv[1:3] == ["pip", "check"]
        )
        assert executable not in docker


def test_独立期限監視にも絶対Pythonとコードパスを渡す(tmp_path, monkeypatch):
    from colorstats.trial_native_common import CODE_PATH, CONTROLLER_PYTHON

    Image.new("RGB", (16, 16), "silver").save(tmp_path / "input.png")
    spec = {
        "configuration_id": "E",
        "external_deadline": datetime.now(UTC).isoformat(),
        "attempt": "E_new",
        "trial_id": "T001",
        "contract": {},
    }
    (tmp_path / "request.json").write_text(json.dumps(spec))
    calls = []

    def unavailable(*args):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(trial_native.os, "getpgrp", lambda: 123)
    monkeypatch.setattr(trial_native.os, "getpid", lambda: 123)
    monkeypatch.setattr(
        trial_native.subprocess, "Popen", lambda argv, **kwargs: calls.append((argv, kwargs))
    )
    monkeypatch.setattr(trial_native, "environment", lambda spec: None)
    monkeypatch.setattr(trial_native, "run_phases", unavailable)
    monkeypatch.setattr(sys, "argv", ["native", "--directory", str(tmp_path)])
    trial_native.main()
    argv, kwargs = calls[0]
    assert argv[:5] == [
        "/usr/bin/env",
        f"PYTHONPATH={CODE_PATH}",
        CONTROLLER_PYTHON,
        "-m",
        "colorstats.trial_native",
    ]
    assert "--expire-only" in argv and kwargs["start_new_session"] is True
