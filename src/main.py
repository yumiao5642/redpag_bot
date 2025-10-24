import asyncio
import json
import httpx
import re
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, InlineQueryHandler,
    filters, TypeHandler, ChosenInlineResultHandler   # ← 新增 ChosenInlineResultHandler
)
from telegram import BotCommand, BotCommandScopeDefault, Update
from telegram.request import HTTPXRequest
from .config import (
    BOT_TOKEN,
    TELEGRAM_CONNECT_TIMEOUT, TELEGRAM_READ_TIMEOUT, TELEGRAM_WRITE_TIMEOUT, TELEGRAM_POOL_TIMEOUT, TELEGRAM_PROXY,
    USDT_CONTRACT, AGGREGATE_ADDRESS,
    WEBHOOK_MODE, WEBHOOK_HOST, WEBHOOK_PORT, WEBHOOK_URL_PATH, WEBHOOK_URL_FULL, WEBHOOK_SECRET, ALLOWED_UPDATES
)

from .db import init_pool, close_pool
from datetime import datetime
from .handlers import start as h_start
from .handlers import wallet as h_wallet
from .handlers import red_packet as h_rp
from .handlers import recharge as h_recharge
from .handlers import withdraw as h_withdraw
from .handlers import ledger as h_ledger
from .handlers import address_book as h_addrbook
from .handlers import fx as h_fx
from .handlers import addr_query as h_addrquery
from .handlers import support as h_support
from .handlers import password as h_password
from .handlers import common as h_common
from .logger import app_logger

import asyncio, sys


def _mask(s: str, keep_tail: int = 4) -> str:
    if not s:
        return ""
    tail = s[-keep_tail:] if len(s) >= keep_tail else s
    return f"<len={len(s)}>***{tail}"

async def _probe_url(url: str) -> dict:
    """启动时探测一下公网 URL（GET 一下，Webhook 端口返回 405 也算正常）"""
    out = {"ok": False, "status": None, "detail": ""}
    try:
        timeout = httpx.Timeout(10.0, connect=10.0, read=10.0)
        async with httpx.AsyncClient(timeout=timeout, verify=True) as client:
            r = await client.get(url)
            out["status"] = r.status_code
            out["ok"] = True
            out["detail"] = (r.text or "")[:200]
    except Exception as e:
        out["detail"] = str(e)
    return out

# 1) 文件顶部已有 from datetime import datetime

def _json_default(o):
    if isinstance(o, datetime):
        return o.isoformat()
    try:
        return str(o)
    except Exception:
        return "<non-serializable>"

async def _log_startup_config(app):
    me = await app.bot.get_me()
    wh = await app.bot.get_webhook_info()
    probe = await _probe_url(WEBHOOK_URL_FULL) if (WEBHOOK_MODE == "webhook" and WEBHOOK_URL_FULL.startswith("https://")) else {"ok": False}

    cfg = {
        "mode": WEBHOOK_MODE,
        "bot": {"id": me.id, "username": f"@{me.username}"},
        "webhook_local": {"listen": f"{WEBHOOK_HOST}:{WEBHOOK_PORT}", "url_path": f"/{WEBHOOK_URL_PATH}"},
        "webhook_public": {
            "full_url": WEBHOOK_URL_FULL,
            "secret_token_tail": WEBHOOK_SECRET[-4:] if WEBHOOK_SECRET else "",
            "secret_len": len(WEBHOOK_SECRET or ""),
        },
        "telegram_webhook_info": {
            "url": wh.url,
            "has_cert": wh.has_custom_certificate,
            "pending": wh.pending_update_count,
            "ip_address": getattr(wh, "ip_address", None),
            "allowed_updates": wh.allowed_updates,
            "last_error_date": (getattr(wh, "last_error_date", None).isoformat()
                                if isinstance(getattr(wh, "last_error_date", None), datetime)
                                else getattr(wh, "last_error_date", None)),
            "last_error_message": getattr(wh, "last_error_message", None),
            "max_connections": getattr(wh, "max_connections", None),
        },
        "allowed_updates_local": ALLOWED_UPDATES,
        "timeouts": {
            "connect": TELEGRAM_CONNECT_TIMEOUT,
            "read": TELEGRAM_READ_TIMEOUT,
            "write": TELEGRAM_WRITE_TIMEOUT,
            "pool": TELEGRAM_POOL_TIMEOUT,
        },
        "proxy": TELEGRAM_PROXY or "",
        "token_masked": _mask(BOT_TOKEN),
        "aggregate_addr": AGGREGATE_ADDRESS,
        "usdt_contract_hint": (USDT_CONTRACT[:6] + "..." + USDT_CONTRACT[-6:]) if USDT_CONTRACT else "",
        "public_url_probe": probe,
    }

    mismatch = (WEBHOOK_MODE == "webhook" and (wh.url or "") != WEBHOOK_URL_FULL)
    if mismatch:
        app_logger.error("❌ Webhook URL 不一致：Telegram=%s  Local=%s", wh.url, WEBHOOK_URL_FULL)
    if WEBHOOK_MODE == "webhook" and probe and isinstance(probe.get("status"), int) and probe["status"] == 404:
        app_logger.error("❌ 公网 URL 探测返回 404：Cloudflare/反向代理未转发到 /%s（或路径被改写）", WEBHOOK_URL_PATH)

    app_logger.info("🔧 Startup config dump:\n%s", json.dumps(cfg, ensure_ascii=False, indent=2, default=_json_default))

# 便捷健康检查命令
async def ping(update, context):
    await update.message.reply_text("pong")

async def diag(update, context):
    wh = await context.bot.get_webhook_info()
    txt = [
        f"mode = {WEBHOOK_MODE}",
        f"listen = {WEBHOOK_HOST}:{WEBHOOK_PORT}",
        f"url_path = /{WEBHOOK_URL_PATH}",
        f"public = {WEBHOOK_URL_FULL}",
        f"wh.url = {wh.url}",
        f"allowed_updates(local) = {ALLOWED_UPDATES}",
        f"allowed_updates(tg) = {wh.allowed_updates}",
        f"last_error = {getattr(wh, 'last_error_message', None)}",
        f"pending = {wh.pending_update_count}",
        f"secret.len = {len(WEBHOOK_SECRET or '')}",
    ]
    await update.message.reply_text("\n".join(txt))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

async def _tap(update: Update, context):
    try:
        app_logger.info("⬅️ incoming update keys: %s", list(update.to_dict().keys()))
    except Exception:
        pass

async def on_error(update, context):
    app_logger.exception("🔥 Handler error: %s | update=%s", context.error, getattr(update, "to_dict", lambda: update)())


async def on_text_router(update, context):
    await h_common.autoclean_on_new_action(update, context)

    text = (update.message.text or "").strip()
    if text in ("/start", "start"):
        return await h_start.start(update, context)

    # 通用：用户直接输入“取消/退出/cancel”也能取消任何输入流程
    if text in ("取消", "cancel", "退出"):
        h_common.clear_user_flow_flags(context)
        return await h_start.start(update, context)

    # 主菜单入口（兼容老文案）
    if text.startswith("💰 我的钱包") or text.startswith("一、我的钱包"):
        return await h_wallet.show_wallet(update, context)
    if text.startswith("💱 汇率查询") or text.startswith("二、汇率查询"):
        return await h_fx.show_fx(update, context)
    if text.startswith("🧭 地址查询") or text.startswith("三、地址查询"):
        return await h_addrquery.addr_query(update, context)
    if text.startswith("🆘 联系客服") or text.startswith("四、联系客服"):
        return await h_support.show_support(update, context)
    if text.startswith("🔐 设置密码") or text.startswith("五、设置密码"):
        return await h_password.set_password(update, context)

    # 钱包子菜单（兼容老文案）
    if text.startswith("🧧 红包") or text.startswith("1、红包"):
        return await h_rp.show_red_packets(update, context)
    if text.startswith("➕ 充值") or text.startswith("2、充值"):
        return await h_recharge.show_recharge(update, context)
    if text.startswith("💸 提现") or text.startswith("3、提现"):
        return await h_withdraw.show_withdraw(update, context)
    if text.startswith("📒 资金明细") or text.startswith("4、资金明细"):
        return await h_ledger.show_ledger(update, context)
    if text.startswith("📎 常用地址") or text.startswith("5、常用地址"):
        return await h_addrbook.address_entry(update, context)
    if text.startswith("⬅️ 返回主菜单") or text.startswith("返回主菜单"):
        return await h_start.start(update, context)
    if text.startswith("🔐 密码管理"):
        return await h_password.set_password(update, context)

    # 其他输入流（只路由到需要的 on_text）
    await h_rp.on_user_text(update, context)
    await h_password.on_text(update, context)
    await h_addrquery.on_text(update, context)
    await h_addrbook.on_text(update, context)   # 常用地址添加/删除输入
    await h_withdraw.on_text(update, context)   # 提现页添加地址/金额输入

from .services.tron import is_valid_address
async def _startup(app):
    await init_pool()
    # === 启动自检：避免把 ERC20/EVM 地址错配到 TRON ===
    if not is_valid_address(AGGREGATE_ADDRESS):
        app_logger.error("AGGREGATE_ADDRESS=%s 不是有效的 TRON 地址（应以 T 开头，34 位）。请检查 .env（USDT-TRC20）", AGGREGATE_ADDRESS)
        raise RuntimeError("Invalid AGGREGATE_ADDRESS for TRON/USDT-TRC20")
    # 合约主网常见值：TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj（仅提醒，不强制）
    if len(USDT_CONTRACT) < 34:
        app_logger.warning("USDT_CONTRACT 看起来不标准（Tron 主网 USDT 示例：TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj）。当前：%s", USDT_CONTRACT)



    await app.bot.set_my_commands(
        [
            BotCommand("start", "开始 / 主菜单"),
            BotCommand("wallet", "我的钱包"),
            BotCommand("recharge", "充值"),
            BotCommand("withdraw", "提现"),
            BotCommand("records", "资金明细"),
            BotCommand("addr", "地址查询"),
            BotCommand("support", "联系客服"),
            BotCommand("password", "设置/修改交易密码"),
        ],
        scope=BotCommandScopeDefault(),
    )
    await _log_startup_config(app)
    app_logger.info("🚀 机器人已启动，等待消息...")

async def _shutdown(app):
    await close_pool()
    app_logger.info("🛑 机器人已关闭。")

def build_app():
    req_kwargs = {
        "connect_timeout": TELEGRAM_CONNECT_TIMEOUT,
        "read_timeout": TELEGRAM_READ_TIMEOUT,
        "write_timeout": TELEGRAM_WRITE_TIMEOUT,
        "pool_timeout": TELEGRAM_POOL_TIMEOUT,
    }
    if TELEGRAM_PROXY:
        req_kwargs["proxy_url"] = TELEGRAM_PROXY
    request = HTTPXRequest(**req_kwargs)

    app = ApplicationBuilder().token(BOT_TOKEN).request(request).build()

    # 诊断命令
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("diag", diag))
    # ……这里保留你现有的 handler 注册……
    # Commands
    app.add_handler(CommandHandler("start", h_start.start))
    app.add_handler(CommandHandler("wallet", h_wallet.show_wallet))
    app.add_handler(CommandHandler("recharge", h_recharge.show_recharge))
    app.add_handler(CommandHandler("withdraw", h_withdraw.show_withdraw))
    app.add_handler(CommandHandler("records", h_ledger.show_ledger))
    app.add_handler(CommandHandler("addr", h_addrquery.addr_query))
    app.add_handler(CommandHandler("support", h_support.show_support))
    app.add_handler(CommandHandler("password", h_password.set_password))

    # CallbackQuery：红包 / 充值 / 提现 / 密码键盘 / 常用地址回调
    app.add_handler(CallbackQueryHandler(h_rp.rp_callback, pattern=r"^(rp_|rpd_)"))
    app.add_handler(CallbackQueryHandler(h_rp.rppwd_callback, pattern=r"^rppwd:"))
    app.add_handler(CallbackQueryHandler(h_recharge.recharge_callback, pattern=r"^recharge_"))
    app.add_handler(CallbackQueryHandler(h_withdraw.withdraw_callback, pattern=r"^withdraw_"))
    app.add_handler(CallbackQueryHandler(h_password.password_kb_callback, pattern=r"^pwd:"))
    app.add_handler(CallbackQueryHandler(h_addrbook.address_kb_callback, pattern=r"^addrbook"))

    # Inline Query（红包预览卡片）
    app.add_handler(InlineQueryHandler(h_rp.inlinequery_handle))
    # Chosen Inline Result（用户真正把卡片发送出去）
    app.add_handler(ChosenInlineResultHandler(h_rp.on_chosen_inline_result))

    # 普通文本路由
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_router))
    app.add_handler(CallbackQueryHandler(h_withdraw.wdpwd_callback, pattern=r"^wdpwd:"))
    app.add_handler(CallbackQueryHandler(h_common.cancel_any_input, pattern=r"^cancel"))

    # 在 main() 里、所有 handler 加完后追加：
    app.add_error_handler(on_error)
    app.add_handler(TypeHandler(Update, _tap), group=999)

    # 生命周期钩子
    app_logger.info("Allowed updates = %s", ALLOWED_UPDATES)
    app.post_init = _startup
    app.post_shutdown = _shutdown
    return app

def main():
    app = build_app()

    if WEBHOOK_MODE == "polling":
        app_logger.info("🟡 RUN POLLING mode")
        app.run_polling(allowed_updates=ALLOWED_UPDATES, drop_pending_updates=False)
        return
    app_logger.info("🟢 RUN WEBHOOK mode: listen=%s:%s path=/%s url=%s",
                      WEBHOOK_HOST, WEBHOOK_PORT, WEBHOOK_URL_PATH, WEBHOOK_URL_FULL)
    # === Webhook 模式：url_path 必须与 setWebhook 的 path 完全一致 ===
    app.run_webhook(
        listen=WEBHOOK_HOST,
        port=WEBHOOK_PORT,
        url_path=WEBHOOK_URL_PATH,         # ← 不带前导斜杠
        webhook_url=WEBHOOK_URL_FULL,      # ← 例如 https://rpapi.../rptg/webhook
        secret_token=(WEBHOOK_SECRET or None),
        allowed_updates=ALLOWED_UPDATES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
