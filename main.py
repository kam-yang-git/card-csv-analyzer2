# -*- coding: utf-8 -*-
"""
main.py
-------
gui.py から呼ぶ「窓口」。
実際の処理は db / merge / analyze に任せ、GUI側が import しやすい名前でまとめる。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import db
import merge
import analyze as analyze_mod
from paths import (
    CATEGORIES,
    DATE_FORMAT_CANDIDATES,
    ENCODING_CANDIDATES,
    MINUS_FORMAT_CANDIDATES,
    MSG_ERROR,
    MSG_EXCLUDED,
    ensure_directories,
)
from normalize import make_lookup_key


def initialize() -> None:
    """アプリ起動時にフォルダ作成とDBテーブル準備を行う。"""
    ensure_directories()
    db.init_db()


# ----- GUIが参照する定数（末尾 _ は「main経由で渡している」目印） -----
CATEGORIES_ = CATEGORIES  # 分類の選択肢
ENCODING_CANDIDATES_ = ENCODING_CANDIDATES  # 文字コード候補
DATE_FORMAT_CANDIDATES_ = DATE_FORMAT_CANDIDATES  # 日付書式候補
MINUS_FORMAT_CANDIDATES_ = MINUS_FORMAT_CANDIDATES  # マイナス表記候補
MSG_ERROR_ = MSG_ERROR  # エラー時ポップアップ文言
MSG_EXCLUDED_ = MSG_EXCLUDED  # 除外行ありのポップアップ文言


# ----- プロファイル -----

def list_profiles(enabled_only: bool = False) -> list[dict[str, Any]]:
    """プロファイル一覧を返す。enabled_only=True なら有効なものだけ。"""
    return db.list_profiles(enabled_only=enabled_only)


def get_profile(profile_id: int) -> dict[str, Any] | None:
    """IDでプロファイルを1件取得する。無ければ None。"""
    return db.get_profile(profile_id)


def save_profile(data: dict[str, Any]) -> int:
    """プロファイルを新規保存または更新し、IDを返す。"""
    return db.save_profile(data)


def set_profile_enabled(profile_id: int, enabled: bool) -> None:
    """プロファイルの有効／無効を切り替える。"""
    db.set_profile_enabled(profile_id, enabled)


def delete_profile(profile_id: int) -> None:
    """プロファイルを削除する。"""
    db.delete_profile(profile_id)


def duplicate_profile(profile_id: int, new_name: str) -> int:
    """既存プロファイルを別名で複製し、新しいIDを返す。"""
    return db.duplicate_profile(profile_id, new_name)


# ----- 店名辞書 -----

def list_merchant_aliases(search: str = "") -> list[dict[str, Any]]:
    """店名辞書の一覧。search があれば部分一致で絞り込み。"""
    return db.list_merchant_aliases(search)


def save_merchant_alias(data: dict[str, Any]) -> int:
    """店名辞書を保存（新規/更新）し、IDを返す。"""
    return db.save_merchant_alias(data)


def delete_merchant_alias(alias_id: int) -> None:
    """店名辞書の1件を削除する。"""
    db.delete_merchant_alias(alias_id)


def reapply_merchant_aliases() -> int:
    """店名辞書を手修正以外の明細へ再適用し、更新件数を返す。"""
    return db.reapply_merchant_aliases()


# ----- 未登録店名 -----

def list_unregistered_merchants() -> list[dict[str, Any]]:
    """辞書未登録の店名一覧を返す。"""
    return db.list_unregistered_merchants()


def register_unregistered_as_alias(
    *,
    lookup_key: str,
    original_name: str,
    normalized_name: str,
    category: str,
) -> int:
    """未登録店名を店名辞書へ登録する（登録後は未登録一覧から消える）。"""
    alias_id = db.save_merchant_alias(
        {
            "lookup_key": lookup_key or make_lookup_key(original_name),
            "original_name": original_name,
            "normalized_name": normalized_name,
            "default_category": category,
            "enabled": 1,
        }
    )
    return alias_id


# ----- マージ -----

def preview_csv(path: str | Path, profile: dict[str, Any], limit: int = 20):
    """テスト読込用。変換できた明細の先頭だけ返す。"""
    return merge.preview_csv(Path(path), profile, limit=limit)


def validate_file(path: str | Path, profile: dict[str, Any]) -> tuple[bool, str, int]:
    """1ファイルを検証する。戻り値: (成功か, メッセージ, 有効件数)。"""
    return merge.validate_file(Path(path), profile)


def merge_files(
    file_profile_pairs: list[tuple[str | Path, dict[str, Any]]],
    progress: Callable[[str], None] | None = None,
) -> merge.MergeResult:
    """複数CSVをマージしてDBへ蓄積する。progress に進捗メッセージ用コールバックを渡せる。"""
    jobs = [
        merge.FileJob(path=Path(path), profile=profile)
        for path, profile in file_profile_pairs
    ]
    return merge.merge_files(jobs, progress=progress)


# ----- 明細 -----

def list_transactions(
    *,
    year_month_from: str | None = None,
    year_month_to: str | None = None,
    card_company: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """蓄積明細の一覧。"""
    return db.list_transactions(
        year_month_from=year_month_from,
        year_month_to=year_month_to,
        card_company=card_company,
        category=category,
    )


def count_transactions() -> int:
    """明細の総件数。"""
    return db.count_transactions()


def transaction_year_months() -> list[str]:
    """明細に含まれる年月一覧。"""
    return db.transaction_year_months()


def transaction_card_companies() -> list[str]:
    """明細に含まれるカード会社一覧。"""
    return db.transaction_card_companies()


def update_transaction_category(tx_id: int, category: str) -> None:
    """明細の分類を手修正する。"""
    db.update_transaction_category(tx_id, category)


def export_transactions_csv(path: str | Path) -> int:
    """明細をバックアップCSVへ書き出す。"""
    return db.export_transactions_csv(path)


def restore_transactions_csv(path: str | Path) -> int:
    """バックアップCSVで明細を差し替え復元する。"""
    return db.restore_transactions_csv(path)


# ----- 分析 -----

def load_transactions_df():
    """DB明細を分析用 DataFrame として返す。"""
    return analyze_mod.load_transactions_df()


def available_year_months(df=None) -> list[str]:
    """データに含まれる年月（YYYY/MM）の一覧。"""
    return analyze_mod.available_year_months(df)


def available_card_companies(df=None) -> list[str]:
    """データに含まれるカード会社名の一覧。"""
    return analyze_mod.available_card_companies(df)


def analyze(
    df,
    *,
    year_month_from: str | None = None,
    year_month_to: str | None = None,
    card_company: str | None = None,
    category: str | None = None,
    include_negative: bool = True,
):
    """絞り込み条件つきで分類集計と円グラフを作る。"""
    return analyze_mod.analyze(
        df,
        year_month_from=year_month_from,
        year_month_to=year_month_to,
        card_company=card_company,
        category=category,
        include_negative=include_negative,
    )


def save_summary_csv(summary, total_amount: int, total_count: int) -> Path:
    """分類集計表を results にCSV保存し、保存先パスを返す。"""
    return analyze_mod.save_summary_csv(summary, total_amount, total_count)


def save_pie_png(figure) -> Path:
    """円グラフを results にPNG保存し、保存先パスを返す。"""
    return analyze_mod.save_pie_png(figure)


def save_detail_csv(filtered_df, path: str | Path | None = None) -> Path:
    """フィルタ後明細をCSV保存する。"""
    return analyze_mod.save_detail_csv(filtered_df, path)


def make_lookup_key_(value: str) -> str:
    """店名の照合キーを作る（GUIから呼びやすい別名）。"""
    return make_lookup_key(value)
