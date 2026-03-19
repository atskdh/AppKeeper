"""
icon_source.png の中心部分を拡大クロップしてシールドを大きく見せる
元画像 2048x2048 のうち、シールドが占める中央領域を切り出してリサイズ
"""
from PIL import Image
import os
import struct
import io

BASE = os.path.dirname(os.path.abspath(__file__))
src  = os.path.join(BASE, "icon_source.png")

img = Image.open(src).convert("RGBA")
W, H = img.size  # 2048 x 2048

# 元画像の余白（ネイビー背景）は上下左右それぞれ約12%程度
# 中央の約76%（シールド部分）を切り出して正方形にする
margin = int(W * 0.10)  # 10% クロップ（余白を削る）
cropped = img.crop((margin, margin, W - margin, H - margin))
print(f"Cropped size: {cropped.size}")

# ── ICO 生成（PNG 圧縮、高品質）──────────────────
def make_ico(img_rgba: Image.Image, sizes: list, out_path: str):
    images = []
    for s in sizes:
        resized = img_rgba.resize((s, s), Image.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format="PNG")
        images.append((s, buf.getvalue()))

    num = len(images)
    header = struct.pack("<HHH", 0, 1, num)
    dir_size   = num * 16
    data_offset = 6 + dir_size

    entries = b""
    data    = b""
    offset  = data_offset
    for s, png_bytes in images:
        w = h = s if s < 256 else 0
        entry = struct.pack(
            "<BBBBHHII",
            w, h, 0, 0, 1, 32,
            len(png_bytes), offset
        )
        entries += entry
        data    += png_bytes
        offset  += len(png_bytes)

    with open(out_path, "wb") as f:
        f.write(header + entries + data)

sizes    = [16, 24, 32, 48, 64, 128, 256]
ico_path = os.path.join(BASE, "appkeeper.ico")
make_ico(cropped, sizes, ico_path)
print(f"ICO saved: {ico_path}  ({os.path.getsize(ico_path):,} bytes)")

# ── タスクトレイ用 PNG (64x64) ──────────────────
tray_path = os.path.join(BASE, "icon_tray.png")
cropped.resize((64, 64), Image.LANCZOS).save(tray_path, format="PNG")
print(f"Tray PNG saved: {tray_path}")

# ── ウィンドウタイトルバー用 PNG (32x32) ──────────
win_path = os.path.join(BASE, "icon_window.png")
cropped.resize((32, 32), Image.LANCZOS).save(win_path, format="PNG")
print(f"Window PNG saved: {win_path}")

# ── プレビュー用 256px PNG ──────────────────────
prev_path = os.path.join(BASE, "icon_preview_256.png")
cropped.resize((256, 256), Image.LANCZOS).save(prev_path, format="PNG")
print(f"Preview PNG saved: {prev_path}")

print("Done.")
