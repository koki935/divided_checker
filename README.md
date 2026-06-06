# 配当違反チェッカー（分配可能額超過配当スクリーニング）

EDINET API から有価証券報告書の XBRL データを取得し、**会社法461条（分配可能額超過配当）** に抵触している可能性がある上場企業をスクリーニングするツールです。

---

## 概要

### 対象とする違反類型

| 根拠条文 | 内容 |
|---|---|
| **会社法461条2項** | 配当総額が分配可能額を超えた場合は違法配当となる |

### 分配可能額の計算式

```
分配可能額
  = その他資本剰余金
  + 繰越利益剰余金（その他利益剰余金）
  - 自己株式の帳簿価額
  - のれん等調整額（会社法計算規則158条）
      ※ のれん÷2 + 繰延資産 が 資本金+準備金合計 を超える場合のみ控除
```

> **重要**: 連結ではなく**単体財務諸表**ベースで判定します。

---

## セットアップ

### 必要環境

- Python 3.12 以上
- [uv](https://docs.astral.sh/uv/)（パッケージマネージャー）
- EDINET API キー（無料・要登録）

### インストール

```bash
# 依存パッケージをインストール
uv sync
```

### API キーの設定

`.env` ファイルを編集し、取得した API キーを設定します。

```
EDINET_API_KEY=ここにAPIキーを貼る
```

> EDINET API キーの取得: https://api.edinet-fsa.go.jp/

---

## ディレクトリ構成

```
.
├── src/
│   ├── edinet_client.py    # EDINET API 通信・XBRL ダウンロード
│   ├── xbrl_parser.py      # XBRL から財務データを抽出
│   └── dividend_checker.py # 分配可能額計算・違反判定ロジック
├── data/
│   ├── raw/                # ダウンロードした XBRL ファイル（キャッシュ）
│   └── processed/          # 抽出済み中間 CSV
├── output/                 # スクリーニング結果（Excel）
├── verify_one.py           # Step1: 1社検証スクリプト
├── main.py                 # Step2: 全社一括スキャン（実装予定）
├── .env                    # API キー（Git 管理外）
└── pyproject.toml
```

---

## 使い方

### Step 1: 1社で動作確認（まずここから）

任意の日付の有報を1件取得し、分配可能額を計算・表示します。

```bash
uv run python verify_one.py
```

`verify_one.py` の先頭にある定数で対象を変更できます。

```python
TARGET_DATE = "2024-06-28"          # 有報の提出日
TARGET_COMPANY_NAME = "トーアミ"    # None の場合は当日提出の先頭1件を自動選択
```

**出力例（正常企業の場合）:**

```
[2] 対象企業: トーアミ (E01441)
    決算期末 : 2024-03-31

[4] 抽出結果
  other_capital_surplus    :        6,656,000,000 円  (tag: OtherCapitalSurplus)
  retained_earnings        :    1,082,499,000,000 円  (tag: RetainedEarningsBroughtForward)
  treasury_stock           :     -328,087,000,000 円  (tag: TreasuryStock)
  dividends_paid           :      -90,363,000,000 円  (tag: DividendsFromSurplus)

[5] 計算結果
  分配可能額   :      761,068,000,000 円
  配当総額     :       90,363,000,000 円
  超過額       :     -670,705,000,000 円  ← マイナス = 余裕あり
  違反候補     : [NO]
  信頼度       : HIGH
```

### Step 2: 全社一括スキャン（実装予定）

```bash
uv run python main.py
```

東証プライム上場企業（約1,600社）× 複数年度を一括処理し、`output/violations.xlsx` に結果を出力します。

---

## 各モジュールの説明

### `src/edinet_client.py`

EDINET API v2 との通信を担当します。

| 関数 | 説明 |
|---|---|
| `get_documents_by_date(date)` | 指定日の有報一覧を取得 |
| `download_xbrl(doc_id)` | XBRL zip をダウンロード・展開 |
| `find_docs_for_company(edinet_code, start, end)` | 期間内の特定企業の有報を収集 |

### `src/xbrl_parser.py`

XBRL ファイルから財務数値を抽出します。

- 単体コンテキスト（`NonConsolidatedMember`）を優先して取得
- 当期末 → 直前期末 の順で優先度付け
- タグが複数候補ある場合は優先リスト順にフォールバック

**取得するタグ一覧:**

| 項目 | 優先タグ |
|---|---|
| その他資本剰余金 | `OtherCapitalSurplus` |
| 繰越利益剰余金 | `RetainedEarningsBroughtForward` → `RetainedEarnings` |
| 自己株式 | `TreasuryStock` |
| のれん | `Goodwill` |
| 繰延資産 | `DeferredAssets` |
| 資本金 | `CapitalStock` |
| 資本準備金 | `LegalCapitalSurplus` → `CapitalSurplus` |
| 利益準備金 | `LegalRetainedEarnings` |
| 配当支払額 | `DividendsFromSurplus` → `TotalAmountOfDividendsDividendsOfSurplus` → `CashDividendsPaidFinCF` |

### `src/dividend_checker.py`

分配可能額の計算と違反判定を行います。

**信頼度の基準:**

| 信頼度 | 条件 |
|---|---|
| HIGH | 主要3項目（資本剰余金・繰越利益・配当額）が全取得かつ欠損2項目以内 |
| MEDIUM | 主要項目の欠損が1つ以内 |
| LOW | 主要項目に複数欠損あり・要手動確認 |

---

## 注意事項・既知の限界

| 項目 | 内容 |
|---|---|
| **単体ベース** | 分配可能額は単体財務諸表で判定。連結数値を誤取得すると結果がズレる |
| **XBRL タグのブレ** | 企業独自の拡張タグを使っている場合は取得不可（LOWとして除外） |
| **中間配当の扱い** | 中間・期末の合算が正しく取れない場合あり（変動計算書ベースで対処） |
| **のれん等調整額** | 条件分岐が複雑なため過少控除になる可能性あり（保守的推定） |
| **法的効力なし** | 本ツールの結果は参考情報であり、法的判断には専門家の確認が必要 |

---

## 開発ステータス

- [x] EDINET API 疎通確認
- [x] XBRL パーサー実装（単体コンテキスト対応）
- [x] 分配可能額計算ロジック実装
- [x] 1社検証スクリプト（`verify_one.py`）
- [ ] プライム全社リスト取得
- [ ] 複数年度一括スキャン（`main.py`）
- [ ] 結果 Excel 出力（`output/violations.xlsx`）
- [ ] 誤検知フィルタリング

---

## 参考

- [EDINET API 仕様書](https://api.edinet-fsa.go.jp/)
- [会社法461条（剰余金の配当等の制限）](https://elaws.e-gov.go.jp/document?lawid=417AC0000000086)
- [会社法計算規則158条（のれん等調整額）](https://elaws.e-gov.go.jp/document?lawid=418M60000010013)
