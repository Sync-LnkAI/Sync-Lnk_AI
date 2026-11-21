from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client, create_client

from backend.app.config import SUPABASE_ANON_KEY, SUPABASE_URL


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    auth_user_id: str
    legacy_user_id: str
    supabase: Client
#================================================

def create_authenticated_supabase(access_token: str) -> Client:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(
            status_code=503,
            detail="Supabaseの接続設定がありません",
        )

    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    client.postgrest.auth(access_token)
    return client
#================================================

# Bearerトークンを検証して認証ユーザーを返す関数
def get_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthenticatedUser:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=401,
            detail="認証情報がありません",
        )

    access_token = credentials.credentials
    client = create_authenticated_supabase(access_token)

    try:
        auth_response = client.auth.get_user(access_token)
        auth_user = auth_response.user

        if auth_user is None:
            raise HTTPException(
                status_code=401,
                detail="認証情報を確認できませんでした",
            )

        auth_user_id = str(auth_user.id).strip()

        link_response = (
            client.table("user_id_links")
            .select("legacy_user_id")
            .eq("auth_user_id", auth_user_id)
            .maybe_single()
            .execute()
        )
        link_data = getattr(link_response, "data", None) or {}

        if not link_data:
            raise HTTPException(
                status_code=403,
                detail="ユーザー登録情報を確認できませんでした",
            )

        return AuthenticatedUser(
            auth_user_id=auth_user_id,
            legacy_user_id=str(link_data["legacy_user_id"]).strip(),
            supabase=client,
        )

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=401,
            detail="認証情報を確認できませんでした",
        ) from error
#================================================