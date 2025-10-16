#!/usr/bin/env bash
set -euo pipefail
PATCH=${1:-assistant.patch}
test -f "$PATCH" || { echo "缺少补丁文件 $PATCH"; exit 1; }
git checkout -b assistant/local-$(date +%s)
git apply --whitespace=fix "$PATCH"
git add -A
git commit -m "chore: apply assistant patch locally"
git push -u origin HEAD
echo ">> 已推送到远端，建议发起 PR 合并。"
