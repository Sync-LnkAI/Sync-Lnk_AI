from fastapi import APIRouter, HTTPException
from backend.app.calculations.general import (
    calculate_compound_interest,
    calculate_fire_insurance_refund,
    calculate_loan_payment,
    calculate_percentage_calculation,
    calculate_real_estate_sale,
    calculate_recurring_investment,
    calculate_simple_interest,
)
from backend.app.schemas.calculations import (
    CompoundInterestRequest,
    CompoundInterestResponse,
    FireInsuranceRefundRequest,
    FireInsuranceRefundResponse,
    LoanPaymentRequest,
    LoanPaymentResponse,
    PercentageCalculationRequest,
    PercentageCalculationResponse,
    RealEstateSaleRequest,
    RealEstateSaleResponse,
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

@router.post(
    "/loan-payment",
    response_model=LoanPaymentResponse,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "計算条件が不正な場合"
        }
    }
)
def loan_payment(request: LoanPaymentRequest):
    try:
        result = calculate_loan_payment(
            principal=request.principal,
            annual_rate=request.annual_rate,
            years=request.years,
            payments_per_year=request.payments_per_year,
            repayment_method=request.repayment_method,
            bonus_payment=request.bonus_payment
        )
        return {
            "status": "success",
            "calculation_type": "loan_payment",
            "result": result
        }
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

@router.post(
    "/fire-insurance-refund",
    response_model=FireInsuranceRefundResponse,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "計算条件が不正な場合"
        }
    }
)
def fire_insurance_refund(request: FireInsuranceRefundRequest):
    try:
        result = calculate_fire_insurance_refund(
            paid_premium=request.paid_premium,
            contract_months=request.contract_months,
            elapsed_months=request.elapsed_months,
            contract_start_date=request.contract_start_date,
            cancellation_date=request.cancellation_date,
            cancellation_date_defaulted=(
                request.cancellation_date_defaulted
            )
        )

        return {
            "status": "success",
            "calculation_type": "fire_insurance_refund",
            "result": result
        }

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        ) from error

@router.post(
    "/real-estate-sale",
    response_model=RealEstateSaleResponse,
    responses={400: {"model": ErrorResponse, "description": "計算条件が不正な場合"}}
)
def real_estate_sale(request: RealEstateSaleRequest):
    try:
        result = calculate_real_estate_sale(
            owner_type=request.owner_type,
            sale_price=request.sale_price,
            loan_balance=request.loan_balance,
            land_acquisition_cost=request.land_acquisition_cost,
            building_acquisition_cost=request.building_acquisition_cost,
            accumulated_depreciation=request.accumulated_depreciation,
            building_tax_basis=request.building_tax_basis,
            acquisition_related_costs=request.acquisition_related_costs,
            total_acquisition_cost=request.total_acquisition_cost,
            brokerage_fee=request.brokerage_fee,
            transfer_expenses=request.transfer_expenses,
            other_cash_expenses=request.other_cash_expenses,
            acquisition_date=request.acquisition_date,
            sale_date=request.sale_date,
            holding_period_type=request.holding_period_type,
            special_deduction=request.special_deduction,
            corporate_effective_tax_rate=request.corporate_effective_tax_rate,
            use_deemed_acquisition_cost=request.use_deemed_acquisition_cost,
            deemed_acquisition_cost_rate=request.deemed_acquisition_cost_rate
        )
        return {
            "status": "success",
            "calculation_type": "real_estate_sale",
            "result": result
        }
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
