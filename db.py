# -*- coding: utf-8 -*-
"""
db.py
-----
SQLite（data/app.db）への読み書きを担当する。
テーブルは次の4つ。
  - profiles … 伝票（CSV）の読み方設定
  - merchant_aliases … 店名の分析用名称と既定分類
  - unregistered_merchants … 辞書にまだ無い店名
  - transactions … マージ済み明細
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from normalize import format_amount, make_lookup_key, resolve_category
from paths import (
    BACKUP_COLUMNS,
    CATEGORIES,
    CATEGORY_UNCATEGORIZED,
    DB_PATH,
    ensure_directories,
)


def _now() -> str:
    """現在時刻を ISO8601 文字列で返す（created_at / updated_at 用）。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    """DBへ接続する。行を dict のように扱えるよう設定する。"""
    ensure_directories()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 列名でアクセスできるようにする
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """必要なテーブルが無ければ作成する（初回起動時）。"""
    ensure_directories()
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_name TEXT NOT NULL UNIQUE,
                card_company TEXT NOT NULL,
                encoding TEXT NOT NULL,
                header_row INTEGER NOT NULL,
                footer_rows INTEGER NOT NULL DEFAULT 0,
                date_column TEXT NOT NULL,
                merchant_column TEXT NOT NULL,
                amount_column TEXT NOT NULL,
                date_format TEXT NOT NULL,
                thousands_separator TEXT NOT NULL DEFAULT ',',
                currency_symbol TEXT NOT NULL DEFAULT '',
                minus_format TEXT NOT NULL DEFAULT 'sign',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS merchant_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lookup_key TEXT NOT NULL UNIQUE,
                original_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                default_category TEXT NOT NULL DEFAULT '未分類',
                notes TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS unregistered_merchants (
                lookup_key TEXT PRIMARY KEY,
                sample_original_name TEXT NOT NULL,
                occurrence_count INTEGER NOT NULL DEFAULT 0,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_card_company TEXT NOT NULL DEFAULT '',
                last_source_file TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usage_date TEXT NOT NULL,
                merchant_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                category TEXT NOT NULL,
                amount INTEGER NOT NULL,
                card_company TEXT NOT NULL,
                source_file TEXT NOT NULL,
                source_line INTEGER NOT NULL,
                category_manual INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (
                    card_company, usage_date, merchant_name,
                    amount, source_file, source_line
                )
            );
            """
        )


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """sqlite3.Row を通常の dict に変換する。無ければ None。"""
    if row is None:
        return None
    return dict(row)


# ---- profiles（伝票形式の設定） ----

def list_profiles(*, enabled_only: bool = False) -> list[dict[str, Any]]:
    """プロファイル一覧を返す。enabled_only=True なら有効なものだけ。"""
    sql = "SELECT * FROM profiles"
    params: tuple[Any, ...] = ()
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY profile_name COLLATE NOCASE"
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_profile(profile_id: int) -> dict[str, Any] | None:
    """IDでプロファイルを1件取得する。"""
    with connect() as conn:
        return _row_to_dict(
            conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        )


def get_profile_by_name(profile_name: str) -> dict[str, Any] | None:
    """プロファイル名で1件取得する。"""
    with connect() as conn:
        return _row_to_dict(
            conn.execute(
                "SELECT * FROM profiles WHERE profile_name = ?", (profile_name,)
            ).fetchone()
        )


def save_profile(data: dict[str, Any]) -> int:
    """
    プロファイルを新規追加または更新し、IDを返す。
    data に id があれば更新、無ければ新規。
    """
    now = _now()
    profile_id = data.get("id")
    fields = {
        "profile_name": data["profile_name"].strip(),
        "card_company": data["card_company"].strip(),
        "encoding": data["encoding"].strip(),
        "header_row": int(data["header_row"]),
        "footer_rows": int(data.get("footer_rows", 0)),
        "date_column": data["date_column"].strip(),
        "merchant_column": data["merchant_column"].strip(),
        "amount_column": data["amount_column"].strip(),
        "date_format": data["date_format"].strip(),
        "thousands_separator": data.get("thousands_separator", ",") or "",
        "currency_symbol": data.get("currency_symbol", "") or "",
        "minus_format": data.get("minus_format", "sign") or "sign",
        "enabled": 1 if int(data.get("enabled", 1)) else 0,
        "updated_at": now,
    }
    if not fields["profile_name"]:
        raise ValueError("プロファイル名は必須です")
    if fields["header_row"] < 1:
        raise ValueError("ヘッダー行は1以上です")
    if fields["footer_rows"] < 0:
        raise ValueError("末尾不要行数は0以上です")

    with connect() as conn:
        if profile_id:
            conn.execute(
                """
                UPDATE profiles SET
                    profile_name=:profile_name,
                    card_company=:card_company,
                    encoding=:encoding,
                    header_row=:header_row,
                    footer_rows=:footer_rows,
                    date_column=:date_column,
                    merchant_column=:merchant_column,
                    amount_column=:amount_column,
                    date_format=:date_format,
                    thousands_separator=:thousands_separator,
                    currency_symbol=:currency_symbol,
                    minus_format=:minus_format,
                    enabled=:enabled,
                    updated_at=:updated_at
                WHERE id=:id
                """,
                {**fields, "id": profile_id},
            )
            return int(profile_id)

        fields["created_at"] = now
        cur = conn.execute(
            """
            INSERT INTO profiles (
                profile_name, card_company, encoding, header_row, footer_rows,
                date_column, merchant_column, amount_column, date_format,
                thousands_separator, currency_symbol, minus_format,
                enabled, created_at, updated_at
            ) VALUES (
                :profile_name, :card_company, :encoding, :header_row, :footer_rows,
                :date_column, :merchant_column, :amount_column, :date_format,
                :thousands_separator, :currency_symbol, :minus_format,
                :enabled, :created_at, :updated_at
            )
            """,
            fields,
        )
        return int(cur.lastrowid)


def set_profile_enabled(profile_id: int, enabled: bool) -> None:
    """プロファイルの有効／無効を切り替える。"""
    with connect() as conn:
        conn.execute(
            "UPDATE profiles SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, _now(), profile_id),
        )


def delete_profile(profile_id: int) -> None:
    """プロファイルを削除する。"""
    with connect() as conn:
        conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))


def duplicate_profile(profile_id: int, new_name: str) -> int:
    """既存プロファイルを別名で複製して保存する。"""
    src = get_profile(profile_id)
    if src is None:
        raise ValueError("コピー元プロファイルが見つかりません")
    data = dict(src)
    data.pop("id", None)
    data["profile_name"] = new_name
    data["enabled"] = 1
    return save_profile(data)


# ---- merchant_aliases（店名辞書） ----

def list_merchant_aliases(search: str = "") -> list[dict[str, Any]]:
    """店名辞書の一覧。search があれば部分一致で絞り込む。"""
    with connect() as conn:
        if search.strip():
            like = f"%{search.strip()}%"
            rows = conn.execute(
                """
                SELECT * FROM merchant_aliases
                WHERE original_name LIKE ? OR normalized_name LIKE ?
                   OR lookup_key LIKE ? OR default_category LIKE ?
                ORDER BY normalized_name COLLATE NOCASE, original_name COLLATE NOCASE
                """,
                (like, like, like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM merchant_aliases
                ORDER BY normalized_name COLLATE NOCASE, original_name COLLATE NOCASE
                """
            ).fetchall()
        return [dict(r) for r in rows]


def get_merchant_alias_by_key(lookup_key: str) -> dict[str, Any] | None:
    """照合キーで有効な辞書エントリを1件取得する。"""
    with connect() as conn:
        return _row_to_dict(
            conn.execute(
                """
                SELECT * FROM merchant_aliases
                WHERE lookup_key = ? AND enabled = 1
                """,
                (lookup_key,),
            ).fetchone()
        )


def save_merchant_alias(data: dict[str, Any]) -> int:
    """
    店名辞書を保存する（新規／更新）。
    新規登録時は、同じ照合キーの未登録一覧も削除する。
    """
    from normalize import make_lookup_key

    now = _now()
    original = str(data["original_name"]).strip()
    normalized = str(data.get("normalized_name") or original).strip()
    lookup_key = str(data.get("lookup_key") or make_lookup_key(original)).strip()
    category = str(data.get("default_category") or CATEGORY_UNCATEGORIZED).strip()
    notes = str(data.get("notes") or "")
    enabled = 1 if int(data.get("enabled", 1)) else 0
    alias_id = data.get("id")

    if not original:
        raise ValueError("原文は必須です")
    if not normalized:
        raise ValueError("分析用名称は必須です")
    if not lookup_key:
        raise ValueError("照合キーを生成できません")

    with connect() as conn:
        if alias_id:
            conn.execute(
                """
                UPDATE merchant_aliases SET
                    lookup_key = ?, original_name = ?, normalized_name = ?,
                    default_category = ?, notes = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    lookup_key,
                    original,
                    normalized,
                    category,
                    notes,
                    enabled,
                    now,
                    alias_id,
                ),
            )
            return int(alias_id)

        cur = conn.execute(
            """
            INSERT INTO merchant_aliases (
                lookup_key, original_name, normalized_name, default_category,
                notes, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (lookup_key, original, normalized, category, notes, enabled, now, now),
        )
        # 辞書に登録できたので未登録一覧からは外す
        conn.execute(
            "DELETE FROM unregistered_merchants WHERE lookup_key = ?",
            (lookup_key,),
        )
        return int(cur.lastrowid)


def delete_merchant_alias(alias_id: int) -> None:
    """店名辞書の1件を削除する。"""
    with connect() as conn:
        conn.execute("DELETE FROM merchant_aliases WHERE id = ?", (alias_id,))


def load_alias_map() -> dict[str, dict[str, Any]]:
    """有効な店名辞書を {照合キー: 行データ} にして返す（マージ時の高速照合用）。"""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM merchant_aliases WHERE enabled = 1"
        ).fetchall()
        return {r["lookup_key"]: dict(r) for r in rows}


# ---- unregistered_merchants（未登録店名） ----

def list_unregistered_merchants() -> list[dict[str, Any]]:
    """未登録店名を出現回数の多い順で返す。"""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM unregistered_merchants
            ORDER BY occurrence_count DESC, last_seen_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_unregistered(
    *,
    lookup_key: str,
    sample_original_name: str,
    card_company: str,
    source_file: str,
    count: int = 1,
) -> None:
    """
    未登録店名を追加、または既にあれば出現回数などを更新する。
    upsert = update + insert の意味。
    """
    now = _now()
    with connect() as conn:
        existing = conn.execute(
            "SELECT * FROM unregistered_merchants WHERE lookup_key = ?",
            (lookup_key,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE unregistered_merchants SET
                    sample_original_name = ?,
                    occurrence_count = occurrence_count + ?,
                    last_seen_at = ?,
                    last_card_company = ?,
                    last_source_file = ?
                WHERE lookup_key = ?
                """,
                (
                    sample_original_name,
                    count,
                    now,
                    card_company,
                    source_file,
                    lookup_key,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO unregistered_merchants (
                    lookup_key, sample_original_name, occurrence_count,
                    first_seen_at, last_seen_at, last_card_company, last_source_file
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lookup_key,
                    sample_original_name,
                    count,
                    now,
                    now,
                    card_company,
                    source_file,
                ),
            )


def delete_unregistered(lookup_key: str) -> None:
    """未登録一覧から1件削除する。"""
    with connect() as conn:
        conn.execute(
            "DELETE FROM unregistered_merchants WHERE lookup_key = ?",
            (lookup_key,),
        )


# ---- transactions（マージ済み明細） ----

def _tx_row_to_jp(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """DB行を画面／CSV向けの日本語キー dict に変換する。"""
    r = dict(row)
    return {
        "id": r["id"],
        "利用年月日": r["usage_date"],
        "利用店名": r["merchant_name"],
        "正規化店名": r["normalized_name"],
        "分類": r["category"],
        "利用金額": int(r["amount"]),
        "カード会社": r["card_company"],
        "取込元ファイル名": r["source_file"],
        "取込行番号": int(r["source_line"]),
        "分類手動": int(r["category_manual"]),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def insert_transactions(records: list[dict[str, Any]]) -> tuple[int, int]:
    """
    マージ明細を登録する。重複キーはスキップ。
    records のキーは日本語列名（利用金額は int）。
    戻り値: (登録件数, スキップ件数)
    """
    if not records:
        return 0, 0
    now = _now()
    inserted = 0
    skipped = 0
    sql = """
        INSERT OR IGNORE INTO transactions (
            usage_date, merchant_name, normalized_name, category, amount,
            card_company, source_file, source_line, category_manual,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with connect() as conn:
        for rec in records:
            cur = conn.execute(
                sql,
                (
                    str(rec["利用年月日"]),
                    str(rec["利用店名"]),
                    str(rec["正規化店名"]),
                    str(rec["分類"]),
                    int(rec["利用金額"]),
                    str(rec["カード会社"]),
                    str(rec["取込元ファイル名"]),
                    int(rec["取込行番号"]),
                    int(rec.get("分類手動", 0)),
                    now,
                    now,
                ),
            )
            if cur.rowcount == 1:
                inserted += 1
            else:
                skipped += 1
    return inserted, skipped


def list_transactions(
    *,
    year_month_from: str | None = None,
    year_month_to: str | None = None,
    card_company: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """明細一覧を返す（フィルタ任意）。年月は YYYY/MM。"""
    sql = "SELECT * FROM transactions WHERE 1=1"
    params: list[Any] = []
    if year_month_from:
        sql += " AND substr(usage_date, 1, 7) >= ?"
        params.append(year_month_from)
    if year_month_to:
        sql += " AND substr(usage_date, 1, 7) <= ?"
        params.append(year_month_to)
    if card_company and card_company != "すべて":
        sql += " AND card_company = ?"
        params.append(card_company)
    if category and category != "すべて":
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY usage_date, id"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [_tx_row_to_jp(r) for r in rows]


def count_transactions() -> int:
    """明細の総件数。"""
    with connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM transactions").fetchone()
        return int(row["c"]) if row else 0


def transaction_year_months() -> list[str]:
    """明細に含まれる年月（YYYY/MM）の一覧。"""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT substr(usage_date, 1, 7) AS ym
            FROM transactions
            ORDER BY ym
            """
        ).fetchall()
        return [r["ym"] for r in rows if r["ym"]]


def transaction_card_companies() -> list[str]:
    """明細に含まれるカード会社名の一覧。"""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT card_company
            FROM transactions
            ORDER BY card_company COLLATE NOCASE
            """
        ).fetchall()
        return [r["card_company"] for r in rows if r["card_company"]]


def update_transaction_category(tx_id: int, category: str) -> None:
    """明細の分類を手修正し、分類手動フラグを立てる。"""
    category = str(category).strip()
    if category not in CATEGORIES:
        raise ValueError(f"不正な分類です: {category}")
    with connect() as conn:
        cur = conn.execute(
            """
            UPDATE transactions
            SET category = ?, category_manual = 1, updated_at = ?
            WHERE id = ?
            """,
            (category, _now(), tx_id),
        )
        if cur.rowcount == 0:
            raise ValueError("明細が見つかりません")


def reapply_merchant_aliases() -> int:
    """
    店名辞書を category_manual=0 の明細へ再適用する。
    戻り値: 更新件数。
    """
    alias_map = load_alias_map()
    now = _now()
    updated = 0
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, merchant_name, normalized_name, category
            FROM transactions
            WHERE category_manual = 0
            """
        ).fetchall()
        for row in rows:
            lookup_key = make_lookup_key(row["merchant_name"])
            normalized_name, category = resolve_category(lookup_key, alias_map)
            if not normalized_name:
                normalized_name = row["merchant_name"]
                category = CATEGORY_UNCATEGORIZED
            if (
                normalized_name == row["normalized_name"]
                and category == row["category"]
            ):
                continue
            conn.execute(
                """
                UPDATE transactions
                SET normalized_name = ?, category = ?, updated_at = ?
                WHERE id = ?
                """,
                (normalized_name, category, now, row["id"]),
            )
            updated += 1
    return updated


def export_transactions_csv(path: str | Path) -> int:
    """全明細をバックアップCSV（9列）へ書き出す。戻り値は件数。"""
    path = Path(path)
    rows = list_transactions()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=BACKUP_COLUMNS,
            quoting=csv.QUOTE_ALL,
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "利用年月日": row["利用年月日"],
                    "利用店名": row["利用店名"],
                    "正規化店名": row["正規化店名"],
                    "分類": row["分類"],
                    "利用金額": format_amount(int(row["利用金額"])),
                    "カード会社": row["カード会社"],
                    "取込元ファイル名": row["取込元ファイル名"],
                    "取込行番号": str(row["取込行番号"]),
                    "分類手動": str(int(row["分類手動"])),
                }
            )
    return len(rows)


def _parse_manual_flag(value: Any) -> int:
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "はい"):
        return 1
    return 0


def restore_transactions_csv(path: str | Path) -> int:
    """
    バックアップCSVで明細を差し替え復元する（既存全削除→挿入）。
    戻り値: 復元件数。
    """
    path = Path(path)
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSVにヘッダーがありません")
        missing = [c for c in BACKUP_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise ValueError(f"必須列が不足しています: {missing}")
        records: list[dict[str, Any]] = []
        for i, row in enumerate(reader, start=2):
            amount_raw = str(row["利用金額"]).replace(",", "").strip()
            try:
                amount = int(amount_raw)
                source_line = int(str(row["取込行番号"]).strip())
            except ValueError as exc:
                raise ValueError(f"{i}行目: 数値の変換に失敗しました") from exc
            category = str(row["分類"]).strip() or CATEGORY_UNCATEGORIZED
            if category not in CATEGORIES:
                raise ValueError(f"{i}行目: 不正な分類です: {category}")
            records.append(
                {
                    "利用年月日": str(row["利用年月日"]).strip(),
                    "利用店名": str(row["利用店名"]),
                    "正規化店名": str(row["正規化店名"]),
                    "分類": category,
                    "利用金額": amount,
                    "カード会社": str(row["カード会社"]),
                    "取込元ファイル名": str(row["取込元ファイル名"]),
                    "取込行番号": source_line,
                    "分類手動": _parse_manual_flag(row["分類手動"]),
                }
            )

    now = _now()
    with connect() as conn:
        conn.execute("DELETE FROM transactions")
        conn.executemany(
            """
            INSERT INTO transactions (
                usage_date, merchant_name, normalized_name, category, amount,
                card_company, source_file, source_line, category_manual,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r["利用年月日"],
                    r["利用店名"],
                    r["正規化店名"],
                    r["分類"],
                    r["利用金額"],
                    r["カード会社"],
                    r["取込元ファイル名"],
                    r["取込行番号"],
                    r["分類手動"],
                    now,
                    now,
                )
                for r in records
            ],
        )
    return len(records)
