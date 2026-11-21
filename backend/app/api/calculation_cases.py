from fastapi import APIRouter, Depends, HTTPException

from backend.app.schemas.calculations import (
    CalculationCaseCandidateResponse,
    CalculationCaseCreateRequest,
    CalculationCaseCreateResponse,
    CalculationCaseDetailResponse,
    CalculationCaseUpdateRequest,
    CalculationCaseUpdateResponse,
)
from backend.app.services.auth_service import (
    AuthenticatedUser,
    get_authenticated_user,
)
from backend.app.services.calculation_case_service import (
    CalculationCaseService,
)

router = APIRouter(
    prefix="/calculation-cases",
    tags=["calculation-cases"],
)

@router.get("/candidates", response_model=CalculationCaseCandidateResponse)
def get_calculation_case_candidates(
    case_type: str,
    user_input: str = "",
    limit: int = 5,
    user: AuthenticatedUser = Depends(get_authenticated_user),
):
    service = CalculationCaseService(
        supabase=user.supabase,
        user_id=user.legacy_user_id,
    )

    candidates = service.get_candidates(
        case_type=case_type,
        user_input=user_input,
        limit=max(1, min(limit, 20)),
    )

    return {"status": "success", "candidates": candidates}

@router.get("/{case_id}", response_model=CalculationCaseDetailResponse)
def get_calculation_case(
    case_id: str,
    user: AuthenticatedUser = Depends(get_authenticated_user),
):
    service = CalculationCaseService(
        supabase=user.supabase,
        user_id=user.legacy_user_id,
    )

    case = service.get_case(case_id)

    if not case:
        raise HTTPException(status_code=404, detail="計算案件が見つかりません")

    return {"status": "success", "case": case}

@router.post("", response_model=CalculationCaseCreateResponse)
def create_calculation_case(
    request: CalculationCaseCreateRequest,
    user: AuthenticatedUser = Depends(get_authenticated_user),
):
    service = CalculationCaseService(
        supabase=user.supabase,
        user_id=user.legacy_user_id,
    )

    plan_code = service.get_current_plan_code()
    created = service.create_case(
        case_type=request.case_type,
        property_usage=request.property_usage,
        case_data=request.case_data,
        plan_code=plan_code,
    )

    if not created.get("success") or not created.get("case_id"):
        raise HTTPException(
            status_code=500,
            detail="計算案件を作成できませんでした",
        )

    return {
        "status": "success",
        "case_id": created["case_id"],
        "case": created["case"],
    }

@router.patch("/{case_id}", response_model=CalculationCaseUpdateResponse)
def update_calculation_case(
    case_id: str,
    request: CalculationCaseUpdateRequest,
    user: AuthenticatedUser = Depends(get_authenticated_user),
):
    service = CalculationCaseService(user.supabase, user.legacy_user_id)
    updated = service.update_case(
        case_id=case_id,
        new_case_data=request.case_data,
        case_name=request.case_name,
        case_status=request.case_status,
        property_usage=request.property_usage,
    )

    if not updated:
        raise HTTPException(status_code=404, detail="計算案件が見つかりません")

    return {"status": "success", "case_id": case_id}
