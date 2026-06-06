"""
全社一括スキャン: 東証プライム × 複数年度 の分配可能額超過配当チェック

使い方:
    uv run python main.py

設定（このファイルの先頭を編集）:
    FISCAL_YEARS  : チェック対象年度（有報の提出年ベース）
    MAX_COMPANIES : テスト用上限（None で全件）
    USE_CACHE     : プライムリストと日付キャッシュを再利用するか
"""

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent / "src"))

from edinet_client import fetch_xbrl_bytes
from xbrl_parser import parse_xbrl_bytes
from dividend_checker import check_violation
from prime_list import get_prime_edinet_list
from doc_finder import bulk_find_docs
from reporter import export_violations

load_dotenv()
API_KEY = os.getenv("EDINET_API_KEY")

# ========================================
# 設定
# ========================================
FISCAL_YEARS = [2022, 2023, 2024]  # 有報提出年（例: 3月決算2024年3月期 → 提出は2024年6月 → 2024）
MAX_COMPANIES = None                # テスト時は 10 などに制限。None で全件
USE_CACHE = True                    # True: キャッシュ利用（2回目以降は高速）
CHECKPOINT_PATH = Path("data/processed/checkpoint.json")   # 中断再開用
OUTPUT_FILENAME = "violations.xlsx"
# ========================================


def load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        with open(CHECKPOINT_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"done_doc_ids": [], "results": []}


def save_checkpoint(done_doc_ids: list, results: list):
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump({"done_doc_ids": done_doc_ids, "results": results}, f, ensure_ascii=False)


def main():
    print("=" * 70)
    print("配当違反スクリーニング 全社スキャン")
    print(f"対象年度: {FISCAL_YEARS}")
    print("=" * 70)

    # Step 1: プライム銘柄リスト取得
    print("\n[1] 東証プライム銘柄リスト取得...")
    companies = get_prime_edinet_list(API_KEY, use_cache=USE_CACHE)
    companies = [c for c in companies if c.get("edinet_code")]  # 対応表ありのみ
    if MAX_COMPANIES:
        companies = companies[:MAX_COMPANIES]
    print(f"  対象: {len(companies)} 社")

    # Step 2: 有報 docID 収集
    print("\n[2] 有報 docID 収集（API を複数日サンプリング）...")
    doc_list = bulk_find_docs(companies, API_KEY, FISCAL_YEARS)
    print(f"  合計 {len(doc_list)} 件の有報を収集")

    # Step 3: チェックポイント読み込み（中断再開対応）
    checkpoint = load_checkpoint()
    done_ids = set(checkpoint["done_doc_ids"])
    results = checkpoint["results"]
    print(f"\n[3] チェックポイント: 処理済み {len(done_ids)} 件")

    # Step 4: XBRL 取得・パース・違反チェック
    remaining = [d for d in doc_list if d["doc_id"] not in done_ids]
    total = len(remaining)
    print(f"[4] XBRL 取得・チェック開始: 残り {total} 件\n")

    for i, doc_info in enumerate(remaining):
        doc_id = doc_info["doc_id"]
        name = doc_info.get("name", "不明")
        period = doc_info.get("period_end", "不明")
        print(f"  [{i+1}/{total}] {name} ({period}) docID={doc_id}", end=" ", flush=True)

        try:
            xbrl_bytes = fetch_xbrl_bytes(doc_id)
            data = parse_xbrl_bytes(xbrl_bytes)
            result = check_violation(data)

            record = {
                **doc_info,
                **result,
                # タグ情報をサマリに含める
                "dividends_paid_tag": data.get("dividends_paid_tag"),
            }
            results.append(record)
            done_ids.add(doc_id)

            status = "[YES]" if result["is_violation_candidate"] else "[no]"
            conf = result["confidence"]
            print(f"-> {status} conf={conf}")

        except Exception as e:
            print(f"-> ERROR: {e}")
            results.append({**doc_info, "error": str(e), "confidence": "LOW", "is_violation_candidate": False})
            done_ids.add(doc_id)

        # 50件ごとにチェックポイント保存
        if (i + 1) % 50 == 0:
            save_checkpoint(list(done_ids), results)
            print(f"\n  [checkpoint] {i+1}/{total} 件完了\n")

        time.sleep(0.5)  # レート制限対策

    # 最終チェックポイント保存
    save_checkpoint(list(done_ids), results)

    # Step 5: Excel 出力
    print("\n[5] Excel 出力...")
    output_path = export_violations(results, OUTPUT_FILENAME)
    print(f"  -> {output_path}")

    # サマリ表示
    violations = [r for r in results if r.get("is_violation_candidate") and r.get("confidence") in ("HIGH", "MEDIUM")]
    print("\n" + "=" * 70)
    print(f"スキャン完了")
    print(f"  処理件数         : {len(results)} 件")
    print(f"  違反候補(HIGH/MEDIUM) : {len(violations)} 件")
    print(f"  出力ファイル     : {output_path}")
    print("=" * 70)

    if violations:
        print("\n--- 違反候補 超過額トップ10 ---")
        top = sorted(violations, key=lambda r: r.get("excess", 0) or 0, reverse=True)[:10]
        for r in top:
            print(f"  {r.get('name', ''):20s} {r.get('period_end', '')} "
                  f"超過={r.get('excess', 0):>15,.0f}円 "
                  f"({r.get('excess_rate', 0) or 0:.1f}%) conf={r.get('confidence')}")


if __name__ == "__main__":
    main()
