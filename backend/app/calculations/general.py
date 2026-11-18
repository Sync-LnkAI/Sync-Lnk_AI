import calendar

from datetime import date, datetime
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

# 日付をdate型へ変換する処理関数
def parse_date(
    value: str | date | datetime
) -> date:
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    return date.fromisoformat(
        str(value).strip()
    )
#================================================

# 年数を安全に加算する処理関数
def add_years_safely(
    original_date: date,
    years: int
) -> date:
    """
    2月29日など、加算先の年に同日が存在しない場合は、
    その月の最終日へ補正する。
    """
    target_year = original_date.year + years
    target_month = original_date.month

    last_day = calendar.monthrange(
        target_year,
        target_month
    )[1]

    target_day = min(
        original_date.day,
        last_day
    )

    return date(
        target_year,
        target_month,
        target_day
    )
#================================================

# 個人の不動産保有期間を判定する処理関数
def determine_individual_holding_type(
    acquisition_date: str | date | datetime,
    sale_date: str | date | datetime
) -> str:
    """
    個人の土地建物譲渡について、
    売却年1月1日時点の所有期間が
    5年を超えるかで判定する。
    """
    try:
        acquired = parse_date(acquisition_date)
        sold = parse_date(sale_date)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "acquisition_dateとsale_dateは"
            "YYYY-MM-DD形式にしてください"
        ) from error

    if sold < acquired:
        raise ValueError(
            "sale_dateがacquisition_dateより前です"
        )

    sale_year_start = date(
        sold.year,
        1,
        1
    )

    five_year_anniversary = add_years_safely(
        acquired,
        5
    )

    if five_year_anniversary < sale_year_start:
        return "long_term"

    return "short_term"
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

# 火災保険の簡易解約返戻金計算関数
def calculate_fire_insurance_refund(
    paid_premium: Any,
    contract_months: Any,
    elapsed_months: Any = None,
    contract_start_date: str | None = None,
    cancellation_date: str | None = None,
    cancellation_date_defaulted: bool = False
) -> dict:
    paid_premium_d = to_decimal(paid_premium)
    contract_months_d = to_decimal(contract_months)

    if paid_premium_d <= 0:
        raise ValueError("paid_premiumは0より大きくしてください")
    if contract_months_d <= 0:
        raise ValueError("contract_monthsは0より大きくしてください")
    if contract_months_d != contract_months_d.to_integral_value():
        raise ValueError("contract_monthsは整数にしてください")

    start_date = None
    end_date = None

    if contract_start_date and cancellation_date:
        try:
            start_date = parse_date(contract_start_date)
            end_date = parse_date(cancellation_date)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "保険日付はYYYY-MM-DD形式にしてください"
            ) from error

        if end_date < start_date:
            raise ValueError(
                "解約予定日は契約開始日以後にしてください"
            )

        completed_months = (
            (end_date.year - start_date.year) * 12
            + end_date.month
            - start_date.month
        )

        if end_date.day < start_date.day:
            completed_months -= 1

        elapsed_months_d = Decimal(str(completed_months))

    elif elapsed_months is not None:
        elapsed_months_d = to_decimal(elapsed_months)

    else:
        raise ValueError(
            "elapsed_monthsまたは契約開始日と解約予定日が必要です"
        )

    if elapsed_months_d < 0:
        raise ValueError("elapsed_monthsは0以上にしてください")
    if elapsed_months_d != elapsed_months_d.to_integral_value():
        raise ValueError("elapsed_monthsは整数にしてください")
    if elapsed_months_d > contract_months_d:
        raise ValueError(
            "elapsed_monthsはcontract_months以下にしてください"
        )

    remaining_months = contract_months_d - elapsed_months_d
    refund_amount = (
        paid_premium_d
        * remaining_months
        / contract_months_d
    )

    return {
        "paid_premium": round_to_integer(paid_premium_d),
        "contract_months": int(contract_months_d),
        "elapsed_months": int(elapsed_months_d),
        "remaining_months": int(remaining_months),
        "refund_amount": round_to_integer(refund_amount),
        "contract_start_date": (
            start_date.isoformat()
            if start_date
            else None
        ),
        "cancellation_date": (
            end_date.isoformat()
            if end_date
            else None
        ),
        "cancellation_date_defaulted": bool(
            cancellation_date_defaulted
        )
    }
#================================================

# 不動産売却計算関数
def calculate_real_estate_sale(
    *,
    owner_type: str,
    sale_price: Any,
    loan_balance: Any = 0,

    # 土地の税務上の取得費
    land_acquisition_cost: Any = 0,

    # 建物の取得価額と減価償却累計額
    building_acquisition_cost: Any = 0,
    accumulated_depreciation: Any = 0,

    # 建物未償却残高・建物簿価
    # 入力されている場合は減価償却を再計算せず、
    # この金額をそのまま建物の税務上の残高として使用する
    building_tax_basis: Any | None = None,

    # 取得費に含める購入時経費等
    acquisition_related_costs: Any = 0,
    total_acquisition_cost: Any = 0,

    # 仲介手数料
    brokerage_fee: Any | None = None,

    # 売却のために直接要した譲渡費用
    transfer_expenses: Any = 0,

    # 抵当権抹消など、現金手残りから控除する費用
    other_cash_expenses: Any = 0,

    # 個人の場合に使用
    acquisition_date: str | date | datetime | None = None,
    sale_date: str | date | datetime | None = None,

    holding_period_type: str | None = None,

    # 該当する特例が確認できている場合のみ入力
    special_deduction: Any = 0,

    # 法人の場合のみ任意指定
    corporate_effective_tax_rate: Any | None = None,

    # 取得費不明時の概算取得費を利用する場合
    use_deemed_acquisition_cost: bool = False,

    # 概算取得費率。通常は売却価額の5%
    deemed_acquisition_cost_rate: Any = "0.05"
    ) -> dict:
    """
    不動産売却の概算計算。

    owner_type:
        "individual" または "corporate"

    注意:
    ・個人の通常の土地建物譲渡を想定。
    ・法人税額は会社全体の所得等に左右されるため、
      実効税率が指定された場合だけ概算する。
    ・消費税、特例、損益通算、欠損金、圧縮記帳等は
      この関数では自動判定しない。
    """

    owner_type = owner_type.strip().lower()

    if owner_type not in {
        "individual",
        "corporate"
    }:
        raise ValueError("owner_typeはindividualまたはcorporateを指定してください")

    sale_price_d = to_decimal(sale_price)
    loan_balance_d = to_decimal(loan_balance)

    land_cost_d = to_decimal(land_acquisition_cost)
    building_cost_d = to_decimal(building_acquisition_cost)
    depreciation_d = to_decimal(accumulated_depreciation)
    acquisition_costs_d = to_decimal(acquisition_related_costs)
    transfer_expenses_d = to_decimal(transfer_expenses)

    # 仲介手数料が未入力なら法定上限額で試算
    if brokerage_fee is None:
        brokerage_fee_d = (sale_price_d * Decimal("0.03") + Decimal("60000")) * Decimal("1.10")
        brokerage_fee_method = ("statutory_max_estimate")
    else:
        brokerage_fee_d = to_decimal(brokerage_fee)
        brokerage_fee_method = ("specified")

    other_cash_expenses_d = to_decimal(other_cash_expenses)
    special_deduction_d = to_decimal(special_deduction)

    validation_values = {
        "sale_price": sale_price_d,
        "loan_balance": loan_balance_d,
        "land_acquisition_cost": land_cost_d,
        "building_acquisition_cost": building_cost_d,
        "accumulated_depreciation": depreciation_d,
        "acquisition_related_costs": acquisition_costs_d,
        "brokerage_fee": brokerage_fee_d,
        "transfer_expenses": transfer_expenses_d,
        "other_cash_expenses": other_cash_expenses_d,
        "special_deduction": special_deduction_d
    }
    
    for field_name, field_value in validation_values.items():
        if field_value < 0:
            raise ValueError(
                f"{field_name}は0以上にしてください"
            )

    if depreciation_d > building_cost_d:
        raise ValueError(
            "減価償却累計額が建物取得価額を超えています"
        )

    # 建物の税務上の未償却残高
    if building_tax_basis is not None:
        # ユーザーが建物未償却残高・建物簿価を明示した場合
        # すでに減価償却後の金額なので再計算しない
        building_tax_basis_d = to_decimal(
            building_tax_basis
        )

        if building_tax_basis_d < Decimal("0"):
            raise ValueError(
                "building_tax_basisは0以上にしてください"
            )

    else:
        # 建物未償却残高が未入力の場合だけ、
        # 建物取得価額から減価償却累計額を差し引く
        building_tax_basis_d = (
            building_cost_d
            - depreciation_d
        )

    total_acquisition_cost_d = to_decimal(total_acquisition_cost)
    if total_acquisition_cost_d > Decimal("0"):
        actual_acquisition_basis = (total_acquisition_cost_d)
    else:
        actual_acquisition_basis = (
            land_cost_d
            + building_tax_basis_d
            + acquisition_costs_d
        )

    deemed_rate_d = to_decimal(
        deemed_acquisition_cost_rate
    )
    if not (
        Decimal("0")
        <= deemed_rate_d
        <= Decimal("1")
    ):
        raise ValueError(
            "deemed_acquisition_cost_rateは"
            "0から1の範囲で指定してください"
        )

    # 取得費不明時などに使う概算取得費
    deemed_acquisition_basis = (
        sale_price_d
        * deemed_rate_d
    )

    if use_deemed_acquisition_cost:
        acquisition_basis = (
            deemed_acquisition_basis
        )
        acquisition_basis_method = (
            "deemed_5_percent"
        )
    else:
        acquisition_basis = (
            actual_acquisition_basis
        )
        acquisition_basis_method = "actual"

    # 特別控除前の譲渡損益
    capital_gain_before_deduction = (
        sale_price_d
        - acquisition_basis
        - brokerage_fee_d
        - transfer_expenses_d
    )

    # 特別控除は譲渡益を超えて控除しない
    applied_special_deduction = min(
        max(
            special_deduction_d,
            Decimal("0")
        ),
        max(
            capital_gain_before_deduction,
            Decimal("0")
        )
    )

    taxable_gain = max(
        capital_gain_before_deduction
        - applied_special_deduction,
        Decimal("0")
    )

    holding_type = None
    tax_rate = None
    estimated_tax = None
    tax_calculation_status = None

    if owner_type == "individual":
        if sale_date is not None:
            holding_type = (
                determine_individual_holding_type(
                    acquisition_date,
                    sale_date
                )
            )

        elif holding_period_type in {
            "long_term",
            "short_term"
        }:
            holding_type = holding_period_type

        else:
            holding_type = None

        if taxable_gain <= Decimal("0"):
            estimated_tax = Decimal("0")
            tax_calculation_status = "no_taxable_gain"
        elif holding_type == "long_term":
            tax_rate = Decimal("0.20315")
            estimated_tax = taxable_gain * tax_rate
            tax_calculation_status = "individual_estimated"
        elif holding_type == "short_term":
            tax_rate = Decimal("0.3963")
            estimated_tax = taxable_gain * tax_rate
            tax_calculation_status = "individual_estimated"
        else:
            tax_calculation_status = "holding_period_not_determined"

    else:
        if taxable_gain <= Decimal("0"):
            estimated_tax = Decimal("0")
            tax_calculation_status = "no_taxable_gain"

        elif corporate_effective_tax_rate is None:
            tax_calculation_status = (
                "corporate_tax_not_calculated"
            )

        else:
            tax_rate = to_decimal(
                corporate_effective_tax_rate
            )

            if not (
                Decimal("0")
                <= tax_rate
                <= Decimal("1")
            ):
                raise ValueError(
                    "corporate_effective_tax_rateは"
                    "0から1の範囲で指定してください"
                )

            estimated_tax = (
                taxable_gain
                * tax_rate
            )

            tax_calculation_status = (
                "corporate_effective_rate_estimate"
            )

    # 税引前の現金手残り
    cash_before_tax = (
        sale_price_d
        - loan_balance_d
        - brokerage_fee_d
        - transfer_expenses_d
        - other_cash_expenses_d
    )

    # 税額を計算できる場合だけ税引後を算出
    if estimated_tax is None:
        cash_after_tax = None
    else:
        cash_after_tax = (
            cash_before_tax
            - estimated_tax
        )

    return {
        "owner_type": owner_type,
        "holding_type": holding_type,
        "acquisition_basis_method": acquisition_basis_method,
        "sale_price": round_to_integer(sale_price_d),
        "loan_balance": round_to_integer(loan_balance_d),
        "land_acquisition_cost": round_to_integer(land_cost_d),
        "building_acquisition_cost": round_to_integer(building_cost_d),
        "accumulated_depreciation": round_to_integer(depreciation_d),
        "building_tax_basis": round_to_integer(building_tax_basis_d),
        "acquisition_related_costs": round_to_integer(acquisition_costs_d),
        "brokerage_fee": round_to_integer(brokerage_fee_d),
        "brokerage_fee_method": brokerage_fee_method,
        "actual_acquisition_basis": round_to_integer(actual_acquisition_basis),
        "deemed_acquisition_basis": round_to_integer(deemed_acquisition_basis),
        "applied_acquisition_basis": round_to_integer(acquisition_basis),
        "transfer_expenses": round_to_integer(transfer_expenses_d),
        "other_cash_expenses": round_to_integer(other_cash_expenses_d),
        "capital_gain_before_deduction": round_to_integer(capital_gain_before_deduction),
        "special_deduction": round_to_integer(applied_special_deduction),
        "taxable_gain": round_to_integer(taxable_gain),
        "tax_rate": (
            float(tax_rate)
            if tax_rate is not None
            else None
        ),
        "estimated_tax": (
            round_to_integer(estimated_tax)
            if estimated_tax is not None
            else None
        ),
        "cash_before_tax": round_to_integer(cash_before_tax),
        "cash_after_tax": (
            round_to_integer(cash_after_tax)
            if cash_after_tax is not None
            else None
        ),
        "tax_calculation_status": tax_calculation_status
    }
#================================================