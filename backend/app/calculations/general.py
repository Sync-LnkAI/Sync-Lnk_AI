from decimal import Decimal, ROUND_HALF_UP
from typing import Any

# 数値をDecimalへ安全に変換する処理関数
def to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value

    if value is None:
        raise ValueError("数値が指定されていません")

    normalized_value = str(value).replace(",", "").strip()

    try:
        return Decimal(normalized_value)
    except Exception as error:
        raise ValueError(
            f"数値へ変換できません: {value}"
        ) from error
#================================================

# 計算結果を四捨五入して整数にする処理関数
def round_to_integer(value: Decimal) -> int:
    return int(
        value.quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP
        )
    )
#================================================

# 複利計算関数
def calculate_compound_interest(
    principal: Any,
    annual_rate: Any,
    years: Any,
    compounding_per_year: Any = 1
) -> dict:
    principal_d = to_decimal(principal)
    annual_rate_d = to_decimal(annual_rate)
    years_d = to_decimal(years)
    compounding_per_year_d = to_decimal(compounding_per_year)

    if principal_d < 0:
        raise ValueError("principalは0以上にしてください")
    if annual_rate_d < 0:
        raise ValueError("annual_rateは0以上にしてください")
    if years_d <= 0:
        raise ValueError("yearsは0より大きくしてください")
    if compounding_per_year_d <= 0:
        raise ValueError("compounding_per_yearは0より大きくしてください")
    if compounding_per_year_d != compounding_per_year_d.to_integral_value():
        raise ValueError("compounding_per_yearは整数にしてください")

    period_count = years_d * compounding_per_year_d
    if period_count != period_count.to_integral_value():
        raise ValueError("運用期間と複利回数から求めた期間数が整数になりません")

    periodic_rate = annual_rate_d / compounding_per_year_d
    final_amount = principal_d * (
        Decimal("1") + periodic_rate
    ) ** int(period_count)
    profit = final_amount - principal_d

    return {
        "principal": round_to_integer(principal_d),
        "annual_rate": float(annual_rate_d),
        "years": float(years_d),
        "compounding_per_year": int(compounding_per_year_d),
        "period_count": int(period_count),
        "final_amount": round_to_integer(final_amount),
        "profit": round_to_integer(profit)
    }
#================================================

# 割合・増減率・差額の計算関数
def calculate_percentage_calculation(
    base_value: Any,
    comparison_value: Any,
    rate: Any,
    calculation_mode: str
) -> dict:
    normalized_mode = str(calculation_mode or "").strip().lower()
    allowed_modes = {
        "percentage_of_value",
        "ratio",
        "percentage_change",
        "difference",
        "discounted_value",
        "increased_value"
    }

    if normalized_mode not in allowed_modes:
        raise ValueError("対応していないcalculation_modeです")

    base_value_d = to_decimal(base_value) if base_value is not None else None
    comparison_value_d = to_decimal(comparison_value) if comparison_value is not None else None
    rate_d = to_decimal(rate) if rate is not None else None

    if base_value_d is not None and base_value_d < 0:
        raise ValueError("base_valueは0以上にしてください")
    if comparison_value_d is not None and comparison_value_d < 0:
        raise ValueError("comparison_valueは0以上にしてください")
    if rate_d is not None and rate_d < 0:
        raise ValueError("rateは0以上にしてください")

    if normalized_mode in {"percentage_of_value", "discounted_value", "increased_value"}:
        if base_value_d is None or rate_d is None:
            raise ValueError("base_valueとrateが必要です")

    if normalized_mode in {"ratio", "percentage_change", "difference"}:
        if base_value_d is None or comparison_value_d is None:
            raise ValueError("base_valueとcomparison_valueが必要です")

    if normalized_mode == "percentage_of_value":
        result_value = base_value_d * rate_d
    elif normalized_mode == "ratio":
        if base_value_d == 0:
            raise ValueError("割合計算のbase_valueを0にはできません")
        result_value = comparison_value_d / base_value_d
    elif normalized_mode == "percentage_change":
        if base_value_d == 0:
            raise ValueError("増減率計算のbase_valueを0にはできません")
        result_value = (comparison_value_d - base_value_d) / base_value_d
    elif normalized_mode == "difference":
        result_value = comparison_value_d - base_value_d
    elif normalized_mode == "discounted_value":
        if rate_d > 1:
            raise ValueError("割引率は0から1の範囲にしてください")
        result_value = base_value_d * (Decimal("1") - rate_d)
    else:
        result_value = base_value_d * (Decimal("1") + rate_d)

    result_type = "rate" if normalized_mode in {"ratio", "percentage_change"} else "value"

    return {
        "calculation_mode": normalized_mode,
        "base_value": float(base_value_d) if base_value_d is not None else None,
        "comparison_value": float(comparison_value_d) if comparison_value_d is not None else None,
        "rate": float(rate_d) if rate_d is not None else None,
        "result_type": result_type,
        "result": float(result_value) if result_type == "rate" else round_to_integer(result_value),
        "result_percent": float(result_value * Decimal("100")) if result_type == "rate" else None
    }
#================================================
