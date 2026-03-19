# AppKeeper

![AppKeeper Logo](assets/icon_preview_256.png)

AppKeeper は、Windows上で動作するアプリケーションやスクリプトの起動管理・死活監視を自動化するためのツールです。特に、PC起動時に一度だけ実行が必要な初期化処理と、その後の常時監視をシームレスに連携させることで、無人環境での安定稼働を実現します。


## 🚀 クイックスタート

1. **[最新版をダウンロード](https://github.com/atskdh/AppKeeper/releases/latest )**
   - `AppKeeper_v2.9.zip` をダウンロードして解凍してください。
2. **AppKeeper.exe を実行**
   - 同梱の `config.json` をデフォルトサンプルConfigです。
3. **マニュアルを確認**
   - 詳細な使い方は [ビジュアルマニュアル](https://atskdh.github.io/AppKeeper/docs/AppKeeper_manual_v29.html ) をご覧ください。


## 主な機能

*   **起動スクリプト管理**: PC起動時に一度だけ実行するBAT/CMDファイルなどを登録し、指定した条件（時間待機、プロセス起動待ち）が満たされるまで次の処理を保留します。
*   **プロセス死活監視**: 登録されたアプリケーションが停止した場合、自動的に再起動します。
*   **ハングアップ検知**: アプリケーションが「応答なし」状態になった場合も検知し、自動再起動します。
*   **二重起動防止**: 起動スクリプトと監視エントリを併用する際、既に起動中のアプリに対してAppKeeperが重ねて起動をかけるのを防ぎます。
*   **ログ記録**: すべての起動・再起動イベントをログファイルに記録します。
*   **タスクトレイ常駐**: バックグラウンドで動作し、タスクトレイから設定変更や終了が可能です。



## 開発者向け情報

ソースコードからビルドしたい場合や、カスタマイズしたい方は以下を参照してください。

## 動作環境

*   Windows 10 / 11
*   Python 3.10 以上

## インストールと実行

AppKeeper は PyInstaller を使用して単一の実行ファイル（.exe）としてビルドできます。

### 1. リポジトリのクローン

```bash
git clone https://github.com/atskdh/AppKeeper.git
cd AppKeeper
```

### 2. 必要なライブラリのインストール

```bash
pip install customtkinter psutil pystray pillow pyinstaller
```

### 3. アイコンデータの生成

`assets/` フォルダ内の `gen_icon_data.py` を実行して、プログラムに埋め込むアイコンデータを生成します。

```bash
python assets/gen_icon_data.py
```

### 4. アプリケーションのビルド

`build_windows.bat` を実行すると、`dist/` フォルダ内に `AppKeeper.exe` が生成されます。

```bash
build_windows.bat
```

または、直接 PyInstaller コマンドを使用する場合：

```bash
python -m PyInstaller --clean AppKeeper.spec
```

### 5. 実行

`dist/AppKeeper.exe` をダブルクリックして実行します。

## フォルダ構成

```
AppKeeper/
├── README.md             # このファイル
├── LICENSE               # ライセンス情報
├── .gitignore            # Git管理から除外するファイル設定
├── build_windows.bat     # Windows向けビルドスクリプト
├── AppKeeper.spec        # PyInstallerビルド設定ファイル
│
├── src/                  # プログラムのソースコード
│   ├── appkeeper.py      # メインプログラム
│   └── icon_data.py      # 埋め込みアイコンデータ
│
├── assets/               # アイコン素材と生成ツール
│   ├── appkeeper.ico     # 最終的なアイコンファイル
│   ├── gen_icon_data.py  # icon_data.py生成スクリプト
│   ├── icon_source.png   # アイコンの元画像
│   └── make_icon.py      # .pngから.icoを生成するスクリプト
│
└── docs/                 # ドキュメント
    └── AppKeeper_manual_v29.html # 詳細マニュアル
```

## 使い方

詳細な使い方は `docs/AppKeeper_manual_v29.html` を参照してください。

## ライセンス

このプロジェクトは MIT ライセンスの下で公開されています。詳細は `LICENSE` ファイルを参照してください。

## 貢献

バグ報告や機能改善の提案は、GitHubのIssuesまたはPull Requestでお気軽にお寄せください。

---

© 2026 [atsushi-k] - All Rights Reserved.
