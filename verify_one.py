"""
Step 1: 1社・1年度で疎通確認するスクリプト
使い方: uv run python verify_one.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from edinet_client import get_documents_by_date, download_xbrl
from xbrl_parser import parse_xbrl_dir
from dividend_checker import check_violation

# ========================================
# 確認対象を変更したい場合はここを編集
# ========================================
# 任意の日付を指定（その日に提出された有報の中から1件取得）
TARGET_DATE = "2024-06-28"
TARGET_COMPANY_NAME = None  # None の場合は最初の1件を自動選択
# ========================================


def main():
    print("=" * 60)
    print("EDINET API 疎通確認 & 1社検証")
    print("=" * 60)

    # Step 1: 書類一覧取得
    print(f"\n[1] {TARGET_DATE} の有価証券報告書一覧を取得中...")
    docs = get_documents_by_date(TARGET_DATE)
    annual_reports = [d for d in docs if d.get("formCode") == "030000"]
    print(f"  → {len(annual_reports)} 件取得")

    if not annual_reports:
        print("  有報が見つかりませんでした。日付を変えてください。")
        return

    # Step 2: 対象企業を選択
    if TARGET_COMPANY_NAME:
        target = next(
            (d for d in annual_reports if TARGET_COMPANY_NAME in d.get("filerName", "")),
            None,
        )
        if not target:
            print(f"  '{TARGET_COMPANY_NAME}' が見つかりません。最初の1件を使います。")
            target = annual_reports[0]
    else:
        target = annual_reports[0]

    doc_id = target["docID"]
    company = target.get("filerName", "不明")
    edinet_code = target.get("edinetCode", "不明")
    fiscal_year = target.get("periodEnd", "不明")

    print(f"\n[2] 対象企業: {company} ({edinet_code})")
    print(f"    docID   : {doc_id}")
    print(f"    決算期末 : {fiscal_year}")

    # Step 3: XBRLダウンロード
    print(f"\n[3] XBRLをダウンロード中...")
    xbrl_dir = download_xbrl(doc_id)
    xbrl_files = list(xbrl_dir.rglob("*.xbrl"))
    print(f"  → {len(xbrl_files)} 件のXBRLファイルを取得")
    for f in xbrl_files[:5]:
        print(f"    {f.name}")

    # Step 4: パース
    print(f"\n[4] XBRLをパース中...")
    data = parse_xbrl_dir(xbrl_dir)

    print("\n  --- 抽出結果 ---")
    numeric_fields = [k for k in data if not k.endswith("_tag")]
    for field in numeric_fields:
        val = data[field]
        tag = data.get(f"{field}_tag", "-")
        if val is not None:
            try:
                print(f"  {field:35s}: {float(val):>20,.0f} 円  (tag: {tag})")
            except (TypeError, ValueError):
                print(f"  {field:35s}: {str(val):>20s}  (tag: {tag})")
        else:
            print(f"  {field:35s}: {'取得不可':>20s}  (tag: {tag})")

    # Step 5: 違反チェック
    print(f"\n[5] 分配可能額計算 & 違反チェック...")
    result = check_violation(data)

    print(f"\n  --- 計算結果 ---")
    da = result["distributable_amount"]
    dp = result["dividends_paid"]
    print(f"  分配可能額   : {da:>20,.0f} 円" if da is not None else "  分配可能額   : 計算不可")
    print(f"  配当総額     : {dp:>20,.0f} 円" if dp is not None else "  配当総額     : 取得不可")

    if result["excess"] is not None:
        excess = result["excess"]
        rate = result["excess_rate"]
        print(f"  超過額       : {excess:>20,.0f} 円")
        if rate is not None:
            print(f"  超過率       : {rate:>19.1f} %")
        print(f"  違反候補     : {'[YES]' if result['is_violation_candidate'] else '[NO]'}")

    print(f"  信頼度       : {result['confidence']}")
    if result["missing_fields"]:
        print(f"  取得不可項目 : {', '.join(result['missing_fields'])}")

    print(f"\n  --- 構成要素内訳 ---")
    for k, v in result["components"].items():
        print(f"  {k:35s}: {v:>20,.0f} 円")

    print("\n" + "=" * 60)
    print("検証完了。有報の記載と数値を手動で照合してください。")
    print("=" * 60)


if __name__ == "__main__":
    main()
