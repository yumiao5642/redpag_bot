#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
redpag_bot 本地体检脚本
逐项检查以下落地情况（打印 ✅/❌）：
  1. 充值成功后刷新页：到账金额+当前余额、二维码缩放叠字、CODE复制样式（弹窗）
  2. “我的钱包”不再显示“充值地址（专属）”
  3. 操作结束后回显主菜单（统一 show_main_menu）
  4. 功能锁：红包/提现入口拦截（sys_flags.lock_redpacket / lock_withdraw）
  5. 金额显示两位小数（fmt_amount）
  6. Bot Menu：set_my_commands / chat menu
  7. 充值直接弹窗（reply_photo + InlineKeyboard）
  8. 仅处理私聊（filters.ChatType.PRIVATE）
  9. 地址查询：TRX/USDT余额、资源、最近10笔转账；非法格式提示
 10. 九宫格交易密码
 11. 红包类型可切换（随机|平均|专属）并有“当前选中”指示
 12. 归集成功后：私聊用户通知 + 对账锁（聚合地址 USDT vs 用户总余额）
"""
import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

def ok(msg): print("✅", msg)
def ng(msg): print("❌", msg)

def rd(p: pathlib.Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""

def has(p: pathlib.Path, *pats) -> bool:
    s = rd(p)
    return s and all(re.search(x, s, re.S) for x in pats)

# 1 充值成功展示
def check_recharge_success():
    p = SRC / "handlers" / "recharge.py"
    s = rd(p)
    if not s: return ng("缺文件：src/handlers/recharge.py")
    a = ("recharge_status" in s) and (("到账金额" in s) or ("get_ledger_amount_by_ref" in s) or ("ledger" in s))
    b = ("reply_photo" in s and ("make_qr_png_bytes" in s or "qrcode" in s))
    c = ("点击复制" in s and "`" in s)
    if a: ok("充值成功显示到账金额+当前余额 OK")
    else: ng("充值成功页未检测到 到账金额/余额 刷新")
    if b: ok("充值弹窗/二维码缩放 OK")
    else: ng("充值未见弹窗或二维码缩放")
    if c: ok("地址/订单号 CODE 样式 OK")
    else: ng("未检测到 CODE 样式 ‘`...`  👈 点击复制’")

# 2 钱包页不显示“充值地址（专属）”
def check_wallet_page():
    p = SRC / "handlers" / "wallet.py"
    s = rd(p)
    if not s: return ng("缺文件：src/handlers/wallet.py")
    if ("充值地址" in s and "专属" in s):
        ng("我的钱包仍出现“充值地址（专属）”字样")
    else:
        ok("我的钱包未显示“充值地址（专属）” OK")

# 3 操作结束回显主菜单
def check_show_menu():
    any_hit = False
    for name in ["recharge.py","addr_query.py","red_packet.py","withdraw.py","password.py","wallet.py"]:
        p = SRC / "handlers" / name
        if p.exists() and "show_main_menu" in rd(p):
            any_hit = True; break
    if any_hit:
        ok("结束后回显主菜单（show_main_menu）已在多个 handler 使用")
    else:
        ng("未检测到 show_main_menu 用于回显主菜单")

# 4 功能锁
def check_feature_locks():
    rp = SRC / "handlers" / "red_packet.py"
    wd = SRC / "handlers" / "withdraw.py"
    rp_ok = rp.exists() and ("lock_redpacket" in rd(rp))
    wd_ok = wd.exists() and ("lock_withdraw" in rd(wd))
    if rp_ok and wd_ok:
        ok("功能锁入口拦截（红包/提现）OK")
    else:
        ng("功能锁入口拦截存在缺口（检查 get_flag('lock_*')）")

# 5 金额统一两位小数
def check_fmt_amount():
    common = SRC / "handlers" / "common.py"
    s = rd(common)
    if s and ("def fmt_amount" in s and ".2f" in s):
        ok("fmt_amount 两位小数 OK")
    else:
        ng("未检测到 fmt_amount 或未统一两位小数（handlers/common.py）")

# 6 Bot Menu
def check_menu_register():
    p = SRC / "main.py"
    s = rd(p)
    if s and ("set_my_commands" in s or "set_chat_menu_button" in s):
        ok("Bot Menu 注册 OK")
    else:
        ng("未检测到 set_my_commands / set_chat_menu_button")

# 7 充值弹窗
def check_popup_recharge():
    p = SRC / "handlers" / "recharge.py"
    s = rd(p)
    if s and ("reply_photo" in s and "InlineKeyboard" in s):
        ok("充值弹窗（二维码+按钮）OK")
    else:
        ng("充值弹窗未检测到 reply_photo/InlineKeyboard")

# 8 仅私聊
def check_private_only():
    p = SRC / "main.py"
    s = rd(p)
    if s and (re.search(r"ChatType\\.?PRIVATE", s) or "filters.ChatType.PRIVATE" in s):
        ok("仅处理私聊 OK")
    else:
        ng("未检测到仅私聊过滤（filters.ChatType.PRIVATE）")

# 9 地址查询增强
def check_addr_query():
    p = SRC / "handlers" / "addr_query.py"
    s = rd(p)
    if not s: return ng("缺文件：src/handlers/addr_query.py")
    a = ("当前仅支持TRC-20格式地址" in s) or ("当前仅支持 TRC-20 格式地址" in s)
    b = ("get_trx_balance" in s and "get_trc20_balance" in s and "get_account_resource" in s)
    c = ("get_recent_transfers" in s)
    if a and b and c:
        ok("地址查询：校验+余额+资源+最近10笔 OK")
    else:
        ng("地址查询未完全实现（或函数调用未命中）")

# 10 九宫格交易密码
def check_password_grid():
    p = SRC / "handlers" / "password.py"
    s = rd(p)
    if s and ("InlineKeyboardButton" in s and "•" in s or "●" in s):
        ok("九宫格交易密码 UI OK")
    else:
        ng("未检测到九宫格密码 UI")

# 11 红包类型切换
def check_redpacket_types():
    p = SRC / "handlers" / "red_packet.py"
    s = rd(p)
    if s and ("随机" in s and "平均" in s and "专属" in s and "set_rp_type" in s):
        ok("红包类型可切换（随机|平均|专属）OK")
    else:
        ng("红包类型切换功能未检测到（或缺少指示当前选中）")

# 12 归集成功通知 + 对账锁
def check_collector_notify_reconcile():
    p = SRC / "collectors" / "recharge_collector.py"
    s = rd(p)
    if not s: return ng("缺文件：src/collectors/recharge_collector.py")
    a = ("send_message" in s and "充值成功" in s) or ("_notify" in s and "success" in s)
    b = ("sum_user_usdt_balance" in s and "get_trc20_balance" in s and ("set_flag(\"lock_" in s or "lock_" in s))
    if a: ok("归集成功后用户通知 OK")
    else: ng("归集成功后用户通知未检测到")
    if b: ok("对账 + 锁开关 校验 OK")
    else: ng("对账/锁开关逻辑未检测到")

def main():
    print("=== redpag_bot 本地体检 ===")
    check_recharge_success()
    check_wallet_page()
    check_show_menu()
    check_feature_locks()
    check_fmt_amount()
    check_menu_register()
    check_popup_recharge()
    check_private_only()
    check_addr_query()
    check_password_grid()
    check_redpacket_types()
    check_collector_notify_reconcile()
    print("=== 体检结束 ===")

if __name__ == "__main__":
    main()
