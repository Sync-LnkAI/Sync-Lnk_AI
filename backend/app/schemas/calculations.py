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
