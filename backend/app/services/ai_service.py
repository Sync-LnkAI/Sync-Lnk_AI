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
        raise RuntimeError(
            "OpenAIクライアントが初期化されていません"
        )

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
    genai_module: Any,
    system_instruction: str,
    user_prompt: str,
    response_format_json: bool = False,
    model_name: str | None = None
) -> dict:
    selected_model = model_name or "gemini-3.5-flash-lite"

    if genai_module is None:
        raise RuntimeError(
            "Geminiクライアントが初期化されていません"
        )

    generation_config = {}

    if response_format_json:
        generation_config["response_mime_type"] = "application/json"

    model_kwargs = {"model_name": selected_model}

    if system_instruction and str(system_instruction).strip():
        model_kwargs["system_instruction"] = system_instruction

    model = genai_module.GenerativeModel(**model_kwargs)

    response = model.generate_content(
        [{"role": "user", "parts": [user_prompt]}],
        generation_config=generation_config
    )

    in_tokens = 0
    out_tokens = 0

    if (
        hasattr(response, "usage_metadata")
        and response.usage_metadata
    ):
        in_tokens = (
            response.usage_metadata.prompt_token_count or 0
        )
        out_tokens = (
            response.usage_metadata.candidates_token_count or 0
        )

    return {
        "text": response.text or "",
        "in_tokens": in_tokens,
        "out_tokens": out_tokens,
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
            genai_module=genai_module,
            system_instruction=system_instruction,
            user_prompt=user_prompt,
            response_format_json=response_format_json,
            model_name=model_name
        )

    raise ValueError(
        f"未対応のAIプロバイダーです: {provider}"
    )
#==============================================