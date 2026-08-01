# 設計書

## 1. 概要

本システムは、複数カード会社の利用明細CSVを共通形式へマージし、店名辞書による名寄せ・分類付与のうえ、分類分析を行うデスクトップアプリである。

- GUI: Tkinter（`gui.py`）
- 業務ロジック: `main.py`（必要に応じてモジュール分割）
- 永続化: SQLite（`data/app.db`）
  - プロファイル・店名辞書・未登録店名・**マージ明細**を同一DBに保持
- 主要ライブラリ: pandas, matplotlib

関連文書: [要件定義書](./requirements.md) / [テスト仕様書](./test-spec.md) / [テスト結果報告書](./test-results.md)

---

## 2. ディレクトリ構成

```text
card-csv-analyzer/
├── docs/
│   ├── requirements.md
│   ├── design.md
│   ├── test-spec.md         # テスト仕様
│   └── test-results.md      # テスト結果
├── data/
│   └── app.db               # 初回起動時に生成
├── results/
│   ├── category_summary_YYYYMMDD_HHMMSS.csv
│   ├── category_pie_YYYYMMDD_HHMMSS.png
│   └── （明細バックアップ／分析明細CSVの保存先候補）
├── log/
│   └── merge_YYYYMMDD_HHMMSS.log
├── tests/                   # pytest
│   ├── fixtures/
│   └── test_*.py
├── gui.py                   # Tkinter UI・起動エントリ
├── main.py                  # ロジック（gui から呼び出し）
├── db.py / merge.py / analyze.py / normalize.py / paths.py
├── pyproject.toml           # pytest / coverage 設定
└── requirements.txt
```

起動:

```text
python gui.py
```

テスト:

```text
pytest
```

---

## 3. モジュール責務

| モジュール | 責務 |
|------------|------|
| `gui.py` | 画面構築、ユーザー操作、ダイアログ、スレッド起動、結果表示 |
| `main.py` | DB初期化、プロファイルCRUD、CSV読込・検証・マージ、店名照合、分析集計、ログ出力 |

行数が大きくなる場合の分割案:

| モジュール | 責務 |
|------------|------|
| `db.py` | SQLite接続、スキーマ作成、CRUD（明細含む） |
| `merge.py` | 読込・検証・正規化・明細化・DB登録 |
| `analyze.py` | DB明細の読込・集計・円グラフ生成・明細CSV出力 |
| `main.py` | 上記の窓口、または薄いファサード |

原則として **GUIはロジックを持たず、`main`（または分割モジュール）を呼び出すのみ** とする。

---

## 4. データ設計

### 4.1 SQLite: `data/app.db`

1ファイルに4テーブルを格納する。初期データは空（テーブルのみ作成）。

#### profiles

伝票形式ごとの読込条件。

| 列 | 型 | 説明 |
|----|-----|------|
| id | INTEGER PK | |
| profile_name | TEXT UNIQUE | プロファイル名 |
| card_company | TEXT | カード会社名（マージ結果に出力） |
| encoding | TEXT | 例: `cp932`, `utf-8-sig`, `utf-8` |
| header_row | INTEGER | ヘッダー行（UIは1始まり、内部でpandas用に変換） |
| footer_rows | INTEGER | 末尾不要行数（0以上） |
| date_column | TEXT | 日付列名 |
| merchant_column | TEXT | 店名列名 |
| amount_column | TEXT | 金額列名 |
| date_format | TEXT | 例: `%Y/%m/%d`, `%Y年%m月%d日` |
| thousands_separator | TEXT | 例: `,` または空 |
| currency_symbol | TEXT | 例: `¥`, `￥`, `円` または空 |
| minus_format | TEXT | 例: `sign` / `paren` |
| enabled | INTEGER | 1=有効, 0=無効 |
| created_at | TEXT | ISO8601 |
| updated_at | TEXT | ISO8601 |

#### merchant_aliases

店名辞書。

| 列 | 型 | 説明 |
|----|-----|------|
| id | INTEGER PK | |
| lookup_key | TEXT UNIQUE | NFKC等で生成した照合キー |
| original_name | TEXT | 登録時の原文サンプル |
| normalized_name | TEXT | 分析用名称 |
| default_category | TEXT | 固定費／変動費／臨時費／未分類 |
| notes | TEXT | 備考（任意） |
| enabled | INTEGER | 1=有効, 0=無効 |
| created_at | TEXT | |
| updated_at | TEXT | |

#### unregistered_merchants

辞書未登録店名。

| 列 | 型 | 説明 |
|----|-----|------|
| lookup_key | TEXT PK | 照合キー |
| sample_original_name | TEXT | 代表となる原文 |
| occurrence_count | INTEGER | 累計出現回数 |
| first_seen_at | TEXT | |
| last_seen_at | TEXT | |
| last_card_company | TEXT | |
| last_source_file | TEXT | |

#### transactions

マージ済み明細の蓄積。

| 列 | 型 | 説明 |
|----|-----|------|
| id | INTEGER PK | |
| usage_date | TEXT | 利用年月日（`YYYY/MM/DD`） |
| merchant_name | TEXT | 利用店名（原文） |
| normalized_name | TEXT | 正規化店名 |
| category | TEXT | 分類 |
| amount | INTEGER | 利用金額（円） |
| card_company | TEXT | カード会社 |
| source_file | TEXT | 取込元ファイル名 |
| source_line | INTEGER | 取込行番号 |
| category_manual | INTEGER | 1=手修正済み, 0=未手修正 |
| created_at | TEXT | ISO8601 |
| updated_at | TEXT | ISO8601 |

一意制約（重複判定キー）:

```text
UNIQUE (card_company, usage_date, merchant_name, amount, source_file, source_line)
```

同一キーのINSERTはスキップする（`INSERT OR IGNORE` 等）。

### 4.2 分類の決定

マージ時・辞書再適用時:

```text
resolve_category(lookup_key):
  辞書に有効なエントリあり → default_category（空なら「未分類」）
  なし → 「未分類」
```

明細の分類上書き:

```text
ユーザーが分類を個別変更
  → category を更新
  → category_manual = 1
```

辞書再適用:

```text
transactions の各行について:
  category_manual = 1 → スキップ（normalized_name / category を変更しない）
  category_manual = 0 → 店名辞書で normalized_name / category を再設定
```

分類決定・再適用ロジックは単一箇所に集約する。

### 4.3 照合キー生成

```text
lookup_key = NFKC(原文).strip()
空白の連続は1つに正規化
```

出力する「利用店名」は常に伝票原文。照合キーは辞書引き専用。

### 4.4 CSV列との対応

| CSV列名 | DB列 | 備考 |
|---------|------|------|
| 利用年月日 | usage_date | `YYYY/MM/DD` |
| 利用店名 | merchant_name | |
| 正規化店名 | normalized_name | |
| 分類 | category | |
| 利用金額 | amount | CSVはカンマ付き文字列、DBはINTEGER |
| カード会社 | card_company | |
| 取込元ファイル名 | source_file | |
| 取込行番号 | source_line | |
| 分類手動 | category_manual | バックアップ専用。`0`/`1` |

分析の明細CSV出力は上記のうち先頭8列（分類手動を除く）。

---

## 5. 処理設計

### 5.1 マージ全体フロー

```text
[開始] ログ作成（merge_YYYYMMDD_HHMMSS.log）
  ↓
ファイルごとに:
  プロファイル取得（手動割当済み）
  → 指定encodingで読込
  → header_row / footer_rows 適用
  → 期待ヘッダー検証（失敗=検証エラー→全体中止）
  → 行ごとに日付・金額変換
      失敗行 → 除外（ログ記録、処理継続）
      成功行 → 店名照合・分類付与・明細化
  ↓
未登録店名を DB 更新
  ↓
明細を transactions へ INSERT（重複キーはスキップ）
  ※ merged_*.csv の自動出力は行わない
  ↓
[終了] ログに終了を記録（登録件数・スキップ件数など）
  ↓
除外あり → ポップアップ（ログ誘導）
エラーあり → DBへ登録せず、ポップアップ（ログ誘導）
```

### 5.2 単票読込（固定＋検証）

1. `encoding` でデコード（失敗は検証エラー）
2. `header_row`（1始まり）でヘッダー位置を決定
3. `footer_rows` で末尾行を除外
4. `date_column` / `merchant_column` / `amount_column` がヘッダーに存在するか検証
5. 各データ行:
   - 日付: `date_format` で解析 → 内部は date/datetime、保存は `%Y/%m/%d`
   - 金額: 通貨記号・カンマ除去、`minus_format` に応じて符号処理 → 整数
   - 日付または金額が変換不可 → 除外行
6. 有効明細が0件 → 検証エラー（全体中止）

### 5.3 金額・日付の扱い

| 項目 | 処理中 | DB保存時 | バックアップCSV出力時 |
|------|--------|----------|----------------------|
| 日付 | datetime/date | `YYYY/MM/DD` 文字列 | `YYYY/MM/DD` 文字列 |
| 金額 | int | INTEGER | カンマ付き文字列（例: `1,234`） |

バックアップ／リストアCSV共通:

- `encoding="utf-8"`（BOMなし）
- `quoting=csv.QUOTE_ALL`
- 列順は要件定義書どおり（9列）

### 5.4 除外とエラーの違い

| 種別 | 例 | マージ結果 | UI |
|------|-----|------------|-----|
| 除外行 | 合計行、空行、日付不正 | 有効明細はDBへ登録 | 全処理後にログ誘導ポップアップ |
| 検証エラー | 文字コード失敗、ヘッダー不一致 | DB登録しない | 即中止、ログ誘導ポップアップ |

除外の詳細（ファイル名、行番号、元データ抜粋など）はログのみ。ポップアップ本文は固定文言。

### 5.5 CSVバックアップ／リストア

**バックアップ**

```text
ファイルダイアログで保存先を選択
  ↓
transactions 全件を9列CSVで出力
  （利用金額はカンマ付き、分類手動は 0/1）
```

**リストア**

```text
ファイルダイアログで読込元を選択
  ↓
CSV検証（必須列・型）
  ↓
トランザクション開始
  → transactions を全削除
  → CSV行を INSERT
  → コミット
```

リストアは「差し替え復元」。マージ時のような重複スキップ追記ではない。

### 5.6 辞書再適用

```text
店名辞書タブ等から「再適用」実行
  ↓
category_manual = 0 の明細のみ
  利用店名から lookup_key を生成し辞書照合
  → normalized_name / category を更新
  ↓
更新件数を案内
```

### 5.7 分析フロー

```text
data/app.db の transactions を読込
  ↓
期間（年月）・カード会社・分類でフィルタ
  ↓
マイナス金額 OFF なら amount < 0 を除外
  ↓
分類ごとに合計・件数・割合を算出
  ↓
円グラフ表示（matplotlib, フォント=Meiryo）
集計表表示
  ↓
任意で 集計CSV / PNG / フィルタ後明細CSV を保存
```

円グラフ:

- 区分: 固定費／変動費／臨時費／未分類
- 金額0の区分は表示しない
- 未分類は色を区別し、登録漏れに気づけるようにする

分析対象のCSV選択UIは廃止する（常にDB）。

---

## 6. UI設計

### 6.1 起動時のウィンドウ配置

メインウィンドウは起動時に画面の上下左右中央へ配置する。

- ウィンドウサイズ確定後に、画面幅・高さから中央座標を算出して geometry を設定する
- 複数モニタ環境では、主にプライマリモニタ中央を想定する

### 6.2 タブ構成

```text
[マージ] [明細] [プロファイル設定] [店名辞書] [未登録店名] [分析]
```

### 6.3 マージタブ

- 伝票追加／選択削除／すべて削除
- 一覧: ファイル名、カード会社（プロファイル）、状態、エラー概要
- 行ごとにプロファイル手動選択
- 検証ボタン、マージ実行ボタン
- 進捗表示（別スレッド）

完了時:

- 成功: 登録件数・スキップ件数などのサマリ。除外があれば除外ポップアップ
- 失敗: エラーポップアップ（ログ誘導）

### 6.4 明細タブ

蓄積明細の閲覧・分類編集・CSVバックアップ／リストアを担う。

- フィルタ: 年月（期間）、カード会社、分類 など
- 一覧: 利用年月日、利用店名、正規化店名、分類、利用金額、カード会社、分類手動 など
- 選択行の分類変更（変更後は分類手動=1）
- **CSVバックアップ／CSVリストア**ボタン（ファイルダイアログ）
- リストア前は、既存明細が消える旨を確認ダイアログで案内する
- 明細の削除UIは置かない

### 6.5 プロファイル設定タブ

- 左: プロファイル一覧
- 右: 編集フォーム
- 操作: 新規／複製／保存／無効化／削除／テスト読込
- 文字コード・日付書式は候補＋手入力可
- ヘッダー行は1始まりで表示し、説明を添える

### 6.6 店名辞書タブ

- 検索付き一覧（原文、照合キー、分析用名称、既定分類、有効）
- 追加／編集／削除
- 照合キーは自動生成表示（基本編集不可）
- 既定分類は Combobox（readonly）
- **辞書再適用**ボタン（手修正明細は対象外）

### 6.7 未登録店名タブ

- 未登録一覧
- 分析用名称・分類を入力して辞書登録
- 可能なら複数選択の一括登録

### 6.8 分析タブ

集計・可視化に専念する（明細編集・バックアップ／リストアは明細タブ）。

- 上部: 期間（年月）、カード会社、分類、マイナス含むか、集計実行（対象CSV選択はなし）
- 左: 円グラフ
- 右: 集計表（合計・件数・割合）＋未分類サマリ
- 下部: PNG保存、集計CSV保存、**フィルタ後の明細CSV出力**

---

## 7. ログ設計

ファイル: `log/merge_YYYYMMDD_HHMMSS.log`（マージ開始時刻）

記録内容（例）:

```text
[START] 2026-07-20 12:50:00 merge started
[INFO]  file=a.csv profile=A社カード
[EXCLUDE] file=a.csv line=120 reason=invalid_date raw=...
[ERROR] file=b.csv reason=header_mismatch detail=...
[END] status=aborted|completed inserted_rows=... skipped_rows=... excluded_rows=...
```

エンコードは UTF-8 を推奨。

---

## 8. 候補値（プロファイルUI）

### 文字コード

- `cp932`
- `utf-8-sig`
- `utf-8`
- （手入力可）

### 日付書式

- `%Y/%m/%d`
- `%Y-%m-%d`
- `%Y年%m月%d日`
- （手入力可）

### マイナス表記

- `sign`: `-1000`
- `paren`: `(1,000)`

### 分類

- 固定費
- 変動費
- 臨時費
- 未分類

---

## 9. エラーハンドリング方針

1. ユーザー向けメッセージは短く、詳細はログへ
2. 検証エラーはフェイルファスト（全体中止、DB非登録）
3. 除外行は可能な限り継続し、有効明細はDBへ登録
4. GUIスレッドで重いI/O・集計を行わない
5. DB更新はトランザクションで行う
6. CSVリストアは検証後に全削除→挿入を同一トランザクションで行う

---

## 10. 将来拡張を見据えた設計上の配慮

| 将来機能 | 本版での備え |
|----------|----------------|
| 追加分析（月別・店別） | 分析は `transactions` を入力とする |
| スキーマ変更 | DBに schema_version を持たせてもよい（任意） |

---

## 11. 依存関係

`requirements.txt` で管理する想定パッケージ:

- pandas
- matplotlib

標準ライブラリ利用:

- tkinter / ttk
- sqlite3
- csv
- unicodedata
- threading / concurrent（GUIフリーズ防止）

---

## 12. 実装時の前提まとめ

- プロファイル割当は手動のみ
- 金額は整数円のみ
- マイナスは取り込み、分析時ON/OFF
- 日付保存・出力は `YYYY/MM/DD`
- マージ結果はDB蓄積（CSV自動出力なし）
- 同一明細は6キーでスキップ
- CSVバックアップ／リストアは明細タブのボタン＋ファイルダイアログ
- リストアは既存明細の全消去後に復元
- バックアップには分類手動を含める
- 辞書再適用は手修正明細を触らない
- 明細タブで一覧閲覧・個別分類編集あり、削除なし
- 分析は常にDBから集計に専念、フィルタ後明細CSVを出力可能
- 円グラフ日本語フォントは Meiryo
- DBパスは `data/app.db`
- タブは「マージ／明細／プロファイル設定／店名辞書／未登録店名／分析」
- ロジックとGUIを分離し、起動は `gui.py`
- 起動時のメインウィンドウは画面中央に配置する
