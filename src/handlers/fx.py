# -*- coding: utf-8 -*-
import httpx
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from ..logger import app_logger

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
    """
    欧易 C2C：取 sell 前 10 条，显示 price + nickName，使用 code 块呈现。
    """
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
        app_logger.exception("📉 汇率查询失败：用户 %s，错误：%s", u.id, e)
        await update.message.reply_text("汇率查询失败，请稍后重试。")
        return

    data = (js.get("data") or {})
    sell = (data.get("sell") or [])[:10]

    lines = []
    for it in sell:
        price = str(it.get("price") or "-")
        nick = _safe(it.get("nickName") or it.get("nick_name") or "-")
        # 与图例一致：价格靠左，后接昵称
        lines.append(f"{price:<8} {nick}")

    head = "汇率实时查询\n数据来源：欧易 - 出售\n前十笔订单价格：\n"
    body = "```" + ("\n".join(lines) if lines else "暂无数据") + "```"
    await update.message.reply_text(head + body, parse_mode=ParseMode.MARKDOWN)

    if sell:
        app_logger.info("📈 汇率查询：用户 %s，取到 %d 条，首价=%s", u.id, len(sell), str(sell[0].get("price")))
    else:
        app_logger.info("📈 汇率查询：用户 %s，暂无数据", u.id)
