from telegram import Update
from telegram.ext import ContextTypes


# 占位：可对接第三方行情（如 CoinGecko / Binance API）
async def show_fx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "汇率查询占位：USDT≈1 USD；可在此接入第三方行情接口。"
    )
