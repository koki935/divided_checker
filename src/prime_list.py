"""東証プライム銘柄リストの取得とEDINETコードへの変換"""
import time
import requests
import xlrd
from pathlib import Path

JPX_LIST_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
CACHE_PATH = Path(__file__).parent.parent / "data" / "processed" / "prime_edinet_map.json"


def fetch_prime_sec_codes() -> list[dict]:
    """JPXサイトから東証プライム銘柄の証券コード・会社名を取得する"""
    resp = requests.get(JPX_LIST_URL, timeout=30)
    resp.raise_for_status()
    wb = xlrd.open_workbook(file_contents=resp.content)
    ws = wb.sheet_by_index(0)

    prime = []
    for row in range(1, ws.nrows):
        market = ws.cell_value(row, 3)
        if "プライム" not in str(market):
            continue
        raw_code = ws.cell_value(row, 1)
        code = str(int(raw_code)).zfill(4) if isinstance(raw_code, float) else str(raw_code)
        name = ws.cell_value(row, 2)
        prime.append({"sec_code": code, "name": name})

    return prime


def build_sec_to_edinet_map(api_key: str, sample_dates: list[str]) -> dict[str, str]:
    """
    EDINET の書類一覧APIを複数日サンプリングして
    証券コード → EDINETコード の対応表を作る。
    """
    mapping: dict[str, str] = {}
    for date in sample_dates:
        try:
            resp = requests.get(
                "https://api.edinet-fsa.go.jp/api/v2/documents.json",
                params={"date": date, "type": 2, "Subscription-Key": api_key},
                timeout=30,
            )
            docs = resp.json().get("results", [])
            for doc in docs:
                sec = (doc.get("secCode") or "")[:4]
                edinet = doc.get("edinetCode", "")
                if sec and edinet and doc.get("formCode") == "030000":
                    mapping[sec] = edinet
        except Exception as e:
            print(f"  [{date}] 取得失敗: {e}")
        time.sleep(0.3)

    return mapping


def get_prime_edinet_list(api_key: str, use_cache: bool = True) -> list[dict]:
    """
    プライム銘柄の EDINETコード付きリストを返す。

    Returns:
        [{"sec_code": "1301", "name": "...", "edinet_code": "E00xxx"}, ...]
        edinet_code が None の銘柄は対応表に見つからなかった企業
    """
    import json

    if use_cache and CACHE_PATH.exists():
        print(f"  キャッシュから読み込み: {CACHE_PATH}")
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)

    print("  プライム銘柄リストを JPX から取得中...")
    prime = fetch_prime_sec_codes()
    print(f"  -> {len(prime)} 銘柄")

    # EDINET の有報提出が集中する日程をサンプリング
    # 3月決算が多い6月末・12月決算が多い3月末などをカバー
    sample_dates = [
        "2024-06-28", "2024-06-27", "2024-06-26", "2024-06-25",
        "2024-03-29", "2024-03-28",
        "2023-06-30", "2023-06-29", "2023-06-28",
        "2023-03-31", "2023-03-30",
        "2022-06-30", "2022-06-29", "2022-06-28",
        "2022-03-31", "2022-03-30",
        "2021-06-30", "2021-06-29",
        "2021-03-31", "2021-03-30",
        # 9月決算・12月決算対応
        "2024-11-29", "2024-12-27",
        "2023-11-30", "2023-12-28",
    ]

    print("  EDINETコード対応表を構築中（しばらくかかります）...")
    sec_to_edinet = build_sec_to_edinet_map(api_key, sample_dates)
    print(f"  -> {len(sec_to_edinet)} 件の対応を取得")

    # 結合
    result = []
    matched = 0
    for p in prime:
        edinet = sec_to_edinet.get(p["sec_code"])
        if edinet:
            matched += 1
        result.append({**p, "edinet_code": edinet})

    print(f"  EDINETコード紐付き: {matched}/{len(prime)} 銘柄")

    # キャッシュ保存
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  キャッシュ保存: {CACHE_PATH}")

    return result


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    API_KEY = os.getenv("EDINET_API_KEY")
    companies = get_prime_edinet_list(API_KEY, use_cache=False)
    no_edinet = [c for c in companies if not c["edinet_code"]]
    print(f"\n結果: {len(companies)} 銘柄中 {len(no_edinet)} 銘柄はEDINETコード未取得")
