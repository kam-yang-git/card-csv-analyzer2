# -*- coding: utf-8 -*-
"""
analyze.py
----------
DBに蓄積した明細を読み、分類ごとの集計と円グラフを作る。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

import db
from normalize import format_amount
from paths import CATEGORIES, CATEGORY_UNCATEGORIZED, MERGED_COLUMNS, RESULTS_DIR, ensure_directories


def _setup_japanese_font() -> str:
    """
    円グラフの日本語が文字化けしないようフォントを選ぶ。
    優先: Meiryo → Yu Gothic → MS Gothic。見つかった名前を返す。
    """
    preferred = ["Meiryo", "Yu Gothic", "MS Gothic"]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in preferred:
        if name in available:
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False  # マイナス記号の文字化け防止
            return name
    plt.rcParams["axes.unicode_minus"] = False
    return ""


def load_transactions_df() -> pd.DataFrame:
    """
    DBの明細を読み、分析しやすい列を追加する。
      利用金額_num … 整数金額
      利用年月日_dt … 日付型
      年月 … YYYY/MM（期間フィルタ用）
    """
    rows = db.list_transactions()
    if not rows:
        df = pd.DataFrame(
            columns=[
                *MERGED_COLUMNS,
                "id",
                "分類手動",
                "利用金額_num",
                "利用年月日_dt",
                "年月",
            ]
        )
        return df

    df = pd.DataFrame(rows)
    df["利用金額_num"] = df["利用金額"].astype(int)
    df["利用年月日_dt"] = pd.to_datetime(
        df["利用年月日"], format="%Y/%m/%d", errors="coerce"
    )
    df["年月"] = df["利用年月日_dt"].dt.strftime("%Y/%m")
    return df


def available_year_months(df: pd.DataFrame | None = None) -> list[str]:
    """データに出てくる年月（YYYY/MM）の一覧を昇順で返す。"""
    if df is None:
        return db.transaction_year_months()
    if df.empty or "年月" not in df.columns:
        return []
    values = sorted({v for v in df["年月"].dropna().tolist() if v and v != "NaT"})
    return values


def available_card_companies(df: pd.DataFrame | None = None) -> list[str]:
    """データに出てくるカード会社名の一覧。"""
    if df is None:
        return db.transaction_card_companies()
    if df.empty or "カード会社" not in df.columns:
        return []
    return sorted({str(v) for v in df["カード会社"].tolist() if str(v).strip()})


@dataclass
class AnalysisResult:
    """集計結果一式（表・合計・グラフ）。"""

    summary: pd.DataFrame  # 分類ごとの合計・件数・割合
    total_amount: int  # 金額の総合計
    total_count: int  # 明細件数の合計
    uncategorized_amount: int  # 未分類の金額
    uncategorized_count: int  # 未分類の件数
    filtered_df: pd.DataFrame  # 絞り込み後の明細
    figure: Any  # matplotlib の Figure（円グラフ）


def analyze(
    df: pd.DataFrame,
    *,
    year_month_from: str | None = None,
    year_month_to: str | None = None,
    card_company: str | None = None,
    category: str | None = None,
    include_negative: bool = True,
) -> AnalysisResult:
    """
    条件で絞り込んで分類集計し、円グラフ付きの結果を返す。
    include_negative=False のときはマイナス金額（返金など）を除く。
    """
    work = df.copy()

    if year_month_from:
        work = work[work["年月"] >= year_month_from]
    if year_month_to:
        work = work[work["年月"] <= year_month_to]
    if card_company and card_company != "すべて":
        work = work[work["カード会社"] == card_company]
    if category and category != "すべて":
        work = work[work["分類"] == category]
    if not include_negative:
        work = work[work["利用金額_num"] >= 0]

    # 分類ごとに合計と件数
    if work.empty:
        grouped = pd.DataFrame(
            {"分類": list(CATEGORIES), "利用金額合計": 0, "明細件数": 0}
        )
    else:
        grouped = (
            work.groupby("分類", dropna=False)
            .agg(利用金額合計=("利用金額_num", "sum"), 明細件数=("利用金額_num", "count"))
            .reset_index()
        )
        # 固定費〜未分類が必ず行として並ぶように穴埋め
        base = pd.DataFrame({"分類": list(CATEGORIES)})
        grouped = base.merge(grouped, on="分類", how="left").fillna(
            {"利用金額合計": 0, "明細件数": 0}
        )
    grouped["利用金額合計"] = grouped["利用金額合計"].astype(int)
    grouped["明細件数"] = grouped["明細件数"].astype(int)

    total_amount = int(grouped["利用金額合計"].sum())
    total_count = int(grouped["明細件数"].sum())
    if total_amount != 0:
        grouped["割合"] = grouped["利用金額合計"].map(
            lambda v: f"{(v / total_amount) * 100:.2f}%"
        )
    else:
        grouped["割合"] = "0.00%"

    uncategorized = grouped[grouped["分類"] == CATEGORY_UNCATEGORIZED].iloc[0]
    uncategorized_amount = int(uncategorized["利用金額合計"])
    uncategorized_count = int(uncategorized["明細件数"])

    _setup_japanese_font()
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    pie_df = grouped[grouped["利用金額合計"] != 0].copy()
    # 円グラフは負の値を描けないので、扇の大きさは絶対値を使う
    if pie_df.empty or pie_df["利用金額合計"].abs().sum() == 0:
        ax.text(0.5, 0.5, "表示するデータがありません", ha="center", va="center")
        ax.axis("off")
    else:
        sizes = pie_df["利用金額合計"].abs().tolist()
        labels = [
            f"{row.分類}\n{format_amount(int(row.利用金額合計))}円"
            for row in pie_df.itertuples()
        ]
        # 未分類は赤系にして登録漏れに気づきやすくする
        colors = {
            "固定費": "#4C78A8",
            "変動費": "#F58518",
            "臨時費": "#54A24B",
            "未分類": "#E45756",
        }
        pie_colors = [colors.get(c, "#9D755D") for c in pie_df["分類"]]
        ax.pie(
            sizes,
            labels=labels,
            colors=pie_colors,
            autopct="%1.1f%%",
            startangle=90,
            textprops={"fontsize": 9},
        )
        ax.set_title("分類別利用金額")
        ax.axis("equal")

    fig.tight_layout()
    return AnalysisResult(
        summary=grouped,
        total_amount=total_amount,
        total_count=total_count,
        uncategorized_amount=uncategorized_amount,
        uncategorized_count=uncategorized_count,
        filtered_df=work,
        figure=fig,
    )


def save_summary_csv(summary: pd.DataFrame, total_amount: int, total_count: int) -> Path:
    """分類集計表を results にCSV保存し、保存先パスを返す。"""
    ensure_directories()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"category_summary_{stamp}.csv"
    out = summary.copy()
    out["利用金額合計"] = out["利用金額合計"].map(lambda v: format_amount(int(v)))
    # 表の末尾に合計行を足す
    total_row = pd.DataFrame(
        [
            {
                "分類": "合計",
                "利用金額合計": format_amount(total_amount),
                "明細件数": total_count,
                "割合": "100.00%" if total_amount != 0 or total_count != 0 else "0.00%",
            }
        ]
    )
    out = pd.concat([out, total_row], ignore_index=True)
    out.to_csv(
        path,
        index=False,
        encoding="utf-8",
        quoting=csv.QUOTE_ALL,
        lineterminator="\n",
    )
    return path


def save_pie_png(figure: Any) -> Path:
    """円グラフを results にPNG保存し、保存先パスを返す。"""
    ensure_directories()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"category_pie_{stamp}.png"
    figure.savefig(path, dpi=120, bbox_inches="tight")
    return path


def save_detail_csv(filtered_df: pd.DataFrame, path: str | Path | None = None) -> Path:
    """フィルタ後明細を8列CSVで保存する。"""
    ensure_directories()
    if path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = RESULTS_DIR / f"category_detail_{stamp}.csv"
    else:
        path = Path(path)

    if filtered_df.empty:
        out = pd.DataFrame(columns=MERGED_COLUMNS)
    else:
        out = filtered_df.copy()
        for col in MERGED_COLUMNS:
            if col not in out.columns:
                out[col] = ""
        out = out[MERGED_COLUMNS].copy()
        out["利用金額"] = out["利用金額"].map(
            lambda v: format_amount(int(str(v).replace(",", "")))
        )
        out["取込行番号"] = out["取込行番号"].map(lambda v: str(int(v)))

    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(
        path,
        index=False,
        encoding="utf-8",
        quoting=csv.QUOTE_ALL,
        lineterminator="\n",
    )
    return path
