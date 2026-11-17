from fastapi import APIRouter, HTTPException
from backend.app.calculations.general import (
    calculate_compound_interest,
    calculate_percentage_calculation,
)
from backend.app.schemas.calculations import (
    CompoundInterestRequest,
    CompoundInterestResponse,
    PercentageCalculationRequest,
    PercentageCalculationResponse,
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
