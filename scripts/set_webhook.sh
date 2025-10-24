#!/usr/bin/env bash
set -e
source /root/shell/bin/redpag/.env
URL="${PUBLIC_URL%/}${WEBHOOK_PATH}"
echo "SetWebhook => $URL"
curl -sS -X POST "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -F "url=${URL}" \
  -F "secret_token=${WEBHOOK_SECRET}" \
  -F "allowed_updates=[\"message\",\"callback_query\",\"inline_query\",\"chosen_inline_result\",\"pre_checkout_query\",\"shipping_query\"]" \
| jq .
