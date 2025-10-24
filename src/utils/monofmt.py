# -*- coding: utf-8 -*-
# src/utils/monofmt.py
import unicodedata

def _w(ch: str) -> int:
    """East Asian Width: F/W 记作 2，其他 1。"""
    if not ch:
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1

def display_len(s: str) -> int:
    if s is None:
        return 0
    return sum(_w(ch) for ch in str(s))

def _truncate_to_width(s: str, width: int) -> str:
    """按显示宽度截断到 width。"""
    s = str(s)
    cur = 0
    out = []
    for ch in s:
        w = _w(ch)
        if cur + w > width:
            break
        out.append(ch)
        cur += w
    return "".join(out)

def pad(s: str, width: int, align: str = "left") -> str:
    """按显示宽度补齐/截断；align: left/right/center"""
    s = "" if s is None else str(s)
    l = display_len(s)
    if l > width:
        return _truncate_to_width(s, width)
    pad_len = width - l
    if align == "right":
        return " " * pad_len + s
    if align == "center":
        left = pad_len // 2
        right = pad_len - left
        return " " * left + s + " " * right
    return s + " " * pad_len
