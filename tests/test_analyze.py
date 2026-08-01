# -*- coding: utf-8 -*-
"""AT-A*: analyze の統合テスト。"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import pytest

import analyze as analyze_mod
import db


@pytest.fixture
def sample_merged_df() -> pd.DataFrame:
    """load_transactions_df 相当の列を持つサンプル。"""
    raw = pd.DataFrame(
        [
            {
                "利用年月日": "2026/01/10",
                "利用店名": "店A",
                "正規化店名": "店A",
                "分類": "固定費",
                "利用金額": 1000,
                "カード会社": "A社",
                "取込元ファイル名": "a.csv",
                "取込行番号": 2,
            },
            {
                "利用年月日": "2026/01/20",
                "利用店名": "店B",
                "正規化店名": "店B",
                "分類": "変動費",
                "利用金額": 500,
                "カード会社": "A社",
                "取込元ファイル名": "a.csv",
                "取込行番号": 3,
            },
            {
                "利用年月日": "2026/02/05",
                "利用店名": "店C",
                "正規化店名": "店C",
                "分類": "未分類",
                "利用金額": 2000,
                "カード会社": "B社",
                "取込元ファイル名": "b.csv",
                "取込行番号": 2,
            },
            {
                "利用年月日": "2026/02/10",
                "利用店名": "返金",
                "正規化店名": "返金",
                "分類": "変動費",
                "利用金額": -200,
                "カード会社": "A社",
                "取込元ファイル名": "a.csv",
                "取込行番号": 4,
            },
        ]
    )
    raw["利用金額_num"] = raw["利用金額"].astype(int)
    raw["利用年月日_dt"] = pd.to_datetime(raw["利用年月日"], format="%Y/%m/%d")
    raw["年月"] = raw["利用年月日_dt"].dt.strftime("%Y/%m")
    return raw


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def test_filter_by_year_month(sample_merged_df):
    # AT-A01
    result = analyze_mod.analyze(
        sample_merged_df,
        year_month_from="2026/02",
        year_month_to="2026/02",
    )
    assert result.total_count == 2  # 2月の2件（未分類 + 返金）
    months = set(result.filtered_df["年月"])
    assert months == {"2026/02"}


def test_filter_card_and_category(sample_merged_df):
    # AT-A02
    result = analyze_mod.analyze(
        sample_merged_df,
        card_company="A社",
        category="固定費",
    )
    assert result.total_count == 1
    assert result.total_amount == 1000


def test_exclude_negative(sample_merged_df):
    # AT-A03
    result = analyze_mod.analyze(sample_merged_df, include_negative=False)
    assert (result.filtered_df["利用金額_num"] >= 0).all()
    assert result.total_count == 3


def test_summary_and_uncategorized(sample_merged_df):
    # AT-A04
    result = analyze_mod.analyze(sample_merged_df)
    assert set(result.summary["分類"]) >= {"固定費", "変動費", "臨時費", "未分類"}
    assert result.uncategorized_amount == 2000
    assert result.uncategorized_count == 1
    assert "割合" in result.summary.columns
    assert result.figure is not None


def test_save_summary_and_pie(app_dirs, sample_merged_df):
    # AT-A05, AT-A06
    result = analyze_mod.analyze(sample_merged_df)
    csv_path = analyze_mod.save_summary_csv(
        result.summary, result.total_amount, result.total_count
    )
    png_path = analyze_mod.save_pie_png(result.figure)

    assert csv_path.exists()
    assert csv_path.name.startswith("category_summary_")
    assert png_path.exists()
    assert png_path.name.startswith("category_pie_")
    assert png_path.stat().st_size > 0


def test_load_transactions_from_db(app_dirs):
    db.insert_transactions(
        [
            {
                "利用年月日": "2026/03/01",
                "利用店名": "店",
                "正規化店名": "店",
                "分類": "臨時費",
                "利用金額": 300,
                "カード会社": "C社",
                "取込元ファイル名": "c.csv",
                "取込行番号": 2,
                "分類手動": 0,
            }
        ]
    )
    df = analyze_mod.load_transactions_df()
    assert "利用金額_num" in df.columns
    assert df.iloc[0]["利用金額_num"] == 300
    assert "2026/03" in analyze_mod.available_year_months(df)
    assert "C社" in analyze_mod.available_card_companies(df)


def test_save_detail_csv(app_dirs, sample_merged_df):
    result = analyze_mod.analyze(sample_merged_df, category="固定費")
    path = analyze_mod.save_detail_csv(result.filtered_df)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "利用年月日" in text
    assert "分類手動" not in text
