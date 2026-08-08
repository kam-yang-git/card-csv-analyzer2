# -*- coding: utf-8 -*-
"""
merge.py
--------
伝票CSVを読み、検証し、マージ済み明細をSQLiteへ蓄積する。
失敗（検証エラー）と、明細にできない行（除外）を区別して扱う。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from db import insert_transactions, load_alias_map, upsert_unregistered
from normalize import (
    format_amount,
    format_date,
    make_lookup_key,
    parse_amount,
    parse_date,
    resolve_category,
)
from paths import LOG_DIR, ensure_directories


# 進捗メッセージを受け取る関数の型（例: GUIのステータス更新）
ProgressCallback = Callable[[str], None]


class MergeValidationError(Exception):
    """検証エラー。発生するとマージ全体を中止する。"""


@dataclass
class FileJob:
    """マージ対象の「ファイル1つ + 使うプロファイル」。"""

    path: Path  # CSVファイルの場所
    profile: dict[str, Any]  # 読み方の設定


@dataclass
class MergeResult:
    """マージ処理の結果まとめ（GUIが表示・判断に使う）。"""

    ok: bool  # True=成功してDB登録済み / False=中止
    log_path: Path | None = None  # ログファイル
    merged_rows: int = 0  # 処理できた明細数（重複含む候補件数）
    inserted_rows: int = 0  # 新規登録件数
    skipped_rows: int = 0  # 重複スキップ件数
    excluded_rows: int = 0  # 除外した行数
    unregistered_count: int = 0  # 今回見つかった未登録店名の種類数
    error_message: str = ""  # 失敗理由（ログにも書く）
    has_exclusions: bool = False  # 除外が1件でもあれば True


@dataclass
class _Logger:
    """マージ用ログをメモリに溜め、最後にファイルへ書き出す小さなヘルパー。"""

    path: Path
    lines: list[str] = field(default_factory=list)

    def write(self, level: str, message: str) -> None:
        """1行追記する。level 例: START / INFO / EXCLUDE / ERROR / END"""
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{level}] {stamp} {message}"
        self.lines.append(line)

    def flush(self) -> None:
        """溜めた内容をログファイルに保存する。"""
        ensure_directories()
        self.path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def _timestamp() -> str:
    """ファイル名用の日時文字列（例: 20260720_153000）。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_csv_with_profile(path: Path, profile: dict[str, Any]) -> pd.DataFrame:
    """
    プロファイルの文字コード・ヘッダー行・末尾不要行に従ってCSVを読む。
    失敗時は MergeValidationError を投げる。
    """
    encoding = profile["encoding"]
    header_row = int(profile["header_row"])  # 画面は1始まり
    footer_rows = int(profile.get("footer_rows") or 0)

    try:
        raw = path.read_bytes()
        text = raw.decode(encoding)
    except UnicodeDecodeError as exc:
        raise MergeValidationError(
            f"文字コードの読込に失敗しました: {path.name} encoding={encoding}"
        ) from exc
    except OSError as exc:
        raise MergeValidationError(f"ファイルを開けません: {path.name}") from exc

    try:
        df = pd.read_csv(
            StringIO(text),
            header=header_row - 1,  # pandas は0始まりなので -1
            skipfooter=footer_rows,
            engine="python",  # skipfooter 利用のため
            dtype=str,
            keep_default_na=False,
        )
    except Exception as exc:  # noqa: BLE001
        raise MergeValidationError(
            f"CSVの解析に失敗しました: {path.name} ({exc})"
        ) from exc

    df.columns = [str(c).strip() for c in df.columns]
    return df


def validate_headers(df: pd.DataFrame, profile: dict[str, Any], filename: str) -> None:
    """日付・店名・金額の列名がヘッダーに揃っているか確認する。"""
    required = [
        profile["date_column"],
        profile["merchant_column"],
        profile["amount_column"],
    ]
    missing = [name for name in required if name not in df.columns]
    if missing:
        raise MergeValidationError(
            f"ヘッダー不一致: {filename} 不足列={missing} 実列={list(df.columns)}"
        )


def preview_csv(path: Path, profile: dict[str, Any], limit: int = 20) -> pd.DataFrame:
    """テスト読込用。日付・金額を変換でき、店名が空でない行だけ先頭から返す。"""
    df = read_csv_with_profile(path, profile)
    validate_headers(df, profile, path.name)
    rows: list[dict[str, Any]] = []
    date_col = profile["date_column"]
    merchant_col = profile["merchant_column"]
    amount_col = profile["amount_column"]
    header_row = int(profile["header_row"])

    for offset, (_, series) in enumerate(df.iterrows()):
        source_line = header_row + 1 + offset  # 元ファイル上の行番号
        raw_merchant = series.get(merchant_col, "")
        merchant = str(raw_merchant).strip()
        dt = parse_date(series.get(date_col), profile["date_format"])
        amount = parse_amount(
            series.get(amount_col),
            thousands_separator=profile.get("thousands_separator") or "",
            currency_symbol=profile.get("currency_symbol") or "",
            minus_format=profile.get("minus_format") or "sign",
        )
        if dt is None or amount is None or not merchant:
            continue
        rows.append(
            {
                "取込行番号": source_line,
                "利用年月日": format_date(dt),
                "利用店名": str(raw_merchant),
                "利用金額": format_amount(amount),
            }
        )
        if len(rows) >= limit:
            break

    if not rows:
        raise MergeValidationError(f"有効な明細がありません: {path.name}")
    return pd.DataFrame(rows)


def _process_file(
    job: FileJob,
    alias_map: dict[str, dict[str, Any]],
    logger: _Logger,
) -> tuple[list[dict[str, Any]], list[tuple[str, str, int]], int]:
    """
    1ファイル分の明細を作る。

    戻り値:
        records … マージ用の明細リスト
        unregistered … 辞書に無かった店 (照合キー, 原文, 1)
        excluded … 除外した行数
    """
    path = job.path
    profile = job.profile
    logger.write("INFO", f"file={path.name} profile={profile['profile_name']}")

    df = read_csv_with_profile(path, profile)
    validate_headers(df, profile, path.name)

    date_col = profile["date_column"]
    merchant_col = profile["merchant_column"]
    amount_col = profile["amount_column"]
    header_row = int(profile["header_row"])
    card_company = profile["card_company"]

    records: list[dict[str, Any]] = []
    unregistered: list[tuple[str, str, int]] = []
    excluded = 0

    for offset, (_, series) in enumerate(df.iterrows()):
        source_line = header_row + 1 + offset
        raw_date = series.get(date_col, "")
        raw_merchant = series.get(merchant_col, "")
        raw_amount = series.get(amount_col, "")

        # 全部空の行は除外
        if (
            str(raw_date).strip() == ""
            and str(raw_merchant).strip() == ""
            and str(raw_amount).strip() == ""
        ):
            excluded += 1
            logger.write(
                "EXCLUDE",
                f"file={path.name} line={source_line} reason=empty_row",
            )
            continue

        dt = parse_date(raw_date, profile["date_format"])
        amount = parse_amount(
            raw_amount,
            thousands_separator=profile.get("thousands_separator") or "",
            currency_symbol=profile.get("currency_symbol") or "",
            minus_format=profile.get("minus_format") or "sign",
        )
        merchant = str(raw_merchant).strip()

        # 日付・金額が読めない、または店名が空の行は除外（マージ自体は続行）
        if dt is None or amount is None or not merchant:
            excluded += 1
            reason = []
            if dt is None:
                reason.append("invalid_date")
            if amount is None:
                reason.append("invalid_amount")
            if not merchant:
                reason.append("empty_merchant")
            logger.write(
                "EXCLUDE",
                f"file={path.name} line={source_line} reason={'+'.join(reason)} "
                f"date={raw_date!r} amount={raw_amount!r} merchant={raw_merchant!r}",
            )
            continue

        original_name = str(raw_merchant)
        lookup_key = make_lookup_key(original_name)
        normalized_name, category = resolve_category(lookup_key, alias_map)
        if not normalized_name:
            # 辞書未登録 → 分析用名称は原文のまま、未登録リストへ
            normalized_name = original_name
            unregistered.append((lookup_key, original_name, 1))

        records.append(
            {
                "利用年月日": format_date(dt),
                "利用店名": original_name,
                "正規化店名": normalized_name,
                "分類": category,
                "利用金額": amount,
                "カード会社": card_company,
                "取込元ファイル名": path.name,
                "取込行番号": source_line,
                "分類手動": 0,
            }
        )

    if not records:
        raise MergeValidationError(f"有効な明細がありません: {path.name}")

    return records, unregistered, excluded


def merge_files(
    jobs: list[FileJob],
    progress: ProgressCallback | None = None,
) -> MergeResult:
    """
    複数ファイルを順に処理してDBへ蓄積する。
    検証エラー時はDBへ登録せず aborted。除外のみなら有効明細は登録する。
    """
    ensure_directories()
    stamp = _timestamp()
    log_path = LOG_DIR / f"merge_{stamp}.log"
    logger = _Logger(log_path)
    logger.write("START", "merge started")

    if not jobs:
        logger.write("ERROR", "no files")
        logger.write(
            "END",
            "status=aborted inserted_rows=0 skipped_rows=0 excluded_rows=0",
        )
        logger.flush()
        return MergeResult(
            ok=False,
            log_path=log_path,
            error_message="マージ対象ファイルがありません",
        )

    alias_map = load_alias_map()
    all_records: list[dict[str, Any]] = []
    total_excluded = 0
    unregistered_agg: dict[str, dict[str, Any]] = {}

    try:
        for job in jobs:
            if progress:
                progress(f"処理中: {job.path.name}")
            records, unregistered, excluded = _process_file(job, alias_map, logger)
            all_records.extend(records)
            total_excluded += excluded
            for lookup_key, original, _ in unregistered:
                bucket = unregistered_agg.setdefault(
                    lookup_key,
                    {
                        "original": original,
                        "count": 0,
                        "card_company": job.profile["card_company"],
                        "source_file": job.path.name,
                    },
                )
                bucket["count"] += 1
                bucket["card_company"] = job.profile["card_company"]
                bucket["source_file"] = job.path.name
                bucket["original"] = original

        if progress:
            progress("未登録店名を更新中…")
        for lookup_key, info in unregistered_agg.items():
            upsert_unregistered(
                lookup_key=lookup_key,
                sample_original_name=info["original"],
                card_company=info["card_company"],
                source_file=info["source_file"],
                count=info["count"],
            )

        if progress:
            progress("DBへ登録中…")
        all_records.sort(
            key=lambda r: (r["利用年月日"], r["取込元ファイル名"], r["取込行番号"])
        )
        inserted, skipped = insert_transactions(all_records)

        logger.write(
            "END",
            f"status=completed merged_rows={len(all_records)} "
            f"inserted_rows={inserted} skipped_rows={skipped} "
            f"excluded_rows={total_excluded}",
        )
        logger.flush()
        return MergeResult(
            ok=True,
            log_path=log_path,
            merged_rows=len(all_records),
            inserted_rows=inserted,
            skipped_rows=skipped,
            excluded_rows=total_excluded,
            unregistered_count=len(unregistered_agg),
            has_exclusions=total_excluded > 0,
        )
    except MergeValidationError as exc:
        logger.write("ERROR", str(exc))
        logger.write(
            "END",
            f"status=aborted inserted_rows=0 skipped_rows=0 "
            f"excluded_rows={total_excluded}",
        )
        logger.flush()
        return MergeResult(
            ok=False,
            log_path=log_path,
            excluded_rows=total_excluded,
            error_message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        logger.write("ERROR", f"unexpected: {exc}")
        logger.write(
            "END",
            f"status=aborted inserted_rows=0 skipped_rows=0 "
            f"excluded_rows={total_excluded}",
        )
        logger.flush()
        return MergeResult(
            ok=False,
            log_path=log_path,
            excluded_rows=total_excluded,
            error_message=str(exc),
        )


def validate_file(path: Path, profile: dict[str, Any]) -> tuple[bool, str, int]:
    """
    マージ前の単票チェック。
    戻り値: (成功か, メッセージ, 有効明細数)
    """
    try:
        df = read_csv_with_profile(path, profile)
        validate_headers(df, profile, path.name)
        preview = preview_csv(path, profile, limit=10_000)
        return True, f"検証OK（有効明細 {len(preview)} 件）", len(preview)
    except MergeValidationError as exc:
        return False, str(exc), 0
    except Exception as exc:  # noqa: BLE001
        return False, str(exc), 0
