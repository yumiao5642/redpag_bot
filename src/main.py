import asyncio
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from telegram import BotCommand, BotCommandScopeDefault, Update
from telegram.request import HTTPXRequest
from .config import (
    BOT_TOKEN,
    TELEGRAM_CONNECT_TIMEOUT, TELEGRAM_READ_TIMEOUT, TELEGRAM_WRITE_TIMEOUT, TELEGRAM_POOL_TIMEOUT, TELEGRAM_PROXY,
    USDT_CONTRACT, AGGREGATE_ADDRESS
)
from .db import init_pool, close_pool

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
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


async def on_text_router(update, context):
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
    app_logger.info("🚀 机器人已启动，等待消息...")

async def _shutdown(app):
    await close_pool()
    app_logger.info("🛑 机器人已关闭。")


def main():
    # 扩大 Telegram 请求超时 + 可选代理，解决 get_me 启动超时
    req = HTTPXRequest(
        read_timeout=TELEGRAM_READ_TIMEOUT,
        write_timeout=TELEGRAM_WRITE_TIMEOUT,
        connect_timeout=TELEGRAM_CONNECT_TIMEOUT,
        pool_timeout=TELEGRAM_POOL_TIMEOUT,
        proxy=TELEGRAM_PROXY or None,
    )

    app = ApplicationBuilder()\
        .token(BOT_TOKEN)\
        .concurrent_updates(True)\
        .request(req)\
        .build()
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
    app.add_handler(CallbackQueryHandler(h_rp.rp_callback, pattern=r"^rp_"))
    app.add_handler(CallbackQueryHandler(h_rp.rppwd_callback, pattern=r"^rppwd:"))  # ← 新增：红包支付数字键盘
    app.add_handler(CallbackQueryHandler(h_recharge.recharge_callback, pattern=r"^recharge_"))
    app.add_handler(CallbackQueryHandler(h_withdraw.withdraw_callback, pattern=r"^withdraw_"))
    app.add_handler(CallbackQueryHandler(h_password.password_kb_callback, pattern=r"^pwd:"))
    app.add_handler(CallbackQueryHandler(h_addrbook.address_kb_callback, pattern=r"^addrbook"))

    # 普通文本路由
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_router))

    app.add_handler(CallbackQueryHandler(h_common.cancel_any_input, pattern=r"^cancel"))

    app.post_init = _startup
    app.post_shutdown = _shutdown

    try:
        app.run_polling(close_loop=False, allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        app_logger.exception("❌ 机器人启动失败：%s", e)
        raise

if __name__ == "__main__":
    main()
