from fastapi import APIRouter, HTTPException

from backend.app.config import get_background_ai_config
from backend.app.schemas.calculations import (
    RealEstateExtractRequest,
    RealEstateExtractResponse,
)
from backend.app.schemas.common import ErrorResponse
from backend.app.services.ai_clients import (
    get_gemini_client,
    get_openai_client,
)
from backend.app.services.ai_service import (
    calculate_ai_cost,
    generate_ai_response,
)
from backend.app.services.real_estate_extractor import (
    extract_real_estate_sale_parameters,
)

router = APIRouter(prefix="/real-estate", tags=["real-estate"])

def generate_backend_ai_response(**kwargs):
    provider = str(kwargs.get("provider", "")).lower()
    return generate_ai_response(
        **kwargs,
        openai_client=(
            get_openai_client()
            if provider == "gpt"
            else None
        ),
        gemini_client=(
            get_gemini_client()
            if provider == "gemini"
            else None
        )
    )


@router.post(
    "/extract",
    response_model=RealEstateExtractResponse,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "入力または抽出処理が不正な場合"
        },
        503: {
            "model": ErrorResponse,
            "description": "AIサービスを利用できない場合"
        }
    }
)
def extract_real_estate(
    request: RealEstateExtractRequest
):
    try:
        provider, model_name = get_background_ai_config()

        result = extract_real_estate_sale_parameters(
            user_input=request.user_input,
            recent_history=request.recent_history,
            calculation_pending=request.calculation_pending,
            generate_response=generate_backend_ai_response,
            calculate_cost=calculate_ai_cost,
            provider=provider,
            model_name=model_name
        )

        if result.get("extraction_status") == "extraction_error":
            raise HTTPException(
                status_code=503,
                detail="不動産売却条件を抽出できませんでした"
            )

        result.pop("error", None)

        return {
            "status": "success",
            "extraction_type": "real_estate_sale",
            "result": result
        }

    except HTTPException:
        raise

    except RuntimeError as error:
        raise HTTPException(
            status_code=503,
            detail=str(error)
        ) from error

    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        ) from error
