from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

MAIN_MENU = ReplyKeyboardMarkup([
    [KeyboardButton("💰 我的钱包")],
    [KeyboardButton("💱 汇率查询"), KeyboardButton("🧭 地址查询")],
    [KeyboardButton("🆘 联系客服"), KeyboardButton("🔐 设置密码/修改密码")]
], resize_keyboard=True)

WALLET_MENU = ReplyKeyboardMarkup([
    [KeyboardButton("🧧 红包"), KeyboardButton("➕ 充值")],
    [KeyboardButton("💸 提现"), KeyboardButton("📒 资金明细")],
    [KeyboardButton("📎 常用地址")],
    [KeyboardButton("⬅️ 返回主菜单")]
], resize_keyboard=True)

def redpacket_inline_menu(rp_id: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🧧 立即领取", callback_data=f"rp_claim:{rp_id}")
    ],[
        InlineKeyboardButton("查看详情", callback_data=f"rp_detail:{rp_id}")
    ]])

def _type_row(rp_id: int, rp_type: str):
    def _btn(t, label):
        hand = "👉 " if t == rp_type else ""
        return InlineKeyboardButton(f"{hand}{label}", callback_data=f"rp_type:{rp_id}:{t}")
    return [
        _btn("random", "随机"),
        _btn("average", "平均"),
        _btn("exclusive", "专属"),
    ]

def redpacket_create_menu(rp_id: int, rp_type: str):
    if rp_type in ("random", "average"):
        row1 = [
            InlineKeyboardButton("设置红包数量", callback_data=f"rp_set_count:{rp_id}"),
            InlineKeyboardButton("设置红包金额", callback_data=f"rp_set_amount:{rp_id}")
        ]
    else:  # exclusive
        row1 = [
            InlineKeyboardButton("设置专属对象", callback_data=f"rp_set_exclusive:{rp_id}"),
            InlineKeyboardButton("设置红包金额", callback_data=f"rp_set_amount:{rp_id}")
        ]
    row2 = [
        InlineKeyboardButton("设置封面", callback_data=f"rp_set_cover:{rp_id}"),
        InlineKeyboardButton("确认支付", callback_data=f"rp_pay:{rp_id}")
    ]
    return InlineKeyboardMarkup([_type_row(rp_id, rp_type), row1, row2])
