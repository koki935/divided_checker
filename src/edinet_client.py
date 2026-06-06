"""EDINET API クライアント"""
import os
import time
import zipfile
import io
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("EDINET_API_KEY")
BASE_URL = "https://api.edinet-fsa.go.jp/api/v2"


def get_documents_by_date(date: str) -> list[dict]:
    """指定日の書類一覧を取得する（type=2: 有価証券報告書）"""
    url = f"{BASE_URL}/documents.json"
    params = {
        "date": date,
        "type": 2,
        "Subscription-Key": API_KEY,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("results", [])


def fetch_xbrl_bytes(doc_id: str) -> bytes:
    """
    有報 XBRL をメモリ上で取得し、有報本体 .xbrl ファイルの内容を bytes で返す。
    ディスクには何も書かない。
    """
    url = f"{BASE_URL}/documents/{doc_id}"
    params = {"type": 1, "Subscription-Key": API_KEY}  # type=1: 書類一式zip
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        names = z.namelist()
        # 有報本体 (jpcrp030000) を優先、次に jpcrp 全般、監査報告書(jpaud)は除外
        candidates = [n for n in names if "jpcrp030000" in n and n.endswith(".xbrl")]
        if not candidates:
            candidates = [n for n in names if "jpcrp" in n and n.endswith(".xbrl")]
        if not candidates:
            candidates = [n for n in names if n.endswith(".xbrl") and "jpaud" not in n]
        if not candidates:
            candidates = [n for n in names if n.endswith(".xbrl")]
        if not candidates:
            raise FileNotFoundError(f"XBRLファイルが見つかりません: {doc_id}")
        return z.read(candidates[0])


def find_docs_for_company(edinet_code: str, start_date: str, end_date: str) -> list[dict]:
    """
    指定期間内で特定企業（EDINETコード）の有報書類を収集する。
    日付ループで全日程を走査するため、件数が多い期間はやや遅い。
    """
    from datetime import date, timedelta

    results = []
    current = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    while current <= end:
        date_str = current.isoformat()
        try:
            docs = get_documents_by_date(date_str)
            for doc in docs:
                if (
                    doc.get("edinetCode") == edinet_code
                    and doc.get("formCode") == "030000"  # 有価証券報告書
                ):
                    results.append(doc)
        except Exception as e:
            print(f"  [{date_str}] 取得失敗: {e}")
        current += timedelta(days=1)
        time.sleep(0.3)  # レート制限対策

    return results


if __name__ == "__main__":
    # 動作確認: 任意の日付で書類一覧を取得
    test_date = "2024-06-28"
    print(f"=== {test_date} の有報一覧を取得 ===")
    docs = get_documents_by_date(test_date)
    annual_reports = [d for d in docs if d.get("formCode") == "030000"]
    print(f"  有価証券報告書: {len(annual_reports)} 件")
    if annual_reports:
        sample = annual_reports[0]
        print(f"  サンプル: {sample.get('filerName')} / docID={sample.get('docID')}")
