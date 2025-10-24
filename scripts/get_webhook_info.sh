#!/usr/bin/env bash
set -e
source /root/shell/bin/redpag/.env
curl -sS "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo" | jq .
