from typing import Any


# ChatGPT呼び出し関数
def generate_gpt_response(
    *,
    client: Any,
    system_instruction: str,
    user_prompt: str,
    response_format_json: bool = False,
    model_name: str | None = None
) -> dict:
    selected_model = model_name or "gpt-4o-mini"

    if client is None:
        raise RuntimeError("OpenAIクライアントが初期化されていません")

    response = client.chat.completions.create(
        model=selected_model,
        messages=[
            {
                "role": "system",
                "content": system_instruction
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        response_format=(
            {"type": "json_object"}
            if response_format_json
            else None
        )
    )

    content = (
        response.choices[0].message.content
        if response.choices
        else ""
    )
    usage = response.usage

    return {
        "text": content or "",
        "in_tokens": usage.prompt_tokens if usage else 0,
        "out_tokens": usage.completion_tokens if usage else 0,
        "provider": "gpt",
        "model_name": selected_model
    }
#==============================================

# Gemini呼び出し関数
def generate_gemini_response(
    *,
    client: Any,
    system_instruction: str,
    user_prompt: str,
    response_format_json: bool = False,
    model_name: str | None = None
) -> dict:
    selected_model = model_name or "gemini-3.1-flash-lite"

    if client is None:
        raise RuntimeError("Geminiクライアントが初期化されていません")

    config = {}
    if system_instruction and system_instruction.strip():
        config["system_instruction"] = system_instruction
    if response_format_json:
        config["response_mime_type"] = "application/json"

    response = client.models.generate_content(
        model=selected_model,
        contents=user_prompt,
        config=config
    )
    usage = getattr(response, "usage_metadata", None)

    return {
        "text": response.text or "",
        "in_tokens": getattr(usage, "prompt_token_count", 0) or 0
        if usage else 0,
        "out_tokens": getattr(usage, "candidates_token_count", 0) or 0
        if usage else 0,
        "provider": "gemini",
        "model_name": selected_model
    }
#==============================================

# 共通振り分け関数
def generate_ai_response(
    *,
    provider: str,
    system_instruction: str,
    user_prompt: str,
    response_format_json: bool = False,
    model_name: str | None = None,
    openai_client: Any = None,
    genai_module: Any = None
) -> dict:
    selected_provider = str(provider or "").strip().lower()

    if selected_provider == "gpt":
        return generate_gpt_response(
            client=openai_client,
            system_instruction=system_instruction,
            user_prompt=user_prompt,
            response_format_json=response_format_json,
            model_name=model_name
        )

    if selected_provider == "gemini":
        return generate_gemini_response(
            client=gemini_client,
            system_instruction=system_instruction,
            user_prompt=user_prompt,
            response_format_json=response_format_json,
            model_name=model_name
        )

    raise ValueError(f"未対応のAIプロバイダーです: {provider}")
#==============================================