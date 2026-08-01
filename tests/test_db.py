# -*- coding: utf-8 -*-
"""AT-D*: db の統合テスト（一時 app.db）。"""
from __future__ import annotations

import db
from normalize import make_lookup_key


def test_init_db_empty_tables(app_dirs):
    # AT-D01
    assert db.list_profiles() == []
    assert db.list_merchant_aliases() == []
    assert db.list_unregistered_merchants() == []
    assert db.list_transactions() == []
    assert db.count_transactions() == 0


def test_profile_crud(app_dirs, sample_profile):
    # AT-D02
    pid = db.save_profile(sample_profile)
    got = db.get_profile(pid)
    assert got is not None
    assert got["profile_name"] == "テストカード"
    assert got["enabled"] == 1

    got["card_company"] = "更新後会社"
    db.save_profile(got)
    assert db.get_profile(pid)["card_company"] == "更新後会社"

    db.set_profile_enabled(pid, False)
    assert db.get_profile(pid)["enabled"] == 0
    assert db.list_profiles(enabled_only=True) == []
    assert len(db.list_profiles(enabled_only=False)) == 1

    new_id = db.duplicate_profile(pid, "テストカードコピー")
    assert new_id != pid
    copy = db.get_profile(new_id)
    assert copy["profile_name"] == "テストカードコピー"
    assert copy["enabled"] == 1

    db.delete_profile(pid)
    assert db.get_profile(pid) is None


def test_merchant_alias_crud(app_dirs):
    # AT-D03
    alias_id = db.save_merchant_alias(
        {
            "original_name": "アマゾン",
            "normalized_name": "Amazon",
            "default_category": "変動費",
        }
    )
    rows = db.list_merchant_aliases(search="Amazon")
    assert len(rows) == 1
    assert rows[0]["id"] == alias_id
    assert rows[0]["lookup_key"] == make_lookup_key("アマゾン")

    by_key = db.get_merchant_alias_by_key(make_lookup_key("アマゾン"))
    assert by_key is not None
    assert by_key["default_category"] == "変動費"

    db.delete_merchant_alias(alias_id)
    assert db.list_merchant_aliases() == []


def test_unregistered_upsert(app_dirs):
    # AT-D04
    key = make_lookup_key("新規店")
    db.upsert_unregistered(
        lookup_key=key,
        sample_original_name="新規店",
        card_company="A社",
        source_file="a.csv",
        count=1,
    )
    db.upsert_unregistered(
        lookup_key=key,
        sample_original_name="新規店",
        card_company="B社",
        source_file="b.csv",
        count=2,
    )
    rows = db.list_unregistered_merchants()
    assert len(rows) == 1
    assert rows[0]["occurrence_count"] == 3
    assert rows[0]["last_card_company"] == "B社"
    assert rows[0]["last_source_file"] == "b.csv"


def test_save_alias_removes_unregistered(app_dirs):
    # AT-D05
    key = make_lookup_key("登録予定店")
    db.upsert_unregistered(
        lookup_key=key,
        sample_original_name="登録予定店",
        card_company="A社",
        source_file="a.csv",
        count=1,
    )
    db.save_merchant_alias(
        {
            "original_name": "登録予定店",
            "normalized_name": "登録予定店",
            "default_category": "固定費",
        }
    )
    assert db.list_unregistered_merchants() == []
    assert db.get_merchant_alias_by_key(key) is not None


def test_transactions_insert_skip_and_category(app_dirs):
    rec = {
        "利用年月日": "2026/01/01",
        "利用店名": "店X",
        "正規化店名": "店X",
        "分類": "未分類",
        "利用金額": 1000,
        "カード会社": "A社",
        "取込元ファイル名": "a.csv",
        "取込行番号": 2,
        "分類手動": 0,
    }
    inserted, skipped = db.insert_transactions([rec])
    assert inserted == 1 and skipped == 0
    inserted2, skipped2 = db.insert_transactions([rec])
    assert inserted2 == 0 and skipped2 == 1

    rows = db.list_transactions()
    assert len(rows) == 1
    tx_id = rows[0]["id"]
    db.update_transaction_category(tx_id, "固定費")
    updated = db.list_transactions()[0]
    assert updated["分類"] == "固定費"
    assert updated["分類手動"] == 1


def test_reapply_skips_manual(app_dirs):
    db.insert_transactions(
        [
            {
                "利用年月日": "2026/01/01",
                "利用店名": "アマゾン",
                "正規化店名": "アマゾン",
                "分類": "未分類",
                "利用金額": 500,
                "カード会社": "A社",
                "取込元ファイル名": "a.csv",
                "取込行番号": 2,
                "分類手動": 0,
            },
            {
                "利用年月日": "2026/01/02",
                "利用店名": "手修正店",
                "正規化店名": "手修正店",
                "分類": "臨時費",
                "利用金額": 800,
                "カード会社": "A社",
                "取込元ファイル名": "a.csv",
                "取込行番号": 3,
                "分類手動": 1,
            },
        ]
    )
    db.save_merchant_alias(
        {
            "original_name": "アマゾン",
            "normalized_name": "Amazon",
            "default_category": "変動費",
        }
    )
    db.save_merchant_alias(
        {
            "original_name": "手修正店",
            "normalized_name": "上書きされない店",
            "default_category": "固定費",
        }
    )
    updated = db.reapply_merchant_aliases()
    assert updated == 1
    rows = {r["利用店名"]: r for r in db.list_transactions()}
    assert rows["アマゾン"]["正規化店名"] == "Amazon"
    assert rows["アマゾン"]["分類"] == "変動費"
    assert rows["手修正店"]["分類"] == "臨時費"
    assert rows["手修正店"]["正規化店名"] == "手修正店"


def test_backup_restore(app_dirs, tmp_path):
    db.insert_transactions(
        [
            {
                "利用年月日": "2026/01/01",
                "利用店名": "店Y",
                "正規化店名": "店Y",
                "分類": "変動費",
                "利用金額": 1200,
                "カード会社": "B社",
                "取込元ファイル名": "b.csv",
                "取込行番号": 5,
                "分類手動": 1,
            }
        ]
    )
    backup = tmp_path / "backup.csv"
    assert db.export_transactions_csv(backup) == 1

    db.insert_transactions(
        [
            {
                "利用年月日": "2026/02/01",
                "利用店名": "別店",
                "正規化店名": "別店",
                "分類": "未分類",
                "利用金額": 10,
                "カード会社": "B社",
                "取込元ファイル名": "b.csv",
                "取込行番号": 6,
                "分類手動": 0,
            }
        ]
    )
    assert db.count_transactions() == 2

    restored = db.restore_transactions_csv(backup)
    assert restored == 1
    rows = db.list_transactions()
    assert len(rows) == 1
    assert rows[0]["利用店名"] == "店Y"
    assert rows[0]["分類手動"] == 1
    assert rows[0]["利用金額"] == 1200
