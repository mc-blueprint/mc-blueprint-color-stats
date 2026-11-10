#!/bin/bash
# #122と同じ隔離DB検証を、#114のworktreeと専用ポートで実行する。
set -euo pipefail
export COLORSTATS_VERIFY_ISSUE=114
export COLORSTATS_VERIFY_PORT=55114
export COLORSTATS_VERIFY_WORKTREE=/mnt/h/mc-blueprint/worktrees/colorstats-114/mc-blueprint-color-stats
bash <(sed 's/\r$//' "$(dirname "$0")/../issue122/verify.sh") "$@"
