# -*- coding: utf-8 -*-
"""
paths.py
--------
アプリ全体で使う「フォルダの場所」や「決まった文言・候補一覧」をまとめたファイル。
ここを変えれば、保存先や分類名などを一括で揃えられる。
"""
from __future__ import annotations

from pathlib import Path

# このファイル（paths.py）がある場所＝プロジェクトのルートフォルダ
ROOT_DIR = Path(__file__).resolve().parent

# データベースを置くフォルダ
DATA_DIR = ROOT_DIR / "data"

# 分析結果CSV/PNG・バックアップ候補を置くフォルダ
RESULTS_DIR = ROOT_DIR / "results"

# マージ処理のログを置くフォルダ
LOG_DIR = ROOT_DIR / "log"

# SQLiteのデータベースファイル本体
DB_PATH = DATA_DIR / "app.db"

# 支出の分類（コンボボックスなどで使う選択肢）
CATEGORIES = ("固定費", "変動費", "臨時費", "未分類")

# 辞書に無い店名など、分類が決まらないときの値
CATEGORY_UNCATEGORIZED = "未分類"

# プロファイル画面で選べる文字コードの候補
ENCODING_CANDIDATES = ("cp932", "utf-8-sig", "utf-8")

# プロファイル画面で選べる日付書式の候補（strftime形式）
DATE_FORMAT_CANDIDATES = ("%Y/%m/%d", "%Y-%m-%d", "%Y年%m月%d日")

# マイナス金額の書き方候補
#   sign  … -1000 のようにマイナス記号
#   paren … (1,000) のように括弧
MINUS_FORMAT_CANDIDATES = ("sign", "paren")

# マージ結果・分析明細CSVの列の並び
MERGED_COLUMNS = [
    "利用年月日",
    "利用店名",
    "正規化店名",
    "分類",
    "利用金額",
    "カード会社",
    "取込元ファイル名",
    "取込行番号",
]

# 明細バックアップ／リストアCSVの列（分類手動を含む）
BACKUP_COLUMNS = [
    *MERGED_COLUMNS,
    "分類手動",
]

# 除外行があったときに画面へ出す短いメッセージ
MSG_EXCLUDED = "除外行があります。詳細はログを確認してください。"

# 検証エラーなどでマージ失敗したときに画面へ出す短いメッセージ
MSG_ERROR = "エラーが発生しました。詳細はログを確認してください。"


def ensure_directories() -> None:
    """data / results / log フォルダが無ければ作成する。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
