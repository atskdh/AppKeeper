"""
アイコンファイルを base64 エンコードして icon_data.py に書き出すスクリプト
build_windows.bat から自動実行される
"""
import base64, os

BASE = os.path.dirname(os.path.abspath(__file__))

files = {
    "ICON_ICO_B64":    os.path.join(BASE, "appkeeper.ico"),
    "ICON_TRAY_B64":   os.path.join(BASE, "icon_tray.png"),
    "ICON_WINDOW_B64": os.path.join(BASE, "icon_window.png"),
}

out_path = os.path.join(BASE, "icon_data.py")
with open(out_path, "w", encoding="utf-8") as f:
    f.write('"""Auto-generated icon data (base64). Do not edit manually."""\n\n')
    for var, path in files.items():
        if os.path.isfile(path):
            data = open(path, "rb").read()
            b64  = base64.b64encode(data).decode()
            f.write(f'{var} = "{b64}"\n\n')
        else:
            f.write(f'{var} = ""\n\n')
            print(f"WARNING: {path} not found, {var} will be empty")

print(f"icon_data.py generated: {out_path}")
