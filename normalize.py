# -*- coding: utf-8 -*-
"""
normalize.py
------------
日付・金額・店名を「比較や計算しやすい形」に整える。
マージや辞書照合の前準備として使う。
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any

from paths import CATEGORY_UNCATEGORIZED


def make_lookup_key(value: Any) -> str:
    """
    店名の「照合キー」を作る。

    半角カナ→全角など（NFKC）、前後の空白削除、連続空白の整理を行い、
    表記ゆれを少し吸収したうえで辞書と突き合わせるための文字列にします。
    出力CSVの「利用店名」（原文）は変えません。
    """
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKC", text)  # 半角カナなどを全角寄りに揃える
    text = text.strip()
    text = re.sub(r"\s+", " ", text)  # 空白の連続を1つにする
    return text


def resolve_category(
    lookup_key: str,
    alias_map: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """
    照合キーから「分析用店名」と「分類」を決める（初期版の分類決定の中心）。

    戻り値:
        (normalized_name, category)
        - 辞書にある場合: 登録された分析用名称と既定分類
        - 辞書にない場合: ("", "未分類")
          ※ 呼び出し側で分析用名称を原文に差し替える
    """
    if alias_map is None:
        from db import load_alias_map

        alias_map = load_alias_map()

    alias = alias_map.get(lookup_key)
    if not alias:
        return "", CATEGORY_UNCATEGORIZED

    name = str(alias.get("normalized_name") or "").strip()
    category = str(alias.get("default_category") or "").strip() or CATEGORY_UNCATEGORIZED
    return name, category


def parse_date(value: Any, date_format: str) -> datetime | None:
    """
    文字列の日付を datetime に変換する。
    失敗したら None（その行は除外対象）。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, date_format)
    except ValueError:
        return None


def parse_amount(
    value: Any,
    *,
    thousands_separator: str = ",",
    currency_symbol: str = "",
    minus_format: str = "sign",
) -> int | None:
    """
    金額文字列を整数（円）に変換する。

    例: "1,200" → 1200 / "(1,000)" → -1000（parenのとき）
    変換できない場合は None（その行は除外対象）。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    negative = False  # 最終的にマイナスにするか
    if minus_format == "paren":
        # (1,000) 形式をマイナスとみなす
        if text.startswith("(") and text.endswith(")"):
            negative = True
            text = text[1:-1].strip()

    # 通貨記号や「円」を除去
    for sym in filter(None, [currency_symbol, "¥", "￥", "円", "\\"]):
        text = text.replace(sym, "")

    if thousands_separator:
        text = text.replace(thousands_separator, "")

    text = text.replace(",", "").replace(" ", "")
    if not text:
        return None

    if text.startswith("-"):
        negative = True
        text = text[1:]
    elif text.startswith("+"):
        text = text[1:]

    # 数字以外が残っていたら失敗
    if not re.fullmatch(r"\d+", text):
        return None

    amount = int(text)
    return -amount if negative else amount


def format_amount(amount: int) -> str:
    """整数金額をカンマ付き文字列にする（例: 1200 → "1,200"）。"""
    return f"{amount:,}"


def format_date(dt: datetime) -> str:
    """日付を YYYY/MM/DD 形式の文字列にする。"""
    return dt.strftime("%Y/%m/%d")
