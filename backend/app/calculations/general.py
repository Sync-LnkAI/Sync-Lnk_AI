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

# 単利計算関数
def calculate_simple_interest(
    principal: Any,
    annual_rate: Any,
    years: Any
) -> dict:
    principal_d = to_decimal(principal)
    annual_rate_d = to_decimal(annual_rate)
    years_d = to_decimal(years)

    if principal_d < 0:
        raise ValueError("principalは0以上にしてください")
    if annual_rate_d < 0:
        raise ValueError("annual_rateは0以上にしてください")
    if years_d <= 0:
        raise ValueError("yearsは0より大きくしてください")

    interest = principal_d * annual_rate_d * years_d
    final_amount = principal_d + interest

    return {
        "principal": round_to_integer(principal_d),
        "annual_rate": float(annual_rate_d),
        "years": float(years_d),
        "interest": round_to_integer(interest),
        "final_amount": round_to_integer(final_amount)
    }
#================================================

# 定期積立のPython計算関数
def calculate_recurring_investment(
    initial_principal: Any,
    contribution_amount: Any,
    contributions_per_year: Any,
    annual_rate: Any,
    years: Any,
    compounding_per_year: Any,
    contribution_timing: str
) -> dict:
    initial_principal_d = to_decimal(initial_principal or 0)
    contribution_amount_d = to_decimal(contribution_amount)
    contributions_per_year_d = to_decimal(contributions_per_year)
    annual_rate_d = to_decimal(annual_rate)
    years_d = to_decimal(years)
    compounding_per_year_d = to_decimal(compounding_per_year)
    normalized_timing = str(contribution_timing or "").strip().lower()

    if initial_principal_d < 0:
        raise ValueError("initial_principalは0以上にしてください")
    if contribution_amount_d < 0:
        raise ValueError("contribution_amountは0以上にしてください")
    if annual_rate_d < 0:
        raise ValueError("annual_rateは0以上にしてください")
    if years_d <= 0:
        raise ValueError("yearsは0より大きくしてください")
    if contributions_per_year_d <= 0:
        raise ValueError("contributions_per_yearは0より大きくしてください")
    if compounding_per_year_d <= 0:
        raise ValueError("compounding_per_yearは0より大きくしてください")
    if contributions_per_year_d != contributions_per_year_d.to_integral_value():
        raise ValueError("contributions_per_yearは整数にしてください")
    if compounding_per_year_d != compounding_per_year_d.to_integral_value():
        raise ValueError("compounding_per_yearは整数にしてください")
    if normalized_timing not in {"beginning", "end"}:
        raise ValueError("contribution_timingはbeginningまたはendにしてください")

    contributions_per_year_i = int(contributions_per_year_d)
    compounding_per_year_i = int(compounding_per_year_d)

    if compounding_per_year_i % contributions_per_year_i != 0:
        raise ValueError("複利回数は積立回数の整数倍にしてください")

    contribution_count = years_d * contributions_per_year_d
    compounding_period_count = years_d * compounding_per_year_d

    if contribution_count != contribution_count.to_integral_value():
        raise ValueError("積立期間から求めた積立回数が整数になりません")
    if compounding_period_count != compounding_period_count.to_integral_value():
        raise ValueError("運用期間から求めた複利回数が整数になりません")

    contribution_count_i = int(contribution_count)
    compounding_period_count_i = int(compounding_period_count)
    periodic_rate = (Decimal("1") + annual_rate_d) ** (
        Decimal("1") / compounding_per_year_d
    ) - Decimal("1")
    compound_periods_per_contribution = compounding_per_year_i // contributions_per_year_i
    contribution_period_rate = (
        Decimal("1") + periodic_rate
    ) ** compound_periods_per_contribution - Decimal("1")
    initial_principal_final = initial_principal_d * (
        Decimal("1") + periodic_rate
    ) ** compounding_period_count_i

    if contribution_period_rate == 0:
        contributions_final = contribution_amount_d * contribution_count_i
    else:
        contributions_final = contribution_amount_d * (
            (Decimal("1") + contribution_period_rate) ** contribution_count_i
            - Decimal("1")
        ) / contribution_period_rate
        if normalized_timing == "beginning":
            contributions_final *= Decimal("1") + contribution_period_rate

    total_contributions = initial_principal_d + contribution_amount_d * contribution_count_i
    final_amount = initial_principal_final + contributions_final
    profit = final_amount - total_contributions

    return {
        "initial_principal": round_to_integer(initial_principal_d),
        "contribution_amount": round_to_integer(contribution_amount_d),
        "contributions_per_year": contributions_per_year_i,
        "annual_rate": float(annual_rate_d),
        "years": float(years_d),
        "compounding_per_year": compounding_per_year_i,
        "contribution_timing": normalized_timing,
        "contribution_count": contribution_count_i,
        "total_contributions": round_to_integer(total_contributions),
        "final_amount": round_to_integer(final_amount),
        "profit": round_to_integer(profit)
    }
#================================================

# 元利均等返済のPython計算関数
def calculate_loan_payment(
    principal: Any,
    annual_rate: Any,
    years: Any,
    payments_per_year: Any,
    repayment_method: str,
    bonus_payment: Any
) -> dict:
    principal_d = to_decimal(principal)
    annual_rate_d = to_decimal(annual_rate)
    years_d = to_decimal(years)
    payments_per_year_d = to_decimal(payments_per_year)
    bonus_payment_d = to_decimal(bonus_payment)
    normalized_method = str(repayment_method or "").strip().lower()

    if principal_d <= 0:
        raise ValueError("principalは0より大きくしてください")
    if annual_rate_d < 0:
        raise ValueError("annual_rateは0以上にしてください")
    if years_d <= 0:
        raise ValueError("yearsは0より大きくしてください")
    if payments_per_year_d <= 0:
        raise ValueError("payments_per_yearは0より大きくしてください")
    if payments_per_year_d != payments_per_year_d.to_integral_value():
        raise ValueError("payments_per_yearは整数にしてください")
    if normalized_method != "equal_payment":
        raise ValueError("現在対応している返済方式は元利均等返済だけです")
    if bonus_payment_d != 0:
        raise ValueError("現在はボーナス返済なしの計算だけに対応しています")

    payment_count = years_d * payments_per_year_d
    if payment_count != payment_count.to_integral_value():
        raise ValueError("返済期間から求めた返済回数が整数になりません")

    payment_count_i = int(payment_count)
    payments_per_year_i = int(payments_per_year_d)
    periodic_rate = annual_rate_d / payments_per_year_d

    if periodic_rate == 0:
        payment_amount = principal_d / payment_count_i
    else:
        growth_factor = (Decimal("1") + periodic_rate) ** payment_count_i
        payment_amount = (
            principal_d * periodic_rate * growth_factor
            / (growth_factor - Decimal("1"))
        )

    total_payment = payment_amount * payment_count_i
    total_interest = total_payment - principal_d

    return {
        "principal": round_to_integer(principal_d),
        "annual_rate": float(annual_rate_d),
        "years": float(years_d),
        "payments_per_year": payments_per_year_i,
        "repayment_method": normalized_method,
        "bonus_payment": round_to_integer(bonus_payment_d),
        "payment_count": payment_count_i,
        "payment_amount": round_to_integer(payment_amount),
        "total_payment": round_to_integer(total_payment),
        "total_interest": round_to_integer(total_interest)
    }
#================================================