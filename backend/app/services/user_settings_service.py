from typing import Any

from supabase import Client

DEFAULT_SETTINGS = {
    "theme_color": "パステル",
    "concierge_name": "コンシェルジュ",
    "user_name": "ユーザー",
    "user_honorific": "さん",
}

class UserSettingsService:
    def __init__(self, supabase: Client, user_id: str) -> None:
        self.supabase = supabase
        self.user_id = str(user_id or "").strip()

        if not self.user_id:
            raise ValueError("user_idが指定されていません")

    def get_settings(self) -> dict[str, Any]:
        response = (
            self.supabase.table("user_memories")
            .select("fact")
            .eq("user_id", self.user_id)
            .eq("source", "manual")
            .order("id", desc=False)
            .execute()
        )

        settings = dict(DEFAULT_SETTINGS)

        prefixes = {
            "カラーテーマ:": "theme_color",
            "AIの名前:": "concierge_name",
            "ユーザー名:": "user_name",
            "ユーザー敬称:": "user_honorific",
        }

        for memory in response.data or []:
            fact = str(memory.get("fact", "") or "").strip()

            for prefix, key in prefixes.items():
                if fact.startswith(prefix):
                    value = fact.removeprefix(prefix).strip()
                    if value:
                        settings[key] = value
                    break

        return settings
