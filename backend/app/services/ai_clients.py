from typing import Any

from google import genai
from openai import OpenAI

from backend.app.config import GEMINI_API_KEY, OPENAI_API_KEY


_openai_client = None
_gemini_client = None


def get_openai_client() -> Any:
    global _openai_client

    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEYが設定されていません")

    if _openai_client is None:
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)

    return _openai_client


def get_gemini_client() -> Any:
    global _gemini_client

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY_PROが設定されていません")

    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)

    return _gemini_client