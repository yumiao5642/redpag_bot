
import asyncio
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from .config import BOT_TOKEN
from .db import init_pool
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
from .logger import app_logger

async def on_text_router(update, context):
    text = (update.message.text or "").strip()
    if text in ("/start", "start"):
        return await h_start.start(update, context)

    # 主菜单入口
    if text.startswith("一、我的钱包"):
        return await h_wallet.show_wallet(update, context)
    if text.startswith("二、汇率查询"):
        return await h_fx.show_fx(update, context)
    if text.startswith("三、地址查询"):
        return await h_addrquery.addr_query(update, context)
    if text.startswith("四、联系客服"):
        return await h_support.show_support(update, context)
    if text.startswith("五、设置密码"):
        return await h_password.set_password(update, context)

    # 钱包子菜单
    if text.startswith("1、红包"):
        return await h_rp.show_red_packets(update, context)
    if text.startswith("2、充值"):
        return await h_recharge.show_recharge(update, context)
    if text.startswith("3、提现"):
        return await h_withdraw.show_withdraw(update, context)
    if text.startswith("4、资金明细"):
        return await h_ledger.show_ledger(update, context)
    if text.startswith("5、常用地址"):
        return await h_addrbook.address_entry(update, context)
    if text.startswith("返回主菜单"):
        return await h_start.start(update, context)

    # 其他输入流（红包创建、地址绑定、密码设置、地址查询等）
    await h_rp.on_user_text(update, context)
    await h_addrbook.address_entry(update, context)
    await h_password.on_text(update, context)
    await h_addrquery.addr_query_ontext(update, context)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", h_start.start))
    app.add_handler(CallbackQueryHandler(h_rp.rp_callback, pattern=r"^rp_"))
    app.add_handler(CallbackQueryHandler(h_recharge.recharge_callback, pattern=r"^recharge_"))
    app.add_handler(CallbackQueryHandler(h_withdraw.withdraw_callback, pattern=r"^withdraw_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_router))

    async def _startup(_):
        await init_pool()
        app_logger.info("🚀 机器人已启动，等待消息...")
    app.post_init = _startup

    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
