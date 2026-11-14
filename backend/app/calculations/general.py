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