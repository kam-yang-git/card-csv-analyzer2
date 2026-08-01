# カード明細CSVアナライザ

複数カード会社の利用明細CSVを共通形式にマージし、店名辞書で分類を付与したうえで、固定費／変動費／臨時費の比率を分析するデスクトップアプリです。  
マージ結果は SQLite に蓄積し、明細の閲覧・分類の手修正・CSVバックアップ／リストアも行えます。

## できること

- カード会社ごとの読込条件を**プロファイル**として登録
- 複数CSVをマージし、明細を DB に蓄積（同一明細は重複スキップ）
- **明細**タブで一覧・フィルタ・分類の個別修正
- 明細の **CSVバックアップ／リストア**（手修正フラグ含む）
- **店名辞書**で分析用名称と分類を管理し、既存明細へ再適用
- 未登録店名を一覧から辞書へ登録
- 期間・カード会社・分類で絞り込み、円グラフと集計表を表示・保存

## 必要環境

- Python 3.10 以降（推奨）
- Windows（円グラフの日本語表示に Meiryo を使用）

## セットアップ

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 起動

```bash
python gui.py
```

初回起動時に `data/app.db` と必要なフォルダ（`data/`・`results/`・`log/`）が自動作成されます。

## 使い方（概要）

1. **プロファイル設定** … カード会社ごとの文字コード・ヘッダー行・列名・日付／金額書式を登録（テスト読込で確認可）
2. **マージ** … CSVを追加し、ファイルごとにプロファイルを選んで検証 → マージ実行（結果は DB に蓄積）
3. **明細** … 蓄積明細の確認、分類の手修正、CSVバックアップ／リストア
4. **未登録店名 / 店名辞書** … 未ヒットの店を辞書登録し、必要なら「辞書を明細へ再適用」
5. **分析** … DB の明細を対象に集計し、円グラフ／集計CSV／フィルタ後明細CSVを保存

## タブ構成

```text
[マージ] [明細] [プロファイル設定] [店名辞書] [未登録店名] [分析]
```

## 出力・保存先

| 種類 | パス例 |
|------|--------|
| DB（プロファイル・辞書・明細） | `data/app.db` |
| 明細バックアップCSV | ファイルダイアログで指定（例: `results/transactions_backup.csv`） |
| 分類集計CSV | `results/category_summary_YYYYMMDD_HHMMSS.csv` |
| 分析明細CSV | ファイルダイアログで指定 |
| 円グラフPNG | `results/category_pie_YYYYMMDD_HHMMSS.png` |
| マージログ | `log/merge_YYYYMMDD_HHMMSS.log` |

DB 全体のバックアップは `data/app.db` の手動コピーでも可能です。明細だけなら明細タブの CSVバックアップ／リストアを使えます。

## テスト

```bash
pytest
```

カバレッジ報告（HTML）は `htmlcov/` に出力されます。

## ディレクトリ構成

```text
card-csv-analyzer/
├── gui.py              # Tkinter UI・起動エントリ
├── main.py             # GUI 向け窓口
├── db.py / merge.py / analyze.py / normalize.py / paths.py
├── docs/               # 要件・設計・テスト文書
├── data/               # app.db
├── results/            # 分析結果・バックアップ候補
├── log/                # マージログ
├── tests/
├── requirements.txt
└── pyproject.toml
```

## 詳細ドキュメント

- [要件定義書](docs/requirements.md)
- [設計書](docs/design.md)
- [テスト仕様書](docs/test-spec.md)
- [テスト結果報告書](docs/test-results.md)

## 注意事項

- プロファイルの自動判定はありません（ファイルごとに手動選択）
- 店名照合は照合キーの完全一致のみ（あいまい一致なし）
- 金額は整数（円）のみ
- 辞書再適用時、分類を手修正した明細は変更しません
- CSVリストアは既存明細を全消去してから復元します

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。
