from fastapi import APIRouter, HTTPException
from backend.app.calculations.general import (
    calculate_compound_interest,
    calculate_percentage_calculation,
    calculate_recurring_investment,
    calculate_simple_interest,
)
from backend.app.schemas.calculations import (
    CompoundInterestRequest,
    CompoundInterestResponse,
    PercentageCalculationRequest,
    PercentageCalculationResponse,
    RecurringInvestmentRequest,
    RecurringInvestmentResponse,
    SimpleInterestRequest,
    SimpleInterestResponse,
)
from backend.app.schemas.common import ErrorResponse

router = APIRouter(
    prefix="/api/v1/calculations",
    tags=["calculations"]
)

@router.post(
    "/compound-interest",
    response_model=CompoundInterestResponse,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "計算条件が不正な場合"
        }
    }
)

def compound_interest(
    request: CompoundInterestRequest
):
    try:
        result = calculate_compound_interest(
            principal=request.principal,
            annual_rate=request.annual_rate,
            years=request.years,
            compounding_per_year=request.compounding_per_year
        )

        return {
            "status": "success",
            "calculation_type": "compound_interest",
            "result": result
        }

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        ) from error

@router.post(
    "/percentage",
    response_model=PercentageCalculationResponse,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "計算条件が不正な場合"
        }
    }
)
def percentage_calculation(request: PercentageCalculationRequest):
    try:
        result = calculate_percentage_calculation(
            base_value=request.base_value,
            comparison_value=request.comparison_value,
            rate=request.rate,
            calculation_mode=request.calculation_mode
        )
        return {
            "status": "success",
            "calculation_type": "percentage_calculation",
            "result": result
        }
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

@router.post(
    "/simple-interest",
    response_model=SimpleInterestResponse,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "計算条件が不正な場合"
        }
    }
)
def simple_interest(request: SimpleInterestRequest):
    try:
        result = calculate_simple_interest(
            principal=request.principal,
            annual_rate=request.annual_rate,
            years=request.years
        )
        return {
            "status": "success",
            "calculation_type": "simple_interest",
            "result": result
        }
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

@router.post(
    "/recurring-investment",
    response_model=RecurringInvestmentResponse,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "計算条件が不正な場合"
        }
    }
)
def recurring_investment(request: RecurringInvestmentRequest):
    try:
        result = calculate_recurring_investment(
            initial_principal=request.initial_principal,
            contribution_amount=request.contribution_amount,
            contributions_per_year=request.contributions_per_year,
            annual_rate=request.annual_rate,
            years=request.years,
            compounding_per_year=request.compounding_per_year,
            contribution_timing=request.contribution_timing
        )
        return {
            "status": "success",
            "calculation_type": "recurring_investment",
            "result": result
        }
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
