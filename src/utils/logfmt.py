# -*- coding: utf-8 -*-
def log_user(u) -> str:
    nick = (u.full_name or "").strip()
    uname = f"@{u.username}" if getattr(u, "username", None) else ""
    return f"{u.id}（{nick} | {uname}）"
