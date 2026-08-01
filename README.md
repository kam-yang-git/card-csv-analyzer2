# カード明細CSVアナライザ

複数カード会社の利用明細CSVを共通形式にマージし、店名辞書で分類を付与したうえで、固定費／変動費／臨時費の比率を分析するデスクトップアプリです。

## できること

- カード会社ごとの読込条件を**プロファイル**として登録
- 複数CSVをマージし、店名・分類を付与したCSVを出力
- **店名辞書**で分析用名称と分類（固定費／変動費／臨時費／未分類）を管理
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

初回起動時に `db/settings.db` と必要なフォルダ（`db/`・`results/`・`log/`）が自動作成されます。

## 使い方（概要）

1. **プロファイル設定** … カード会社ごとの文字コード・ヘッダー行・列名・日付／金額書式を登録（テスト読込で確認可）
2. **マージ** … CSVを追加し、ファイルごとにプロファイルを選んで検証 → マージ実行
3. **未登録店名 / 店名辞書** … 未ヒットの店を分析用名称・分類付きで辞書登録
4. **分析** … `results/` のマージCSVを対象に集計し、円グラフ／集計CSVを保存

## 出力先

| 種類 | パス例 |
|------|--------|
| マージCSV | `results/merged_YYYYMMDD_HHMMSS.csv` |
| 分類集計CSV | `results/category_summary_YYYYMMDD_HHMMSS.csv` |
| 円グラフPNG | `results/category_pie_YYYYMMDD_HHMMSS.png` |
| マージログ | `log/merge_YYYYMMDD_HHMMSS.log` |

設定・辞書は `db/settings.db`（SQLite）に保存されます。バックアップはファイルの手動コピーで行ってください。

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
├── db/                 # settings.db
├── results/            # マージ・分析結果
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

## 注意事項（初期版）

- プロファイルの自動判定はありません（ファイルごとに手動選択）
- 店名照合は照合キーの完全一致のみ（あいまい一致なし）
- 金額は整数（円）のみ。明細単位の分類上書きは対象外です

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。
