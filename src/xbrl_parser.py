"""XBRLファイルから財務データを抽出する"""
from pathlib import Path
from lxml import etree

# -----------------------------------------------------------------------
# コンテキスト優先順位の設計思想
#
# 会社法461条の分配可能額は「最終事業年度の末日（前期末）のBS」を基準とする。
# 配当は当期中（株主総会後）に支払われるため、
#   分配可能額の計算基準 = 前期末BS（Prior1YearInstant）
#   配当支払額          = 当期変動計算書（CurrentYearDuration）
# の組み合わせが正しい比較となる。
#
# したがってBSタグ（残高）は Prior1YearInstant を優先し、
# 配当タグ（変動）は CurrentYearDuration を優先する。
# -----------------------------------------------------------------------

# BSタグ用コンテキスト優先順（前期末を優先）
BS_CONTEXT_PRIORITY = [
    "Prior1YearInstant_NonConsolidatedMember",   # 前期末・単体 ← 最優先
    "CurrentYearInstant_NonConsolidatedMember",  # 当期末・単体（フォールバック）
    "Prior1YearInstant",                         # 前期末・単体のみ会社
    "CurrentYearInstant",                        # 当期末・単体のみ会社
    "FilingDateInstant_Row1Member",
    "FilingDateInstant",
]

# 配当タグ用コンテキスト優先順（当期の支払いを取得）
DIV_CONTEXT_PRIORITY = [
    "CurrentYearDuration_NonConsolidatedMember",  # 当期変動・単体 ← 最優先
    "CurrentYearDuration",                        # 当期変動・単体のみ会社
    "Prior1YearDuration_NonConsolidatedMember",   # 前期変動・フォールバック
    "Prior1YearDuration",
]

# 連結コンテキストは除外
CONSOLIDATED_EXCLUDE = [
    "ConsolidatedMember",
]

# BSタグ（残高系）
BS_TAGS = {
    "other_capital_surplus": ["OtherCapitalSurplus"],
    "retained_earnings": [
        "RetainedEarnings",
        "OtherRetainedEarnings",
        "RetainedEarningsBroughtForward",
    ],
    "treasury_stock": ["TreasuryStock"],
    "goodwill": ["Goodwill"],
    "deferred_assets": ["DeferredAssets"],
    "capital_stock": ["CapitalStock"],
    "capital_surplus": ["LegalCapitalSurplus", "CapitalSurplus"],
    "legal_reserve": [
        "LegalRetainedEarnings",
        "LegalRetainedEarningsReserve",
        "LegalRevenueReserve",
    ],
}

# 配当タグ（変動系）
DIV_TAGS = {
    "dividends_paid": [
        "DividendsFromSurplus",
        "TotalAmountOfDividendsDividendsOfSurplus",
        "CashDividendsPaidFinCF",
        "DividendsPaid",
    ],
}

# 後方互換用（旧コードの参照）
TARGET_TAGS = {**BS_TAGS, **DIV_TAGS}


def _context_score(context_id: str, priority_list: list) -> int:
    """コンテキストIDのスコア（低いほど優先）。除外対象は -1。"""
    for excl in CONSOLIDATED_EXCLUDE:
        if excl in context_id and "NonConsolidated" not in context_id:
            return -1
    for i, kw in enumerate(priority_list):
        if kw in context_id:
            return i
    return len(priority_list)  # 優先リスト外


def parse_xbrl_bytes(xbrl_bytes: bytes) -> dict:
    """XBRL ファイルの bytes を直接受け取ってパースする（ディスク不使用）"""
    root = etree.fromstring(xbrl_bytes)
    return _extract_from_root(root)


def parse_xbrl_dir(xbrl_dir: Path) -> dict:
    """展開済みXBRLディレクトリから財務データを抽出する（後方互換用）"""
    xbrl_files = list(xbrl_dir.rglob("*.xbrl"))
    main_files = [f for f in xbrl_files if "jpcrp030000" in f.name or "jpcrp" in f.name]
    if not main_files:
        main_files = [f for f in xbrl_files if "jpaud" not in f.name]
    if not main_files:
        main_files = xbrl_files
    if not main_files:
        return {"error": "XBRLファイルが見つかりません"}
    return _extract_from_file(main_files[0])


def _extract_from_file(xbrl_path: Path) -> dict:
    tree = etree.parse(str(xbrl_path))
    root = tree.getroot()
    return _extract_from_root(root)


def _extract_from_root(root) -> dict:
    """
    BSタグは前期末（Prior1YearInstant）優先で取得。
    配当タグは当期変動（CurrentYearDuration）優先で取得。
    会社法461条の分配可能額は「最終事業年度末日のBS」が基準であり、
    当期中に支払われた配当と比較するためこの組み合わせが正しい。
    """
    result = {}

    # BSタグ（残高）: 前期末優先
    for field, tag_candidates in BS_TAGS.items():
        best_value = None
        best_score = 9999
        best_tag = None

        for tag in tag_candidates:
            elements = root.xpath(f"//*[local-name()='{tag}']")
            for elem in elements:
                context_id = elem.get("contextRef", "")
                score = _context_score(context_id, BS_CONTEXT_PRIORITY)
                if score == -1:
                    continue
                if elem.text and elem.text.strip():
                    try:
                        raw = float(elem.text.strip())
                        if score < best_score:
                            best_score = score
                            best_value = raw
                            best_tag = tag
                    except (ValueError, TypeError):
                        continue

            if best_value is not None and best_score == 0:
                break

        result[field] = best_value
        result[f"{field}_tag"] = best_tag

    # 配当タグ（変動）: 当期変動優先
    for field, tag_candidates in DIV_TAGS.items():
        best_value = None
        best_score = 9999
        best_tag = None

        for tag in tag_candidates:
            elements = root.xpath(f"//*[local-name()='{tag}']")
            for elem in elements:
                context_id = elem.get("contextRef", "")
                score = _context_score(context_id, DIV_CONTEXT_PRIORITY)
                if score == -1:
                    continue
                if elem.text and elem.text.strip():
                    try:
                        raw = float(elem.text.strip())
                        if score < best_score:
                            best_score = score
                            best_value = raw
                            best_tag = tag
                    except (ValueError, TypeError):
                        continue

            if best_value is not None and best_score == 0:
                break

        result[field] = best_value
        result[f"{field}_tag"] = best_tag

    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("使い方: uv run python src/xbrl_parser.py <XBRLディレクトリパス>")
        sys.exit(1)
    data = parse_xbrl_dir(Path(sys.argv[1]))
    for k, v in data.items():
        if not k.endswith("_tag"):
            tag = data.get(f"{k}_tag", "-")
            print(f"  {k:40s}: {v}  (tag: {tag})")
