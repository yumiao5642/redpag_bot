<<<<<<< HEAD
# src/services/qrcode_util.py
import io
from typing import Optional

import qrcode
from PIL import Image, ImageDraw, ImageFont


def make_qr_png_bytes(
    data: str, scale: float = 0.5, caption: Optional[str] = None
) -> bytes:
    # 生成二维码
    qr = qrcode.QRCode(border=2, box_size=10)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    # 缩放
    if 0 < scale < 1.0:
        w, h = img.size
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
=======
# -*- coding: utf-8 -*-
import io
import qrcode
from PIL import Image, ImageDraw, ImageFont

def make_qr_png_bytes(data, scale=0.5, caption=None):
    qr = qrcode.QRCode(border=2, box_size=10)
    qr.add_data(data); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    # 缩放
    if isinstance(scale, float) and 0 < scale < 1.0:
        w, h = img.size
        img = img.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
>>>>>>> 441209c (feat(bot): 充值成功回显到账+余额；主菜单回显；功能锁(红包/提现)；地址查询增强；二维码缩放与CODE复制；仅私聊安全)

    # 叠加地址文字（自动换行）
    if caption:
        pad = 16
        W, H = img.size
        font = ImageFont.load_default()
        draw = ImageDraw.Draw(img)
<<<<<<< HEAD

        # 简单按宽度截断换行
        lines, cur, maxw = [], "", W - 20
        for ch in caption:
            trial = cur + ch
            if draw.textlength(trial, font=font) > maxw:
                lines.append(cur)
                cur = ch
            else:
                cur = trial
        if cur:
            lines.append(cur)

        line_h = 14
        text_h = line_h * len(lines) + pad
        canvas = Image.new("RGB", (W, H + text_h), "white")
        canvas.paste(img, (0, 0))
        draw = ImageDraw.Draw(canvas)
        y = H + (pad // 2)
=======
        lines, cur, maxw = [], "", W - 20
        for ch in caption:
            tmp = cur + ch
            if draw.textlength(tmp, font=font) > maxw:
                lines.append(cur); cur = ch
            else:
                cur = tmp
        if cur:
            lines.append(cur)
        line_h = 14
        text_h = line_h*len(lines) + pad
        canvas = Image.new("RGB", (W, H + text_h), "white")
        canvas.paste(img, (0, 0))
        draw = ImageDraw.Draw(canvas)
        y = H + (pad//2)
>>>>>>> 441209c (feat(bot): 充值成功回显到账+余额；主菜单回显；功能锁(红包/提现)；地址查询增强；二维码缩放与CODE复制；仅私聊安全)
        for ln in lines:
            draw.text((10, y), ln, fill="black", font=font)
            y += line_h
        img = canvas

<<<<<<< HEAD
    # 输出 PNG
=======
>>>>>>> 441209c (feat(bot): 充值成功回显到账+余额；主菜单回显；功能锁(红包/提现)；地址查询增强；二维码缩放与CODE复制；仅私聊安全)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
