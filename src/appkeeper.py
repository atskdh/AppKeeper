"""
AppKeeper v2.9 - プロセス監視・自動再起動ツール
Python + CustomTkinter + psutil + pystray

v2.9 変更点:
  - UI改善: チェックボックスのテキストを短縮し、詳細な説明を別行に配置して見切れを完全に解消

v2.8 変更点:
  - バグ修正: 設定ダイアログのフリーズおよび描画不具合（wraplengthの問題）を修正
  - UI改善: 長い説明文を別行に配置することで、見切れを防ぎつつ安全に表示

v2.7 変更点:
  - UI改善: 設定ダイアログの長い説明文が折り返されるように修正（見切れ防止）
  - UI改善: 設定ダイアログの初期幅をさらに拡大

v2.6 変更点:
  - バグ修正: 起動直後に「起動スクリプト」タブの内容が表示されない不具合を修正

v2.5 変更点:
  - 直列化: 起動スクリプトが全て完了（待機含む）してから監視エントリを起動するように修正
  - タブ順序: 「起動スクリプト」を左側に配置し、起動時のデフォルト表示に設定
  - UI改善: 設定項目増加に合わせて、編集ダイアログの初期サイズを拡大

v2.4 変更点:
  - 起動スクリプト: コンソールウィンドウ表示/非表示の選択オプションを追加
  - 起動スクリプト: BAT/CMDをcmd.exe明示呼び出しでコンソール画面を正しく表示
  - 起動スクリプト: 待機モードを「待機なし / 時間待機 / プロセス起動待ち」の3選択式に整理
  - 監視エントリ: 「監視開始時にプロセスが既に起動中なら起動をスキップ」オプションを追加（起動スクリプトと並用時の二重起動防止）
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import json
import os
import sys
import threading
import subprocess
import time
import psutil
import winreg
import base64
import tempfile
import struct
import io
from datetime import datetime
from PIL import Image, ImageDraw

# Windows API（ハング検知用）
if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes
    user32 = ctypes.windll.user32

# ─────────────────────────────────────────
# 定数
# ─────────────────────────────────────────
APP_NAME    = "AppKeeper"
BASE_DIR    = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
LOG_DIR     = os.path.join(BASE_DIR, "log")
AUTORUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
MAX_LOG     = 200   # 画面表示の最大行数

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ─────────────────────────────────────────
# アイコン埋め込みデータ読み込み
# ─────────────────────────────────────────
def _load_icon_b64():
    """icon_data.py からアイコンの base64 データを読み込む。
    ファイルがなければ外部ファイルから読み込む（開発時用）。"""
    try:
        from icon_data import ICON_ICO_B64, ICON_TRAY_B64, ICON_WINDOW_B64
        return ICON_ICO_B64, ICON_TRAY_B64, ICON_WINDOW_B64
    except ImportError:
        pass
    # フォールバック：外部ファイルから読み込む
    def _read_b64(fname):
        path = os.path.join(BASE_DIR, fname)
        if os.path.isfile(path):
            return base64.b64encode(open(path, "rb").read()).decode()
        return ""
    return _read_b64("appkeeper.ico"), _read_b64("icon_tray.png"), _read_b64("icon_window.png")

_ICON_ICO_B64, _ICON_TRAY_B64, _ICON_WINDOW_B64 = _load_icon_b64()

# 一時ファイルとして ICO を書き出す（iconbitmap に必要）
_TEMP_ICO_PATH = None
def _get_temp_ico():
    global _TEMP_ICO_PATH
    if _TEMP_ICO_PATH and os.path.isfile(_TEMP_ICO_PATH):
        return _TEMP_ICO_PATH
    if _ICON_ICO_B64:
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".ico", delete=False)
            tmp.write(base64.b64decode(_ICON_ICO_B64))
            tmp.close()
            _TEMP_ICO_PATH = tmp.name
            return _TEMP_ICO_PATH
        except Exception:
            pass
    return None

def _b64_to_pil(b64str: str) -> Image.Image | None:
    """base64 文字列を PIL Image に変換する"""
    if not b64str:
        return None
    try:
        data = base64.b64decode(b64str)
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


# ─────────────────────────────────────────
# 設定管理
# ─────────────────────────────────────────
DEFAULT_CONFIG = {
    "autostart":        False,
    "start_minimized":  False,
    "entries":          [],
    "startup_scripts":  []   # 起動時に1回だけ実行するスクリプト一覧
}

DEFAULT_ENTRY = {
    "name":             "新しいアプリ",
    "process":          "",
    "launch_path":      "",       # 起動ファイルのパス（BAT/EXE どちらでも可）
    "exe_args":         "",       # 起動引数（オプション）
    "interval":         5,
    "delay":            3,
    "enabled":          True,
    "launch_mode":      "always", # "always"=常時監視 / "once"=起動時ㅧ1回のみ / "limited"=回数制限
    "max_restarts":     3,        # launch_mode=="limited" のときの最大再起動回数
    "hang_detect":      False,    # ハング検知を有効にするか
    "hang_threshold":   30,       # 何秒間「応答なし」で再起動するか
    "hang_action":      "restart", # "restart" or "log_only"
    "skip_if_running":  False     # 監視開始時にプロセスが既存なら起動をスキップ
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in DEFAULT_CONFIG.items():
                    data.setdefault(k, v)
                return data
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────
# ログファイル書き出し
# ─────────────────────────────────────────
def get_log_path():
    os.makedirs(LOG_DIR, exist_ok=True)
    filename = datetime.now().strftime("%Y%m%d") + ".log"
    return os.path.join(LOG_DIR, filename)


def write_log_file(line: str):
    try:
        with open(get_log_path(), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


# ─────────────────────────────────────────
# Windows 自動起動レジストリ操作
# ─────────────────────────────────────────
def get_exe_path():
    return os.path.abspath(sys.argv[0])


def set_autostart(enabled: bool):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTORUN_KEY, 0, winreg.KEY_SET_VALUE)
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{get_exe_path()}"')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


# ─────────────────────────────────────────
# ハング検知ユーティリティ
# ─────────────────────────────────────────
def get_process_hwnd(pid: int):
    """指定PIDのメインウィンドウハンドルを取得する"""
    if sys.platform != "win32":
        return None
    result = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    def callback(hwnd, lParam):
        pid_buf = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
        if pid_buf.value == pid and user32.IsWindowVisible(hwnd):
            result.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return result[0] if result else None


def is_window_hung(hwnd) -> bool:
    """IsHungAppWindow で「応答なし」かどうかを判定する"""
    if sys.platform != "win32" or hwnd is None:
        return False
    try:
        return bool(user32.IsHungAppWindow(hwnd))
    except Exception:
        return False


# ─────────────────────────────────────────
# タスクトレイアイコン生成
# ─────────────────────────────────────────
def create_tray_icon_image(active=True):
    """タスクトレイ用アイコンを返す。埋め込みデータを優先使用する"""
    img = _b64_to_pil(_ICON_TRAY_B64)
    if img:
        return img.resize((64, 64), Image.LANCZOS)
    # フォールバック：プログラム生成アイコン
    size  = 64
    img   = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw  = ImageDraw.Draw(img)
    color = "#2fa572" if active else "#555555"
    draw.ellipse([4, 4, size - 4, size - 4], fill=color)
    draw.ellipse([20, 20, size - 20, size - 20], fill="white")
    return img


# ─────────────────────────────────────────
# 監視ワーカー（エントリごとにスレッド）
# ─────────────────────────────────────────
class WatchWorker(threading.Thread):
    def __init__(self, entry: dict, log_callback, minimize_callback=None):
        super().__init__(daemon=True)
        self.entry             = entry
        self.log_callback      = log_callback
        self.minimize_callback = minimize_callback  # 起動前にAppKeeperを最小化するコールバック
        self._stop_event       = threading.Event()

    def stop(self):
        self._stop_event.set()

    def get_process(self):
        """監視対象プロセスオブジェクトを返す（なければNone）"""
        pname = self.entry.get("process", "").strip()
        if not pname:
            return None
        for p in psutil.process_iter(["name", "pid"]):
            try:
                if p.info["name"] and \
                   p.info["name"].lower().rstrip(".exe") == pname.lower().rstrip(".exe"):
                    return p
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return None

    def is_running_process(self):
        return self.get_process() is not None

    def launch_app(self):
        """起動ファイル（BAT/EXE）を実行する。
        起動前にAppKeeperを最小化し、起動後に対象アプリを前面表示する。"""
        path = self.entry.get("launch_path", "").strip()
        # 旧設定との互換性（bat_pathが残っている場合）
        if not path:
            path = self.entry.get("bat_path", "").strip()

        if not path or not os.path.isfile(path):
            self.log_callback(self.entry["name"],
                              f"起動ファイルが見つかりません: {path}")
            return

        # ① AppKeeperを一時最小化（フォーカス保護を回避するため）
        if self.minimize_callback:
            self.minimize_callback()
            time.sleep(0.5)  # ウィンドウが最小化されるのを待つ

        try:
            ext  = os.path.splitext(path)[1].lower()
            args = self.entry.get("exe_args", "").strip()

            if ext == ".exe":
                cmd = [path] + (args.split() if args else [])
                subprocess.Popen(
                    cmd,
                    cwd=os.path.dirname(path),
                    creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
                )
                self.log_callback(self.entry["name"],
                                  f"EXEを起動しました: {os.path.basename(path)}"
                                  + (f" (引数: {args})" if args else ""))
            else:
                # BAT / CMD など
                cmd = path + (f" {args}" if args else "")
                subprocess.Popen(
                    cmd,
                    shell=True,
                    cwd=os.path.dirname(path),
                    creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
                )
                self.log_callback(self.entry["name"],
                                  f"BATファイルを実行しました: {os.path.basename(path)}")

            # ② 起動後、対象プロセスのウィンドウを前面に強制表示
            if sys.platform == "win32":
                proc_name = self.entry.get("process", "").strip()
                if proc_name:
                    self._bring_to_front(proc_name)

        except Exception as e:
            self.log_callback(self.entry["name"], f"起動エラー: {e}")

    def _bring_to_front(self, proc_name: str, timeout: int = 20):
        """起動したプロセスのウィンドウが現れるまで待ち、前面に表示する。
        AttachThreadInput + keybd_event を使いWindowsのフォーカス保護を確実に突破する。"""
        if sys.platform != "win32":
            return

        import ctypes
        kernel32 = ctypes.windll.kernel32

        deadline = time.time() + timeout
        hwnd = None

        # ウィンドウが現れるまで待機
        while time.time() < deadline:
            if self._stop_event.is_set():
                return
            proc = self.get_process()
            if proc:
                hwnd = get_process_hwnd(proc.pid)
                if hwnd:
                    break
            time.sleep(0.5)

        if not hwnd:
            return

        try:
            # ウィンドウが描画されるまで少し待つ
            time.sleep(1.0)

            # SW_RESTORE=9 で最小化・非表示を解除
            user32.ShowWindow(hwnd, 9)
            time.sleep(0.2)

            # --- AttachThreadInput による確実な前面表示 ---
            # 現在のフォアグラウンドウィンドウのスレッドIDを取得
            fg_hwnd   = user32.GetForegroundWindow()
            fg_tid    = user32.GetWindowThreadProcessId(fg_hwnd, None)
            # 対象ウィンドウのスレッドIDを取得
            tgt_tid   = user32.GetWindowThreadProcessId(hwnd, None)
            # 自分のスレッドIDを取得
            my_tid    = kernel32.GetCurrentThreadId()

            # 対象スレッドをフォアグラウンドスレッドにアタッチ
            attached_fg  = False
            attached_my  = False
            if fg_tid and fg_tid != tgt_tid:
                attached_fg = bool(user32.AttachThreadInput(tgt_tid, fg_tid, True))
            if my_tid and my_tid != tgt_tid:
                attached_my = bool(user32.AttachThreadInput(tgt_tid, my_tid, True))

            # Alt キーを一瞬押してフォーカス保護を解除（Windowsの仕様上の回避策）
            VK_MENU = 0x12  # Alt キー
            KEYEVENTF_KEYUP = 0x0002
            user32.keybd_event(VK_MENU, 0, 0, 0)                   # Alt 押下
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)    # Alt 離す
            time.sleep(0.05)

            # 前面に強制表示
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)

            # SetWindowPos で Z オーダーを最前面に
            SWP_NOMOVE    = 0x0002
            SWP_NOSIZE    = 0x0001
            SWP_SHOWWINDOW = 0x0040
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)

            # アタッチを解除
            if attached_fg:
                user32.AttachThreadInput(tgt_tid, fg_tid, False)
            if attached_my:
                user32.AttachThreadInput(tgt_tid, my_tid, False)

        except Exception:
            pass

    def kill_process(self, proc):
        """プロセスを強制終了する"""
        try:
            proc.kill()
            self.log_callback(self.entry["name"], "ハングしたプロセスを強制終了しました")
        except Exception as e:
            self.log_callback(self.entry["name"], f"プロセス強制終了エラー: {e}")

    def run(self):
        name           = self.entry.get("name", "")
        interval       = max(1, int(self.entry.get("interval", 5)))
        delay          = max(0, int(self.entry.get("delay", 3)))
        hang_detect    = self.entry.get("hang_detect", False)
        hang_threshold = max(5, int(self.entry.get("hang_threshold", 30)))
        hang_action    = self.entry.get("hang_action", "restart")
        launch_mode    = self.entry.get("launch_mode", "always")
        max_restarts   = max(1, int(self.entry.get("max_restarts", 3)))

        hang_seconds    = 0
        restart_count   = 0
        self.log_callback(name, "監視を開始しました")

        # ── 起動時1回のみモード ──────────────────
        if launch_mode == "once":
            if not self.is_running_process():
                self.log_callback(name, "起動時1回実行: 起動します")
                self.launch_app()
            else:
                self.log_callback(name, "起動時1回実行: すでに起動中のためスキップしました")
            self.log_callback(name, "監視を停止しました（起動時1回モード）")
            return

        # ── 常時監視 / 回数制限モード ────────────
        # 初回起動スキップ：監視開始時にプロセスが既に存在する場合は起動しない
        skip_if_running = self.entry.get("skip_if_running", False)
        if skip_if_running and self.is_running_process():
            self.log_callback(name, "プロセスが既に起動中のため初回起動をスキップしました（監視は継続）")
        elif not self.is_running_process():
            # 初回起動（プロセスがない場合は起動する）
            self.launch_app()

        while not self._stop_event.is_set():
            proc = self.get_process()

            if proc is None:
                hang_seconds = 0

                # 回数制限チェック
                if launch_mode == "limited":
                    if restart_count >= max_restarts:
                        self.log_callback(
                            name,
                            f"再起動回数が上限（{max_restarts}回）に達しました。監視を停止します。")
                        return
                    restart_count += 1
                    self.log_callback(
                        name,
                        f"プロセスが停止しました。{delay}秒後に再起動します... "
                        f"({restart_count}/{max_restarts}回目)")
                else:
                    self.log_callback(name, f"プロセスが停止しました。{delay}秒後に再起動します...")

                for _ in range(delay):
                    if self._stop_event.is_set():
                        return
                    time.sleep(1)
                if not self._stop_event.is_set():
                    self.launch_app()

            elif hang_detect:
                hwnd = get_process_hwnd(proc.pid)
                if hwnd and is_window_hung(hwnd):
                    hang_seconds += interval
                    self.log_callback(
                        name,
                        f"応答なし検知中... ({hang_seconds}/{hang_threshold}秒)")

                    if hang_seconds >= hang_threshold:
                        hang_seconds = 0
                        if hang_action == "restart":
                            self.log_callback(
                                name,
                                f"応答なしが{hang_threshold}秒継続。プロセスを強制終了して再起動します...")
                            self.kill_process(proc)

                            # 回数制限チェック（ハング再起動にも適用）
                            if launch_mode == "limited":
                                if restart_count >= max_restarts:
                                    self.log_callback(
                                        name,
                                        f"再起動回数が上限（{max_restarts}回）に達しました。監視を停止します。")
                                    return
                                restart_count += 1

                            for _ in range(delay):
                                if self._stop_event.is_set():
                                    return
                                time.sleep(1)
                            if not self._stop_event.is_set():
                                self.launch_app()
                        else:
                            self.log_callback(
                                name,
                                f"応答なしが{hang_threshold}秒継続しています（ログのみ・再起動なし）")
                else:
                    if hang_seconds > 0:
                        self.log_callback(name, "応答が回復しました")
                        hang_seconds = 0

            self._stop_event.wait(interval)

        self.log_callback(name, "監視を停止しました")


# ─────────────────────────────────────────
# 起動スクリプト設定ダイアログ
# ─────────────────────────────────────────
class StartupScriptDialog(ctk.CTkToplevel):
    """起動スクリプトの設定ダイアログ。
    設定項目: 表示名 / 起動ファイル / 起動引数 / コンソール表示 / 待機設定
    プロセス監視・ハング検知などの設定は一切ない。
    """
    def __init__(self, parent, script: dict | None, on_save):
        super().__init__(parent)
        self.title("起動スクリプトの設定")
        self.geometry("640x560")
        self.minsize(600, 500)
        self.resizable(True, True)
        self.grab_set()
        self.lift()
        self.focus_force()

        self.on_save = on_save
        self.script  = dict(script) if script else {
            "name": "", "launch_path": "", "exe_args": "",
            "show_console": True,
            "wait_mode": "none",   # "none" / "time" / "process"
            "wait_after": 5,
            "wait_process": "",
            "wait_process_timeout": 30
        }

        self._init_vars()
        self._build_ui()

    def _init_vars(self):
        sc = self.script
        self.name_var            = ctk.StringVar(value=sc.get("name", ""))
        self.launch_path_var     = ctk.StringVar(value=sc.get("launch_path", ""))
        self.exe_args_var        = ctk.StringVar(value=sc.get("exe_args", ""))
        self.show_console_var    = ctk.BooleanVar(value=sc.get("show_console", True))
        # wait_mode: "none" / "time" / "process"
        # 旧データの後方互換：wait_after>0なら"time"、wait_processありなら"process"
        _wm = sc.get("wait_mode", "")
        if not _wm:
            if sc.get("wait_process", "").strip():
                _wm = "process"
            elif int(sc.get("wait_after", 0)) > 0:
                _wm = "time"
            else:
                _wm = "none"
        self.wait_mode_var       = ctk.StringVar(value=_wm)
        self.wait_after_var      = ctk.StringVar(value=str(sc.get("wait_after", 5)))
        self.wait_process_var    = ctk.StringVar(value=sc.get("wait_process", ""))
        self.wait_timeout_var    = ctk.StringVar(value=str(sc.get("wait_process_timeout", 30)))

    def _build_ui(self):
        pad = {"padx": 16, "pady": 6}

        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True)
        scroll.columnconfigure(1, weight=1)
        sf = scroll

        # ── 基本設定 ──
        ctk.CTkLabel(sf, text="表示名").grid(row=0, column=0, sticky="w", **pad)
        ctk.CTkEntry(sf, textvariable=self.name_var, width=340,
                     placeholder_text="例: ライセンスツール").grid(
            row=0, column=1, columnspan=2, sticky="ew", **pad)

        ctk.CTkLabel(sf, text="起動ファイル").grid(row=1, column=0, sticky="w", **pad)
        self.path_entry = ctk.CTkEntry(
            sf, textvariable=self.launch_path_var, width=280,
            placeholder_text="BATまたはEXEのパス")
        self.path_entry.grid(row=1, column=1, sticky="ew", **pad)
        ctk.CTkButton(sf, text="参照", width=70,
                      command=self._browse).grid(row=1, column=2, **pad)

        ctk.CTkLabel(sf, text="起動引数").grid(row=2, column=0, sticky="w", **pad)
        ctk.CTkEntry(sf, textvariable=self.exe_args_var, width=340,
                     placeholder_text="例: --silent --port 8080 (不要なら空欄)").grid(
            row=2, column=1, columnspan=2, sticky="ew", **pad)

        # ── コンソールウィンドウ ──
        ctk.CTkFrame(sf, height=1, fg_color="gray40").grid(
            row=3, column=0, columnspan=3, sticky="ew", padx=16, pady=4)
        ctk.CTkLabel(sf, text="コンソール",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=4, column=0, sticky="w", padx=16, pady=(4, 2))
        ctk.CTkCheckBox(
            sf,
            text="コンソールを表示する",
            variable=self.show_console_var
        ).grid(row=5, column=1, sticky="w", padx=16, pady=(2, 0))
        ctk.CTkLabel(
            sf,
            text="（BAT実行時にコマンドプロンプト画面を表示）",
            font=ctk.CTkFont(size=11),
            text_color="gray70"
        ).grid(row=6, column=1, columnspan=2, sticky="w", padx=40, pady=(0, 4))

        # ── 待機設定 ──
        ctk.CTkFrame(sf, height=1, fg_color="gray40").grid(
            row=7, column=0, columnspan=3, sticky="ew", padx=16, pady=4)
        ctk.CTkLabel(sf, text="実行後の待機",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=8, column=0, sticky="w", padx=16, pady=(4, 2))
        ctk.CTkLabel(
            sf,
            text="次のスクリプトまたは監視エントリの起動前に待機する時間を設定できます",
            text_color="gray60", font=ctk.CTkFont(size=10)
        ).grid(row=9, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 4))

        # 待機モード選択
        mode_frame = ctk.CTkFrame(sf, fg_color="transparent")
        mode_frame.grid(row=10, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 2))
        ctk.CTkRadioButton(mode_frame, text="待機なし",
                           variable=self.wait_mode_var, value="none",
                           command=self._on_wait_mode_change).pack(side="left", padx=(0, 12))
        ctk.CTkRadioButton(mode_frame, text="時間待機",
                           variable=self.wait_mode_var, value="time",
                           command=self._on_wait_mode_change).pack(side="left", padx=(0, 12))
        ctk.CTkRadioButton(mode_frame, text="プロセス起動待ち",
                           variable=self.wait_mode_var, value="process",
                           command=self._on_wait_mode_change).pack(side="left")

        # 時間待機行
        self._time_row = ctk.CTkFrame(sf, fg_color="transparent")
        self._time_row.grid(row=11, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 2))
        ctk.CTkLabel(self._time_row, text="待機時間:", text_color="gray70").pack(side="left")
        self._wait_after_entry = ctk.CTkEntry(
            self._time_row, textvariable=self.wait_after_var, width=60)
        self._wait_after_entry.pack(side="left", padx=(6, 4))
        ctk.CTkLabel(self._time_row, text="秒待機してから次へ進む",
                     text_color="gray70").pack(side="left")

        # プロセス待ち行
        self._proc_row = ctk.CTkFrame(sf, fg_color="transparent")
        self._proc_row.grid(row=12, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 2))
        ctk.CTkLabel(self._proc_row, text="プロセス名:", text_color="gray70").pack(side="left")
        ctk.CTkEntry(
            self._proc_row, textvariable=self.wait_process_var, width=160,
            placeholder_text="例: MyApp.exe"
        ).pack(side="left", padx=(6, 12))
        ctk.CTkLabel(self._proc_row, text="タイムアウト:",
                     text_color="gray70").pack(side="left")
        ctk.CTkEntry(
            self._proc_row, textvariable=self.wait_timeout_var, width=55
        ).pack(side="left", padx=(6, 4))
        ctk.CTkLabel(self._proc_row, text="秒",
                     text_color="gray70").pack(side="left")

        ctk.CTkLabel(
            sf,
            text="ℹ AppKeeper起動時に登録順に1回だけ実行されます。プロセス監視は行いません。",
            text_color="gray60", font=ctk.CTkFont(size=10)
        ).grid(row=13, column=0, columnspan=3, sticky="w", padx=16, pady=(4, 2))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=(4, 12))
        ctk.CTkButton(btn_frame, text="保存", width=120, command=self._save).pack(
            side="left", padx=8)
        ctk.CTkButton(btn_frame, text="キャンセル", width=120, fg_color="gray40",
                      command=self.destroy).pack(side="left", padx=8)

        self._on_wait_mode_change()

    def _on_wait_mode_change(self):
        mode = self.wait_mode_var.get()
        # 時間待機行の有効無効
        state_time = "normal" if mode == "time" else "disabled"
        self._wait_after_entry.configure(state=state_time)
        # プロセス待ち行の有効無効
        state_proc = "normal" if mode == "process" else "disabled"
        for w in self._proc_row.winfo_children():
            if isinstance(w, ctk.CTkEntry):
                w.configure(state=state_proc)

    def _browse(self):
        path = filedialog.askopenfilename(
            title="起動ファイルを選択",
            filetypes=[
                ("実行ファイル", "*.bat *.exe *.cmd"),
                ("すべてのファイル", "*.*")
            ]
        )
        if path:
            self.launch_path_var.set(path)

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("入力エラー", "表示名を入力してください。", parent=self)
            return

        mode = self.wait_mode_var.get()
        wait_after = 0
        wait_process = ""
        wait_timeout = 30

        if mode == "time":
            try:
                wait_after = int(self.wait_after_var.get())
                assert wait_after >= 1
            except Exception:
                messagebox.showerror("入力エラー",
                                     "待機時間は1以上の整数を入力してください。", parent=self)
                return
        elif mode == "process":
            wait_process = self.wait_process_var.get().strip()
            if not wait_process:
                messagebox.showerror("入力エラー",
                                     "プロセス名を入力してください。", parent=self)
                return
            try:
                wait_timeout = int(self.wait_timeout_var.get())
                assert wait_timeout >= 1
            except Exception:
                messagebox.showerror("入力エラー",
                                     "タイムアウトは1以上の整数を入力してください。", parent=self)
                return

        self.script.update({
            "name":                  name,
            "launch_path":           self.launch_path_var.get().strip(),
            "exe_args":              self.exe_args_var.get().strip(),
            "show_console":          self.show_console_var.get(),
            "wait_mode":             mode,
            "wait_after":            wait_after,
            "wait_process":          wait_process,
            "wait_process_timeout":  wait_timeout
        })
        if self.on_save:
            self.on_save(self.script)
        self.destroy()


# ─────────────────────────────────────────
# 監視エントリ設定ダイアログ
# ─────────────────────────────────────────
class EntryDialog(ctk.CTkToplevel):
    def __init__(self, parent, entry: dict = None, on_save=None):
        super().__init__(parent)
        self.title("監視エントリの設定")
        self.geometry("640x740")
        self.minsize(600, 640)
        self.resizable(True, True)
        self.grab_set()
        self.lift()
        self.focus_force()

        self.on_save = on_save
        self.entry   = dict(DEFAULT_ENTRY)
        if entry:
            self.entry.update(entry)

        # StringVar を事前に値付きで作成してから UI を構築する
        # （CTkToplevel の非同期再構築による上書きを回避）
        self._init_vars()
        self._build_ui()

    def _init_vars(self):
        """StringVar / BooleanVar を値付きで事前作成する。
        CTkToplevel は __init__ 後に非同期でウィンドウを再構築するため、
        _build_ui() 内で StringVar を作ると値がリセットされる場合がある。
        事前に値を持たせた Var を作っておくことで確実に反映される。"""
        e = self.entry
        path = e.get("launch_path") or e.get("bat_path", "")
        self.name_var           = ctk.StringVar(value=e.get("name", ""))
        self.proc_var           = ctk.StringVar(value=e.get("process", ""))
        self.launch_path_var    = ctk.StringVar(value=path)
        self.exe_args_var       = ctk.StringVar(value=e.get("exe_args", ""))
        self.interval_var       = ctk.StringVar(value=str(e.get("interval", 5)))
        self.delay_var          = ctk.StringVar(value=str(e.get("delay", 3)))
        self.enabled_var        = ctk.BooleanVar(value=e.get("enabled", True))
        self.hang_detect_var    = ctk.BooleanVar(value=e.get("hang_detect", False))
        self.hang_threshold_var = ctk.StringVar(value=str(e.get("hang_threshold", 30)))
        self.hang_action_var    = ctk.StringVar(value=e.get("hang_action", "restart"))
        self.launch_mode_var    = ctk.StringVar(value=e.get("launch_mode", "always"))
        self.max_restarts_var   = ctk.StringVar(value=str(e.get("max_restarts", 3)))
        self.skip_if_running_var = ctk.BooleanVar(value=e.get("skip_if_running", False))

    def _build_ui(self):
        pad = {"padx": 16, "pady": 6}

        # スクロール可能なメインフレーム
        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=0, pady=0)
        scroll.columnconfigure(1, weight=1)
        # 以降のgridはscrollに対して行う
        self._sf = scroll

        # 基本設定
        ctk.CTkLabel(scroll, text="表示名").grid(row=0, column=0, sticky="w", **pad)
        sf = self._sf  # スクロールフレームへの参照

        ctk.CTkEntry(sf, textvariable=self.name_var, width=340).grid(
            row=0, column=1, columnspan=2, sticky="ew", **pad)

        ctk.CTkLabel(sf, text="プロセス名").grid(row=1, column=0, sticky="w", **pad)
        ctk.CTkEntry(sf, textvariable=self.proc_var, width=340,
                     placeholder_text="例: MyUnityApp（拡張子なし可）").grid(
            row=1, column=1, columnspan=2, sticky="ew", **pad)

        # 起動ファイルパス（BAT/EXE 統合・すべてのファイル選択可）
        ctk.CTkLabel(sf, text="起動ファイル").grid(row=2, column=0, sticky="w", **pad)
        self.launch_path_entry = ctk.CTkEntry(
            sf, textvariable=self.launch_path_var, width=260,
            placeholder_text="BATまたはEXEのパスを入力またはドロップ")
        self.launch_path_entry.grid(row=2, column=1, sticky="ew", **pad)
        ctk.CTkButton(sf, text="参照", width=70, command=self._browse_launch).grid(
            row=2, column=2, **pad)

        # 起動引数（常時有効）
        ctk.CTkLabel(sf, text="起動引数").grid(row=3, column=0, sticky="w", **pad)
        ctk.CTkEntry(
            sf, textvariable=self.exe_args_var, width=340,
            placeholder_text="例: -screen-width 1920 -screen-height 1080 -popupwindow"
        ).grid(row=3, column=1, columnspan=2, sticky="ew", **pad)

        ctk.CTkLabel(sf, text="監視間隔（秒）").grid(row=4, column=0, sticky="w", **pad)
        ctk.CTkEntry(sf, textvariable=self.interval_var, width=100).grid(
            row=4, column=1, sticky="w", **pad)

        ctk.CTkLabel(sf, text="再起動待機（秒）").grid(row=5, column=0, sticky="w", **pad)
        ctk.CTkEntry(sf, textvariable=self.delay_var, width=100).grid(
            row=5, column=1, sticky="w", **pad)

        ctk.CTkCheckBox(sf, text="監視を有効にする",
                        variable=self.enabled_var).grid(row=6, column=1, sticky="w", **pad)

        # 区切り線
        ctk.CTkFrame(sf, height=1, fg_color="gray40").grid(
            row=7, column=0, columnspan=3, sticky="ew", padx=16, pady=4)

        # 起動モード設定
        ctk.CTkLabel(sf, text="起動モード",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=8, column=0, sticky="w", padx=16, pady=(4, 2))

        mode_frame = ctk.CTkFrame(sf, fg_color="transparent")
        mode_frame.grid(row=9, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 4))
        ctk.CTkRadioButton(mode_frame, text="常時監視（落ちたら何度でも再起動）",
                           variable=self.launch_mode_var, value="always",
                           command=self._on_mode_toggle).pack(side="left", padx=(0, 12))
        ctk.CTkRadioButton(mode_frame, text="起動時1回のみ",
                           variable=self.launch_mode_var, value="once",
                           command=self._on_mode_toggle).pack(side="left", padx=(0, 12))
        ctk.CTkRadioButton(mode_frame, text="再起動回数制限",
                           variable=self.launch_mode_var, value="limited",
                           command=self._on_mode_toggle).pack(side="left")

        limit_row = ctk.CTkFrame(sf, fg_color="transparent")
        limit_row.grid(row=10, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 4))
        ctk.CTkLabel(limit_row, text="最大再起動回数:", text_color="gray70").pack(side="left")
        self.max_restarts_entry = ctk.CTkEntry(
            limit_row, textvariable=self.max_restarts_var, width=60)
        self.max_restarts_entry.pack(side="left", padx=(6, 4))
        ctk.CTkLabel(limit_row, text="回まで再起動したら監視停止",
                     text_color="gray70").pack(side="left")

        # 区切り線
        ctk.CTkFrame(sf, height=1, fg_color="gray40").grid(
            row=11, column=0, columnspan=3, sticky="ew", padx=16, pady=4)

        # ハング検知設定
        ctk.CTkLabel(sf, text="ハング検知",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=12, column=0, sticky="w", padx=16, pady=(4, 2))

        ctk.CTkCheckBox(sf, text="「応答なし」を検知して再起動する",
                        variable=self.hang_detect_var,
                        command=self._on_hang_toggle).grid(
            row=13, column=1, columnspan=2, sticky="w", **pad)

        ctk.CTkLabel(sf, text="応答なし継続時間（秒）").grid(row=14, column=0, sticky="w", **pad)
        self.hang_threshold_entry = ctk.CTkEntry(
            sf, textvariable=self.hang_threshold_var, width=100)
        self.hang_threshold_entry.grid(row=14, column=1, sticky="w", **pad)
        ctk.CTkLabel(sf, text="秒継続で判定", text_color="gray70").grid(
            row=14, column=2, sticky="w")

        ctk.CTkLabel(sf, text="検知時の動作").grid(row=15, column=0, sticky="w", **pad)
        action_frame = ctk.CTkFrame(sf, fg_color="transparent")
        action_frame.grid(row=15, column=1, columnspan=2, sticky="w", **pad)
        ctk.CTkRadioButton(action_frame, text="強制終了して再起動",
                           variable=self.hang_action_var, value="restart").pack(
            side="left", padx=(0, 12))
        ctk.CTkRadioButton(action_frame, text="ログのみ（再起動しない）",
                           variable=self.hang_action_var, value="log_only").pack(side="left")

        # 区切り線
        ctk.CTkFrame(sf, height=1, fg_color="gray40").grid(
            row=16, column=0, columnspan=3, sticky="ew", padx=16, pady=4)

        # 起動オプション
        ctk.CTkLabel(sf, text="起動オプション",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=17, column=0, sticky="w", padx=16, pady=(4, 2))
        ctk.CTkCheckBox(
            sf,
            text="既に起動中なら起動をスキップ",
            variable=self.skip_if_running_var
        ).grid(row=18, column=1, sticky="w", padx=16, pady=(2, 0))
        ctk.CTkLabel(
            sf,
            text="（監視開始時に既存なら起動せず二重起動を防止）",
            font=ctk.CTkFont(size=11),
            text_color="gray70"
        ).grid(row=19, column=1, columnspan=2, sticky="w", padx=40, pady=(0, 4))

        # 保存・キャンセル（スクロールフレームの外・ウィンドウ下部に固定）
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=(4, 12))
        ctk.CTkButton(btn_frame, text="保存", width=120, command=self._save).pack(
            side="left", padx=8)
        ctk.CTkButton(btn_frame, text="キャンセル", width=120, fg_color="gray40",
                      command=self.destroy).pack(side="left", padx=8)

        self.launch_path_entry.bind("<Drop>", self._on_drop)

        # 初期状態を反映
        self._on_mode_toggle()
        if not self.hang_detect_var.get():
            self.hang_threshold_entry.configure(state="disabled")

    def _on_mode_toggle(self):
        """起動モードに応じて最大再起動回数欄の有効/無効を切り替える"""
        state = "normal" if self.launch_mode_var.get() == "limited" else "disabled"
        self.max_restarts_entry.configure(state=state)

    def _on_hang_toggle(self):
        state = "normal" if self.hang_detect_var.get() else "disabled"
        self.hang_threshold_entry.configure(state=state)

    def _on_drop(self, event):
        path = event.data.strip().strip("{}")
        self.launch_path_var.set(path)

    def _browse_launch(self):
        path = filedialog.askopenfilename(
            title="起動ファイルを選択",
            filetypes=[
                ("実行ファイル", "*.bat *.exe *.cmd"),
                ("すべてのファイル", "*.*")
            ]
        )
        if path:
            self.launch_path_var.set(path)

    def _save(self):
        try:
            interval = int(self.interval_var.get())
            delay    = int(self.delay_var.get())
            assert interval >= 1 and delay >= 0
        except Exception:
            messagebox.showerror(
                "入力エラー",
                "監視間隔は1以上、再起動待機は0以上の整数を入力してください。",
                parent=self)
            return

        # ハング検知が有効な場合のみ継続時間をバリデーション
        hang_thr = 30
        if self.hang_detect_var.get():
            try:
                hang_thr = int(self.hang_threshold_var.get())
                assert hang_thr >= 1
            except Exception:
                messagebox.showerror(
                    "入力エラー",
                    "応答なし継続時間は1以上の整数を入力してください。",
                    parent=self)
                return

        # 回数制限モードのときのみ最大回数をバリデーション
        max_restarts = 3
        if self.launch_mode_var.get() == "limited":
            try:
                max_restarts = int(self.max_restarts_var.get())
                assert max_restarts >= 1
            except Exception:
                messagebox.showerror(
                    "入力エラー",
                    "最大再起動回数は1以上の整数を入力してください。",
                    parent=self)
                return

        self.entry.update({
            "name":             self.name_var.get().strip() or "無名",
            "process":          self.proc_var.get().strip(),
            "launch_path":      self.launch_path_var.get().strip(),
            "exe_args":         self.exe_args_var.get().strip(),
            "interval":         interval,
            "delay":            delay,
            "enabled":          self.enabled_var.get(),
            "launch_mode":      self.launch_mode_var.get(),
            "max_restarts":     max_restarts,
            "hang_detect":      self.hang_detect_var.get(),
            "hang_threshold":   hang_thr,
            "hang_action":      self.hang_action_var.get(),
            "skip_if_running":  self.skip_if_running_var.get()
        })
        if self.on_save:
            self.on_save(self.entry)
        self.destroy()


# ─────────────────────────────────────────
# メインウィンドウ
# ─────────────────────────────────────────
class AppKeeperApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("860x600")
        self.minsize(760, 500)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # ウィンドウアイコンを設定（埋め込みデータから）
        ico_path = _get_temp_ico()
        if ico_path:
            try:
                self.iconbitmap(ico_path)
            except Exception:
                pass
        win_img = _b64_to_pil(_ICON_WINDOW_B64)
        if win_img:
            try:
                # PIL Image → PhotoImage
                buf = io.BytesIO()
                win_img.resize((32, 32), Image.LANCZOS).save(buf, format="PNG")
                buf.seek(0)
                photo = tk.PhotoImage(data=base64.b64encode(buf.read()).decode())
                self.iconphoto(True, photo)
                self._icon_photo = photo  # GC防止
            except Exception:
                pass

        self.config   = load_config()
        self.workers  = {}
        self._tray    = None
        self._tray_thread = None

        self._build_ui()
        self._refresh_list()
        self._refresh_startup_list()  # 初期表示の起動スクリプトタブを描画
        self._start_all_enabled()
        self._setup_tray()

        if self.config.get("start_minimized", False):
            self.after(200, self._hide_to_tray)
        else:
            self.bind("<Unmap>", self._on_unmap)

    # ── UI構築 ──────────────────────────────
    def _build_ui(self):
        header = ctk.CTkFrame(self, height=52, corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text=f"  {APP_NAME}",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(
            side="left", padx=12, pady=10)
        self.status_label = ctk.CTkLabel(header, text="", font=ctk.CTkFont(size=12))
        self.status_label.pack(side="right", padx=16)

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=12, pady=8)

        # 左：タブ切り替え（監視エントリ / 起動スクリプト）
        left = ctk.CTkFrame(main)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        # タブバー（左から: 起動スクリプト → 監視エントリ）
        tab_bar = ctk.CTkFrame(left, fg_color="transparent")
        tab_bar.pack(fill="x", padx=8, pady=(8, 0))
        self._tab_startup_btn = ctk.CTkButton(
            tab_bar, text="起動スクリプト", width=120, height=28,
            command=lambda: self._switch_tab("startup"))
        self._tab_startup_btn.pack(side="left", padx=(0, 4))
        self._tab_watch_btn = ctk.CTkButton(
            tab_bar, text="監視エントリ", width=120, height=28,
            fg_color="gray40",
            command=lambda: self._switch_tab("watch"))
        self._tab_watch_btn.pack(side="left")
        
        # 初期表示に合わせてタブボタンの色を設定
        self._tab_startup_btn.configure(fg_color=["#3B8ED0", "#1F6AA5"])
        self._tab_watch_btn.configure(fg_color="gray40")

        # ── 起動スクリプトパネル ──
        self._panel_startup = ctk.CTkFrame(left, fg_color="transparent")
        self._panel_startup.pack(fill="both", expand=True) # 初期表示

        startup_header = ctk.CTkFrame(self._panel_startup, fg_color="transparent")
        startup_header.pack(fill="x", padx=8, pady=(4, 4))
        ctk.CTkLabel(startup_header,
                     text="AppKeeper起動時に一度だけ実行されます",
                     font=ctk.CTkFont(size=11), text_color="gray60").pack(side="left")
        ctk.CTkButton(startup_header, text="＋ 追加", width=80,
                      command=self._add_startup_script).pack(side="right")

        self.startup_frame = ctk.CTkScrollableFrame(self._panel_startup)
        self.startup_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # ── 監視エントリパネル ──
        self._panel_watch = ctk.CTkFrame(left, fg_color="transparent")
        # 初期は非表示

        watch_header = ctk.CTkFrame(self._panel_watch, fg_color="transparent")
        watch_header.pack(fill="x", padx=8, pady=(4, 4))
        ctk.CTkLabel(watch_header, text="",  # スペーサー
                     font=ctk.CTkFont(size=12)).pack(side="left")
        ctk.CTkButton(watch_header, text="＋ 追加", width=80,
                      command=self._add_entry).pack(side="right")

        self.entry_frame = ctk.CTkScrollableFrame(self._panel_watch)
        self.entry_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._current_tab = "startup"

        # 右：ログ＋設定
        right = ctk.CTkFrame(main, width=295)
        right.pack(side="right", fill="both")
        right.pack_propagate(False)

        ctk.CTkLabel(right, text="ログ",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=10, pady=(8, 2))

        self.log_box = ctk.CTkTextbox(
            right, state="disabled", wrap="word", font=ctk.CTkFont(size=11))
        self.log_box.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        log_btn_row = ctk.CTkFrame(right, fg_color="transparent")
        log_btn_row.pack(fill="x", padx=8, pady=(0, 4))
        ctk.CTkButton(log_btn_row, text="ログをクリア", height=28, fg_color="gray40",
                      command=self._clear_log).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(log_btn_row, text="ログフォルダを開く", height=28, fg_color="gray35",
                      command=self._open_log_folder).pack(side="left", expand=True, fill="x")

        # 設定エリア
        setting_frame = ctk.CTkFrame(right)
        setting_frame.pack(fill="x", padx=8, pady=(0, 8))

        self.autostart_var = ctk.BooleanVar(value=self.config.get("autostart", False))
        ctk.CTkCheckBox(setting_frame, text="Windows起動時に自動起動",
                        variable=self.autostart_var,
                        command=self._toggle_autostart).pack(anchor="w", padx=10, pady=(8, 2))

        self.start_minimized_var = ctk.BooleanVar(
            value=self.config.get("start_minimized", False))
        self.minimized_cb = ctk.CTkCheckBox(
            setting_frame,
            text="起動時にタスクトレイへ最小化",
            variable=self.start_minimized_var,
            command=self._toggle_start_minimized,
            state="normal")
        self.minimized_cb.pack(anchor="w", padx=10, pady=(0, 8))

        ctk.CTkButton(setting_frame, text="すべて開始", height=30,
                      command=self._start_all_enabled).pack(
            fill="x", padx=10, pady=(0, 4))
        ctk.CTkButton(setting_frame, text="すべて停止", height=30, fg_color="gray40",
                      command=self._stop_all).pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkButton(setting_frame, text="AppKeeperを終了", height=30,
                      fg_color="#7b241c", hover_color="#922b21",
                      command=self._quit_app).pack(fill="x", padx=10, pady=(0, 8))

    # ── タブ切り替え ────────────────────────
    def _switch_tab(self, tab: str):
        if tab == "watch":
            self._panel_startup.pack_forget()
            self._panel_watch.pack(fill="both", expand=True)
            self._tab_watch_btn.configure(fg_color=["#3B8ED0", "#1F6AA5"])  # アクティブ色
            self._tab_startup_btn.configure(fg_color="gray40")
        else:
            self._panel_watch.pack_forget()
            self._panel_startup.pack(fill="both", expand=True)
            self._tab_startup_btn.configure(fg_color=["#3B8ED0", "#1F6AA5"])  # アクティブ色
            self._tab_watch_btn.configure(fg_color="gray40")
            self._refresh_startup_list()
        self._current_tab = tab

    # ── エントリリスト描画 ──────────────────
    def _refresh_list(self):
        for w in self.entry_frame.winfo_children():
            w.destroy()

        entries = self.config.get("entries", [])
        if not entries:
            ctk.CTkLabel(self.entry_frame,
                         text="エントリがありません。「＋ 追加」から登録してください。",
                         text_color="gray60").pack(pady=20)
            return

        for i, entry in enumerate(entries):
            self._build_entry_row(i, entry)

        self._update_status()

    def _build_entry_row(self, idx: int, entry: dict):
        row = ctk.CTkFrame(self.entry_frame)
        row.pack(fill="x", pady=3)
        row.columnconfigure(1, weight=1)

        is_watching = idx in self.workers and self.workers[idx].is_alive()
        dot_color   = "#2fa572" if is_watching else "gray50"

        # ● インジケーター
        ctk.CTkLabel(row, text="●", text_color=dot_color, width=24,
                     font=ctk.CTkFont(size=14)).grid(row=0, column=0, rowspan=2,
                                                      padx=(8, 2), pady=4, sticky="ns")

        # 名前・詳細情報
        ctk.CTkLabel(row, text=entry.get("name", ""),
                     font=ctk.CTkFont(size=13, weight="bold"),
                     anchor="w").grid(row=0, column=1, sticky="ew", padx=4, pady=(4, 0))

        proc_text   = entry.get("process", "（プロセス名未設定）") or "（プロセス名未設定）"
        launch_path = entry.get("launch_path") or entry.get("bat_path", "")
        file_text   = os.path.basename(launch_path) if launch_path else "（起動ファイル未設定）"
        hang_text   = " | ハング検知: ON" if entry.get("hang_detect") else ""
        ctk.CTkLabel(row,
                     text=f"PID: {proc_text}  |  {file_text}{hang_text}",
                     font=ctk.CTkFont(size=10), text_color="gray70",
                     anchor="w").grid(row=1, column=1, sticky="ew", padx=4, pady=(0, 4))

        # ボタンエリア（常に右端に固定）
        btn_area = ctk.CTkFrame(row, fg_color="transparent")
        btn_area.grid(row=0, column=2, rowspan=2, padx=6, pady=4, sticky="e")

        if is_watching:
            ctk.CTkButton(btn_area, text="停止", width=52, height=28, fg_color="#c0392b",
                          command=lambda i=idx: self._stop_entry(i)).pack(side="left", padx=2)
        else:
            ctk.CTkButton(btn_area, text="開始", width=52, height=28, fg_color="#2980b9",
                          command=lambda i=idx: self._start_entry(i)).pack(side="left", padx=2)

        ctk.CTkButton(btn_area, text="編集", width=52, height=28, fg_color="gray40",
                      command=lambda i=idx: self._edit_entry(i)).pack(side="left", padx=2)
        ctk.CTkButton(btn_area, text="削除", width=52, height=28, fg_color="gray30",
                      command=lambda i=idx: self._delete_entry(i)).pack(side="left", padx=2)

    # ── エントリ操作 ────────────────────────
    def _add_entry(self):
        EntryDialog(self, entry=None, on_save=self._on_entry_saved_new)

    def _on_entry_saved_new(self, entry):
        self.config.setdefault("entries", []).append(entry)
        save_config(self.config)
        self._refresh_list()

    def _edit_entry(self, idx):
        # 既存エントリのコピーを渡す（編集ダイアログに現在の値を反映）
        entry = dict(self.config["entries"][idx])
        def on_save(updated):
            self.config["entries"][idx] = updated
            save_config(self.config)
            if idx in self.workers:
                self._stop_entry(idx)
                if updated.get("enabled", True):
                    self.after(300, lambda: self._start_entry(idx))
            self._refresh_list()
        EntryDialog(self, entry=entry, on_save=on_save)

    def _delete_entry(self, idx):
        name = self.config["entries"][idx].get("name", "")
        if not messagebox.askyesno("確認", f"「{name}」を削除しますか？", parent=self):
            return
        self._stop_entry(idx)
        del self.config["entries"][idx]
        new_workers = {}
        for k, v in self.workers.items():
            if k < idx:
                new_workers[k] = v
            elif k > idx:
                new_workers[k - 1] = v
        self.workers = new_workers
        save_config(self.config)
        self._refresh_list()

       # ── 起動スクリプト管理 ────────────────────
    def _refresh_startup_list(self):
        for w in self.startup_frame.winfo_children():
            w.destroy()
        scripts = self.config.get("startup_scripts", [])
        if not scripts:
            ctk.CTkLabel(self.startup_frame,
                         text="スクリプトがありません。「＋ 追加」から登録してください。",
                         text_color="gray60").pack(pady=20)
            return
        for i, sc in enumerate(scripts):
            self._build_startup_row(i, sc)

    def _build_startup_row(self, idx: int, sc: dict):
        row = ctk.CTkFrame(self.startup_frame)
        row.pack(fill="x", pady=3)
        row.columnconfigure(1, weight=1)

        ctk.CTkLabel(row, text="▶", text_color="#3B8ED0", width=24,
                     font=ctk.CTkFont(size=14)).grid(
            row=0, column=0, rowspan=2, padx=(8, 2), pady=4, sticky="ns")

        ctk.CTkLabel(row, text=sc.get("name", ""),
                     font=ctk.CTkFont(size=13, weight="bold"),
                     anchor="w").grid(row=0, column=1, sticky="ew", padx=4, pady=(4, 0))

        path = sc.get("launch_path", "")
        file_text = os.path.basename(path) if path else "(起動ファイル未設定)"
        args_text = f"  引数: {sc['exe_args']}" if sc.get("exe_args") else ""
        ctk.CTkLabel(row, text=f"{file_text}{args_text}",
                     font=ctk.CTkFont(size=10), text_color="gray70",
                     anchor="w").grid(row=1, column=1, sticky="ew", padx=4, pady=(0, 4))

        btn_area = ctk.CTkFrame(row, fg_color="transparent")
        btn_area.grid(row=0, column=2, rowspan=2, padx=6, pady=4, sticky="e")
        ctk.CTkButton(btn_area, text="編集", width=52, height=28, fg_color="gray40",
                      command=lambda i=idx: self._edit_startup_script(i)).pack(side="left", padx=2)
        ctk.CTkButton(btn_area, text="削除", width=52, height=28, fg_color="gray30",
                      command=lambda i=idx: self._delete_startup_script(i)).pack(side="left", padx=2)

    def _add_startup_script(self):
        StartupScriptDialog(self, script=None, on_save=self._on_startup_script_saved_new)

    def _on_startup_script_saved_new(self, sc):
        self.config.setdefault("startup_scripts", []).append(sc)
        save_config(self.config)
        self._refresh_startup_list()

    def _edit_startup_script(self, idx):
        sc = dict(self.config["startup_scripts"][idx])
        def on_save(updated):
            self.config["startup_scripts"][idx] = updated
            save_config(self.config)
            self._refresh_startup_list()
        StartupScriptDialog(self, script=sc, on_save=on_save)

    def _delete_startup_script(self, idx):
        name = self.config["startup_scripts"][idx].get("name", "")
        if not messagebox.askyesno("確認", f"「{name}」を削除しますか？", parent=self):
            return
        del self.config["startup_scripts"][idx]
        save_config(self.config)
        self._refresh_startup_list()

    def _run_startup_scripts(self, on_complete=None):
        """起動スクリプトを順番に実行する（別スレッドで実行）。
        on_complete: 全スクリプト完了後に呼び出すコールバック（メインスレッドから呼び出す場合は after() 経由で）
        """
        scripts = self.config.get("startup_scripts", [])
        if not scripts:
            # スクリプトがない場合は即座にコールバック
            if on_complete:
                self.after(0, on_complete)
            return
        def _run():
            for sc in scripts:
                path = sc.get("launch_path", "").strip()
                if not path or not os.path.isfile(path):
                    self._log("起動スクリプト",
                              f"ファイルが見つかりません: {path or '(未設定)'}")
                    continue

                name    = sc.get("name", os.path.basename(path))
                args    = sc.get("exe_args", "").strip()
                # 待機モードの解決（wait_modeがない旧データは自動判定）
                wait_mode = sc.get("wait_mode", "")
                if not wait_mode:
                    if sc.get("wait_process", "").strip():
                        wait_mode = "process"
                    elif int(sc.get("wait_after", 0)) > 0:
                        wait_mode = "time"
                    else:
                        wait_mode = "none"
                wait_s            = int(sc.get("wait_after", 0))
                wait_proc         = sc.get("wait_process", "").strip()
                wait_proc_timeout = int(sc.get("wait_process_timeout", 30))

                try:
                    ext = os.path.splitext(path)[1].lower()
                    cwd = os.path.dirname(path) or "."

                    show_console = sc.get("show_console", True)  # コンソール表示フラグ

                    if sys.platform == "win32":
                        if show_console:
                            # コンソール表示あり: cmd.exe を明示呼び出し + CREATE_NEW_CONSOLE
                            if ext in (".bat", ".cmd"):
                                cmd_parts = ["cmd.exe", "/c", path]
                                if args:
                                    cmd_parts += args.split()
                                subprocess.Popen(
                                    cmd_parts, cwd=cwd,
                                    creationflags=subprocess.CREATE_NEW_CONSOLE
                                )
                            else:
                                cmd_parts = [path] + (args.split() if args else [])
                                subprocess.Popen(
                                    cmd_parts, cwd=cwd,
                                    creationflags=subprocess.CREATE_NEW_CONSOLE
                                )
                        else:
                            # コンソール表示なし: CREATE_NO_WINDOW で非表示起動
                            CREATE_NO_WINDOW = 0x08000000
                            if ext in (".bat", ".cmd"):
                                cmd_parts = ["cmd.exe", "/c", path]
                                if args:
                                    cmd_parts += args.split()
                                subprocess.Popen(
                                    cmd_parts, cwd=cwd,
                                    creationflags=CREATE_NO_WINDOW
                                )
                            else:
                                cmd_parts = [path] + (args.split() if args else [])
                                subprocess.Popen(
                                    cmd_parts, cwd=cwd,
                                    creationflags=CREATE_NO_WINDOW
                                )
                    else:
                        # 非 Windows 環境（開発・テスト用）
                        cmd_str = path + (f" {args}" if args else "")
                        subprocess.Popen(cmd_str, shell=True, cwd=cwd)

                    self._log("起動スクリプト",
                              f"実行しました: {name}" + (f" (引数: {args})" if args else ""))

                except Exception as e:
                    self._log("起動スクリプト", f"起動エラー [{name}]: {e}")
                    continue

                # ④ 待機処理（wait_modeに従って分岐）
                if wait_mode == "process" and wait_proc:
                    self._log("起動スクリプト",
                              f"プロセス起動待ち: {wait_proc} (最大{wait_proc_timeout}秒)")
                    elapsed = 0
                    found   = False
                    while elapsed < wait_proc_timeout:
                        for p in psutil.process_iter(["name"]):
                            try:
                                pn = p.info["name"] or ""
                                if pn.lower().rstrip(".exe") == wait_proc.lower().rstrip(".exe"):
                                    found = True
                                    break
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                        if found:
                            break
                        time.sleep(1)
                        elapsed += 1
                    if found:
                        self._log("起動スクリプト",
                                  f"プロセス確認完了: {wait_proc} ({elapsed}秒後)")
                    else:
                        self._log("起動スクリプト",
                                  f"プロセス待機タイムアウト: {wait_proc} ({wait_proc_timeout}秒)")

                elif wait_mode == "time" and wait_s > 0:
                    self._log("起動スクリプト",
                              f"{wait_s}秒待機中... ({name})")
                    time.sleep(wait_s)

            # 全スクリプト完了後にコールバック（メインスレッドへ转送）
            if on_complete:
                self.after(0, on_complete)

        threading.Thread(target=_run, daemon=True).start()

    # ── 監視制御 ────────────────────────
    def _minimize_for_launch(self):
        """アプリ起動前にAppKeeperを一時最小化する（フォーカス保護回避）"""
        self.after(0, self.iconify)

    def _start_entry(self, idx):
        if idx in self.workers and self.workers[idx].is_alive():
            return
        entry = self.config["entries"][idx]
        if not entry.get("enabled", True):
            return
        worker = WatchWorker(
            entry,
            lambda name, msg: self._log(name, msg),
            minimize_callback=self._minimize_for_launch
        )
        self.workers[idx] = worker
        worker.start()
        self.after(200, self._refresh_list)

    def _stop_entry(self, idx):
        if idx in self.workers:
            self.workers[idx].stop()
            del self.workers[idx]
        self.after(200, self._refresh_list)

    def _start_all_enabled(self):
        """起動スクリプトを全て実行・待機完了後に監視エントリを起動する（直列実行）"""
        def _start_entries():
            for i, entry in enumerate(self.config.get("entries", [])):
                if entry.get("enabled", True):
                    self._start_entry(i)
            self.after(300, self._refresh_list)
        # 起動スクリプト完了後に監視エントリを起動する（on_completeコールバックに渡す）
        self._run_startup_scripts(on_complete=_start_entries)

    def _stop_all(self):
        for idx in list(self.workers.keys()):
            self.workers[idx].stop()
        self.workers.clear()
        self.after(300, self._refresh_list)

    # ── ログ ────────────────────────────────
    def _log(self, name: str, msg: str):
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{name}] {msg}\n"
        write_log_file(line)
        self.after(0, self._append_log, line)

    def _append_log(self, line: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line)
        content = self.log_box.get("1.0", "end").splitlines()
        if len(content) > MAX_LOG:
            self.log_box.delete("1.0", f"{len(content) - MAX_LOG}.0")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _open_log_folder(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(LOG_DIR)

    # ── ステータス ──────────────────────────
    def _update_status(self):
        total   = len(self.config.get("entries", []))
        running = len(self.workers)
        self.status_label.configure(text=f"監視中: {running} / {total} エントリ")

    # ── 自動起動 ────────────────────────────
    def _toggle_autostart(self):
        enabled = self.autostart_var.get()
        self.config["autostart"] = enabled
        save_config(self.config)
        ok = set_autostart(enabled)
        if not ok:
            messagebox.showwarning(
                "警告",
                "レジストリへの書き込みに失敗しました。\n管理者権限で実行してみてください。",
                parent=self)
        # タスクトレイ最小化は自動起動と無関係に常時有効なので状態変更なし

    def _toggle_start_minimized(self):
        self.config["start_minimized"] = self.start_minimized_var.get()
        save_config(self.config)


    # ── タスクトレイ ────────────────────────
    def _setup_tray(self):
        try:
            import pystray
            icon_img = create_tray_icon_image(active=True)
            menu = pystray.Menu(
                pystray.MenuItem("AppKeeperを表示", self._show_window, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("すべて開始", lambda: self._start_all_enabled()),
                pystray.MenuItem("すべて停止", lambda: self._stop_all()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("終了", self._quit_app),
            )
            self._tray = pystray.Icon(APP_NAME, icon_img, APP_NAME, menu)
            self._tray_thread = threading.Thread(target=self._tray.run, daemon=True)
            self._tray_thread.start()
        except Exception:
            pass

    def _hide_to_tray(self):
        self.withdraw()
        self.bind("<Unmap>", self._on_unmap)

    def _show_window(self):
        self.after(0, self._do_show_window)

    def _do_show_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_unmap(self, event):
        if self.state() == "iconic":
            self.withdraw()

    def _on_close(self):
        self.withdraw()

    def _quit_app(self):
        self._stop_all()
        if self._tray:
            try:
                self._tray.stop()
            except Exception:
                pass
        # 一時ファイルを削除
        global _TEMP_ICO_PATH
        if _TEMP_ICO_PATH and os.path.isfile(_TEMP_ICO_PATH):
            try:
                os.unlink(_TEMP_ICO_PATH)
            except Exception:
                pass
        self.after(0, self.destroy)

    def destroy(self):
        self._stop_all()
        super().destroy()


# ─────────────────────────────────────────
# エントリポイント
# ─────────────────────────────────────────
if __name__ == "__main__":
    app = AppKeeperApp()
    app.mainloop()
