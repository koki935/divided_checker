"""EDINETコードと年度から有報のdocIDを効率的に検索する"""
import time
from datetime import date, timedelta
from typing import Generator
import requests


# 有報提出が集中する月（決算月+3ヶ月後が提出期限）
# 3月決算 → 6月末、12月決算 → 3月末、9月決算 → 12月末、6月決算 → 9月末
# 各月末前後2週間を優先的に探索
SUBMISSION_PEAK_MONTHS = {
    3: [6],   # 6月提出
    6: [9],   # 9月提出
    9: [12],  # 12月提出
    12: [3],  # 3月提出
}

# 全月をカバーするデフォルト探索月
ALL_SUBMISSION_MONTHS = [3, 6, 9, 12]


def date_range(start: date, end: date) -> Generator[date, None, None]:
    """開始〜終了日の日付を1日ずつ生成する"""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def find_annual_reports_for_company(
    edinet_code: str,
    api_key: str,
    fiscal_years: list[int],
    cache: dict | None = None,
) -> list[dict]:
    """
    指定企業・指定年度リストの有報docIDを収集する。

    探索戦略:
    - 各年の提出ピーク月（末日前後3週間）だけを探索してAPI呼び出しを削減
    - 見つかった場合はそれ以上その年を探索しない

    Args:
        edinet_code: EDINETコード（例: "E01441"）
        api_key: EDINET APIキー
        fiscal_years: 有報の「提出年」リスト（例: [2022, 2023, 2024]）
        cache: 日付→書類一覧のキャッシュ dict（複数企業で共有して API 呼び出しを削減）

    Returns:
        [{"edinet_code": ..., "doc_id": ..., "fiscal_year": ..., "period_end": ..., "submit_date": ...}]
    """
    if cache is None:
        cache = {}

    results = []

    for year in fiscal_years:
        found = False
        # 各提出ピーク月の末日前後3週間を探索
        for month in ALL_SUBMISSION_MONTHS:
            if found:
                break
            # 月末前後
            try:
                peak_end = date(year, month, 28)
            except ValueError:
                continue
            search_start = peak_end - timedelta(days=14)
            search_end = peak_end + timedelta(days=10)
            # 未来日は除外
            today = date.today()
            if search_start > today:
                continue
            search_end = min(search_end, today)

            for d in date_range(search_start, search_end):
                date_str = d.isoformat()
                if date_str not in cache:
                    try:
                        resp = requests.get(
                            "https://api.edinet-fsa.go.jp/api/v2/documents.json",
                            params={"date": date_str, "type": 2, "Subscription-Key": api_key},
                            timeout=30,
                        )
                        cache[date_str] = resp.json().get("results", [])
                    except Exception:
                        cache[date_str] = []
                    time.sleep(0.2)

                for doc in cache[date_str]:
                    if (
                        doc.get("edinetCode") == edinet_code
                        and doc.get("formCode") == "030000"
                        and doc.get("withdrawalStatus") == "0"  # 取下げ除外
                    ):
                        results.append({
                            "edinet_code": edinet_code,
                            "doc_id": doc["docID"],
                            "fiscal_year": year,
                            "period_end": doc.get("periodEnd"),
                            "submit_date": date_str,
                        })
                        found = True
                        break
                if found:
                    break

    return results


def bulk_find_docs(
    companies: list[dict],
    api_key: str,
    fiscal_years: list[int],
) -> list[dict]:
    """
    複数企業の有報docIDを一括収集する。
    日付→書類一覧キャッシュを全企業で共有してAPI呼び出し数を最小化する。
    """
    shared_cache: dict = {}
    all_results = []
    total = len(companies)

    for i, company in enumerate(companies):
        edinet = company.get("edinet_code")
        if not edinet:
            continue
        name = company.get("name", "不明")
        print(f"  [{i+1}/{total}] {name} ({edinet})", end="", flush=True)

        docs = find_annual_reports_for_company(edinet, api_key, fiscal_years, shared_cache)
        print(f" -> {len(docs)} 件")

        for doc in docs:
            all_results.append({**company, **doc})

    return all_results
