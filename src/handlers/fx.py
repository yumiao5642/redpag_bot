# -*- coding: utf-8 -*-
import httpx
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from ..logger import app_logger
from ..utils.logfmt import log_user

_OKX_URL = "https://www.okx.com/v3/c2c/tradingOrders/books"

def _mk_headers() -> dict:
    # 足够的请求头即可，无需携带 cookie
    return {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
        "Accept": "application/json",
        "App-Type": "web",
        "X-Utc": "8",
        "X-Locale": "zh_CN",
        "Referer": "https://www.okx.com/zh-hans/p2p-markets/cny/buy-usdt",
    }

def _safe(s: str) -> str:
    # 避免 Markdown 解析问题：把反引号/回车去掉
    if not s:
        return ""
    return s.replace("`", " ").replace("\n", " ").replace("\r", " ")

async def show_fx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    params = {
        "quoteCurrency": "CNY",
        "baseCurrency": "USDT",
        "paymentMethod": "all",
        "side": "sell",
        "userType": "all",
    }
    u = update.effective_user
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(_OKX_URL, params=params, headers=_mk_headers())
            r.raise_for_status()
            js = r.json() or {}
    except Exception as e:
        app_logger.exception("📉 汇率查询失败：用户 %s，错误：%s", log_user(u), e)
        await update.message.reply_text("汇率查询失败，请稍后重试。")
        return
    data = (js.get("data") or {})
    sell = (data.get("sell") or [])[:10]

    header = "汇率实时查询\n数据来源：欧易 - 出售\n"
    lines = ["前十笔订单价格："]
    for it in sell:
        price = str(it.get("price") or "-")
        nick = _safe(it.get("nickName") or it.get("nick_name") or "-")
        lines.append(f"{price:<8} {nick}")

    body = "```" + ("\n".join(lines) if lines else "前十笔订单价格：\n暂无数据") + "```"
    await update.message.reply_text(header + body, parse_mode=ParseMode.MARKDOWN)

    if sell:
        app_logger.info("📈 汇率查询：用户 %s，取到 %d 条，首价=%s", log_user(u), len(sell), str(sell[0].get("price")))
    else:
        app_logger.info("📈 汇率查询：用户 %s，暂无数据", log_user(u))
