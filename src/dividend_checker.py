"""分配可能額の計算と配当違反チェック"""


def calc_distributable_amount(data: dict) -> dict:
    """
    会社法461条2項に基づき分配可能額を計算する。

    Returns:
        {
            "distributable_amount": float | None,
            "components": dict,  # 各構成要素
            "missing_fields": list[str],  # 取得できなかった項目
            "confidence": str,  # "HIGH" / "MEDIUM" / "LOW"
        }
    """
    components = {}
    missing = []

    def get(field: str) -> float | None:
        v = data.get(field)
        if v is None:
            missing.append(field)
        return v

    other_capital_surplus = get("other_capital_surplus") or 0.0
    retained_earnings_raw = get("retained_earnings") or 0.0
    treasury_stock = get("treasury_stock") or 0.0  # 通常マイナス値で格納
    goodwill = get("goodwill") or 0.0
    deferred_assets = get("deferred_assets") or 0.0
    capital_stock = get("capital_stock") or 0.0
    capital_surplus = get("capital_surplus") or 0.0
    legal_reserve = get("legal_reserve") or 0.0

    # retained_earnings タグが RetainedEarnings（利益剰余金合計）の場合、
    # 利益準備金（legal_reserve）が含まれているため除く。
    # OtherRetainedEarnings や RetainedEarningsBroughtForward の場合は含まれていない。
    retained_tag = data.get("retained_earnings_tag", "")
    if retained_tag == "RetainedEarnings":
        # 利益剰余金合計 - 利益準備金 = その他利益剰余金（分配可能額の計算対象）
        retained_earnings = retained_earnings_raw - legal_reserve
    else:
        retained_earnings = retained_earnings_raw

    # 自己株式はBSでマイナス計上されているため絶対値に変換して引く
    treasury_stock_abs = abs(treasury_stock)

    # のれん等調整額の計算（会社法計算規則158条）
    goodwill_half = goodwill / 2
    noren_adj_base = goodwill_half + deferred_assets
    reserve_total = capital_stock + capital_surplus + legal_reserve
    noren_adj = max(0.0, noren_adj_base - reserve_total)

    # 分配可能額
    distributable = (
        other_capital_surplus
        + retained_earnings
        - treasury_stock_abs
        - noren_adj
    )

    components = {
        "other_capital_surplus": other_capital_surplus,
        "retained_earnings": retained_earnings,
        "treasury_stock_deduction": -treasury_stock_abs,
        "noren_adjustment": -noren_adj,
        "goodwill_half": goodwill_half,
        "deferred_assets": deferred_assets,
        "reserve_total": reserve_total,
    }

    # 信頼度判定
    critical_fields = ["other_capital_surplus", "retained_earnings", "dividends_paid"]
    missing_critical = [f for f in missing if f in critical_fields]

    if len(missing_critical) == 0 and len(missing) <= 2:
        confidence = "HIGH"
    elif len(missing_critical) <= 1:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return {
        "distributable_amount": distributable,
        "components": components,
        "missing_fields": missing,
        "confidence": confidence,
    }


def check_violation(data: dict) -> dict:
    """
    分配可能額超過配当をチェックする。

    Returns:
        {
            "distributable_amount": float | None,
            "dividends_paid": float | None,
            "excess": float,          # 超過額（正値 = 違反候補）
            "excess_rate": float,     # 超過率(%)
            "is_violation_candidate": bool,
            "confidence": str,
            "missing_fields": list,
        }
    """
    calc = calc_distributable_amount(data)
    distributable = calc["distributable_amount"]
    dividends = data.get("dividends_paid")

    if distributable is None or dividends is None:
        return {
            "distributable_amount": distributable,
            "dividends_paid": dividends,
            "excess": None,
            "excess_rate": None,
            "is_violation_candidate": False,
            "confidence": "LOW",
            "missing_fields": calc["missing_fields"],
            "components": calc["components"],
        }

    # 配当額は正値に統一（CFはマイナスで格納されることがある）
    dividends_abs = abs(dividends)
    excess = dividends_abs - distributable
    excess_rate = (excess / distributable * 100) if distributable != 0 else None

    # 違反候補の条件：配当を実際に支払っており、かつ分配可能額を超過している
    is_violation = excess > 0 and dividends_abs > 0

    return {
        "distributable_amount": distributable,
        "dividends_paid": dividends_abs,
        "excess": excess,
        "excess_rate": excess_rate,
        "is_violation_candidate": is_violation,
        "confidence": calc["confidence"],
        "missing_fields": calc["missing_fields"],
        "components": calc["components"],
    }
