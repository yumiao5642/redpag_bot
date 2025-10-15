# src/main.py
import asyncio
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram import BotCommand
from .config import BOT_TOKEN
from .handlers import wallet as h_wallet, recharge as h_recharge, withdraw as h_withdraw, red_packet as h_rp, addr_query as h_addrq, password as h_pwd


# 仅处理私聊的 filter
PRIVATE = filters.ChatType.PRIVATE

async def on_startup(app):
    # 在 post_init 回调里设置菜单命令，避免模块顶层 await
    await app.bot.set_my_commands([
        BotCommand("start", "开始使用"),
        BotCommand("wallet", "我的钱包"),
        BotCommand("recharge", "充值"),
        BotCommand("withdraw", "提现"),
        BotCommand("redpacket", "红包"),
        BotCommand("help", "帮助"),
    ])

def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()

    # 命令
    app.add_handler(CommandHandler(["start", "wallet"], h_wallet.my_wallet, PRIVATE))
    app.add_handler(CommandHandler("recharge", h_recharge.show_recharge, PRIVATE))
    app.add_handler(CommandHandler("withdraw", h_withdraw.withdraw_entry, PRIVATE))
    app.add_handler(CommandHandler("redpacket", h_rp.entry_menu, PRIVATE))
    app.add_handler(CommandHandler("set_password", h_pwd.start_set_password, PRIVATE))
    app.add_handler(CommandHandler("help", h_wallet.help_text, PRIVATE))

    # 回调按钮
    app.add_handler(CallbackQueryHandler(h_recharge.recharge_callback, PRIVATE & filters.regex(r"^(recharge_|back_to_menu)")))
    app.add_handler(CallbackQueryHandler(h_rp.type_callback, PRIVATE & filters.regex(r"^rp_type:")))
    app.add_handler(CallbackQueryHandler(h_pwd.password_kb_callback, PRIVATE & filters.regex(r"^pwd:(?:\d|ok|back|vis)$")))

    # 地址查询：用户输入地址文本
    app.add_handler(MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, h_addrq.on_text))

    return app

def main():
    app = build_app()
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
