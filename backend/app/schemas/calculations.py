from typing import Literal

from pydantic import BaseModel


class CompoundInterestRequest(BaseModel):
    principal: float
    annual_rate: float
    years: float
    compounding_per_year: int = 1

class CompoundInterestResult(BaseModel):
    principal: int
    annual_rate: float
    years: float
    compounding_per_year: int
    period_count: int
    final_amount: int
    profit: int

class CompoundInterestResponse(BaseModel):
    status: Literal["success"]
    calculation_type: Literal["compound_interest"]
    result: CompoundInterestResult

class PercentageCalculationRequest(BaseModel):
    base_value: float | None = None
    comparison_value: float | None = None
    rate: float | None = None
    calculation_mode: Literal[
        "percentage_of_value",
        "ratio",
        "percentage_change",
        "difference",
        "discounted_value",
        "increased_value"
    ]

class PercentageCalculationResult(BaseModel):
    calculation_mode: str
    base_value: float | None
    comparison_value: float | None
    rate: float | None
    result_type: Literal["rate", "value"]
    result: float | int
    result_percent: float | None

class PercentageCalculationResponse(BaseModel):
    status: Literal["success"]
    calculation_type: Literal["percentage_calculation"]
    result: PercentageCalculationResult

class SimpleInterestRequest(BaseModel):
    principal: float
    annual_rate: float
    years: float

class SimpleInterestResult(BaseModel):
    principal: int
    annual_rate: float
    years: float
    interest: int
    final_amount: int

class SimpleInterestResponse(BaseModel):
    status: Literal["success"]
    calculation_type: Literal["simple_interest"]
    result: SimpleInterestResult

class RecurringInvestmentRequest(BaseModel):
    initial_principal: float = 0
    contribution_amount: float
    contributions_per_year: int
    annual_rate: float
    years: float
    compounding_per_year: int
    contribution_timing: Literal["beginning", "end"]

class RecurringInvestmentResult(BaseModel):
    initial_principal: int
    contribution_amount: int
    contributions_per_year: int
    annual_rate: float
    years: float
    compounding_per_year: int
    contribution_timing: Literal["beginning", "end"]
    contribution_count: int
    total_contributions: int
    final_amount: int
    profit: int

class RecurringInvestmentResponse(BaseModel):
    status: Literal["success"]
    calculation_type: Literal["recurring_investment"]
    result: RecurringInvestmentResult

class LoanPaymentRequest(BaseModel):
    principal: float
    annual_rate: float
    years: float
    payments_per_year: int = 12
    repayment_method: Literal["equal_payment"] = "equal_payment"
    bonus_payment: float = 0

class LoanPaymentResult(BaseModel):
    principal: int
    annual_rate: float
    years: float
    payments_per_year: int
    repayment_method: Literal["equal_payment"]
    bonus_payment: int
    payment_count: int
    payment_amount: int
    total_payment: int
    total_interest: int

class LoanPaymentResponse(BaseModel):
    status: Literal["success"]
    calculation_type: Literal["loan_payment"]
    result: LoanPaymentResult

class FireInsuranceRefundRequest(BaseModel):
    paid_premium: float
    contract_months: int
    elapsed_months: int | None = None
    contract_start_date: str | None = None
    cancellation_date: str | None = None
    cancellation_date_defaulted: bool = False

class FireInsuranceRefundResult(BaseModel):
    paid_premium: int
    contract_months: int
    elapsed_months: int
    remaining_months: int
    refund_amount: int
    contract_start_date: str | None
    cancellation_date: str | None
    cancellation_date_defaulted: bool

class FireInsuranceRefundResponse(BaseModel):
    status: Literal["success"]
    calculation_type: Literal["fire_insurance_refund"]
    result: FireInsuranceRefundResult

class RealEstateSaleRequest(BaseModel):
    owner_type: Literal["individual", "corporate"]
    sale_price: float
    loan_balance: float = 0
    land_acquisition_cost: float = 0
    building_acquisition_cost: float = 0
    accumulated_depreciation: float = 0
    building_tax_basis: float | None = None
    acquisition_related_costs: float = 0
    total_acquisition_cost: float = 0
    brokerage_fee: float | None = None
    transfer_expenses: float = 0
    other_cash_expenses: float = 0
    acquisition_date: str | None = None
    sale_date: str | None = None
    holding_period_type: Literal["long_term", "short_term"] | None = None
    special_deduction: float = 0
    corporate_effective_tax_rate: float | None = None
    use_deemed_acquisition_cost: bool = False
    deemed_acquisition_cost_rate: float = 0.05

class RealEstateSaleResult(BaseModel):
    owner_type: str
    holding_type: str | None
    acquisition_basis_method: str
    sale_price: int
    loan_balance: int
    land_acquisition_cost: int
    building_acquisition_cost: int
    accumulated_depreciation: int
    building_tax_basis: int
    acquisition_related_costs: int
    brokerage_fee: int
    brokerage_fee_method: str
    actual_acquisition_basis: int
    deemed_acquisition_basis: int
    applied_acquisition_basis: int
    transfer_expenses: int
    other_cash_expenses: int
    capital_gain_before_deduction: int
    special_deduction: int
    taxable_gain: int
    tax_rate: float | None
    estimated_tax: int | None
    cash_before_tax: int
    cash_after_tax: int | None
    tax_calculation_status: str | None

class RealEstateSaleResponse(BaseModel):
    status: Literal["success"]
    calculation_type: Literal["real_estate_sale"]
    result: RealEstateSaleResult

class BuildingDepreciationRequest(BaseModel):
    building_original_cost: float
    building_structure: Literal[
        "wood", "light_steel", "steel", "rc", "src"
    ]
    building_acquisition_date: str
    property_usage: Literal["owner_occupied", "business"]
    building_useful_life: float | None = None

class BuildingDepreciationResult(BaseModel):
    building_original_cost: int
    building_structure: str
    building_acquisition_date: str
    property_usage: str
    building_useful_life: float
    calculation_date: str
    elapsed_days: int
    elapsed_years: float
    accumulated_depreciation: int
    building_tax_basis: int

class BuildingDepreciationResponse(BaseModel):
    status: Literal["success"]
    calculation_type: Literal["building_depreciation"]
    result: BuildingDepreciationResult

class RealEstateExtractRequest(BaseModel):
    user_input: str
    recent_history: str = ""
    calculation_pending: bool = False

class RealEstateExtractResult(BaseModel):
    should_calculate: bool
    arguments: dict
    extraction_status: str
    in_tokens: int
    out_tokens: int
    cost: float

class RealEstateExtractResponse(BaseModel):
    status: Literal["success"]
    extraction_type: Literal["real_estate_sale"]
    result: RealEstateExtractResult

class RealEstateCalculateFromTextRequest(BaseModel):
    user_input: str
    recent_history: str = ""
    calculation_pending: bool = False
    previous_arguments: dict = {}

class RealEstateCalculateFromTextResponse(BaseModel):
    status: Literal["success", "missing_fields", "not_applicable"]
    extraction_type: Literal["real_estate_sale"]
    arguments: dict
    missing_fields: list[str]
    missing_field_labels: list[str]
    follow_up_message: str | None = None
    result_message: str | None = None
    result: RealEstateSaleResult | None = None
    in_tokens: int
    out_tokens: int
    cost: float

class CalculationCaseCandidate(BaseModel):
    case_id: str
    case_name: str
    case_type: str
    updated_at: str

class CalculationCaseCandidateResponse(BaseModel):
    status: Literal["success"]
    candidates: list[CalculationCaseCandidate]

class CalculationCaseDetail(BaseModel):
    case_id: str
    case_name: str
    case_type: str
    case_status: str
    property_usage: str | None = None
    case_data: dict
    created_at: str
    updated_at: str
    expires_at: str | None = None

class CalculationCaseDetailResponse(BaseModel):
    status: Literal["success"]
    case: CalculationCaseDetail

class CalculationCaseCreateRequest(BaseModel):
    case_type: str
    property_usage: str
    case_data: dict

class CalculationCaseCreateResponse(BaseModel):
    status: Literal["success"]
    case_id: str
    case: CalculationCaseDetail

class CalculationCaseUpdateRequest(BaseModel):
    case_data: dict
    case_name: str | None = None
    case_status: str | None = None
    property_usage: str | None = None

class CalculationCaseUpdateResponse(BaseModel):
    status: Literal["success"]
    case_id: str

class UserSettingsResponse(BaseModel):
    status: Literal["success"]
    theme_color: str
    concierge_name: str
    user_name: str
    user_honorific: str
