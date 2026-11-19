import os


AI_CONFIGURATION = os.getenv("AI_CONFIGURATION", "hybrid").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY_PRO", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


def get_background_ai_config() -> tuple[str, str]:
    if AI_CONFIGURATION == "gemini":
        return "gemini", "gemini-3.1-flash-lite"

    if AI_CONFIGURATION == "gpt":
        return "gpt", "gpt-4o-mini"

    return "gpt", "gpt-4o-mini"
