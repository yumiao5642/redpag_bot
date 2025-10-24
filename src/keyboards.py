from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# 主菜单：移除“设置密码/修改密码”
MAIN_MENU = ReplyKeyboardMarkup([
    [KeyboardButton("💰 我的钱包")],[KeyboardButton("🆘 联系客服")],
    [KeyboardButton("💱 汇率查询"), KeyboardButton("🧭 地址查询")],
], resize_keyboard=True)

# 钱包子菜单：第1行（充值｜提款），第2行（红包｜资金明细），第3行（常用地址｜密码管理）
WALLET_MENU = ReplyKeyboardMarkup([
    [KeyboardButton("➕ 充值"), KeyboardButton("💸 提现")],
    [KeyboardButton("🧧 红包"), KeyboardButton("📒 资金明细")],
    [KeyboardButton("📎 常用地址"), KeyboardButton("🔐 密码管理")],
    [KeyboardButton("⬅️ 返回主菜单")]
], resize_keyboard=True)

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

def redpacket_draft_menu(rp_type: str):
    def _type_btn(t, label):
        hand = "👉 " if t == rp_type else ""
        return InlineKeyboardButton(f"{hand}{label}", callback_data=f"rpd_type:{t}")

    if rp_type in ("random", "average"):
        row1 = [
            InlineKeyboardButton("设置红包数量", callback_data="rpd_set_count"),
            InlineKeyboardButton("设置红包金额", callback_data="rpd_set_amount"),
        ]
    else:
        row1 = [
            InlineKeyboardButton("设置专属对象", callback_data="rpd_set_exclusive"),
            InlineKeyboardButton("设置红包金额", callback_data="rpd_set_amount"),
        ]
    row2 = [
        InlineKeyboardButton("设置封面", callback_data="rpd_set_cover"),
        InlineKeyboardButton("确认支付", callback_data="rpd_pay"),
    ]
    return InlineKeyboardMarkup([[ _type_btn("random","随机"), _type_btn("average","平均"), _type_btn("exclusive","专属") ], row1, row2])
