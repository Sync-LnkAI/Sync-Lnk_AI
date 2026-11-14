from fastapi import APIRouter, HTTPException
from backend.app.calculations.general import (calculate_compound_interest)
from backend.app.schemas.calculations import (
    CompoundInterestRequest,
    CompoundInterestResponse,
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