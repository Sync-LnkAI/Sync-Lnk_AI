from fastapi import APIRouter, Depends

from backend.app.schemas.calculations import UserSettingsResponse
from backend.app.services.auth_service import AuthenticatedUser, get_authenticated_user
from backend.app.services.user_settings_service import UserSettingsService

router = APIRouter(prefix="/user-settings", tags=["user-settings"])


@router.get("", response_model=UserSettingsResponse)
def get_user_settings(
    user: AuthenticatedUser = Depends(get_authenticated_user),
):
    service = UserSettingsService(user.supabase, user.legacy_user_id)
    settings = service.get_settings()
    return {"status": "success", **settings}
