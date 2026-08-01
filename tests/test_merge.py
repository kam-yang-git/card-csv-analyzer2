# -*- coding: utf-8 -*-
"""AT-M*: merge の統合テスト。"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

import db
import merge
from merge import FileJob, MergeValidationError, merge_files, preview_csv, validate_file
from normalize import make_lookup_key
from paths import BACKUP_COLUMNS


def _job(path: Path, profile: dict) -> FileJob:
    return FileJob(path=path, profile=profile)


def test_merge_with_exclusions(app_dirs, sample_profile, fixtures_dir):
    # AT-M01, AT-M05, AT-M06（paren マイナス）
    profile = dict(sample_profile)
    profile["minus_format"] = "paren"
    csv_path = fixtures_dir / "with_exclusions.csv"
    result = merge_files([_job(csv_path, profile)])

    assert result.ok is True
    assert result.inserted_rows >= 2
    assert result.has_exclusions is True
    assert result.excluded_rows >= 2
    assert result.merged_rows >= 2

    log_text = result.log_path.read_text(encoding="utf-8")
    assert "[START]" in log_text
    assert "[EXCLUDE]" in log_text
    assert "[END]" in log_text
    assert "status=completed" in log_text

    rows = db.list_transactions()
    amounts = {r["利用金額"] for r in rows}
    assert -200 in amounts


def test_merge_header_mismatch_aborts(app_dirs, sample_profile, fixtures_dir):
    # AT-M02, AT-M05
    csv_path = fixtures_dir / "bad_headers.csv"
    result = merge_files([_job(csv_path, sample_profile)])

    assert result.ok is False
    assert result.inserted_rows == 0
    assert db.count_transactions() == 0
    assert "ヘッダー" in result.error_message or "不足" in result.error_message

    log_text = result.log_path.read_text(encoding="utf-8")
    assert "[ERROR]" in log_text
    assert "status=aborted" in log_text


def test_merge_inserts_and_skips_duplicates(app_dirs, sample_profile, fixtures_dir):
    csv_path = fixtures_dir / "ok_utf8.csv"
    first = merge_files([_job(csv_path, sample_profile)])
    assert first.ok is True
    assert first.inserted_rows >= 1
    assert first.skipped_rows == 0

    second = merge_files([_job(csv_path, sample_profile)])
    assert second.ok is True
    assert second.inserted_rows == 0
    assert second.skipped_rows == first.merged_rows
    assert db.count_transactions() == first.inserted_rows


def test_merge_records_unregistered(app_dirs, sample_profile, fixtures_dir):
    # AT-M04
    csv_path = fixtures_dir / "ok_utf8.csv"
    result = merge_files([_job(csv_path, sample_profile)])
    assert result.ok is True
    assert result.unregistered_count >= 1

    unreg = db.list_unregistered_merchants()
    keys = {r["lookup_key"] for r in unreg}
    assert make_lookup_key("アマゾン") in keys
    assert make_lookup_key("コンビニA") in keys


def test_backup_csv_format(app_dirs, sample_profile, fixtures_dir):
    csv_path = fixtures_dir / "ok_utf8.csv"
    result = merge_files([_job(csv_path, sample_profile)])
    assert result.ok is True

    backup = app_dirs / "results" / "backup.csv"
    count = db.export_transactions_csv(backup)
    assert count == result.inserted_rows

    raw = backup.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8")
    first_line = text.splitlines()[0]
    assert first_line.startswith('"')
    assert '"分類手動"' in first_line

    with backup.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == BACKUP_COLUMNS
        rows = list(reader)

    assert any(r["利用金額"] == "1,200" for r in rows)
    assert all("/" in r["利用年月日"] for r in rows)
    assert any(r["利用金額"].startswith("-") for r in rows)


def test_preview_csv_ok(app_dirs, sample_profile, fixtures_dir):
    # AT-M07
    preview = preview_csv(fixtures_dir / "ok_utf8.csv", sample_profile, limit=10)
    assert len(preview) >= 1
    assert "利用年月日" in preview.columns


def test_preview_csv_no_valid_rows(app_dirs, sample_profile, tmp_path):
    # AT-M07
    bad = tmp_path / "empty_valid.csv"
    bad.write_text("利用日,利用店名,利用金額\nbad,店,xxx\n", encoding="utf-8")
    with pytest.raises(MergeValidationError):
        preview_csv(bad, sample_profile)


def test_validate_file(app_dirs, sample_profile, fixtures_dir):
    # AT-M08
    ok, msg, count = validate_file(fixtures_dir / "ok_utf8.csv", sample_profile)
    assert ok is True
    assert count >= 1
    assert "検証OK" in msg

    ng, ng_msg, ng_count = validate_file(fixtures_dir / "bad_headers.csv", sample_profile)
    assert ng is False
    assert ng_count == 0
    assert ng_msg


def test_merge_no_jobs(app_dirs):
    result = merge_files([])
    assert result.ok is False
    assert "ファイル" in result.error_message
