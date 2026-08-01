# -*- coding: utf-8 -*-
"""共通 fixture: 一時 DB / results / log へ差し替え、本番データを汚さない。"""
from __future__ import annotations

import os
from pathlib import Path

import matplotlib

import pytest

# GUI なしで円グラフを生成するため Agg を先に設定
matplotlib.use("Agg")
os.environ.setdefault("MPLBACKEND", "Agg")


@pytest.fixture
def app_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """paths / db / merge / analyze の保存先を tmp_path 配下に切り替える。"""
    import paths
    import db
    import merge
    import analyze

    root = tmp_path
    data_dir = root / "data"
    results_dir = root / "results"
    log_dir = root / "log"
    db_path = data_dir / "app.db"

    monkeypatch.setattr(paths, "ROOT_DIR", root)
    monkeypatch.setattr(paths, "DATA_DIR", data_dir)
    monkeypatch.setattr(paths, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(paths, "LOG_DIR", log_dir)
    monkeypatch.setattr(paths, "DB_PATH", db_path)

    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(merge, "LOG_DIR", log_dir)
    monkeypatch.setattr(analyze, "RESULTS_DIR", results_dir)

    paths.ensure_directories()
    db.init_db()
    return root


@pytest.fixture
def sample_profile() -> dict:
    """UTF-8・ヘッダー1行目・標準列名のプロファイル辞書。"""
    return {
        "profile_name": "テストカード",
        "card_company": "テストカード会社",
        "encoding": "utf-8",
        "header_row": 1,
        "footer_rows": 0,
        "date_column": "利用日",
        "merchant_column": "利用店名",
        "amount_column": "利用金額",
        "date_format": "%Y/%m/%d",
        "thousands_separator": ",",
        "currency_symbol": "",
        "minus_format": "sign",
        "enabled": 1,
    }


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures"
