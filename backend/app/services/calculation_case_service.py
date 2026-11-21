import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from supabase import Client


JST = ZoneInfo("Asia/Tokyo")

def make_json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return (
            int(value)
            if value == value.to_integral_value()
            else float(value)
        )

    if isinstance(value, dict):
        return {
            key: make_json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [make_json_safe(item) for item in value]

    return value

def get_default_case_name(
    case_type: str,
    property_usage: str | None = None,
) -> str:
    if case_type == "real_estate_sale":
        if property_usage == "owner_occupied":
            return "自宅売却"
        if property_usage == "investment":
            return "投資用売却"
        return "その他売却"

    if case_type == "loan_simulation":
        return "住宅ローン"

    if case_type == "nisa_simulation":
        return "NISA"

    return "計算案件"

def get_case_expiration_date(plan_code: str) -> str:
    now = datetime.now(JST)
    normalized_plan_code = str(plan_code or "free").strip().lower()

    if normalized_plan_code == "free":
        expires_at = now + timedelta(days=90)
    else:
        expires_at = now + timedelta(days=365)

    return expires_at.isoformat()

class CalculationCaseService:
    def __init__(self, supabase: Client, user_id: str) -> None:
        self.supabase = supabase
        self.user_id = str(user_id or "").strip()

        if not self.user_id:
            raise ValueError("user_idが指定されていません")
    
    def get_current_plan_code(self) -> str:
        response = (
            self.supabase
            .table("user_subscriptions")
            .select(
                "plan_code,"
                "subscription_status,"
                "expires_at"
            )
            .eq("user_id", self.user_id)
            .limit(1)
            .execute()
        )

        if not response.data:
            return "free"

        subscription = response.data[0]

        plan_code = str(
            subscription.get("plan_code", "free") or "free"
        ).strip().lower()

        if plan_code not in {
            "free",
            "light",
            "standard",
        }:
            return "free"

        subscription_status = str(
            subscription.get(
                "subscription_status",
                "active",
            )
            or "active"
        ).strip().lower()

        if subscription_status not in {
            "active",
            "trial",
        }:
            return "free"

        expires_at = subscription.get("expires_at")

        if expires_at:
            try:
                expiration_datetime = datetime.fromisoformat(
                    str(expires_at).replace("Z", "+00:00")
                )

                if expiration_datetime <= datetime.now(
                    expiration_datetime.tzinfo
                ):
                    return "free"
            except (TypeError, ValueError):
                return "free"

        return plan_code

    def get_candidates(
        self,
        case_type: str,
        user_input: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        now_str = datetime.now(JST).isoformat()

        response = (
            self.supabase
            .table("calculation_cases")
            .select(
                "case_id,"
                "case_name,"
                "case_type,"
                "updated_at"
            )
            .eq("user_id", self.user_id)
            .eq("case_type", case_type)
            .or_(
                f"expires_at.is.null,"
                f"expires_at.gt.{now_str}"
            )
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )

        candidates = response.data or []
        if not candidates:
            return []

        normalized_input = (
            str(user_input or "")
            .replace(" ", "")
            .replace("　", "")
            .lower()
        )

        name_matches = [
            case
            for case in candidates
            if (
                str(case.get("case_name", ""))
                .replace(" ", "")
                .replace("　", "")
                .lower()
                in normalized_input
            )
        ]

        return name_matches if name_matches else candidates

    def get_case(self, case_id: str) -> dict[str, Any]:
        response = (
            self.supabase
            .table("calculation_cases")
            .select("*")
            .eq("case_id", case_id)
            .eq("user_id", self.user_id)
            .limit(1)
            .execute()
        )

        if response.data:
            return response.data[0]

        return {}

    def update_case(
        self,
        case_id: str,
        new_case_data: dict[str, Any],
        case_name: str | None = None,
        case_status: str | None = None,
        property_usage: str | None = None,
    ) -> bool:
        existing = self.get_case(case_id)
        if not existing:
            return False

        merged_case_data = dict(existing.get("case_data") or {})
        merged_case_data.update(new_case_data)

        if "brokerage_fee" not in new_case_data:
            merged_case_data.pop("brokerage_fee", None)

        update_data: dict[str, Any] = {
            "case_data": merged_case_data,
            "updated_at": datetime.now(JST).isoformat(),
        }

        if case_name:
            update_data["case_name"] = case_name
        if case_status:
            update_data["case_status"] = case_status
        if property_usage:
            update_data["property_usage"] = property_usage

        response = (
            self.supabase
            .table("calculation_cases")
            .update(update_data)
            .eq("case_id", case_id)
            .eq("user_id", self.user_id)
            .execute()
        )

        return bool(response.data)
    
    def create_case(
        self,
        case_type: str,
        property_usage: str,
        case_data: dict[str, Any],
        plan_code: str,
    ) -> dict[str, Any]:
        case_id = f"case_{uuid.uuid4().hex[:8]}"
        case_name = get_default_case_name(
            case_type=case_type,
            property_usage=property_usage,
        )
        now_str = datetime.now(JST).isoformat()

        case_record = {
            "user_id": self.user_id,
            "case_id": case_id,
            "case_name": case_name,
            "case_type": case_type,
            "case_status": "draft",
            "property_usage": property_usage,
            "case_data": make_json_safe(case_data),
            "created_at": now_str,
            "updated_at": now_str,
            "expires_at": get_case_expiration_date(plan_code)
        }

        response = (
            self.supabase
            .table("calculation_cases")
            .insert(case_record)
            .execute()
        )

        if not response.data:
            return {
                "success": False,
                "case_id": None,
            }

        return {
            "success": True,
            "case_id": case_id,
            "case": response.data[0],
        }
