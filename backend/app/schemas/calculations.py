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