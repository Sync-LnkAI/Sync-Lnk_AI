from fastapi import APIRouter, HTTPException

from backend.app.config import get_background_ai_config
from backend.app.schemas.calculations import (
    RealEstateExtractRequest,
    RealEstateExtractResponse,
    RealEstateCalculateFromTextRequest,
    RealEstateCalculateFromTextResponse
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
from backend.app.calculations.general import (
    calculate_building_depreciation,
    calculate_real_estate_sale,
)
from backend.app.services.real_estate_normalizer import (
    get_real_estate_sale_missing_fields,
    normalize_real_estate_sale_arguments,
)
import inspect
from backend.app.services.real_estate_normalizer import (
    extract_simple_real_estate_amount_update,
    get_real_estate_sale_missing_fields,
    normalize_real_estate_sale_arguments,
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

@router.post(
    "/calculate-from-text",
    response_model=RealEstateCalculateFromTextResponse,
    responses={
        400: {"model": ErrorResponse, "description": "入力条件が不正な場合"},
        503: {"model": ErrorResponse, "description": "AIサービスを利用できない場合"}
    }
)
def calculate_real_estate_from_text(
    request: RealEstateCalculateFromTextRequest
):
    try:
        provider, model_name = get_background_ai_config()
        extracted = extract_real_estate_sale_parameters(
            user_input=request.user_input,
            recent_history=request.recent_history,
            calculation_pending=request.calculation_pending,
            generate_response=generate_backend_ai_response,
            calculate_cost=calculate_ai_cost,
            provider=provider,
            model_name=model_name
        )

        if extracted.get("extraction_status") == "extraction_error":
            raise HTTPException(
                status_code=503,
                detail="不動産売却条件を抽出できませんでした"
            )

        in_tokens = int(extracted.get("in_tokens", 0) or 0)
        out_tokens = int(extracted.get("out_tokens", 0) or 0)
        cost = float(extracted.get("cost", 0) or 0)

        if not extracted.get("should_calculate", False):
            return {
                "status": "not_applicable",
                "extraction_type": "real_estate_sale",
                "arguments": {},
                "missing_fields": [],
                "result": None,
                "in_tokens": in_tokens,
                "out_tokens": out_tokens,
                "cost": cost
            }

        merged = dict(request.previous_arguments or {})
        merged.update({
            key: value
            for key, value in extracted.get("arguments", {}).items()
            if value is not None and value != ""
        })
        if request.calculation_pending:
            simple_update = extract_simple_real_estate_amount_update(
                request.user_input
            )
            merged.update(simple_update)
        if (
            merged.get("building_acquisition_date")
            and not merged.get("acquisition_date")
        ):
            merged["acquisition_date"] = merged["building_acquisition_date"]

        if (
            merged.get("acquisition_date")
            and not merged.get("building_acquisition_date")
        ):
            merged["building_acquisition_date"] = merged["acquisition_date"]

        arguments = normalize_real_estate_sale_arguments(
            merged,
            apply_defaults=False
        )
        missing_fields = get_real_estate_sale_missing_fields(arguments)

        if missing_fields:
            return {
                "status": "missing_fields",
                "extraction_type": "real_estate_sale",
                "arguments": arguments,
                "missing_fields": missing_fields,
                "result": None,
                "in_tokens": in_tokens,
                "out_tokens": out_tokens,
                "cost": cost
            }

        calculation_arguments = normalize_real_estate_sale_arguments(
            arguments,
            apply_defaults=True
        )
        building_cost = calculation_arguments.get("building_acquisition_cost", 0)
        building_tax_basis = calculation_arguments.get("building_tax_basis")

        if building_cost and building_tax_basis is None:
            depreciation = calculate_building_depreciation(
                building_original_cost=building_cost,
                building_structure=calculation_arguments["building_structure"],
                building_acquisition_date=calculation_arguments[
                    "building_acquisition_date"
                ],
                property_usage=calculation_arguments["property_usage"],
                building_useful_life=calculation_arguments.get(
                    "building_useful_life"
                )
            )
            calculation_arguments["building_tax_basis"] = depreciation[
                "building_tax_basis"
            ]
        allowed_parameters = inspect.signature(
            calculate_real_estate_sale
        ).parameters
        calculation_arguments = {
            key: value
            for key, value in calculation_arguments.items()
            if key in allowed_parameters
        }
        result = calculate_real_estate_sale(**calculation_arguments)

        return {
            "status": "success",
            "extraction_type": "real_estate_sale",
            "arguments": arguments,
            "missing_fields": [],
            "result": result,
            "in_tokens": in_tokens,
            "out_tokens": out_tokens,
            "cost": cost
        }

    except HTTPException:
        raise
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
