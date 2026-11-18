FROM nvidia/cuda:13.0.2-cudnn-devel-ubuntu24.04@sha256:ae7f650405a3964972dacfa889273bf8e3fbe9709899afd187da01c4cdff3105

ENV DEBIAN_FRONTEND=noninteractive \
    HF_HUB_DISABLE_TELEMETRY=1 \
    VLLM_NO_USAGE_STATS=1 \
    DO_NOT_TRACK=1 \
    FLASH_ATTENTION_FORCE_BUILD=TRUE \
    TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3.12 python3.12-venv python3.12-dev build-essential \
       openssh-server openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/ssh/ssh_host_* \
    && mkdir -p /run/sshd /opt/colorstats/locks

WORKDIR /opt/colorstats
COPY ops/vlm-trial/requirements-tools.lock locks/tools.lock
COPY ops/vlm-trial/requirements-controller.lock locks/controller.lock
COPY ops/vlm-trial/requirements-sam3.lock locks/sam3.lock

COPY src/colorstats/trial_paths.json src/colorstats/trial_paths.json
RUN python3.12 - <<'PY'
import json
import subprocess
from pathlib import Path

paths = json.loads(Path("src/colorstats/trial_paths.json").read_text())
for executable in ("tools/bin/python", paths["CONTROLLER_PYTHON"], paths["SAM3_PYTHON"]):
    subprocess.run(["python3.12", "-m", "venv", str(Path(executable).parent.parent)], check=True)
subprocess.run(["tools/bin/pip", "install", "--require-hashes", "-r", "locks/tools.lock"], check=True)
for executable, lock in (
    (paths["CONTROLLER_PYTHON"], "locks/controller.lock"),
    (paths["SAM3_PYTHON"], "locks/sam3.lock"),
):
    subprocess.run(
        ["tools/bin/uv", "pip", "install", "--python", executable, "--require-hashes",
         "--require-build-hashes", "--build-constraint", "locks/controller.lock", "-r", lock],
        check=True,
    )
PY

COPY pyproject.toml README.md LICENSE ./
COPY src src
RUN python3.12 - <<'PY'
import json
import os
import subprocess
from pathlib import Path

paths = json.loads(Path("src/colorstats/trial_paths.json").read_text())
environment = {**os.environ, "PYTHONPATH": paths["PYTHONPATH"]}
subprocess.run(
    ["tools/bin/uv", "pip", "install", "--python", paths["CONTROLLER_PYTHON"],
     "--no-deps", "--no-build-isolation", "."],
    check=True,
    env=environment,
)
for executable in (paths["CONTROLLER_PYTHON"], paths["SAM3_PYTHON"]):
    subprocess.run(
        ["tools/bin/uv", "pip", "check", "--python", executable], check=True, env=environment,
    )
PY

COPY ops/vlm-trial/entrypoint.sh /opt/colorstats/entrypoint.sh
RUN chmod 700 /opt/colorstats/entrypoint.sh
EXPOSE 22
ENTRYPOINT ["/opt/colorstats/entrypoint.sh"]
