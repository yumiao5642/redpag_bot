#!/usr/bin/env bash
set -euo pipefail
OUT=chat_sync_bundle.tgz
mkdir -p chat_sync
echo "Commit: $(git rev-parse HEAD)" > chat_sync/GIT_HEAD.txt
echo "Date: $(date -u +'%F %T UTC')" >> chat_sync/GIT_HEAD.txt
find src scripts -type f | sort > chat_sync/file_list.txt
> chat_sync/all_file.txt
while IFS= read -r f; do
  if file "$f" | grep -qi "text"; then
    echo "=== $f ===" >> chat_sync/all_file.txt
    cat "$f" >> chat_sync/all_file.txt
    echo -e "\n" >> chat_sync/all_file.txt
  fi
done < chat_sync/file_list.txt
if [ -f scripts/audit_repo.py ]; then
  python3 scripts/audit_repo.py > chat_sync/audit_report.txt || true
fi
tar czf "$OUT" chat_sync
echo ">> 生成完成：$OUT（请上传到聊天）"
