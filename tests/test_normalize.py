# -*- coding: utf-8 -*-
"""AT-N*: normalize のユニットテスト。"""
from __future__ import annotations

from datetime import datetime

import pytest

from normalize import (
    format_amount,
    format_date,
    make_lookup_key,
    parse_amount,
    parse_date,
    resolve_category,
)


# AT-N01
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ｱﾏｿﾞﾝ", "アマゾン"),
        ("  店名  ", "店名"),
        ("A　B", "A B"),  # 全角空白も NFKC 後に整理
        ("foo   bar", "foo bar"),
        (None, ""),
    ],
)
def test_make_lookup_key(raw, expected):
    assert make_lookup_key(raw) == expected


# AT-N02
def test_parse_and_format_date_slash():
    dt = parse_date("2026/07/25", "%Y/%m/%d")
    assert dt == datetime(2026, 7, 25)
    assert format_date(dt) == "2026/07/25"


def test_parse_and_format_date_japanese():
    dt = parse_date("2026年07月25日", "%Y年%m月%d日")
    assert dt is not None
    assert format_date(dt) == "2026/07/25"


# AT-N03
@pytest.mark.parametrize(
    ("raw", "kwargs", "expected"),
    [
        ("1,200", {"thousands_separator": ","}, 1200),
        ("¥1,200", {"thousands_separator": ",", "currency_symbol": "¥"}, 1200),
        ("1200円", {"currency_symbol": "円"}, 1200),
        ("500", {}, 500),
    ],
)
def test_parse_amount_positive(raw, kwargs, expected):
    assert parse_amount(raw, **kwargs) == expected


def test_format_amount():
    assert format_amount(1200) == "1,200"
    assert format_amount(-300) == "-300"


# AT-N04
def test_parse_amount_minus_sign():
    assert parse_amount("-1,000", thousands_separator=",", minus_format="sign") == -1000


def test_parse_amount_minus_paren():
    assert parse_amount("(1,000)", thousands_separator=",", minus_format="paren") == -1000


# AT-N05
@pytest.mark.parametrize(
    "raw",
    ["", None, "not-a-date", "2026-13-01"],
)
def test_parse_date_invalid(raw):
    assert parse_date(raw, "%Y/%m/%d") is None


@pytest.mark.parametrize(
    "raw",
    ["", None, "abc", "1.5", "1,2a0"],
)
def test_parse_amount_invalid(raw):
    assert parse_amount(raw, thousands_separator=",") is None


# AT-N06
def test_resolve_category_miss():
    name, category = resolve_category("存在しない店", alias_map={})
    assert name == ""
    assert category == "未分類"


# AT-N07
def test_resolve_category_hit():
    alias_map = {
        "アマゾン": {
            "normalized_name": "Amazon",
            "default_category": "変動費",
        }
    }
    name, category = resolve_category("アマゾン", alias_map=alias_map)
    assert name == "Amazon"
    assert category == "変動費"


def test_resolve_category_empty_default_becomes_uncategorized():
    alias_map = {
        "店X": {
            "normalized_name": "店X",
            "default_category": "",
        }
    }
    name, category = resolve_category("店X", alias_map=alias_map)
    assert name == "店X"
    assert category == "未分類"
