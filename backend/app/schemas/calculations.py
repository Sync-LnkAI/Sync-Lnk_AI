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