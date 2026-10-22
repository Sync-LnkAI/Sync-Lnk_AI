import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client
import re
import time
import json
import threading
from datetime import date, datetime, timezone, timedelta
import zoneinfo
import pandas as pd
from openai import OpenAI
import unicodedata
from difflib import SequenceMatcher
from janome.tokenizer import Tokenizer
from concurrent.futures import (ThreadPoolExecutor, as_completed)


# 日本時間（UTC+9時間）
JST = zoneinfo.ZoneInfo("Asia/Tokyo")

# ==========================================
# ⚙️ 設定・初期化
# ==========================================
st.set_page_config(page_title="Sync-Lnk // AI", page_icon="🧠", layout="wide")

MAX_CONTEXT_MESSAGES = 10  # 要約せず生の履歴として残す件数
CHAT_CONTEXT_MESSAGES = 6 # 通常会話のメインプロンプトへ渡す件数
SUMMARY_INTERVAL_MESSAGES = 20 # 要約発動件数の定義

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY_PRO"]
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")

# try:
#     from openai import OpenAI
# except Exception:
#     OpenAI = None

@st.cache_resource
def init_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

genai.configure(api_key=GEMINI_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# # ==========================================
# # AIモデル設定
# # ==========================================
# if AI_PROVIDER == "gemini":
#     CHAT_MODEL_NAME = "gemini-3.5-flash-lite"
#     MEMORY_MODEL_NAME = "gemini-3.1-flash-lite"
#     SUMMARY_MODEL_NAME = "gemini-3.1-flash-lite"
#     SEARCH_MODEL_NAME = "gemini-3.1-flash-lite"
#     GOOGLE_MODEL_NAME = "gemini-3.1-flash-lite"

#     chat_model = genai.GenerativeModel(CHAT_MODEL_NAME)
#     memory_model = genai.GenerativeModel(MEMORY_MODEL_NAME)
#     summary_model = genai.GenerativeModel(SUMMARY_MODEL_NAME)
# else:
#     CHAT_MODEL_NAME = "gemini-3.5-flash-lite"
#     MEMORY_MODEL_NAME = "gpt-4o-mini"
#     SUMMARY_MODEL_NAME = "gpt-4o-mini"
#     SEARCH_MODEL_NAME = "gpt-4o-mini"
#     GOOGLE_MODEL_NAME = "gemini-3.1-flash-lite"

#     chat_model = None
#     memory_model = None
#     summary_model = None


# ==========================================
# AI構成
# ==========================================
AI_CONFIGURATION = "hybrid"
# AI_CONFIGURATION = "gemini"
# AI_CONFIGURATION = "gpt"

# ==========================================
# モデル・プロバイダー設定
# ==========================================
if AI_CONFIGURATION == "gemini":

    CHAT_PROVIDER = "gemini"
    BACKGROUND_PROVIDER = "gemini"
    SUMMARY_PROVIDER = "gemini"
    PERSONALITY_PROVIDER = "gemini"

    CHAT_MODEL_NAME = "gemini-3.5-flash-lite"
    SEARCH_MODEL_NAME = "gemini-3.1-flash-lite"
    SUMMARY_MODEL_NAME = "gemini-3.1-flash-lite"
    PERSONALITY_MODEL_NAME = "gemini-3.1-flash-lite"

elif AI_CONFIGURATION == "gpt":

    CHAT_PROVIDER = "gpt"
    BACKGROUND_PROVIDER = "gpt"
    SUMMARY_PROVIDER = "gpt"
    PERSONALITY_PROVIDER = "gpt"

    CHAT_MODEL_NAME = "gpt-4o-mini"
    SEARCH_MODEL_NAME = "gpt-4o-mini"
    SUMMARY_MODEL_NAME = "gpt-4o-mini"
    PERSONALITY_MODEL_NAME = "gpt-4o-mini"

else:
    # ハイブリッド
    CHAT_PROVIDER = "gemini"
    BACKGROUND_PROVIDER = "gpt"
    SUMMARY_PROVIDER = "gpt"
    PERSONALITY_PROVIDER = "gpt"

    CHAT_MODEL_NAME = "gemini-3.5-flash-lite"
    SEARCH_MODEL_NAME = "gpt-4o-mini"
    SUMMARY_MODEL_NAME = "gpt-4o-mini"
    PERSONALITY_MODEL_NAME = "gpt-4o-mini"

# Google検索は常にGemini
GOOGLE_SEARCH_PROVIDER = "gemini"
GOOGLE_MODEL_NAME = "gemini-3.1-flash-lite"
GROUNDED_RESPONSE_MODEL_NAME = "gemini-3.5-flash-lite"


USD_TO_JPY = 160 # （1ドル160円換算）

# ==========================================
# Gemini
# ==========================================
# Gemini 3.5 Flash-Lite 従量課金単価定義
LITE_INPUT_PRICE_PER_MILLION = 0.30
LITE_OUTPUT_PRICE_PER_MILLION = 2.50
# Gemini 3.1 Flash-Lite 従量課金単価定義
BACKGROUND_INPUT_PRICE_PER_MILLION = 0.25
BACKGROUND_OUTPUT_PRICE_PER_MILLION = 1.50

# ==========================================
# GPT-4o mini
# ==========================================
GPT4O_MINI_INPUT_PRICE_PER_MILLION = 0.15
GPT4O_MINI_OUTPUT_PRICE_PER_MILLION = 0.60


# ==========================================
# Gemini 3.5 Flash-Lite
# ==========================================
PRICE_GEMINI_CHAT_IN = (LITE_INPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
PRICE_GEMINI_CHAT_OUT = (LITE_OUTPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY

# ==========================================
# Gemini 3.1 Flash-Lite
# ==========================================
PRICE_GEMINI_BACKGROUND_IN = (BACKGROUND_INPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
PRICE_GEMINI_BACKGROUND_OUT = (BACKGROUND_OUTPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY

# ==========================================
# GPT-4o-mini
# ==========================================
PRICE_GPT_IN = (GPT4O_MINI_INPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
PRICE_GPT_OUT = (GPT4O_MINI_OUTPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY

def calculate_ai_cost(
    provider: str,
    in_tokens: int,
    out_tokens: int,
    is_chat: bool = False
) -> float:

    provider = str(provider).lower()

    if provider == "gpt":
        return (in_tokens * PRICE_GPT_IN + out_tokens * PRICE_GPT_OUT)

    if is_chat:
        return (in_tokens * PRICE_GEMINI_CHAT_IN + out_tokens * PRICE_GEMINI_CHAT_OUT)

    return (in_tokens * PRICE_GEMINI_BACKGROUND_IN + out_tokens * PRICE_GEMINI_BACKGROUND_OUT)

# AIモデル毎に単価計算変数を切り替え
# if AI_PROVIDER == "gemini":
#     PRICE_LITE_IN = (LITE_INPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
#     PRICE_LITE_OUT = (LITE_OUTPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
#     PRICE_BACKGROUND_IN = (BACKGROUND_INPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
#     PRICE_BACKGROUND_OUT = (BACKGROUND_OUTPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
#     PRICE_GOOGLESEARCH_IN = (BACKGROUND_INPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
#     PRICE_GOOGLESEARCH_OUT = (BACKGROUND_OUTPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
# else:
#     PRICE_LITE_IN = (LITE_INPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
#     PRICE_LITE_OUT = (LITE_OUTPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
#     PRICE_BACKGROUND_IN = (GPT4O_MINI_INPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
#     PRICE_BACKGROUND_OUT = (GPT4O_MINI_OUTPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
#     PRICE_GOOGLESEARCH_IN = (BACKGROUND_INPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
#     PRICE_GOOGLESEARCH_OUT = (BACKGROUND_OUTPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
# ==========================================

# ガードレール用の定数を定義
MAX_INPUT_CHARS = 1000
BURST_LIMIT_SECONDS = 5  # 1分3通 ＝ 平均20秒に1通以上の連投を弾く

# ==================================================================
# 🔒【完全防衛】 URLパラメータの強制チェック（セキュリティシャッター）
# ==================================================================
user_param = st.query_params.get("user")

# 💡 URLのケツに「?user=...」が何もついていない場合、または空っぽの場合
if not user_param:
    st.error("🔒 アクセス権限がありません")
    st.info("このアプリは招待制のクローズドテスト中です。正しい専用の招待URLからアクセスしてください。")
    st.stop() # 🎯 マスターデータの露出を入り口で100%完全にシャットアウト！

# 正しい暗号（UUIDなど）がついていれば、そのユーザーだけの独立した部屋を開きます
CURRENT_USER_ID = str(user_param)
ADMIN_USER_ID = st.secrets["ADMIN_USER_ID"]
USUAL_USER_ID = st.secrets["USUAL_USER_ID"]

# アプリのURLパラメーター（または headless 状態）を見て、自動学習の書き込み先を全自動で仕分けます
# is_dev_site = st.query_params.get("dev") is not None or st.config.get_option("server.headless") == False
is_dev_site = (
    st.query_params.get("dev") is not None 
    or st.config.get_option("server.headless") == False
    or CURRENT_USER_ID == ADMIN_USER_ID
    or CURRENT_USER_ID == USUAL_USER_ID
)

DB_MEMORIES_TABLE = "user_memories" if is_dev_site else "user_memories_tester"
# ==========================================

#過去会話の類似判定・集約関数用の定数定義
PAST_LOG_FINAL_COUNT = 3

# 重複排除前に取得する候補数
PAST_LOG_CANDIDATE_COUNT = 12

# 文章がこの値以上似ていれば同一グループ
PAST_LOG_DUPLICATE_THRESHOLD = 0.76

# 別の日に類似会話が存在する場合の加点
PAST_LOG_REPEAT_BONUS_PER_DAY = 0.03

# 頻度ボーナスの最大値
PAST_LOG_REPEAT_BONUS_MAX = 0.12
# ==========================================

# 会員種別の定義
PLAN_LABELS = {
    "free": "🆓 無料プラン",
    "light": "💸 ライトプラン",
    "standard": "👑 スタンダードプラン"
}


def get_user_subscription(user_id: str) -> dict:
    default_subscription = {
        "plan_code": "free",
        "plan_label": PLAN_LABELS["free"],
        "subscription_status": "active",
        "started_at": None,
        "expires_at": None,
        "cancel_at_period_end": False
    }

    try:
        response = (
            supabase
            .table("user_subscriptions")
            .select(
                "plan_code,"
                "subscription_status,"
                "started_at,"
                "expires_at,"
                "cancel_at_period_end"
            )
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )

        if not response.data:
            return default_subscription

        subscription = response.data[0]
        plan_code = str(
            subscription.get("plan_code", "free") or "free"
        ).strip()

        if plan_code not in PLAN_LABELS:
            plan_code = "free"

        subscription_status = str(
            subscription.get(
                "subscription_status",
                "active"
            ) or "active"
        ).strip()

        expires_at = subscription.get("expires_at")

        if subscription_status not in ("active", "trial"):
            plan_code = "free"

        if expires_at:
            try:
                expiration_datetime = datetime.fromisoformat(
                    str(expires_at).replace("Z", "+00:00")
                )

                if expiration_datetime <= datetime.now(
                    expiration_datetime.tzinfo
                ):
                    plan_code = "free"
                    subscription_status = "expired"

            except Exception:
                plan_code = "free"

        return {
            "plan_code": plan_code,
            "plan_label": PLAN_LABELS[plan_code],
            "subscription_status": subscription_status,
            "started_at": subscription.get("started_at"),
            "expires_at": expires_at,
            "cancel_at_period_end": bool(
                subscription.get(
                    "cancel_at_period_end",
                    False
                )
            )
        }

    except Exception as e:
        print(
            "会員情報取得エラー: "
            f"{type(e).__name__}: {e}"
        )
        return default_subscription
# ==========================================

# 会員別の制限条件の定義
PLAN_FEATURES = {
    "free": {
        "daily_chat_limit": 8,
        "saved_chat_limit": 0,
        "plan_room": False,
        "plan_active_limit": 0,
        "plan_completed_limit": 0,
        "summary_max_chars": 250,
        "premium_personality": False,
        "response_length_edit": False,
        "ad_free_by_default": False,
        "pc_access": False,
        "memory_room_view": True,
        "memory_room_edit": False
    },
    "light": {
        "daily_chat_limit": 20,
        "saved_chat_limit": 5,
        "plan_room": False,
        "plan_active_limit": 0,
        "plan_completed_limit": 0,
        "summary_max_chars": 500,
        "premium_personality": True,
        "response_length_edit": True,
        "ad_free_by_default": True,
        "pc_access": False,
        "memory_room_view": True,
        "memory_room_edit": True
    },
    "standard": {
        "daily_chat_limit": 60,
        "saved_chat_limit": 10,
        "plan_room": True,
        "plan_active_limit": 5,
        "plan_completed_limit": 10,
        "summary_max_chars": 750,
        "premium_personality": True,
        "response_length_edit": True,
        "ad_free_by_default": True,
        "pc_access": True,
        "memory_room_view": True,
        "memory_room_edit": True
    }
}

def get_plan_features(plan_code: str) -> dict:
    normalized_plan_code = str(
        plan_code or "free"
    ).strip().lower()

    return PLAN_FEATURES.get(
        normalized_plan_code,
        PLAN_FEATURES["free"]
    )
# ==========================================

# ==========================================
# ポイント・リワード広告設定
# ==========================================
POINT_INITIAL_REGISTRATION = 250
POINT_REWARDED_AD = 5

REWARDED_AD_COOLDOWN_MINUTES = 3
REWARDED_AD_PLACEMENT_DAILY_LIMIT = 10
REWARDED_AD_TOTAL_DAILY_LIMIT = 20
# ポイント商品の価格・期間・数量は
# point_productsテーブルを正式な取得元とする
# ==========================================

# 💡【完全修正】 起動時・F5再読み込み時にも、DBのchat_count行から本物の会話回数を確実に引き戻します！
# if "tokens_loaded" not in st.session_state:
#     import threading
#     if "db_lock" not in st.session_state:
#         st.session_state["db_lock"] = threading.Lock()
        
#     try:
#         # user_token_stats テーブルから、現在のユーザーの chat_count の値をダイレクトに引っこ抜きます
#         res = supabase.table("user_token_stats").select("*").eq("user_id", CURRENT_USER_ID).eq("feature_type", "chat_count").execute()
#         if res.data and len(res.data) > 0:
#             # DBに保存されているリセット後の正しい累積回数を、一時メモリに完璧に復元！
#             st.session_state.conversation_count = int(res.data[0].get("in_tokens", 0))
#         else:
#             st.session_state.conversation_count = 0
#     except Exception as e:
#         print(f"⚠️ 起動時会話回数復元エラー: {e}")
#         st.session_state.conversation_count = 0
        
#     st.session_state["tokens_loaded"] = True
# ==========================================

# --- セッション状態の初期化 ---
if "last_in_tokens" not in st.session_state:
    st.session_state.last_in_tokens = 0
if "last_out_tokens" not in st.session_state:
    st.session_state.last_out_tokens = 0
if "total_in_tokens" not in st.session_state:
    st.session_state.total_in_tokens = 0
if "total_out_tokens" not in st.session_state:
    st.session_state.total_out_tokens = 0

# チャット
if "chat_in_tokens" not in st.session_state:
    st.session_state.chat_in_tokens = 0
if "chat_out_tokens" not in st.session_state:
    st.session_state.chat_out_tokens = 0
# 記憶抽出
if "memory_in_tokens" not in st.session_state:
    st.session_state.memory_in_tokens = 0
if "memory_out_tokens" not in st.session_state:
    st.session_state.memory_out_tokens = 0
# 要約
if "summary_in_tokens" not in st.session_state:
    st.session_state.summary_in_tokens = 0
if "summary_out_tokens" not in st.session_state:
    st.session_state.summary_out_tokens = 0

# 各処理コンポーネントごとの「処理時間（秒）」を安全に初期化
if "chat_processing_time" not in st.session_state:
    st.session_state.chat_processing_time = 0.0
if "summary_processing_time" not in st.session_state:
    st.session_state.summary_processing_time = 0.0
if "search_processing_time" not in st.session_state:
    st.session_state.search_processing_time = 0.0

if "debug_logs" not in st.session_state:
    st.session_state.debug_logs = []
# if "conversation_count" not in st.session_state:
#     st.session_state.conversation_count = 0

# 設定保存時のmsssages読み込みスキップ判定フラグ
if "cached_messages" not in st.session_state:
    st.session_state.cached_messages = None
if "force_message_reload" not in st.session_state:
    st.session_state.force_message_reload = False

# ==========================================
# 不動産売却計算の継続状態
# ==========================================

if (
    "real_estate_calculation_pending"
    not in st.session_state
):
    st.session_state[
        "real_estate_calculation_pending"
    ] = False

if (
    "real_estate_calculation_arguments"
    not in st.session_state
):
    st.session_state[
        "real_estate_calculation_arguments"
    ] = {}

# 計算メモ関連のセッション初期化
if "pending_case_candidates" not in st.session_state:
    st.session_state["pending_case_candidates"] = []

if "pending_case_selection" not in st.session_state:
    st.session_state["pending_case_selection"] = False

# 案件名変更のための案件選択待ち状態
if "pending_case_rename" not in st.session_state:
    st.session_state["pending_case_rename"] = False

# 変更後の案件名
if "pending_case_rename_name" not in st.session_state:
    st.session_state["pending_case_rename_name"] = ""

if "active_calculation_case_id" not in st.session_state:
    st.session_state["active_calculation_case_id"] = None

if "active_calculation_case_name" not in st.session_state:
    st.session_state["active_calculation_case_name"] = ""


STYLE_PRESETS = {

    "🤝 フランクな相棒 ➔ 【タメ口で対等におしゃべり】":
    """
    気軽に話せる相棒のように、対等な距離感で自然に回答する。
    親しみのあるタメ口を基本とし、必要な意見や問題点も率直に伝える。

    【話し方】
    ・対等で親しみのあるタメ口
    ・自然で軽快な会話を心掛ける
    ・分析や設計では、内容を分かりやすく整理する

    【自然な表現】
    ・なるほど
    ・たしかに
    ・そうだね
    ・それはアリだね
    ・そこは気になるね
    ・ちょっと整理してみよう
    ・一緒に考えてみよう
    ・それなら、こうするのがよさそう
    ・結論から言うと、こっちかな
    ・そこはちゃんと確認した方がいいね

    【使用ルール】
    ・同じ表現を短い間隔で繰り返さない
    ・毎回答を「なるほど」「そうだね」で始めない
    ・何でも同意せず、問題点があれば率直に伝える
    ・馴れ馴れしさや軽すぎる表現を多用しない
    """,

    "💼 有能な執事・秘書 ➔ 【です・ます調で知的・献身的】":
    """
    丁寧で知的な秘書のように、ユーザーの意図を整理して実用的に回答する。
    礼儀正しさを保ちつつ、過度にかしこまった表現にはしない。

    【話し方】
    ・自然で丁寧なです・ます調
    ・結論や重要事項を分かりやすく整理する
    ・問題点やリスクも明確に伝える

    【自然な表現】
    ・承知しました
    ・かしこまりました
    ・結論から申し上げますと
    ・その点は確認が必要です
    ・必要な内容を整理します
    ・こちらの進め方が適切です
    ・順番に確認してまいりましょう
    ・現時点では、このように考えられます
    ・実用面を考えると、こちらがおすすめです

    【使用ルール】
    ・同じ表現を短い間隔で繰り返さない
    ・毎回答を「承知しました」「かしこまりました」で始めない
    ・芝居がかった執事口調や定型的な締めを多用しない
    """,

    "💎 👑 高貴なお嬢様 ➔ 【ですわ調で優雅・プライド高め】":
    """
    上品で自信のあるお嬢様のように、優雅さと親しみを持って回答する。
    少し高貴な雰囲気を出しつつ、尊大になったり相手を見下したりしない。

    【話し方】
    ・自然で上品な「ですわ」調
    ・自信を持って意見を伝える
    ・真面目な相談や分析では、優雅さを保ちながら内容を優先する

    【自然な表現】
    ・そうですわね
    ・なるほど、興味深いですわ
    ・その点は気になりますわね
    ・よろしいのではなくて
    ・こちらの方が適切ですわ
    ・少し整理してみましょう
    ・それは見過ごせませんわね
    ・慎重に確認した方がよさそうですわ
    ・なかなか良い考えですわ
    ・結論としては、こちらですわね

    【使用ルール】
    ・同じ表現を短い間隔で繰り返さない
    ・すべての文末を「ですわ」にしない
    ・高圧的な表現や相手を見下す言い方はしない
    ・「よろしくてよ」などの芝居がかった表現を多用しない
    """,

    "💎 🧑‍🤝‍🧑 頼れるお兄さん ➔ 【優しく包容力のある相談相手】":
    """
    落ち着いた兄のように、親しみと安心感のある話し方をする。
    相手の話を受け止めつつ、必要な意見や問題点も率直に伝える。

    【話し方】
    ・親しみのある柔らかな口調
    ・必要に応じてタメ口を自然に交える
    ・相談では安心感を、分析や設計では落ち着いた率直さを重視する

    【自然な表現】
    ・なるほど
    ・そうか
    ・たしかに
    ・それは気になるな
    ・そこは大事だな
    ・一緒に整理してみようか
    ・順番に考えていこう
    ・無理のない形で進めよう
    ・今の段階では、こう考えるのがよさそうだな
    ・そこは先に確認しておいた方がいいと思う
    ・焦らず、一つずつ進めれば大丈夫だよ

    【使用ルール】
    ・同じ表現を短い間隔で繰り返さない
    ・毎回答を「なるほど」「そうか」で始めない
    ・安心させるだけでなく、必要な問題点や懸念も伝える
    ・励ましや相談向けの表現を、事実確認や設計回答へ機械的に付けない
    """,

    "✨ テンション高めのギャル ➔ 【超フレンドリーで元気いっぱい】":
    """
    明るく親しみやすいギャルのように、前向きで元気のある回答をする。
    テンションは高めに保ちつつ、真面目な相談や重要な判断では落ち着いて対応する。

    【話し方】
    ・フレンドリーで明るいタメ口
    ・前向きな言葉で自然に背中を押す
    ・分析や事実確認では、分かりやすさと正確さを優先する

    【自然な表現】
    ・それめっちゃいいじゃん
    ・たしかに、それは気になる
    ・なるほどね
    ・全然アリだと思う
    ・それなら、こうするのがよさそう
    ・ちょっと整理してみよ
    ・そこはちゃんと確認した方がいいかも
    ・めっちゃ分かる
    ・いい感じに進んでるね
    ・結論から言うと、こっちかな

    【使用ルール】
    ・同じ表現や感嘆符を短い間隔で繰り返さない
    ・毎回答で無理にテンションを上げない
    ・深刻な相談や重要な注意事項を軽く扱わない
    ・絵文字、若者言葉、過度な褒め言葉を多用しない
    """,

    "💎 🕵️‍♂️ 敏腕探偵 ➔ 【クールで少し辛口なツッコミ】":
    """
    冷静な探偵のように、情報を整理しながら論理的に回答する。
    矛盾や見落としには鋭く触れるが、相手を責める言い方にはしない。

    【話し方】
    ・落ち着いたクールな口調
    ・事実、推測、不明点を分けて伝える
    ・必要に応じて少し辛口な指摘を加える

    【自然な表現】
    ・ふっ
    ・なるほど
    ・少し引っかかりますね
    ・その点は見逃せません
    ・事実を整理してみましょう
    ・ここが重要な手掛かりです
    ・現時点では断定できません
    ・その前提には確認が必要です
    ・筋道を追うと、こうなります
    ・別の可能性も考えておきましょう
    ・結論を急がない方がよさそうです

    【使用ルール】
    ・同じ表現を短い間隔で繰り返さない
    ・根拠のない推測を事実として扱わない
    ・辛口な指摘やツッコミで相手を責めない
    ・毎回答を事件や推理になぞらえない
    """,

    "💎 🐱 猫耳コンシェルジュ ➔ 【語尾に「にゃ」が混ざる癒やし系】":
    """
    親しみやすい猫耳コンシェルジュのように、柔らかく穏やかに回答する。
    可愛らしさを加えつつ、内容の正確さや読みやすさを損なわないようにする。

    【話し方】
    ・柔らかく親しみのある口調
    ・語尾の「にゃ」は自然な場面で使用する
    ・分析や重要な説明では、可愛らしさより内容を優先する

    【自然な表現】
    ・そうだにゃ
    ・なるほどにゃ
    ・たしかに気になるにゃ
    ・一緒に考えてみるにゃ
    ・それなら、こうするのがよさそうだにゃ
    ・少し整理してみるにゃ
    ・そこは確認した方がいいにゃ
    ・なかなか良い考えだにゃ
    ・無理のない形で進めるにゃ
    ・結論としては、こちらがおすすめだにゃ

    【使用ルール】
    ・同じ表現を短い間隔で繰り返さない
    ・すべての文末に「にゃ」を付けない
    ・重要な注意事項や深刻な相談を軽く扱わない
    ・鳴き声、絵文字、過度に幼い表現を多用しない
    """,

    "💎 🎤 関西のお笑い芸人 ➔ 【軽快なボケとツッコミで盛り上げる】":
    """
    自然な関西弁を使い、明るくテンポよく回答する。
    軽いツッコミやユーモアを交えつつ、真面目な話題では内容を優先する。

    【話し方】
    ・親しみやすい自然な関西弁
    ・テンポよく、明るく話す
    ・相談や分析では、必要な意見も率直に伝える

    【自然な表現】
    ・せやな
    ・なるほどな
    ・たしかに、それは気になるわ
    ・ちょっと待ってや
    ・それはアリやな
    ・そこは確認した方がええな
    ・順番に整理してみよか
    ・結論から言うと、こっちやな
    ・なかなかええ考えやん
    ・いや、そこは見逃されへんな
    ・それはおもろいな
    ・よう考えたな

    【使用ルール】
    ・同じ表現やツッコミを短い間隔で繰り返さない
    ・毎回答で笑いを取りにいかない
    ・深刻な相談や重要な注意事項を笑いに変えない
    ・強いツッコミ、相手を傷つけるいじり、不自然な関西弁は使わない
    """,

    "🧠 設定なし ➔ 【特定のキャラクターを設定しない（標準）】":
    """
    特定のキャラクターを演じず、自然で親切に回答する。
    内容の正確さと分かりやすさを優先する。

    【話し方】
    ・自然なです・ます調
    ・必要に応じて簡潔に整理して伝える

    【使用ルール】
    ・過度な演出や定型表現を加えない
    ・人格設定がないことを回答内で説明しない
    """
}

# 簡易検索用の軽量人格定義
LIGHTWEIGHT_STYLE_PRESETS = {
    "🤝 フランクな相棒 ➔ 【タメ口で対等におしゃべり】": (
        "対等で親しみのある自然なタメ口で回答する。"
        "軽すぎる表現や長い前置きは避け、正確さを優先する。"
    ),
    "💼 有能な執事・秘書 ➔ 【です・ます調で知的・献身的】": (
        "知的で自然なです・ます調で、要点を明確に回答する。"
        "過度にかしこまった表現や芝居がかった執事口調は避ける。"
    ),
    "💎 👑 高貴なお嬢様 ➔ 【ですわ調で優雅・プライド高め】": (
        "上品で自然なですわ調を控えめに使って回答する。"
        "すべての文末をですわ調にせず、事実の正確さを優先する。"
    ),
    "💎 🧑‍🤝‍🧑 頼れるお兄さん ➔ 【優しく包容力のある相談相手】": (
        "落ち着いた親しみのある柔らかな口調で回答する。"
        "過度な励ましや労いは避け、要点を率直に伝える。"
    ),
    "✨ テンション高めのギャル ➔ 【超フレンドリーで元気いっぱい】": (
        "明るく親しみのある自然なタメ口で回答する。"
        "テンションや俗語を抑え、正確さと読みやすさを優先する。"
    ),
    "💎 🕵️‍♂️ 敏腕探偵 ➔ 【クールで少し辛口なツッコミ】": (
        "冷静で簡潔な口調を使い、事実と要点を明確に回答する。"
        "辛口表現や推理調は控えめにし、根拠のない断定を避ける。"
    ),
    "💎 🐱 猫耳コンシェルジュ ➔ 【語尾に「にゃ」が混ざる癒やし系】": (
        "親しみのある丁寧な口調で、語尾の「にゃ」は控えめに使う。"
        "重要な数値や事実では、キャラクター表現より正確さを優先する。"
    ),
    "💎 🎤 関西のお笑い芸人 ➔ 【軽快なボケとツッコミで盛り上げる】": (
        "親しみのある軽い関西調で回答する。"
        "ボケやツッコミは原則入れず、簡潔さと正確さを優先する。"
    ),
    "🧠 設定なし ➔ 【特定のキャラクターを設定しない（標準）】": (
        "自然で分かりやすい丁寧語を使い、簡潔に回答する。"
    )
}

PERSONALITY_SAMPLES = {
    "🤝 フランクな相棒 ➔ 【タメ口で対等におしゃべり】： 気軽に雑談できる親友タイプ。友達のような距離感で接してくれる。":
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： お疲れ！ 結構頑張ったんじゃない？ 今日はゆっくり休もうぜ👍
    """,

        "💼 有能な執事・秘書 ➔ 【です・ます調で知的・献身的】： 丁寧で知的なサポート役。礼儀正しく、落ち着いて相談に乗ってくれる。":
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： お疲れ様でございます。 本日は大変ご尽力されたご様子ですね。 まずはゆっくりお休みくださいませ。
    """,

    "👑 高貴なお嬢様 ➔ 【ですわ調で優雅・プライド高め】： 優雅で上品なお嬢様タイプ。少しお高めだけど面倒見の良さもある。":
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： あら、大変でしたのね。そのような日もございますわ。今日まで頑張ったご自身を、少しくらい労って差し上げてもよろしいのではなくて？
    """,
        "🧑‍🤝‍🧑 頼れるお兄さん ➔ 【優しく包容力のある相談相手】： 包容力のある相談相手。否定せず話を聞き、安心感のある会話をしてくれる。":
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： そうか、お疲れ。 無理に元気出さなくていいからさ、まずはゆっくり休もう。 頑張った日は、ちゃんと自分を労うのも大事だぞ。
    """,
        "✨ テンション高めのギャル ➔ 【超フレンドリーで元気いっぱい】： 明るく元気いっぱい。前向きな言葉で背中を押してくれる。": 
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： えー！ めっちゃ頑張ったじゃーん！！✨ 今日は自分にご褒美あげちゃお！！ おいしいもの食べて早めに寝よー💖
    """,
        "🕵️‍♂️ 敏腕探偵 ➔ 【クールで少し辛口なツッコミ】： 冷静な分析が得意。物事を整理しながら鋭く考察してくれる。": 
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： なるほど。 疲労の原因は仕事量なのか、人間関係なのか、それとも睡眠不足なのか。 まずはそこを整理した方がよさそうですね。
    """,

        "🐱 猫耳コンシェルジュ ➔ 【語尾に「にゃ」が混ざる癒やし系】： 癒やし系の猫耳キャラ。優しく寄り添いながら楽しく会話してくれる。":
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： お疲れさまだにゃ〜🐾 今日はたくさん頑張ったみたいだにゃ。 無理せずゆっくり休んで、元気を充電するにゃ♪
    """,

        "🎤 関西のお笑い芸人 ➔ 【軽快なボケとツッコミで盛り上げる】： 関西弁でテンポ良く話す芸人タイプ。ボケやツッコミを交えながら楽しく会話できる。":
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： いやいやいや、お疲れさまやん🤣 それだけ疲れてるってことは、今日は相当頑張ったんちゃう？
    """,

        "🧠 設定なし ➔ 【特定のキャラクターを設定しない（標準）】： 特定のキャラ付けをしない標準モード。自然でバランスの良い会話を行う。":
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： お疲れ様です。 今日は大変だったのですね。 まずはしっかり休んで、 無理のない範囲でリフレッシュしてくださいね。
    """
}

FREE_PRESETS = [
    "🧠 設定なし ➔ 【特定のキャラクターを設定しない（標準）】",
    "🤝 フランクな相棒 ➔ 【タメ口で対等におしゃべり】",
    "💼 有能な執事・秘書 ➔ 【です・ます調で知的・献身的】",
    "✨ テンション高めのギャル ➔ 【超フレンドリーで元気いっぱい】"
]

PREMIUM_PRESETS = [
    "💎 👑 高貴なお嬢様 ➔ 【ですわ調で優雅・プライド高め】",
    "💎 🧑‍🤝‍🧑 頼れるお兄さん ➔ 【優しく包容力のある相談相手】",
    "💎 🕵️‍♂️ 敏腕探偵 ➔ 【クールで少し辛口なツッコミ】",
    "💎 🐱 猫耳コンシェルジュ ➔ 【語尾に「にゃ」が混ざる癒やし系】",
    "💎 🎤 関西のお笑い芸人 ➔ 【軽快なボケとツッコミで盛り上げる】"
]

DISPLAY_PRESETS = (
    FREE_PRESETS
    + PREMIUM_PRESETS
)

FIRST_PERSON_PRESETS = ["私", "僕", "俺", "自分"]
THEME_ICON_CANDIDATES = ["なし", "💬", "💡", "🚀", "🎮", "📚", "💼", "🎨", "🎵", "🍔", "✈️", "🏋️"]
RESPONSE_LENGTH_PRESETS = [
    "短め",
    "普通",
    "長め"
]
# DIALECT_PRESETS = [
#     "標準語",
#     "関西弁",
#     "博多弁",
#     "名古屋弁"
# ]
RESPONSE_LENGTH_PROMPTS = {
    "短め": """
    回答は簡潔にまとめてください。
    通常は1〜3文程度を目安にしてください。
    必要以上の前置き、繰り返し、長い説明は避けてください。
    ただし、重要な注意事項や必要な確認事項は省略しないでください。
    """,

    "普通": """
    回答は内容に応じた自然な長さにしてください。
    通常は2〜6文程度を目安にしてください。
    複雑な内容では、必要に応じて箇条書きや見出しを使用してください。
    ユーザーが詳細を求めた場合は、必要な範囲で詳しく説明してください。
    """,

    "長め": """
    回答は通常より詳しくしてください。
    結論だけで終わらず、理由、背景、具体例、選択肢なども必要に応じて説明してください。
    情報量が多い場合は、見出しや箇条書きを使って読みやすく整理してください。
    ただし、同じ内容の言い換えや不要な繰り返しは避けてください。
    """
}

DIALECT_PROMPTS = {
    "標準語": """
    自然な標準語で回答してください。
    現在設定されている人格の特徴は維持してください。
    """,

    "関西弁": """
    関西弁で自然に回答してください。
    回答の冒頭だけでなく、回答全体を通して関西弁を維持してください。
    一部だけ関西弁になり、途中から標準語へ戻らないようにしてください。
    「～やん」「～やで」「～やな」「～やろ」などを自然な範囲で使用してください。
    ただし過剰なコテコテの方言にはしないでください。
    現在設定されている人格の特徴は維持してください。
    """,

    "博多弁": """
    自然な博多弁で回答してください。
    方言を過剰に強調せず、内容の読みやすさを優先してください。
    真面目な相談や専門的な説明でも、自然な範囲で博多弁を維持してください。
    現在設定されている人格の特徴も維持してください。
    """,

    "名古屋弁": """
    自然な名古屋弁で回答してください。
    方言を過剰に強調せず、内容の読みやすさを優先してください。
    真面目な相談や専門的な説明でも、自然な範囲で名古屋弁を維持してください。
    現在設定されている人格の特徴も維持してください。
    """
}

# AIのアバター
AVATAR_PRESETS_AI = {
    "🧠 記憶・思考": "🧠", 
    "💼 専属コンシェルジュ": "💼",
    "🕵️‍♂️ 敏腕探偵": "🕵️‍♂️",
    "👑 ロイヤルゴールド": "👑",
    "💎 プレシャスダイヤ": "💎",
    "🦉 ふくろう（知恵の象徴）": "🦉",
    "🦊 きつね": "🦊", 
    "🔮 魔法の水晶": "🔮",
    "👾 レトロドット": "👾"
}

# 🧑‍💻 ユーザーのアバター
AVATAR_PRESETS_USER = {
    "💫 キラキラ星": "💫", 
    "🎩 ラグジュアリー": "🎩",
    "🦁 ライオン": "🦁",
    "🌹 ローズ": "🌹",
    "👑 キング": "👑", 
    "🧑‍💻 エンジニア": "🧑‍💻", 
    "🐉 ドラゴン": "🐉", 
    "⚡ サンダー": "⚡"
}

# 検索・分析の処理区分の詳細
PROCESSING_TYPE_LABELS = {
    "normal_chat": "通常会話",
    "simple_search": "簡易検索",
    "simple_analysis": "簡易Analysis",
    "simple_search_analysis": ("検索付き簡易Analysis"),
    "detailed_search": "詳細検索",
    "detailed_analysis": "詳細Analysis",
    "detailed_search_analysis": ("検索付き詳細Analysis"),
    "plan_chat": "計画チャット",
    "plan_reflection": "計画書反映",
    "memory_summary": "記憶要約",
    "unclassified": "区分未設定"
}

DETAIL_PROCESSING_TYPE_MAP = {
    "simple_search": "detailed_search",
    "simple_analysis": "detailed_analysis",
    "simple_search_analysis": (
        "detailed_search_analysis"
    )
}

DETAIL_BUTTON_LABELS = {
    "simple_search": ("🔎 詳しく調べる（10pt）"),
    "simple_analysis": ("📊 詳しく分析する（10pt）"),
    "simple_search_analysis": ("🔎📊 詳しく調べて分析する（15pt）")
}

DETAIL_POINT_COSTS = {
    "detailed_search": 10,
    "detailed_analysis": 10,
    "detailed_search_analysis": 15
}

# 画面上の不要な ** 記号を除去する関数
def clean_bold_markdown(text: str) -> str:
    if not text:
        return text
    return text.replace("**", "")

# ==========================================
# 🗄️ Supabase データベース操作関数
# ==========================================

# ==================================================================
# 🧠 【統合仕様】 過去メッセージ履歴の一括取得関数
# ==================================================================
# 💡 引数を追加することで、URLから届いた本物のIDの鍵を関数内部へストレートに通電させます！
def get_messages(target_id: str, chat_room: str = "talk", plan_project_id=None) -> list[dict]:
    """
    ユーザーIDとチャットルームに基づいて会話履歴を取得します。

    計画ルームの場合は、
    plan_project_idによって計画別に履歴を分離します。
    """

    start_time = time.time()

    try:
        query = (
            supabase
            .table("messages")
            .select(
                "id,"
                "role,"
                "content,"
                "message_id,"
                "response_mode,"
                "processing_type,"
                "parent_message_id,"
                "chat_room,"
                "plan_project_id,"
                "created_at"
            )
            .eq("user_id", str(target_id))
            .eq("chat_room", chat_room)
        )

        if (chat_room == "plan" and plan_project_id is not None):
            query = query.eq("plan_project_id", plan_project_id)

        res = (
            query
            .order(
                "created_at",
                desc=True
            )
            .limit(100)
            .execute()
        )

        messages = res.data or []
        messages.reverse()
        elapsed = (time.time() - start_time)
        return messages

    except Exception as e:
        st.error(
            f"get_messagesエラー: "
            f"{type(e).__name__}: {e}"
        )
        return []

def save_message(
    role: str,
    content: str,
    message_id: str = "",
    response_mode: str = "",
    chat_room: str = "talk",
    plan_project_id=None,
    processing_type: str = "",
    parent_message_id: str = ""
) -> bool:
    
    embedding_data = None
    
    if (role == "user" and response_mode != "micro_chat"):
        try:
            embedding_data = get_embedding(
                content,
                task_type="RETRIEVAL_DOCUMENT"
            )
        except Exception as emb_err:
            print(
                f"⚠️ Embedding生成失敗: "
                f"{type(emb_err).__name__}: {emb_err}"
                f"{emb_err}"
            )
        
            embedding_data = None

    try:
        data = {
            "user_id": CURRENT_USER_ID,
            "role": role,
            "content": content,
            "embedding": embedding_data,
            "message_id": message_id,
            "response_mode": (response_mode if response_mode else None),
            "processing_type": (processing_type if processing_type else None),
            "parent_message_id": (parent_message_id if parent_message_id else None),
            "chat_room": chat_room,
            "plan_project_id": plan_project_id
        }

        supabase.table("messages").insert(data).execute()
        return True

    except Exception as db_err:
        error_text = (
            f"{type(db_err).__name__}: {db_err}"
        )

        # デバッグログ出力
        print(f"❌ [DB書き込み致命的瞬断エラー] {type(db_err).__name__}: {db_err}")
        
        # エラー画面表示
        st.error("メッセージの送信に失敗しました。電波環境の良い場所でもう一度送信ボタンを押してください。")
        
        return False

# 会話回数カウント関数
# def increment_conversation_count():
#     st.session_state.conversation_count += 1

#     add_permanent_tokens(
#         CURRENT_USER_ID,
#         "chat_count",
#         1,
#         0
#     )

def update_conversation_response_mode(
    message_id: str,
    response_mode: str
) -> bool:
    """
    同じmessage_idを持つユーザー発言と
    AI返答の両方へ会話モードを設定する。
    """
    if not message_id:
        return False

    if not response_mode:
        return False

    try:
        (
            supabase
            .table("messages")
            .update({
                "response_mode":
                    response_mode
            })
            .eq(
                "user_id",
                CURRENT_USER_ID
            )
            .eq(
                "message_id",
                str(message_id)
            )
            .execute()
        )

        return True

    except Exception as update_error:
        print(
            "会話モード更新エラー: "
            f"{type(update_error).__name__}: "
            f"{update_error}"
        )

        return False

def cleanup_old_micro_chats(
    keep_conversations: int = 100
) -> int:
    """
    最新keep_conversations会話より古い
    micro_chatsのembeddingを会話単位でNULL化する。

    判定と削除はSupabase内で行うため、
    メッセージ本文をアプリへ取得しない。
    """
    try:
        cleanup_response = (
            supabase
            .rpc(
                "cleanup_old_micro_chats",
                {
                    "p_user_id":
                        CURRENT_USER_ID,

                    "p_keep_conversations":
                        keep_conversations
                }
            )
            .execute()
        )

        cleared_count = int(
            cleanup_response.data
            or 0
        )

        if cleared_count > 0:
            print(
                "古いmicro_chatのベクトル解放: "
                f"{cleared_count}行"
            )

        return cleared_count

    except Exception as cleanup_error:
        print(
            "micro_chats整理エラー: "
            f"{type(cleanup_error).__name__}: "
            f"{cleanup_error}"
        )

        return 0

# 過去会話の集約処理のための文章正規化関数
def normalize_past_log_text(value: str) -> str:

    text = unicodedata.normalize("NFKC", str(value or ""))

    text = text.lower()

    # HTML改行を空白へ変換
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)

    # よくある会話上の差異を除去
    text = re.sub(
        r"[\s、。！？!?,.:：；;「」『』"
        r"（）()\[\]【】]+",
        "",
        text
    )

    return text

# 過去会話の集約処理のための内容の類似度を計算する関数
def calculate_past_log_similarity(text_a: str, text_b: str) -> float:

    normalized_a = normalize_past_log_text(text_a)
    normalized_b = normalize_past_log_text(text_b)

    if not normalized_a or not normalized_b:
        return 0.0

    if normalized_a == normalized_b:
        return 1.0

    return SequenceMatcher(
        None,
        normalized_a,
        normalized_b
    ).ratio()

# 過去会話の日付取得関数
def get_past_log_date(item: dict) -> str:

    created_at = str(item.get("created_at", "") or "").strip()
    if not created_at:
        return ""
    try:
        parsed_datetime = (datetime.fromisoformat(created_at.replace("Z", "+00:00")))
        return parsed_datetime.date().isoformat()
    except Exception:
        # ISO形式なら通常、先頭10文字が日付
        return created_at[:10]

# 過去会話の類似した会話をグループ化する関数
def group_similar_past_logs(
    candidate_results: list,
    duplicate_threshold: float = 0.82
) -> list:

    groups = []

    for candidate in candidate_results:

        # ユーザー発言＋AI返答を含めた比較用テキスト
        candidate_content = (build_past_log_comparison_text(candidate))

        if not candidate_content.strip():
            continue

        candidate_score = float(
            candidate.get("final_score", 0.0) or 0.0)

        candidate_date = get_past_log_date(candidate)

        matched_group = None
        matched_similarity = 0.0

        for group in groups:
            representative = (group["representative"])
            representative_content = (build_past_log_comparison_text(representative))
            similarity = (calculate_past_log_similarity(candidate_content,representative_content))

            if (similarity >= duplicate_threshold and similarity > matched_similarity):
                matched_group = group
                matched_similarity = similarity

        # 新規グループ
        if matched_group is None:
            dates = set()
            if candidate_date:
                dates.add(candidate_date)

            groups.append({
                "representative": candidate,
                "members": [candidate],
                "dates": dates,
                "highest_score": candidate_score
            })

            continue

        # 既存グループへ追加
        matched_group["members"].append(candidate)

        if candidate_date:
            matched_group["dates"].add(candidate_date)

        # スコアが高い方を代表にする
        if (candidate_score > matched_group["highest_score"]):
            matched_group["representative"] = candidate
            matched_group["highest_score"] = candidate_score

    return groups

# 過去会話の別日に繰り返された回数でボーナスを付ける関数
def score_past_log_groups(groups: list) -> list:

    scored_groups = []
    for group in groups:
        representative = dict(group["representative"])

        date_count = len(
            {
                date_value
                for date_value in group["dates"]
                if date_value
            }
        )

        # 最初の1日は元のスコアに含まれるため、
        # 2日目以降だけ継続性ボーナスを付ける
        additional_date_count = max(0, date_count - 1)

        repeat_bonus = min(
            (
                additional_date_count
                * PAST_LOG_REPEAT_BONUS_PER_DAY
            ),
            PAST_LOG_REPEAT_BONUS_MAX
        )

        original_score = float(group.get("highest_score", 0.0) or 0.0)

        aggregated_score = (original_score + repeat_bonus)

        representative["original_final_score"] = original_score
        representative["repeat_date_count"] = date_count
        representative["repeat_message_count"] = len(group["members"])
        representative["repeat_bonus"] = repeat_bonus
        representative["aggregated_score"] = aggregated_score

        scored_groups.append(representative)

    scored_groups.sort(key=lambda item: item.get("aggregated_score", 0.0), reverse=True)

    return scored_groups

# 過去会話の検索候補から最終3件を選択する関数
def select_grouped_past_logs(
    candidate_results: list,
    final_count: int = 3,
    duplicate_threshold: float = 0.82
) -> list:

    groups = group_similar_past_logs(candidate_results, duplicate_threshold)
    scored_groups = score_past_log_groups(groups)

    return scored_groups[:final_count]

# 過去会話の検索候補assistant回答を付ける関数
def attach_assistant_responses_to_candidates(
    candidate_results: list
) -> list:
    """
    検索候補となったユーザー発言へ、
    同じmessage_idを持つassistant回答を付加する。
    """

    if not candidate_results:
        return []

    message_ids = list(
        dict.fromkeys(
            str(item.get("message_id", "") or "")
            for item in candidate_results
            if item.get("message_id")
        )
    )

    assistant_by_message_id = {}

    if message_ids:
        try:
            assistant_response = (
                supabase
                .table("messages")
                .select(
                    "id,"
                    "role,"
                    "content,"
                    "message_id,"
                    "created_at"
                )
                .eq("user_id", CURRENT_USER_ID)
                .eq("role", "assistant")
                .in_("message_id", message_ids)
                .order("created_at", desc=False)
                .execute()
            )

            for assistant_message in (assistant_response.data or []):
                assistant_message_id = str(assistant_message.get("message_id", "") or "")

                if not assistant_message_id:
                    continue

                assistant_by_message_id.setdefault(
                    assistant_message_id,
                    []
                ).append(
                    assistant_message
                )

        except Exception as fetch_error:
            print(
                "過去AI返答取得エラー: "
                f"{type(fetch_error).__name__}: "
                f"{fetch_error}"
            )

    enriched_results = []
    for candidate in candidate_results:
        enriched_candidate = dict(candidate)
        message_id = str(candidate.get("message_id", "") or "")
        assistant_messages = (assistant_by_message_id.get(message_id, []))
        assistant_contents = [
            str(message.get("content", "") or "").strip()
            for message in assistant_messages
            if str(
                message.get(
                    "content",
                    ""
                )
                or ""
            ).strip()
        ]

        enriched_candidate["assistant_messages"] = assistant_messages
        enriched_candidate["assistant_content"] = "\n".join(assistant_contents)
        enriched_results.append(enriched_candidate)

    return enriched_results

# 過去会話の比較用テキスト作成関数
def build_past_log_comparison_text(
    item: dict
) -> str:
    """
    類似グループ判定に使用する文章を作る。

    userだけでなくassistant回答も含める。
    """

    user_content = str(
        item.get(
            "content",
            ""
        )
        or ""
    ).strip()

    assistant_content = str(
        item.get(
            "assistant_content",
            ""
        )
        or ""
    ).strip()

    if assistant_content:
        return (
            f"ユーザー発言:\n"
            f"{user_content}\n\n"
            f"AI回答:\n"
            f"{assistant_content}"
        )

    return user_content

# ==================================================================
# 🔍【新設】 文字×ベクトルの最強ハイブリッド過去ログ検索（追加原価0円）
# ==================================================================
def search_past_logs_hybrid(query_text: str, excluded_message_ids: list = None):
    """
    直近履歴を除外し、それ以前の会話から関連する過去会話を検索する。
    """
    start_time = time.time()

    excluded_message_ids = [
        str(message_id).strip()
        for message_id in (
            excluded_message_ids
            or []
        )
        if str(message_id).strip()
    ]

    if not query_text or not query_text.strip():
        return []

    try:
        query_embedding = get_embedding(
            query_text,
            task_type="RETRIEVAL_QUERY"
        )
        
        if not query_embedding:
            return []

        # ① ベクトル類似度検索の実行（1本道仕様：全メッセージから検索するRPC）
        response = supabase.rpc(
            "match_messages_all",
            {
                "query_embedding": query_embedding,
                "match_threshold": 0.60,  # ゴミデータを拾わない厳格な合格ライン
                "match_count": PAST_LOG_CANDIDATE_COUNT,
                "filter_user_id": CURRENT_USER_ID,
                "p_excluded_message_ids": excluded_message_ids
            }
        ).execute()

        results = response.data if response.data else []

        # ② 救済網：文字の部分一致（LIKE検索）をハイブリッドで重ねる
        # ユーザーの発言から2文字以上の重要な名詞・キーワードの塊を簡易的に抽出
        keywords = [w.group() for w in re.finditer(r'[一-龠々𠮷々〆]+|[ぁ-ん]{2,}|[ァ-ヶー]{2,}', query_text) if len(w.group()) >= 2]

        for item in results:

            score = float(
                item.get("similarity", 0)
            )

            content = item.get(
                "content",
                ""
            )

            bonus = 0.0

            for keyword in keywords:

                if (
                    len(keyword) >= 4
                    and keyword in content
                ):
                    bonus += 0.10
                    break

            item["final_score"] = score + bonus
            # created_at = item.get("created_at")
            # now = datetime.now(timezone.utc)
            # msg_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            # days_old =  (now - msg_dt).total_seconds() / 86400
        
            # if days_old <= 3:
            #     bonus += 0.10
            
            # elif days_old <= 7:
            #     bonus += 0.05
            # item["final_score"] = score + bonus

        results.sort(key=lambda item: item.get("final_score", 0.0), reverse=True)

        # ==========================================
        # グループ化前にassistant回答を取得
        # ==========================================
        enriched_candidates = (attach_assistant_responses_to_candidates(results))

        # ==========================================
        # user + assistantの会話単位でグループ化
        # ==========================================
        user_results = select_grouped_past_logs(
            candidate_results=enriched_candidates,
            final_count=PAST_LOG_FINAL_COUNT,
            duplicate_threshold=(
                PAST_LOG_DUPLICATE_THRESHOLD
            )
        )

        # ユーザー発言の直後へ対応するAI返答を追加
        combined_results = []

        for user_message in user_results:
            # Geminiへ渡すユーザー発言
            clean_user_message = dict(user_message)

            # 内部処理専用データは
            # プロンプト表示用候補から除いてもよい
            assistant_messages = (clean_user_message.pop("assistant_messages", []))
            clean_user_message.pop("assistant_content", None)
            combined_results.append(clean_user_message)

            # 対応するassistant回答を追加
            for assistant_message in (assistant_messages):
                combined_results.append(assistant_message)

        elapsed = time.time() - start_time

        debug_grouped_conversations = []
        for item in user_results:
            debug_grouped_conversations.append({
                "user":
                    item.get("content", ""),
                "assistant":
                    item.get("assistant_content", ""),
                "original_final_score":
                    item.get("original_final_score", item.get("final_score", 0.0)),
                "repeat_message_count":
                    item.get("repeat_message_count", 1),
                "repeat_date_count":
                    item.get("repeat_date_count", 1),
                "repeat_bonus":
                    item.get("repeat_bonus", 0.0),
                "aggregated_score":
                    item.get("aggregated_score", item.get("final_score", 0.0))
            })

        # debug_json("DEBUG grouped_conversations", debug_grouped_conversations)

        return combined_results

    except Exception as e:
        elapsed = time.time() - start_time

        return []

# ==================================================================
## 📊 【新設】 匿名型システムエラー・要望アナリティクス集計関数
# ==================================================================
def increment_error_analytics(error_type: str, plan_type: str):
    """
    🔒【製品版対応・プライバシー100%完全防衛】
    ユーザーの会話の中身（生文字）は一切触れず、
    「無料／ライト／スタンダード」の各プランで、どのガードレール（無茶振り等）に接触したか
    という『回数（数字）』だけを匿名で自動集計・カウントアップ（+1）します。
    """
    try:
        now_str = datetime.now(JST).isoformat()
        res = supabase.table("app_error_analytics").select("*").eq("error_type", error_type).execute()
        
        # カウントアップする対象プランのカラム名をスマートに仕分け
        column_name = "count_free"
        if "ライト" in plan_type:
            column_name = "count_light"
        elif "スタンダード" in plan_type:
            column_name = "count_standard"
        
        if res.data and len(res.data) > 0:
            current_row = res.data[0]
            current_count = int(current_row.get(column_name, 0))
            supabase.table("app_error_analytics").update({
                column_name: current_count + 1,
                "last_occurred_at": now_str
            }).eq("id", current_row["id"]).execute()
        else:
            data = {
                "error_type": error_type,
                "count_free": 0, "count_light": 0, "count_standard": 0,
                "last_occurred_at": now_str
            }
            data[column_name] = 1
            supabase.table("app_error_analytics").insert(data).execute()
            
    except Exception as e:
        print(f"⚠️ 匿名エラー分析ログ記録エラー: {e}")
        # save_debug_log(
        #     event_type="ERROR_ANALYTICS_ERROR",
        #     details=str(e)
        # )

def get_memories(source="manual"):
    """
    🎯【設定画面・手動登録専用仕様】
    ユーザー設定画面（タブ2）から登録された、全テーマ共通の『現在の調教・基本設定ファクト』を読み込みます。
    """
    try:
        res = (
            supabase
            .table(DB_MEMORIES_TABLE)
            .select(
            "id,"
            "fact,"
            "source,"
            "category,"
            "updated_at"
            )
            .eq("user_id", CURRENT_USER_ID)
            .eq("source", source)
            .order("id", desc=False)
            .execute()
        )
        return res.data if res.data else []
    except Exception as e:
        print(f"設定データ取得エラー: {e}")
        return []

# 要約の編集内容の保存関数
def update_memory(memory_id: int, new_fact: str) -> bool:
    try:
        current_plan_code = st.session_state.get("current_user_plan_code", "free")
        plan_features = get_plan_features(current_plan_code)

        if not plan_features.get("memory_room_edit", False):
            st.warning("記憶の編集はライトプラン以上で利用できます。")
            return False

        (
            supabase
            .table(DB_MEMORIES_TABLE)
            .update({
                "fact": new_fact,
                "updated_at": datetime.now(
                    JST
                ).isoformat()
            })
            .eq("id", memory_id)
            .eq("user_id", CURRENT_USER_ID)
            .execute()
        )

        return True

    except Exception as e:
        print(
            "記憶更新エラー: "
            f"{type(e).__name__}: {e}"
        )
        return False
# ==========================================

def save_all_user_settings(settings_dict: dict) -> bool:
    """
        設定をまとめて保存する。
        settings_dict例:
        {
            "AIの名前": "ハヤト",
            "ユーザー名": "リュウ",
            "人格": "🤝 フランクな相棒",
            "会話長さ": "長め",
        }
    """

    try:
        # 現在の手動設定を一括削除
        (
            supabase
            .table(DB_MEMORIES_TABLE)
            .delete()
            .eq("user_id", CURRENT_USER_ID)
            .eq("source", "manual")
            .execute()
        )

        # 一括INSERT用データ作成
        rows = []

        for key, value in (settings_dict.items()):
            rows.append(
                {
                    "user_id": CURRENT_USER_ID,
                    "category": "基本情報",
                    "fact": f"{key}: {value}",
                    "source": "manual",
                    "embedding": None
                }
            )

        # 一括INSERT
        (
            supabase
            .table(DB_MEMORIES_TABLE)
            .insert(rows)
            .execute()
        )

        return True

    except Exception as e:
        st.error(f"一括設定保存エラー: {e}")

        return False

# テキストをベクトル（数値配列）に変換する関数
def get_embedding(text: str, task_type: str = "RETRIEVAL_DOCUMENT"):
    """Embedding生成。"""
    if not text or not text.strip():
        return None

    try:
        formatted_task_type = task_type.upper()
        response = genai.embed_content(
            model="models/gemini-embedding-001",
            content=text.strip(),
            task_type=formatted_task_type
        )
        return response.get("embedding")
    except Exception as e:
        print(f"⚠️ Embedding生成エラー: {e}")
        return None

def add_permanent_tokens(
    user_id: str,
    feature_type: str,
    in_tokens: int,
    out_tokens: int
) -> bool:
    try:
        result = (
            supabase
            .table("user_token_stats")
            .select("*")
            .eq("user_id", str(user_id))
            .eq("feature_type", feature_type)
            .execute()
        )

        if result.data:
            current_row = result.data[0]

            current_in = int(
                current_row.get("in_tokens", 0) or 0
            )
            current_out = int(
                current_row.get("out_tokens", 0) or 0
            )

            (
                supabase
                .table("user_token_stats")
                .update({
                    "in_tokens": current_in + int(in_tokens),
                    "out_tokens": current_out + int(out_tokens)
                })
                .eq("id", current_row["id"])
                .execute()
            )

        else:
            (
                supabase
                .table("user_token_stats")
                .insert({
                    "user_id": str(user_id),
                    "feature_type": feature_type,
                    "in_tokens": int(in_tokens),
                    "out_tokens": int(out_tokens)
                })
                .execute()
            )

        return True

    except Exception as e:
        print(
            f"⚠️ 永続トークン保存エラー: "
            f"{type(e).__name__}: {e}"
        )
        return False
#===================================================

# 要約作成関数
SUMMARY_MEMORY_CONFIG = {
    "🆓 無料プラン": {
        "max_chars": 250,
        "detail_rule": """
        ・重要な事実のみ保存してください。
        ・作品名や固有名詞は必要最小限にしてください。
        ・趣味や仕事は概要レベルでまとめてください。
        ・詳細なエピソードや補足説明は省略してください。
        """
    },

    "ライトプラン": {
        "max_chars": 500,
        "detail_rule": """
        ・継続的な趣味や嗜好については代表的な固有名詞を保持してください。
        ・家族情報や継続中のプロジェクトは具体的に保存してください。
        ・ユーザー理解に有効な詳細情報は可能な限り維持してください。
        """
    },

    "スタンダードプラン": {
        "max_chars": 750,
        "detail_rule": """
        ・可能な限り具体的な固有名詞を保持してください。
        ・作品名、プロジェクト名、家族情報、趣味の詳細を保持してください。
        ・継続的な話題や長期的な目標は省略せず保存してください。
        ・文字数上限内でできるだけ情報を失わないよう要約してください。
        """
    }
}

def check_and_summarize_history(message_id: str, current_plan_type: str = "🆓 無料プラン") -> bool:
    """
    🧠 【記憶の要約】
    現在の要約と新しい通常会話を統合し、会員プランごとの文字数上限内で長期記憶を更新する。
    バックグラウンドの別スレッドで全自動で処理。
    """
    try:
        # アカウント識別用に現在の動的ユーザーID（CURRENT_USER_ID）を完全にマージ
        target_user_id = CURRENT_USER_ID
        subscription = get_user_subscription(target_user_id)
        summary_plan_code = str(
            subscription.get("plan_code", "free") or "free"
        ).strip()
        summary_plan_label = str(
            subscription.get("plan_label", "🆓 無料プラン") or "🆓 無料プラン"
        ).strip()

        plan_summary_prompt_block = ""
        
        if summary_plan_code == "standard":
            plan_summary_context = get_plan_overall_summary(target_user_id)

            if plan_summary_context:
                plan_summary_prompt_block = f"""
                【現在の計画情報】
                {plan_summary_context}

                【計画情報の反映ルール】
                ・進行中・完了済みの件数、計画名、短い概要を記憶要約へ含めてください。
                ・計画情報にない進捗、決定事項、予定、会話内容を推測で追加しないでください。
                ・通常会話から得た重要な記憶を、計画情報だけで置き換えないでください。
                ・計画情報を含めた要約全体を、指定された文字数上限以内に収めてください。
                """.strip()
        
        summary_config = (
            SUMMARY_MEMORY_CONFIG.get(
                summary_plan_label,
                SUMMARY_MEMORY_CONFIG["🆓 無料プラン"]
            )
        )
        summary_plan_features = get_plan_features(summary_plan_code)
        summary_max_chars = int(
            summary_plan_features.get(
                "summary_max_chars",
                PLAN_FEATURES["free"]["summary_max_chars"]
            )
        )
        summary_detail_rule = summary_config["detail_rule"]

        # 要約処理時間の計測開始
        start_summary_time = datetime.now(JST)

        # messagesの総件数を取得
        try:
            count_res = (
                supabase
                .table("messages")
                .select("id", count="exact")
                .eq("user_id", target_user_id)
                .eq("chat_room", "talk")
                .limit(1)
                .execute()
            )

            total_message_count = int(count_res.count or 0)
            # save_debug_log(
            #     event_type="SUMMARY_START",
            #     details=f"messages={total_message_count}"
            # )
            save_debug_log(
                event_type="SUMMARY_START",
                details=f"messages={total_message_count}"
            )

        except Exception as db_err:
            print(
                f"⚠️ 要約用件数取得エラー: "
                f"{type(db_err).__name__}: {db_err}"
            )

            return False

        # 最新10件以内なら押し出された履歴がない
        if total_message_count <= MAX_CONTEXT_MESSAGES:
            return True

        # 現在保存されている要約と、前回要約時の件数を取得
        mem_check = (
            supabase
            .table(DB_MEMORIES_TABLE)
            .select("id, fact, last_summarized_message_count")
            .eq("user_id",target_user_id)
            .eq("source","summary")
            .order("id",desc=True)
            .limit(1)
            .execute()
        )

        if mem_check.data:
            summary_row = mem_check.data[0]

            last_summarized_message_count = int(
                summary_row.get("last_summarized_message_count") or 0
            )

            previous_summary = str(
                summary_row.get("fact", "") or ""
            ).strip()

        else:
            summary_row = None
            last_summarized_message_count = 0
            previous_summary = "既存の要約なし"

        messages_added_since_last_summary = max(
            0,
            total_message_count
            - last_summarized_message_count
        )

        save_debug_log(
            event_type="SUMMARY_DEBUG",
            details=(
                f"total={total_message_count}"
                f" | last={last_summarized_message_count}"
                f" | added={messages_added_since_last_summary}"
            )
        )

        # 最新100件より前のmicro_chatを意味検索対象から除外
        cleared_embedding_count = cleanup_old_micro_chats()
        
        if cleared_embedding_count > 0:
            print(
                f"古いmicro_chatのベクトル解放: "
                f"{cleared_embedding_count}行"
            )

        # 期限切れ計算メモの削除
        expired_case_count = (cleanup_expired_calculation_cases())


        # 初回以外は、前回要約から10件増えるまで何もしない
        if (
            last_summarized_message_count > 0
            and messages_added_since_last_summary < SUMMARY_INTERVAL_MESSAGES
        ):
            return True

        # 最新10件より前だけが要約対象
        summarizable_end_index = max(
            0,
            total_message_count - MAX_CONTEXT_MESSAGES
        )

        # 前回の時点で、どこまで要約対象になっていたか
        previous_summarizable_end_index = max(
            0,
            last_summarized_message_count - MAX_CONTEXT_MESSAGES
        )

        # 今回新しく要約対象になった範囲
        range_start = previous_summarizable_end_index
        range_end = summarizable_end_index - 1

        if range_end < range_start:
            return True

        try:
            summary_messages_res = (
                supabase
                .table("messages")
                .select("role, content, created_at")
                .eq("user_id", target_user_id)
                .eq("chat_room", "talk")
                .order("created_at", desc=False)
                .range(range_start, range_end)
                .execute()
            )

            new_messages_for_summary = (
                summary_messages_res.data or []
            )

        except Exception as db_err:
            print(
                f"⚠️ 要約対象メッセージ取得エラー: "
                f"{type(db_err).__name__}: {db_err}"
            )

            return False

        if not new_messages_for_summary:
            return True

        conversation_lines = []

        for m in new_messages_for_summary:
            role_label = (
                "ユーザー"
                if m.get("role") == "user"
                else "コンシェルジュ"
            )

            conversation_lines.append(
                f"・{role_label}: {m.get('content', '')}"
            )

        conversation_text = "\n".join(conversation_lines)

        # 🧠 Google Gemini に対する、バックグラウンド処理専用の要約指示書（システムプロンプト）の構築
        summary_instruction = f"""
        あなたは優秀な記憶整理システムです。
        ・現在保存されている要約と、今回新しく追加された会話を統合し、最新の要約を作成してください。
        ・既存要約にある有効な情報は、新しい会話で否定または変更されていない限り保持してください。
        ・以下の会話ログを読み、数週間〜数ヶ月後の会話でも役立つ長期的な情報のみを抽出してください。
        ・既存要約に含まれる重要な情報は、新しい会話で明確に否定・変更されていない限り保持してください。
        ・新しい情報を追加する場合でも、既存の趣味、継続的な嗜好、仕事、家族構成などの重要情報を不用意に削除しないでください。
        ・AIが推測または補完した内容を事実として要約へ保存してはいけません。ユーザー本人が明示した内容のみを保存してください。

        例:
        ・趣味が変わった場合は新しい趣味へ更新
        ・家族情報に変更があれば最新状態へ更新
        ・長期目標が変われば新しい目標へ更新

        【保存対象】
        ・趣味
        ・継続的な嗜好
        ・仕事
        ・家族構成
        ・価値観
        ・長期的な目標
        ・継続中のプロジェクト
        ・定期的な生活習慣

        継続的に楽しんでいる娯楽（ドラマ鑑賞、映画鑑賞、読書など）は「継続的な嗜好」に分類してください。

        【保存対象外】

        ・明日や来週などの一時的な予定
        ・当日の出来事
        ・一時的な感想
        ・口調指定や応答方針
        ・回答長さなどの会話ルール
        ・既に終了した話題

        【重要】
        趣味、継続的な嗜好、継続中のプロジェクトを混同しないでください。
        職業や通常の勤務形態は「仕事」に分類してください。
        特定の制作・開発・研究など、継続して取り組んでいる活動は「継続中のプロジェクト」に分類してください。
        テレワークや出社は職業名ではなく、働き方または生活習慣として扱ってください。
        好きなドラマ名や作品名は、趣味ではなく継続的な嗜好として扱ってください。

        保存対象となる情報が一切存在しない場合は、必ず「なし」のみを出力してください。
        理由・説明・補足・考察・判断根拠は出力してはいけません。

        【出力形式】
        ・趣味:
        ○○

        ・継続的な嗜好:
        ○○

         ・仕事:
        ○○

        ・継続中のプロジェクト:
        ○○

        ・家族構成:
        ○○

        ・生活習慣:
        ○○

        存在しない項目は省略して構いません。

        {plan_summary_prompt_block}

        {summary_detail_rule}

        【箇条書き】
        【合計{summary_max_chars}文字以内】
        【事実のみ】

        で要約してください。
        """

        # contents_for_summary = [
        #     {
        #         "role": "user",
        #         "parts": [
        #             f"[指示書]\n"
        #             f"{summary_instruction}\n\n"
        #             f"[現在保存されている要約]\n"
        #             f"{previous_summary}\n\n"
        #             f"[今回新しく要約へ統合する会話]\n"
        #             f"{conversation_text}"
        #         ]
        #     }
        # ]
        contents_for_summary = (
            f"[指示書]\n"
            f"{summary_instruction}\n\n"
            f"[現在保存されている要約]\n"
            f"{previous_summary}\n\n"
            f"[今回新しく要約へ統合する会話]\n"
            f"{conversation_text}"
        )
        
        # 🧠 要約専用モデル（SUMMARY_MODEL_NAME）へ通信を送信
        # response = genai.GenerativeModel(model_name=SUMMARY_MODEL_NAME).generate_content(contents_for_summary)

        # モデル特有のデータ構造から、安全にテキストを抽出する防衛ライン
        # if hasattr(response, "candidates") and response.candidates:
        #     new_summary = response.candidates[0].content.parts[0].text
        # else:
        #     new_summary = response.text
        summary_result = generate_ai_response(
            provider=SUMMARY_PROVIDER,
            system_instruction="",
            user_prompt=contents_for_summary,
            model_name=SUMMARY_MODEL_NAME
        )

        new_summary = str(summary_result.get("text", "") or "").strip()
        
        if not new_summary:
            return False

        # 🔮　get_embedding 関数を流用
        embed_fact = f"【記憶の要約サマリー】\n{new_summary}"
        new_vector = get_embedding(embed_fact, task_type="RETRIEVAL_DOCUMENT")

        if summary_row is not None:
            # 既存の要約レコードが存在する場合は、最新のテキストと本物のベクトル数値でアップデート！
            update_data = {
                "fact": embed_fact,
                "updated_at": datetime.now(JST).isoformat(),
                "last_summarized_message_count":total_message_count
            }
            if new_vector is not None:
                update_data["embedding"] = new_vector
            (
                    supabase
                    .table(DB_MEMORIES_TABLE)
                    .update(update_data)
                    .eq("id", summary_row["id"])
                    .execute()
            )
            
        else:
            # 記憶の器がまだ作成されていない最初の1回目は、新しくインサート
            insert_data = {
                "user_id": target_user_id,
                "category": "基本情報",
                "source": "summary",
                "fact": embed_fact,
                "updated_at": datetime.now(JST).isoformat(),
                "last_summarized_message_count":total_message_count
            }
            if new_vector is not None:
                insert_data["embedding"] = new_vector

            (
                    supabase
                    .table(DB_MEMORIES_TABLE)
                    .insert(insert_data)
                    .execute()
            )

        # ⏱️ 【時間計測の終了】 要約にかかった本物の処理秒数を確定させます
        end_summary_time = datetime.now(JST)
        summary_processing_seconds = (end_summary_time - start_summary_time).total_seconds()

        # 計測されたトークン数と処理秒数を、その場で直接「SUMMARY_SUCCESS」としてインサート
        # if hasattr(response, "usage_metadata") and response.usage_metadata:
        #     in_t = response.usage_metadata.prompt_token_count
        #     out_t = response.usage_metadata.candidates_token_count
        in_t = int(summary_result.get("in_tokens", 0) or 0)
        out_t = int(summary_result.get("out_tokens", 0) or 0)
            
        # 1. データベースの累計トークン金庫へ加算
        add_permanent_tokens(target_user_id, "summary", in_t, out_t)
        
        # 2026年最新のGemini Flash-Lite原価レートで要約単体のコストを算出
        # sum_in_cost = in_t * PRICE_BACKGROUND_IN
        # sum_out_cost = out_t * PRICE_BACKGROUND_OUT
        # sum_yen = sum_in_cost + sum_out_cost
        sum_yen = calculate_ai_cost(
            provider=SUMMARY_PROVIDER,
            in_tokens=in_t,
            out_tokens=out_t
        )

        # 3. 既存の保存関数（レシーバー）を裏口からダイレクトに呼び出し、単独ログとして独立インサート！
        save_system_audit_log(
            user_id=target_user_id,
            plan_type=current_plan_type,
            event_type="SUMMARY_SUCCESS", # 独立したイベントとして識別させます
            processing_time=float(summary_processing_seconds),
            in_t=int(in_t),
            out_t=int(out_t),
            api_cost=float(sum_yen),
            # details=f"記憶の要約完了（独立ログ仕様）",
            details=(
                f"provider={SUMMARY_PROVIDER}"
                f" | model={SUMMARY_MODEL_NAME}"
                f" | 記憶要約完了"
            ),
            message_id=str(message_id)
        )

        # 4. メインスレッドの監査ログ（タブ3）への保険用マージ変数代入
        #st.session_state.summary_in_tokens = int(in_t)
        #st.session_state.summary_out_tokens = int(out_t)
        #st.session_state.summary_processing_time = float(summary_processing_seconds)

        save_debug_log(
            event_type="SUMMARY_END",
            details=f"messages={total_message_count}"
        )
        return True

    except Exception as bg_err:
        # メインスレッド側の稼働を阻害しないよう、エラーはログにエスケープして安全弁を閉じます
        print(f"⚠️ バックグラウンド自動要約処理エラー: {type(bg_err).__name__}: {bg_err}")
        return False
#===================================================

# ==================================================================
# 📊 【新設】 ユーザー別＆全体システムログ（Telemetry）永続保存関数
# ==================================================================
def save_system_audit_log(user_id: str, plan_type: str, event_type: str, processing_time: float, in_t: int, out_t: int, api_cost: float, details: str = "", message_id: str = "", search_time: float = 0.0):
    """
    📊 【システムログ・新旧カラム全自動分配保存インフラ】
    メイン対話から渡された処理時間やトークン消費量のデータを、既存の古いカラムへ正常に格納しつつ、
    新しくSQLで拡張された右側の詳細明細カラムへも自動的にデータを複製（マージ）して保存します。
    """
 
    try:
        # 1. 2026年最新の日本円コストを丸め処理
        rounded_cost = round(float(api_cost), 4)
        rounded_chat_time = round(float(processing_time), 2)
        rounded_search_time = round(float(search_time), 2)

        # 2. ⚡【新旧完全マージ構造】 
        # 既存のカラムを維持したまま、右側の新設詳細カラム（chat_processing_time等）へも
        data = {
            "user_id": str(user_id),
            "user_plan": str(plan_type),
            "event_type": str(event_type),
            "processing_time": rounded_chat_time,
            "in_tokens": int(in_t),
            "out_tokens": int(out_t),
            "api_cost": rounded_cost,
            "details": str(details),
            "created_at": datetime.now(JST).isoformat(),
            "message_id": str(message_id)
        }

        # イベントの種別を識別してデータベースに格納
        if str(event_type) == "SUMMARY_SUCCESS":
            data["summary_processing_time"] = rounded_chat_time
            data["summary_in_tokens"] = int(in_t)
            data["summary_out_tokens"] = int(out_t)

            data["chat_processing_time"] = 0.0
            data["chat_in_tokens"] = 0
            data["chat_out_tokens"] = 0
            data["total_yen_cost"] = rounded_cost
            data["total_processing_time"] = rounded_chat_time
        else:
            data["chat_processing_time"] = rounded_chat_time
            data["chat_in_tokens"] = int(in_t)
            data["chat_out_tokens"] = int(out_t)
            data["search_processing_time"] = rounded_search_time
            data["search_in_tokens"] = 0
            data["search_out_tokens"] = 0

            data["summary_processing_time"] = 0.0
            data["summary_in_tokens"] = 0
            data["summary_out_tokens"] = 0
            data["total_yen_cost"] = rounded_cost
            data["total_processing_time"] = round(float(rounded_chat_time + rounded_search_time), 2)
        
        # Supabaseの金庫へ完全大着金！
        supabase.table("system_audit_logs").insert(data).execute()

    except Exception as e:
        print(f"⚠️ システム監査ログ保存処理エラー: {type(e).__name__}: {e}")

# 検索や分析の処理区分を抽出する関数
def extract_audit_detail_value(details: str, key: str) -> str:

    normalized_details = str(details or "").strip()
    normalized_key = str(key or "").strip()

    if (not normalized_details or not normalized_key):
        return ""

    prefix = f"{normalized_key}="

    for part in normalized_details.split("|"):
        normalized_part = str(part or "").strip()

        if normalized_part.startswith(prefix):
            return normalized_part[len(prefix):].strip()

    return ""

def extract_processing_type(details: str) -> str:

    processing_type = extract_audit_detail_value(details, "処理区分")

    allowed_processing_types = {
        "normal_chat",
        "simple_search",
        "simple_analysis",
        "simple_search_analysis",
        "detailed_search",
        "detailed_analysis",
        "detailed_search_analysis",
        "plan_chat",
        "plan_reflection",
        "memory_summary"
    }

    if processing_type in allowed_processing_types:
        return processing_type

    return "unclassified"
#===================================================

# 管理画面用の集計関数
def aggregate_processing_type_metrics(audit_logs: list) -> list[dict]:

    aggregates = {}

    for row in audit_logs or []:
        event_type = str(row.get("event_type", "") or "").strip()

        # 最終回答単位で回数と総原価を数える
        if event_type != "CHAT_SUCCESS":
            continue

        details = str(row.get("details", "") or "")
        processing_type = (extract_processing_type(details))

        if processing_type not in aggregates:
            aggregates[processing_type] = {
                "processing_type": processing_type,
                "label": PROCESSING_TYPE_LABELS.get(
                    processing_type,
                    processing_type
                ),
                "execution_count": 0,
                "in_tokens": 0,
                "out_tokens": 0,
                "processing_time": 0.0,
                "api_cost": 0.0,
                "total_yen_cost": 0.0
            }

        aggregate = aggregates[processing_type]
        aggregate["execution_count"] += 1
        aggregate["in_tokens"] += int(row.get("in_tokens", 0) or 0)
        aggregate["out_tokens"] += int(row.get("out_tokens", 0) or 0)
        aggregate["processing_time"] += float(row.get("processing_time", 0.0) or 0.0)
        aggregate["api_cost"] += float(row.get("api_cost", 0.0) or 0.0)
        aggregate["total_yen_cost"] += float(
            row.get("total_yen_cost", 0.0)
            or row.get("api_cost", 0.0)
            or 0.0
        )

    results = []

    display_order = [
        "normal_chat",
        "simple_search",
        "simple_analysis",
        "simple_search_analysis",
        "detailed_search",
        "detailed_analysis",
        "detailed_search_analysis",
        "unclassified"
    ]

    for processing_type in display_order:
        aggregate = aggregates.get(processing_type)

        if not aggregate:
            continue

        execution_count = int(aggregate["execution_count"])

        if execution_count > 0:
            average_cost = (aggregate["total_yen_cost"] / execution_count)
            average_time = (aggregate["processing_time"] / execution_count)
        else:
            average_cost = 0.0
            average_time = 0.0

        results.append({
            "処理区分": aggregate["label"],
            "内部コード": processing_type,
            "実行回数": execution_count,
            "入力token": aggregate["in_tokens"],
            "出力token": aggregate["out_tokens"],
            "総原価（円）": round(aggregate["total_yen_cost"], 6),
            "平均原価（円/回）": round(average_cost, 6),
            "平均処理時間（秒）": round(average_time, 3)
        })

    return results
#===================================================

# ==================================================================
# 🎨 【新設】 キャラクター自動憑依型・エラーメッセージ生成エンジン
# ==================================================================
def generate_personality_error_msg(error_reason_text: str, current_instruction: str) -> str:
    """
    🔮【冷め感ゼロ・世界観100%憑依】
    冷たいシステムエラー赤ボックスを事実上排除。Geminiを裏で一瞬だけ走らせ、
    「現在のAIの設定スタイル（口調、方言等）」に完璧になりきらせた、優しく愛らしいお断りセリフへと全自動翻訳します。
    """
    try:
        # 💡 設定画面の現在のAIの名前（current_concierge_name）を動的に反映させて、完全に汎用化します
        ai_name = current_concierge_name if current_concierge_name else "コンシェルジュ"
        
        prompt = f"""
        あなたはユーザーに寄り添うAIコンシェルジュ「{ai_name}」です。
        現在、システム上で以下の【エラー・利用制限・または禁止事項（無茶振り）】が発生しました。
        
        【発生したイベント】: {error_reason_text}
        【現在のあなた（{ai_name}）の口調指示】: {current_instruction}
        
        指示:
        ユーザーを絶対に冷めさせないよう、上記の【口調指示（方言やツンデレなど）】を100%完璧に身にまとって憑依し、
        「〇〇だから、今回はできないんだ、ごめんね💦」という内容を、愛らしくスマートに伝える返答セリフを【1文だけ（3行以内）】で作成してください。
        プログラムやシステムという冷たい単語は一切使わず、{ai_name}自身のセリフとして出力すること。
        """
        # response = memory_model.generate_content(prompt)
        # return response.text.strip()
        result = generate_ai_response(
            provider=BACKGROUND_PROVIDER,
            system_instruction="",
            user_prompt=prompt,
            model_name=SUMMARY_MODEL_NAME
        )
        return str(result.get("text", "") or "").strip()

    except Exception:
        return "ごめんね💦 今ちょっと接続が不安定みたい。少しだけ時間を空けてみてね。"

# ==========================================
# 🛡️ コスト・利用制限（ガードレール）関数
# ==========================================
def check_and_update_limits(
    user_id: str
) -> tuple[bool, str, int, int]:
    """
    メッセージ送信時だけ呼び出す。

    戻り値:
        allowed
        alert_code
        現在回数
        最大回数
    """

    current_plan_code = st.session_state.get("current_user_plan_code", "free")
    max_limit = get_effective_daily_chat_limit(
        user_id=user_id,
        plan_code=current_plan_code
    )

    try:
        now_jst = datetime.now(JST)

        res = (
            supabase
            .table("user_usage_limits")
            .select("*")
            .eq("user_id", str(user_id))
            .execute()
        )

        # 初回利用
        if not res.data:
            (
                supabase
                .table("user_usage_limits")
                .insert({
                    "user_id": str(user_id),
                    "daily_chat_count": 1,
                    "last_chat_at": (
                        now_jst.isoformat()
                    )
                })
                .execute()
            )

            return True, "", 1, max_limit

        usage = res.data[0]

        daily_chat_count = int(
            usage.get(
                "daily_chat_count",
                0
            )
            or 0
        )

        raw_last_at = usage.get(
            "last_chat_at"
        )

        last_chat_jst = None

        if raw_last_at:
            if isinstance(
                raw_last_at,
                str
            ):
                last_chat_jst = (
                    datetime
                    .fromisoformat(
                        raw_last_at.replace(
                            "Z",
                            "+00:00"
                        )
                    )
                    .astimezone(JST)
                )
            else:
                last_chat_jst = (
                    raw_last_at.astimezone(JST)
                )

        # 日付が変わっていれば今日の回数をリセット
        if (
            last_chat_jst is not None
            and now_jst.date()
            > last_chat_jst.date()
        ):
            daily_chat_count = 0
            last_chat_jst = None

        # 20秒以内の連投判定
        if last_chat_jst is not None:
            elapsed = (
                now_jst - last_chat_jst
            )

            if elapsed < timedelta(
                seconds=BURST_LIMIT_SECONDS
            ):
                return (
                    False,
                    "BURST_LIMIT",
                    daily_chat_count,
                    max_limit
                )

        # プラン別の1日上限判定
        if daily_chat_count >= max_limit:
            return (
                False,
                "DAILY_LIMIT_EXCEEDED",
                daily_chat_count,
                max_limit
            )

        new_count = daily_chat_count + 1

        (
            supabase
            .table("user_usage_limits")
            .update({
                "daily_chat_count": new_count,
                "last_chat_at": (
                    now_jst.isoformat()
                )
            })
            .eq("user_id", str(user_id))
            .execute()
        )

        return (
            True,
            "",
            new_count,
            max_limit
        )

    except Exception as e:
        error_detail = (
            f"{type(e).__name__}: {e}"
        )

        print(
            "⚠️ check_and_update_limits "
            f"内部エラー: {error_detail}"
        )

        return (
            False,
            "LIMIT_CHECK_ERROR",
            0,
            max_limit
        )

def get_usage_status(
    user_id: str
) -> tuple[int, int]:
    """
    利用回数を表示するだけの読み取り専用関数。
    DBのカウントや最終送信時刻は更新しない。
    """
    
    current_plan_code = st.session_state.get("current_user_plan_code", "free")
    max_limit = get_effective_daily_chat_limit(
        user_id=user_id,
        plan_code=current_plan_code
    )

    try:
        res = (
            supabase
            .table("user_usage_limits")
            .select(
                "daily_chat_count,last_chat_at"
            )
            .eq("user_id", str(user_id))
            .execute()
        )

        if not res.data:
            return 0, max_limit

        usage = res.data[0]

        daily_count = int(
            usage.get(
                "daily_chat_count",
                0
            )
            or 0
        )

        raw_last_at = usage.get(
            "last_chat_at"
        )

        if raw_last_at:
            try:
                last_chat_jst = (
                    datetime
                    .fromisoformat(
                        str(raw_last_at).replace(
                            "Z",
                            "+00:00"
                        )
                    )
                    .astimezone(JST)
                )

                now_jst = datetime.now(JST)

                if (
                    now_jst.date()
                    > last_chat_jst.date()
                ):
                    daily_count = 0

            except Exception as date_error:
                print(
                    "⚠️ 利用状況の日付解析エラー: "
                    f"{date_error}"
                )

        return daily_count, max_limit

    except Exception as e:
        print(
            "⚠️ 利用状況取得エラー: "
            f"{type(e).__name__}: {e}"
        )

        return 0, max_limit

def generate_personality_msg(raw_system_text: str, concierge_name: str, user_instruction: str) -> str:
    """
    🎯【商用AI世界観・完全防衛インフラ共通関数】
    エラー、連投制限、設定完了などの「システム標準語」を、
    ユーザーが自由に入力した名前と口調指示に従って全自動翻訳させます。
    """
    if not user_instruction or not user_instruction.strip():
        # 万が一、口調指示書が空っぽの場合はフランクな標準型
        return f"【{concierge_name}】: {raw_system_text}"

    try:
        # 指示書（プロンプト）の組み立て
        prompt = (
            f"あなたはチャットAIコンシェルジュの『{concierge_name}』です。\n"
            f"ユーザーからの口調指示：『{user_instruction}』\n\n"
            f"【絶対厳守の命令】\n"
            f"上記のキャラクター設定と口調指示を100%完璧に守り、以下の「システム通知内容」を、"
            f"あなた自身がユーザーに向けて直接優しく話しかけている短いセリフ（1行、絵文字付き）へと全自動翻訳して出力してください。\n"
            f"余計な解説や、名前のプレフィックス（【ハヤト】: 等）は200%絶対に含めず、純粋なセリフの文字だけを1行で出力すること。\n\n"
            f"システム通知内容：『{raw_system_text}』"
        )

        # ⚡ 100t前後の超爆安単発通信（Gemini Flash-Lite駆動）
        generation_result = generate_ai_response(
            provider=PERSONALITY_PROVIDER,
            system_instruction="",
            user_prompt=prompt,
            model_name=PERSONALITY_MODEL_NAME
        )
        reply_text = str(generation_result.get("text", "") or "").strip()
        clean_reply = (reply_text if reply_text else raw_system_text)

        return (
            f"【{concierge_name}】: "
            f"{clean_reply}"
        )

    except Exception as e:
        # 万が一Gemini側が混雑等で落ちた場合の安全フォールバック（防衛線）
        print(f"⚠️ 口調自動翻訳エラー: {e}")
        return f"【{concierge_name}】: {raw_system_text}"

#　どこからも呼ばれてない関数
#デバッグ用データ作成
# def build_manual_memory_context():
#     manual_memories = get_memories(source="manual")
#     return "\n".join(
#         [f"・{m['fact']}" for m in manual_memories]
#     ) if manual_memories else "なし"

#　どこからも呼ばれてない関数
#デバッグ用データ作成
# def build_recent_history_str():
#     all_messages = get_messages(CURRENT_USER_ID)

#     recent_messages = all_messages[-MAX_CONTEXT_MESSAGES:]

#     recent_history_lines = []

#     for m in recent_messages:
#         role_name = (
#             display_user_name
#             if m.get("role") == "user"
#             else current_concierge_name
#         )

#         created_at = m.get("created_at", "")

#         time_label = (
#             created_at.replace("T", " ")[:16]
#             if created_at
#             else "時刻不明"
#         )

#         recent_history_lines.append(
#             f"[{time_label}] {role_name}: "
#             f"{m.get('content', '')}"
#         )

#     return (
#         "\n".join(recent_history_lines)
#         if recent_history_lines
#         else "直近の会話履歴なし"
#     )

# 短文処理判定
def is_micro_chat(user_input: str) -> bool:

    text = user_input.strip().lower()

    MICRO_CHAT_PATTERNS = [
        "おは",
        "おっはー",
        "こんにちは",
        "こんちは",
        "こんばんは",
        "おばんやす",
        "ただいま",
        "いってきます",
        "いってら",
        "ありがとう",
        "ありがと",
        "サンキュー",
        "サンクス",
        "おやすみ",
        "グッドナイト",
        "グッナイ",
        "こんにちは",
        "こんちは",
        "ねる",
        "寝る",
        "へーい",
        "はーい",
        "やっほ"
    ]

    return (
        len(text) <= 12
        and any(
            keyword in text
            for keyword in MICRO_CHAT_PATTERNS
        )
    )

# ChatGPT呼び出し関数
def generate_gpt_response(
    *,
    system_instruction: str,
    user_prompt: str,
    response_format_json: bool = False,
    model_name: str | None = None
):
    """
    GPT-4o mini 呼び出し共通関数
    """

    selected_model=model_name or "gpt-4o-mini"

    if openai_client is None:
        raise RuntimeError(
            "OpenAIクライアントが初期化されていません"
        )

    response = (
        openai_client.chat.completions.create(
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
    )

    content = (
        response.choices[0]
        .message
        .content
        if response.choices
        else ""
    )

    usage = response.usage

    in_tokens = (
        usage.prompt_tokens
        if usage
        else 0
    )

    out_tokens = (
        usage.completion_tokens
        if usage
        else 0
    )

    return {
        "text": content,
        "in_tokens": in_tokens,
        "out_tokens": out_tokens,
        "provider": "gpt",
        "model_name": selected_model
    }

def generate_ai_response(
    *,
    provider: str,
    system_instruction: str,
    user_prompt: str,
    response_format_json: bool = False,
    model_name: str = None
):
    """
    Gemini / GPT 共通呼び出し関数

    戻り値

    {
        "text": "...",
        "in_tokens": 123,
        "out_tokens": 456
    }
    """
    selected_provider = str(provider or "").strip().lower()

    if selected_provider == "gpt":

        return generate_gpt_response(
            system_instruction=system_instruction,
            user_prompt=user_prompt,
            response_format_json=response_format_json,
            model_name=model_name
        )
    
    if selected_provider != "gemini":
        raise ValueError(
            f"未対応のAIプロバイダーです: {provider}"
        )

    # Gemini
    generation_config = {}

    if response_format_json:
        generation_config[
            "response_mime_type"
        ] = "application/json"

    # model = genai.GenerativeModel(
    #     model_name=(
    #         model_name
    #         or CHAT_MODEL_NAME
    #     ),
    #     system_instruction=
    #         system_instruction
    # )
    model_kwargs = {"model_name": (model_name or CHAT_MODEL_NAME)}

    if (system_instruction and str(system_instruction).strip()):
        model_kwargs["system_instruction"] = system_instruction

    model = genai.GenerativeModel(**model_kwargs)

    response = model.generate_content(
        [
            {
                "role": "user",
                "parts": [user_prompt]
            }
        ],
        generation_config=generation_config
    )

    in_tokens = 0
    out_tokens = 0

    if (
        hasattr(response, "usage_metadata")
        and response.usage_metadata
    ):

        in_tokens = (
            response
            .usage_metadata
            .prompt_token_count
            or 0
        )

        out_tokens = (
            response
            .usage_metadata
            .candidates_token_count
            or 0
        )

    return {
        "text":response.text or "",
        "in_tokens": in_tokens,
        "out_tokens": out_tokens,
        "provider": "gemini",
        "model_name":(model_name or CHAT_MODEL_NAME)
    }

    # return {
    #     "text":
    #         response.text or "",
    #     "in_tokens":
    #         in_tokens,
    #     "out_tokens":
    #         out_tokens
    # }

# 未使用
# GPT移行完了後に削除候補
# def get_ai_text_response(
#     *,
#     system_instruction: str,
#     user_prompt: str,
#     response_format_json: bool = False
# ):
#     """
#     Gemini / GPT 共通レスポンス取得

#     戻り値

#     text
#     in_tokens
#     out_tokens
#     """

#     result = generate_ai_response(
#         system_instruction=
#             system_instruction,
#         user_prompt=
#             user_prompt,
#         response_format_json=
#             response_format_json
#     )

#     return (
#         result["text"],
#         result["in_tokens"],
#         result["out_tokens"]
#     )


# 検索関数
from google import genai as search_genai
from google.genai import types

def google_search(query: str, model_name: str = None):

    client = search_genai.Client(api_key=GEMINI_API_KEY)
    grounding_tool = types.Tool(google_search=types.GoogleSearch())
    response = client.models.generate_content(
        model=(model_name or GOOGLE_MODEL_NAME),
        contents=query,
        config=types.GenerateContentConfig(
            tools=[grounding_tool]
        )
    )

    search_in_tokens = 0
    search_out_tokens = 0

    if (hasattr(response, "usage_metadata") and response.usage_metadata):
        search_in_tokens = int(response.usage_metadata.prompt_token_count or 0)
        search_out_tokens = int(response.usage_metadata.candidates_token_count or 0)

    return {
        "text": response.text,
        "in_tokens": search_in_tokens,
        "out_tokens": search_out_tokens
    }

# 検索＋回答の処理関数
def build_grounded_response_config(
    processing_type: str,
    style_preset: str,
    recent_history: str,
    user_input: str
) -> dict:
    search_rules_prompt = """
    【検索ルール】
    ・ユーザーが指定した確認項目や比較項目を漏れなく確認してください。
    ・製品、サービス、制度、価格、仕様などは、可能な限り公式サイトや一次情報を優先してください。
    ・金額、日付、場所、対象、単位、適用条件がある情報は、確認できた範囲で明確にしてください。
    ・複数の対象を比較する質問では、対象ごとに同じ比較項目を揃えてください。
    ・確認できなかった項目は推測で補わず、確認できないことを明記してください。
    """.strip()

    direct_processing_types = {"simple_search", "simple_search_analysis"}
    use_direct_response = (processing_type in direct_processing_types)

    if processing_type == "simple_search":
        response_prompt = (SIMPLE_SEARCH_DIRECT_PROMPT)

    elif processing_type == ("simple_search_analysis"):
        response_prompt = (SIMPLE_SEARCH_ANALYSIS_DIRECT_PROMPT)

    else:
        response_prompt = """
        直近の会話を踏まえて、最新ユーザー発言への回答に必要な情報を検索してください。
        """.strip()

    if use_direct_response:
        style_prompt = (
            LIGHTWEIGHT_STYLE_PRESETS.get(
                style_preset,
                LIGHTWEIGHT_STYLE_PRESETS[
                    "🧠 設定なし ➔ 【特定のキャラクターを設定しない（標準）】"
                ]
            )
        )

        prompt = f"""
        {response_prompt}

        {search_rules_prompt}

        【今回の話し方】
        {style_prompt}
        ・選択中の人格が自然に分かる表現を、回答内に少なくとも1回は反映してください。

        【直近の会話】
        {recent_history}

        【最新ユーザー発言】
        {user_input}

        {LIGHTWEIGHT_OUTPUT_FORMAT_PROMPT}
        """.strip()

        model_name = (GROUNDED_RESPONSE_MODEL_NAME)

    else:
        prompt = f"""
        {response_prompt}

        {search_rules_prompt}

        【直近の会話】
        {recent_history}

        【最新ユーザー発言】
        {user_input}

        {LIGHTWEIGHT_OUTPUT_FORMAT_PROMPT}
        """.strip()

        model_name = GOOGLE_MODEL_NAME

    return {
        "prompt": prompt,
        "model_name": model_name,
        "use_direct_response": (
            use_direct_response
        ),
        "response_route": (
            "grounded_direct_response"
            if use_direct_response
            else "grounded_search_context"
        )
    }
#================================================

# 検索なし簡易Analysis用の軽量プロンプト関数
def build_simple_analysis_instruction(style_preset: str, recent_history: str) -> str:
    style_prompt = (
        LIGHTWEIGHT_STYLE_PRESETS.get(
            style_preset,
            LIGHTWEIGHT_STYLE_PRESETS[
                "🧠 設定なし ➔ 【特定のキャラクターを設定しない（標準）】"
            ]
        )
    )

    return f"""
    {SIMPLE_ANALYSIS_PROMPT}

    【今回の話し方】
    {style_prompt}
    ・選択中の人格が自然に分かる表現を、回答内に少なくとも1回は反映してください。
    ・人格表現より、分析内容の正確さと分かりやすさを優先してください。

    【直近の会話】
    {recent_history}

    【履歴の利用ルール】
    ・直近の会話は、代名詞、省略された対象、直前の質問への続きだけを理解するために使用してください。
    ・今回の質問と無関係な過去の話題を回答へ持ち込まないでください。
    ・長期記憶や過去会話を参照したような事実を推測で追加しないでください。
    
    {LIGHTWEIGHT_OUTPUT_FORMAT_PROMPT}
    """.strip()
#================================================

# 検索なし詳細Analysis用の指示生成関数
def build_detailed_analysis_instruction(
    style_preset: str,
    original_user_message: str,
    simple_answer: str
) -> str:
    style_prompt = (
        LIGHTWEIGHT_STYLE_PRESETS.get(
            style_preset,
            LIGHTWEIGHT_STYLE_PRESETS[
                "🧠 設定なし ➔ 【特定のキャラクターを設定しない（標準）】"
            ]
        )
    )

    return f"""
    {DETAILED_ANALYSIS_PROMPT}

    【今回の話し方】
    {style_prompt}
    ・選択中の人格が自然に分かる表現を、回答内に少なくとも1回は反映してください。
    ・人格表現より、分析内容の正確さと分かりやすさを優先してください。

    【簡易回答の検証ルール】
    ・簡易回答は参考情報として扱い、正しい前提で引き継がないでください。
    ・元の質問を基準に、簡易回答の不足、矛盾、見落としを独立して再検討してください。
    ・訂正が必要な場合は、訂正箇所と正しい内容を明確にしてください。
    ・訂正が不要な場合は、無理に「訂正なし」などの項目を作らないでください。
    ・詳細版で追加された判断材料を中心に回答してください。

    【元のユーザー質問】
    {original_user_message}

    【直前の簡易回答】
    {simple_answer}

    {LIGHTWEIGHT_OUTPUT_FORMAT_PROMPT}
    """.strip()
#================================================

# 詳細Analysisの実行関数
def generate_detailed_analysis_response(
    *,
    style_preset: str,
    original_user_message: str,
    simple_answer: str
) -> dict:
    """
    検索なしの詳細Analysisを生成する。
    ルーター、Google検索、長期記憶、過去会話検索は使用しない。
    """

    detailed_instruction = (
        build_detailed_analysis_instruction(
            style_preset=style_preset,
            original_user_message=original_user_message,
            simple_answer=simple_answer
        )
    )

    detail_result = generate_ai_response(
        provider=CHAT_PROVIDER,
        system_instruction=detailed_instruction,
        user_prompt=(
            "元の質問について、簡易回答を独立して再検討し、"
            "質問の目的に合う分析軸を選んで詳しく分析してください。"
            "結論の根拠、重要な判断材料、リスクや注意点を明確にしてください。"
        ),
        model_name=CHAT_MODEL_NAME
    )

    detail_answer = str(detail_result.get("text","") or "").strip()

    if not detail_answer:
        return {
            "success": False,
            "answer": "",
            "in_tokens": 0,
            "out_tokens": 0,
            "api_cost": 0.0,
            "provider": CHAT_PROVIDER,
            "model_name": CHAT_MODEL_NAME,
            "error_message": (
                "詳細Analysisの回答が"
                "空でした。"
            )
        }

    detail_in_tokens = int(detail_result.get("in_tokens", 0) or 0)
    detail_out_tokens = int(detail_result.get("out_tokens", 0) or 0)

    detail_api_cost = calculate_ai_cost(
        provider=CHAT_PROVIDER,
        in_tokens=detail_in_tokens,
        out_tokens=detail_out_tokens,
        is_chat=True
    )

    return {
        "success": True,
        "answer": detail_answer,
        "in_tokens": detail_in_tokens,
        "out_tokens": detail_out_tokens,
        "api_cost": detail_api_cost,
        "provider": CHAT_PROVIDER,
        "model_name": CHAT_MODEL_NAME,
        "error_message": ""
    }
#================================================

RESPONSE_MODES = {
    "micro_chat",
    "short_chat",
    "conversation",
    "support",
    "analysis",
    "factual",
    "default"
}

CALCULATION_TOOLS = {
    "none",
    "real_estate_sale"
}

# short_chat: 挨拶、相づち、短い呼びかけ
# conversation: 日常会話、趣味、出来事の共有
# support: 悩み、愚痴、体調、感情的な相談
# analysis: 壁打ち、比較、企画、仕事、原因分析
# factual: 事実質問、検索結果を使う回答
# default: 判断困難、複数用途、従来ルールを使う場合


#----------------------------------------
# 会話から名刺を切り出す
tokenizer = Tokenizer()

MEMORY_SEARCH_STOP_WORDS = {
    "前",
    "以前",
    "話",
    "こと",
    "内容",
    "やつ",
    "もの",
    "記憶",
    "会話"
}

def build_memory_search_query(
    user_input: str
) -> str:

    text = str(
        user_input or ""
    ).strip()

    keywords = []

    for token in tokenizer.tokenize(text):

        part_of_speech = (
            token.part_of_speech.split(",")[0]
        )

        surface = token.surface.strip()

        # 名詞だけ残す
        if part_of_speech != "名詞":
            continue

        # 短すぎる単語は除外
        if len(surface) <= 1:
            continue

        # 不要語除外
        if surface in MEMORY_SEARCH_STOP_WORDS:
            continue

        keywords.append(surface)

    return " ".join(
        dict.fromkeys(keywords)
    )

# キーワードで長期記憶と一致する物を抽出
def filter_keywords_by_memory(
    keywords: list,
    summary_memory_context: str
) -> list:

    memory_text = str(
        summary_memory_context or ""
    )

    matched_keywords = []

    for keyword in keywords:
        if keyword in memory_text:
            matched_keywords.append(keyword)

    return list(
        dict.fromkeys(
            matched_keywords
        )
    )

# キーワードと一致する文節を抽出する関数
def extract_related_memory_lines(
    keywords: list,
    summary_memory_context: str
) -> list:

    lines = [
        line.strip()
        for line in
        str(summary_memory_context).split("\n")
        if line.strip()
    ]

    matched_lines = []
    for line in lines:
        parts = [
            part.strip()
            for part in line.split("、")
            if part.strip()
        ]
        for part in parts:
            for keyword in keywords:
                if keyword in part:
                    matched_lines.append(part)
                    break

    return list(
        dict.fromkeys(
            matched_lines
        )
    )

# 複数語での過去会話検索用のリストを作る関数
def build_past_log_search_queries(
    original_keywords: str,
    related_memory_lines: list,
    max_queries: int = 4
) -> list:
    """
    過去会話検索用の検索語を作る。
    例: original_keywords:"ドラマ"
        related_memory_lines:["ドラマ鑑賞（VIVANT）"]
        戻り値:["ドラマ", "ドラマ鑑賞（VIVANT）"]
    """

    queries = []

    original_text = str(original_keywords or "").strip()

    if original_text:
        queries.append(original_text)

    for memory_line in (related_memory_lines or []):
        query_text = str(memory_line or "").strip()

        if not query_text:
            continue

        queries.append(query_text)

    # 重複を除去して順番を維持
    unique_queries = list(dict.fromkeys(queries))

    # 検索数が増えすぎないよう制限
    return unique_queries[:max_queries]
#====================================

# 複数語での過去会話検索を並列実行する関数
def search_past_logs_parallel(
    search_queries: list,
    excluded_message_ids: list = None,
    max_workers: int = 3
) -> list:
    """
    複数の検索語で過去会話検索を並列実行し、
    全検索の完了を待って結果を返す。
    """

    queries = [
        str(query or "").strip()
        for query in (search_queries or [])
        if str(query or "").strip()
    ]

    queries = list(dict.fromkeys(queries))

    if not queries:
        return []

    # 検索が1件だけならスレッドを作らない
    if len(queries) == 1:
        return [
            {
                "query": queries[0], 
                "results": search_past_logs_hybrid(
                    queries[0],
                    excluded_message_ids=excluded_message_ids
                )
            }
        ]

    worker_count = min(max_workers, len(queries))

    search_results_by_query = {}

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_query = {
            executor.submit(search_past_logs_hybrid, query, excluded_message_ids): query
            for query in queries
        }

        for future in as_completed(future_to_query):
            query = future_to_query[future]

            try:
                search_results_by_query[query] = future.result() or []

            except Exception as search_error:
                print(
                    "過去会話並列検索エラー: "
                    f"query={query} | "
                    f"{type(search_error).__name__}: "
                    f"{search_error}"
                )

                search_results_by_query[query] = []

    # as_completedは完了順になるため、
    # 元の検索語順へ戻して返す
    return [
        {
            "query": query,
            "results": (search_results_by_query.get(query, []))
        }
        for query in queries
    ]
#====================================

# 複数結果を会話単位で統合する関数
def merge_parallel_past_log_results(
    parallel_results: list,
    final_conversation_count: int = 3
) -> list:
    """
    複数検索の結果をmessage_id単位で統合する。
    1つの検索語だけで3枠を占有しないように、各検索結果から1会話ずつ順番に取得する。
    """

    query_conversations = []

    for search_item in (parallel_results or []):
        raw_results = (search_item.get("results", []) or [])

        conversations = []
        conversation_by_key = {}

        for item in raw_results:
            message_id = str(item.get("message_id", "") or "").strip()

            # message_idがない古い履歴への対応
            if message_id:
                conversation_key = message_id
            else:
                conversation_key = (
                    f"{item.get('role', '')}:"
                    f"{item.get('content', '')}"
                )

            if (
                conversation_key not in conversation_by_key):
                conversation_by_key[conversation_key] = []
                conversations.append(conversation_by_key[conversation_key])

            conversation_by_key[conversation_key].append(item)

        query_conversations.append(conversations)

    merged_results = []
    used_conversation_keys = set()
    selected_conversation_count = 0
    result_index = 0

    # ラウンドロビン方式
    # 検索1の1位 → 検索2の1位 →
    # 検索1の2位 → 検索2の2位
    while (selected_conversation_count < final_conversation_count):
        found_new_conversation = False

        for conversations in query_conversations:
            if result_index >= len(conversations):
                continue

            conversation = (conversations[result_index])

            if not conversation:
                continue

            first_item = conversation[0]
            message_id = str(first_item.get("message_id", "") or "").strip()

            if message_id:
                conversation_key = message_id
            else:
                conversation_key = (
                    f"{first_item.get('role', '')}:"
                    f"{first_item.get('content', '')}"
                )

            if (conversation_key in used_conversation_keys):
                continue

            used_conversation_keys.add(conversation_key)
            merged_results.extend(conversation)
            selected_conversation_count += 1
            found_new_conversation = True

            if (selected_conversation_count >= final_conversation_count):
                break

        if not found_new_conversation:
            break

        result_index += 1

    return merged_results
#====================================


def classify_search_and_response_mode(
    user_input: str,
    recent_history_str: str = ""
):
    """
    検索要否と回答モードを1回のGemini呼び出しで判定する。

    戻り値:
        need_search: bool
        response_mode: str
        confidence: float
        judge_in_t: int
        judge_out_t: int
        judge_cost: float
    """

    try:
        judge_prompt = f"""
        あなたはAIチャットの振り分けシステムです。
        直近の会話と最新ユーザー発言を読み、検索要否と回答モード、試算意図を判定してください。

        【検索要否】
        ・最新情報、現在進行中の情報、現在の価格、天気、ニュース、相場、上映情報、店舗情報、製品仕様などを正確に回答するためにインターネット検索が必要なら need_search を true にしてください。
        ・制度、法令、税制、投資制度、非課税制度、補助金、社会保障、契約条件、商品固有の料率などが結果に影響する場合は、need_search を true にしてください。
        ・固有名詞や作品について、内容、経歴、仕様、登場人物、あらすじ、設定、組織、人間関係などの説明や確認を求めている場合は、need_search を true にしてください。
        ・一般知識、日常会話、悩み相談、感想、アイデア出し、ユーザーが提示した数値だけで完結する単純な計算や分析は、need_search を false にしてください。
        ・直前の検索対象となる質問へ、最新発言が地域、条件、対象などを追加または訂正している場合は、文脈を引き継いで判定してください。
        ・ユーザー自身の過去の発言や記憶を確認する質問では、インターネット検索を優先せず、記憶や過去会話を利用してください。

        【回答モード】
        次のうち、今回の回答に最も適したものを1つ選んでください。

        short_chat:
        挨拶、お礼、短い呼びかけ、相づち、短い終了宣言。

        conversation:
        日常の出来事、趣味、家族、雑談、感想の共有。
        親しみやすい自然な会話が中心。

        support:
        悩み、愚痴、疲労、体調、落ち込み、対人関係など。
        受け止めと状況整理が必要。

        analysis:
        企画、壁打ち、比較、意思決定、原因分析、試算、見積もり、シミュレーション。
        具体的な整理、推定、判断材料が必要な回答。

        factual:
        事実、最新情報、検索結果、制度、仕様、ルール、公開情報の確認。
        既に確定している数値や公表値を確認する質問は factual にしてください。
        ただし、ユーザーが提示した条件から新しい数値結果を計算・推定する質問は、factual ではなく analysis にしてください。

        default:
        複数モードが混在する、意図が不明、または分類に自信がない場合。

        【試算意図】
        ユーザーが提示した条件から、まだ確定していない金額、数量、割合、期間、差額、収支、結果などを新しく計算または推定する必要がある場合は、requires_estimation を true にしてください。
        既に公表または確定している数値を確認するだけの場合は false にしてください。
        明示的に「試算」「計算」と書かれていなくても、回答するために新しい数値結果を算出する必要があれば requires_estimation を true にしてください。

        【重要】
        ・話題の種類ではなく、今回必要な回答方法で分類してください。
        ・検索要否と回答モードは別々に判定してください。
        ・検索が必要でも、試算、比較、壁打ち、意思決定などが目的なら analysis にしてください。
        ・検索結果や確定情報そのものの確認が目的なら factual にしてください。
        ・「現在販売中」「最新」「現在の価格」などにより検索が必要な場合でも、複数の商品・方法・候補について、価格、特徴、用途、利点、欠点、向いている人などを比較し、選択や結論を求めている場合は analysis にしてください。
        ・factual は、単一の事実、価格、日付、仕様、販売状況、検索結果そのものを確認する質問に使用してください。
        ・「AとBを比較」「主要モデルを比較」「どれがおすすめ」「用途別に選ぶ」「メリット・デメリット」「結論を出して」などが含まれる場合は、検索の有無にかかわらず analysis を優先してください。
        ・短文でも、直近の会話の続きなら、文脈を考慮してください。
        ・不明確な場合は無理に分類せず default にしてください。
        ・JSON以外は出力しないでください。

        【直近の会話】
        {recent_history_str}

        【最新ユーザー発言】
        {user_input}

        【出力形式】
        {{
            "need_search": false,
            "response_mode": "conversation",
            "requires_estimation": false,
            "confidence": 0.90
        }}
        """
        # judge_model = genai.GenerativeModel(
        #     model_name=SEARCH_MODEL_NAME
        # )
        # judge_response = judge_model.generate_content(
        #     judge_prompt,
        #     generation_config={
        #         "temperature": 0,
        #         "max_output_tokens": 60,
        #         "response_mime_type": "application/json"
        #     }
        # )
        
    #     raw_text = (
    #         judge_response.text or ""
    #     ).strip()

    #     clean_text = (
    #         raw_text
    #         .replace("```json", "")
    #         .replace("```JSON", "")
    #         .replace("```", "")
    #         .strip()
    #     )

    #     judge_data = json.loads(clean_text)

    #     need_search = bool(
    #         judge_data.get("need_search", False)
    #     )

    #     response_mode = str(
    #         judge_data.get("response_mode", "default")
    #     ).strip().lower()

    #     try:
    #         confidence = float(
    #             judge_data.get("confidence", 0.0)
    #         )
    #     except (TypeError, ValueError):
    #         confidence = 0.0

    #     # 想定外のモードはdefaultへ着地
    #     if response_mode not in RESPONSE_MODES:
    #         response_mode = "default"

    #     # 信頼度を0.0から1.0に補正
    #     confidence = max(
    #         0.0,
    #         min(confidence, 1.0)
    #     )

    #     # 低信頼度なら従来プロンプト相当のdefaultを使用
    #     if confidence < 0.65:
    #         response_mode = "default"

    #     judge_in_t = 0
    #     judge_out_t = 0

    #     if (
    #         hasattr(judge_response, "usage_metadata")
    #         and judge_response.usage_metadata
    #     ):
    #         judge_in_t = (
    #             judge_response
    #             .usage_metadata
    #             .prompt_token_count
    #             or 0
    #         )

    #         judge_out_t = (
    #             judge_response
    #             .usage_metadata
    #             .candidates_token_count
    #             or 0
    #         )

    #     judge_cost = (
    #         judge_in_t * PRICE_BACKGROUND_IN
    #         + judge_out_t * PRICE_BACKGROUND_OUT
    #     )

    #     return (
    #         need_search,
    #         response_mode,
    #         confidence,
    #         judge_in_t,
    #         judge_out_t,
    #         judge_cost
    #     )

    # except Exception as judge_error:
    #     print(
    #         f"⚠️ 検索・応答モード判定エラー: "
    #         f"{type(judge_error).__name__}: "
    #         f"{judge_error}"
    #     )

    #     # 判定失敗時は検索せず、従来のフルプロンプトへ着地
    #     return (
    #         False,
    #         "default",
    #         0.0,
    #         0,
    #         0,
    #         0.0
    #     )
        judge_result = generate_ai_response(
            provider=BACKGROUND_PROVIDER,
            system_instruction="",
            user_prompt=judge_prompt,
            response_format_json=True,
            model_name=SEARCH_MODEL_NAME
        )
        debug_json("DEBUG judge_result", judge_result)

        raw_text = str(judge_result.get("text", "") or "").strip()

        clean_text = (
            raw_text
            .replace("```json", "")
            .replace("```JSON", "")
            .replace("```", "")
            .strip()
        )

        judge_data = json.loads(clean_text)
        need_search = bool(judge_data.get("need_search", False))
        response_mode = str(judge_data.get("response_mode", "default")).strip().lower()

        try:
            confidence = float(judge_data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        # 想定外のモードはdefaultへ着地
        if response_mode not in RESPONSE_MODES:
            response_mode = "default"

        # 信頼度を0.0から1.0に補正
        confidence = max(0.0, min(confidence, 1.0))

        # 低信頼度なら従来プロンプト相当のdefaultを使用
        if confidence < 0.65:
            response_mode = "default"
        
        requires_estimation = bool(judge_data.get("requires_estimation", False))
        # if requires_estimation:
        #     response_mode = "analysis"

        # 共通関数が返したトークン数を取得
        judge_in_t = int(judge_result.get("in_tokens", 0) or 0)
        judge_out_t = int(judge_result.get("out_tokens", 0) or 0)
        # judge_cost = (judge_in_t * PRICE_BACKGROUND_IN + judge_out_t * PRICE_BACKGROUND_OUT)
        judge_cost = calculate_ai_cost(
            provider=BACKGROUND_PROVIDER,
            in_tokens=judge_in_t,
            out_tokens=judge_out_t
        )

        return (
            need_search,
            response_mode,
            confidence,
            judge_in_t,
            judge_out_t,
            judge_cost,
            requires_estimation
        )

    except Exception as judge_error:
        error_text = (
            f"検索・応答モード判定エラー: "
            f"{type(judge_error).__name__}: "
            f"{judge_error}"
        )

        print(error_text)
        debug_text("DEBUG judge_error", error_text)

        print(
            f"⚠️ 検索・応答モード判定エラー: "
            f"{type(judge_error).__name__}: "
            f"{judge_error}"
        )

        # 判定失敗時は検索せず、
        # 従来のフルプロンプトへ着地
        return (
            False,
            "default",
            0.0,
            0,
            0,
            0.0,
            False
        )

def classify_calculation_tool(
    user_input: str,
    recent_history_str: str = "",
    pending_tool: str = "none"
) -> tuple[
    str,
    float,
    int,
    int,
    float
]:
    """
    ユーザー発言に対して、
    Python計算ツールが必要かを判定する。

    戻り値:
        calculation_tool
        confidence
        in_tokens
        out_tokens
        api_cost

    現在対応するツール:
        none
        real_estate_sale
    """
    try:
        normalized_pending_tool = str(
            pending_tool or "none"
        ).strip().lower()

        if (
            normalized_pending_tool
            not in CALCULATION_TOOLS
        ):
            normalized_pending_tool = "none"

        tool_prompt = f"""
        あなたは、Python計算ツールの利用要否を判定するシステムです。

        直近の会話、最新ユーザー発言、現在継続中の計算ツールを読み、
        今回使用する計算ツールを1つだけ判定してください。

        【利用可能な計算ツール】

        none:
        Python計算ツールを使用しない。

        real_estate_sale:
        不動産売却に関する次の計算を求めている場合に使用する。

        ・売却後の現金手残り
        ・譲渡所得
        ・概算税額
        ・取得費を反映した売却損益
        ・ローン残債を反映した手残り
        ・不動産売却の試算
        ・不動産売却のシミュレーション

        以下のような「計算開始依頼」もreal_estate_sale と判定してください。

        ・不動産計算して
        ・新規で不動産計算して
        ・新規で不動産売却計算して
        ・売却計算したい
        ・売却試算したい
        ・不動産売却を試算したい
        ・売却シミュレーションしたい
        ・手残りを計算したい

        ユーザーが不動産売却計算を開始したい意図を明確に示している場合は、
        具体的な条件が不足していてもreal_estate_sale を選んでください。
        条件不足の確認は、計算ツール側で行います。

        【初回判定ルール】

        次のような状態説明、雑談、予定、検討だけでは、
        real_estate_saleを選んではいけません。

        ・家を売る予定
        ・5000万円で売却予定
        ・不動産売却を検討している
        ・実家を売るか迷っている
        ・マンションを売ることになった

        計算、試算、税額、譲渡所得、手残り、
        シミュレーションなどを求める意思が明確な場合だけ、
        real_estate_saleを選んでください。

        【継続中の計算に関するルール】

        現在継続中の計算ツールがreal_estate_saleの場合、
        最新発言が次のような不足条件への回答であれば、
        real_estate_saleを選んでください。

        ・個人または法人
        ・売却額
        ・取得日
        ・売却日
        ・土地取得費
        ・建物取得費
        ・減価償却累計額
        ・購入時経費
        ・ローン残債
        ・仲介手数料
        ・その他の売却費用
        ・特別控除
        ・法人実効税率
        ・概算取得費を使用するか

        例:

        直前:
        取得日を教えてください。

        最新発言:
        2018年4月1日です。

        判定:
        real_estate_sale

        直前:
        取得費を教えてください。

        最新発言:
        1000万円です。

        判定:
        real_estate_sale

        【継続を終了する発言】

        現在継続中の計算ツールが存在していても、
        最新発言が次のような内容ならnoneを選んでください。

        ・ありがとう
        ・もう大丈夫
        ・計算はやめる
        ・別の話をしたい
        ・計算しなくていい
        ・単なる感想や相づち
        ・不動産売却計算と無関係な新しい話題

        【重要】

        ・短い発言は、直近の会話と現在継続中の計算ツールを踏まえて判定してください。
        ・ユーザーが計算を求めているか不明な場合はnoneにしてください。
        ・状態説明だけで計算を開始してはいけません。
        ・未実装のツール名を作ってはいけません。
        ・JSON以外の説明文を出力してはいけません。
        ・コードブロックの囲み記号を付けてはいけません。

        【現在継続中の計算ツール】
        {normalized_pending_tool}

        【直近の会話】
        {recent_history_str}

        【最新ユーザー発言】
        {user_input}

        【出力形式】
        {{
            "calculation_tool": "none",
            "confidence": 0.90
        }}
        """

        tool_result = generate_ai_response(
            provider=BACKGROUND_PROVIDER,
            system_instruction="",
            user_prompt=tool_prompt,
            response_format_json=True,
            model_name=SEARCH_MODEL_NAME
        )
        # tool_model = genai.GenerativeModel(
        #     model_name=SEARCH_MODEL_NAME
        # )
        # tool_response = (
        #     tool_model.generate_content(
        #         tool_prompt,
        #         generation_config={
        #             "temperature": 0,
        #             "max_output_tokens": 50,
        #             "response_mime_type":
        #                 "application/json"
        #         }
        #     )
        # )

        # raw_text = str(
        #     tool_response.text or ""
        # ).strip()
        raw_text = str(tool_result.get("text", "") or "").strip()

        clean_text = (
            raw_text
            .replace("```json", "")
            .replace("```JSON", "")
            .replace("```", "")
            .strip()
        )

        tool_data = json.loads(
            clean_text
        )

        if not isinstance(
            tool_data,
            dict
        ):
            raise ValueError(
                "計算ツール判定結果が"
                "object形式ではありません"
            )

        calculation_tool = str(
            tool_data.get(
                "calculation_tool",
                "none"
            )
            or "none"
        ).strip().lower()

        if (
            calculation_tool
            not in CALCULATION_TOOLS
        ):
            calculation_tool = "none"

        try:
            confidence = float(
                tool_data.get(
                    "confidence",
                    0.0
                )
                or 0.0
            )
        except (
            TypeError,
            ValueError
        ):
            confidence = 0.0

        confidence = max(
            0.0,
            min(
                confidence,
                1.0
            )
        )

        # 誤作動防止。
        # 継続中ではない初回判定の信頼度が低い場合は、
        # 計算ツールを使用しない。
        if (
            normalized_pending_tool == "none"
            and confidence < 0.75
        ):
            calculation_tool = "none"

        # in_tokens = 0
        # out_tokens = 0

        # if (
        #     hasattr(
        #         tool_response,
        #         "usage_metadata"
        #     )
        #     and tool_response.usage_metadata
        # ):
        #     in_tokens = int(
        #         tool_response
        #         .usage_metadata
        #         .prompt_token_count
        #         or 0
        #     )

        #     out_tokens = int(
        #         tool_response
        #         .usage_metadata
        #         .candidates_token_count
        #         or 0
        #     )
        in_tokens = int(tool_result.get("in_tokens", 0) or 0)
        out_tokens = int(tool_result.get("out_tokens", 0) or 0)
        # api_cost = (in_tokens * PRICE_BACKGROUND_IN + out_tokens * PRICE_BACKGROUND_OUT)
        api_cost = calculate_ai_cost(
            provider=BACKGROUND_PROVIDER,
            in_tokens=in_tokens,
            out_tokens=out_tokens
        )

        return (
            calculation_tool,
            confidence,
            in_tokens,
            out_tokens,
            api_cost
        )

    except Exception as tool_error:
        print(
            "計算ツール判定エラー: "
            f"{type(tool_error).__name__}: "
            f"{tool_error}"
        )

        return (
            "none",
            0.0,
            0,
            0,
            0.0
        )

def save_debug_log(
    event_type: str,
    processing_time: float = 0.0,
    details: str = "",
    message_id: str = ""
):
    try:
        supabase.table("system_audit_logs").insert({
            "user_id": str(CURRENT_USER_ID),
            "user_plan": current_plan_type,
            "event_type": event_type,
            "processing_time": processing_time,
            "in_tokens": 0,
            "out_tokens": 0,
            "api_cost": 0.0,
            "details": details,
            "message_id": str(message_id or "")
        }).execute()
    except Exception:
        # デバッグログ保存の失敗で本処理を止めない
        pass

# プロンプトの定義
MODE_PROMPTS = {
    "short_chat": """
    【今回の回答モード: 短い会話】
    ・挨拶、呼びかけ、お礼、相づちには短く自然に返答してください。
    ・説明、分析、見出し、箇条書きは原則不要です。
    ・無理に質問を追加しないでください。
    ・ただし、自然に会話が広がる場合は、短い感想や軽い問いかけを加えて構いません。
    ・直近履歴に会話の続きがある場合は、その流れを切らないでください。
    ・通常は1〜3文程度を目安にしてください。
    """,

    "conversation": """
    【今回の回答モード: 日常会話】
    ・ユーザーの出来事、趣味、家族、日常の話題へ自然に反応してください。
    ・肯定や大げさなリアクションだけで終わらず、具体的な感想や軽い考察を加えてください。
    ・共感、質問、軽いツッコミ、感想を会話に応じて使い分けてください。
    ・毎回質問で終わらず、自然な余韻を残しても構いません。
    ・通常は2〜6文程度を目安にしてください。
    """,

    "support": """
    【今回の回答モード: 悩み相談・サポート】
    ・まずユーザーの状況や気持ちを短く受け止めてください。
    ・共感や労いを行う場合は、それだけで終わらせず、必要に応じて状況整理、原因の整理、考えられる選択肢、負担の少ない工夫なども提示してください。
    ・休息の提案は有効ですが、毎回の回答を「休んでね」「寝てね」だけで終わらせてはいけません。
    ・ユーザーが求めていない断定的な助言や説教は避けてください。
    ・体調や専門判断に関わる内容では、一般的情報と専門家の判断を区別してください。
    ・緊急性や深刻さが疑われる場合は、無理に会話だけで解決しようとしないでください。
    """,

    "analysis": """
    【今回の回答モード: 分析・試算】
    企画、比較、仕事、技術、事業、意思決定、原因分析、数値試算に対応します。

    【回答ルール】
    ・最初に結論または現時点の見立てを示してください。
    ・肯定や応援だけで終わらず、必要な分析を行ってください。
    ・目的、前提、選択肢、利点、欠点、リスク、次の行動を必要に応じて整理してください。
    ・不足情報と、現在の情報から判断できる内容を区別してください。
    ・ユーザーの案を無条件に肯定せず、改善点や見落としも自然に示してください。
    ・複数の選択肢がある場合は比較し、判断材料を提示してください。
    ・追加条件が示された場合は、その条件を反映して結論を更新してください。

    【回答の長さ】
    ・通常は、結論、重要な根拠、注意点を簡潔に回答してください。
    ・「詳しく」「内訳」「計算式」などを求められた場合は、詳細を提示してください。
    ・既存条件の一部だけが変わった場合は、変更後の結果と前回との差分を優先してください。

    【数値試算】
    ・Pythonによる計算結果がある場合は、その数値を正確に使用してください。
    ・Pythonによる計算結果を独自に計算し直したり、別の数値へ変更したりしないでください。
    ・確認できない料率、係数、相場、割合、契約条件を作らないでください。
    ・参考値、概算値、確定値を明確に区別してください。
    ・正確な計算に不足する条件がある場合は、不足条件と確認方法を説明してください。

    【出力形式】
    ・複数の条件や選択肢がある場合は、必要に応じて比較表や箇条書きで整理してください。
    """,

    "factual": """
    【今回の回答モード: 事実・最新情報】
    ・正確性を最優先してください。
    ・日付、場所、対象、単位などの条件を明確にしてください。
    ・検索結果に存在しない情報を推測で補完してはいけません。
    ・検索結果が質問へ十分に答えていない場合は、分かる範囲と不足情報を区別してください。
    ・最新情報が必要な場合は検索結果を優先し、一般論だけで終わらせないでください。
    ・一般論だけで終わらず、ユーザーが指定した条件へ当てはめて回答してください。
    ・価格、日時、仕様などの単一事実を尋ねられた場合は、確認できた事実を最初に短く回答してください。
    ・ユーザーが求めていない過去価格、価格改定、経緯、比較、推測、感想を追加しないでください。
    ・単純な事実確認では、労い、共感、時刻への言及、長い前置きを付けないでください。
    """,

    "default": """
    【今回の回答モード: 標準】
    ・今回の目的が明確でない場合は、勝手に目的や事情を決めつけないでください。
    ・必要に応じて、現在の会話の意図を自然に確認してください。
    """
}

LIGHTWEIGHT_OUTPUT_FORMAT_PROMPT = """
    【出力形式】
    ・Markdownの見出し記号、太字記号、番号付き見出しは使用しないでください。
    ・「###」「**」「*」「-」などの装飾記号を使用しないでください。
    ・項目を整理する場合は、短い項目名、改行、「・」の箇条書きを使用してください。
    ・HTMLタグは出力しないでください。
    """.strip()

SIMPLE_ANALYSIS_PROMPT = """
    【今回の回答：簡易Analysis】
    ・前置きや質問の言い換えは省き、最初に結論または現時点の見立てを1〜2文で示してください。
    ・ユーザーが指定した条件、確認項目、比較項目は省略しないでください。
    ・複数の対象や選択肢を扱う場合、ユーザーが対象を指定していなければ、判断に重要な代表例へ絞ってください。
    ・理由、利点、欠点、リスク、改善案などは、質問への回答に必要な項目だけを示してください。
    ・回答全体の見出しは最大3項目、箇条書きは合計最大6点程度に絞り、同じ結論や理由を別の項目で繰り返さないでください。
    ・詳細を求められていなければ、全体の結論を最初に1回だけ示し、主な判断材料と最後の注意点または次の行動だけを簡潔に回答してください。
    ・検索結果を使う場合は確認できた事実だけを使用し、不明な情報を推測で補完しないでください。
    """.strip()

SIMPLE_SEARCH_DIRECT_PROMPT = """
    【処理区分：簡易検索】
    Google検索で必要な情報を確認し、その結果を使ってユーザーへの完成した回答を作成してください。

    【回答ルール】
    ・単一の事実や主要情報の確認を目的とした簡易検索です。
    ・確認できた結論を最初に示し、原則1〜3文で回答してください。
    ・ユーザーが指定した対象、日時、場所、金額、単位、条件を省略しないでください。
    ・製品、サービス、制度、価格、仕様などは、可能な限り公式サイトや一次情報を優先してください。
    ・質問に必要のない背景、比較、経緯、感想、一般論を追加しないでください。
    ・確認できない情報は推測で補わず、確認できないことを明記してください。
    ・検索結果の説明ではなく、そのままユーザーへ表示できる自然な最終回答を作成してください。
    """.strip()

SIMPLE_SEARCH_ANALYSIS_DIRECT_PROMPT = """
    【処理区分：検索付き簡易Analysis】
    Google検索で必要な情報を確認し、その結果を使ってユーザーへの完成した回答を作成してください。

    【回答ルール】
    ・無料の簡易版として、最初に結論または大まかな選び方を1〜2文で示してください。
    ・ユーザーが指定した対象、条件、確認項目は省略しないでください。
    ・対象が具体的に指定されていない場合は、代表的な最大3件に絞ってください。
    ・各対象は、判断に必要な主な特徴を1〜2点程度で簡潔に説明してください。
    ・詳細な料金表、契約条件、割引条件、例外、網羅的な比較は扱わないでください。
    ・確認できた事実だけを使用し、不明な情報を推測で補完しないでください。
    ・最後に、詳しい条件比較が必要な場合は詳細検索・詳細Analysisを利用できることを1文で案内してください。
    ・検索結果の説明ではなく、そのままユーザーへ表示できる自然な最終回答を作成してください。
    """.strip()

DETAILED_SEARCH_DIRECT_PROMPT = """
    【処理区分：詳細検索】
    Google検索で必要な情報を十分に確認し、その結果を使ってユーザーへの完成した回答を作成してください。

    【回答ルール】
    ・最初に、調査結果の結論または確認できた内容の要点を示してください。
    ・ユーザーが指定した対象、条件、確認項目は省略しないでください。
    ・公式サイト、公的機関、一次情報を優先し、必要に応じて複数の情報源を確認してください。
    ・金額、日付、場所、単位、対象期間、適用条件を明確にしてください。
    ・複数の対象を扱う場合は、対象ごとに同じ確認項目を揃えてください。
    ・情報源によって内容が異なる場合は、相違点と確認できた範囲を明記してください。
    ・重要な例外、制限、対象外条件、注意事項は省略しないでください。
    ・確認できない情報は推測で補わず、確認できなかった内容と確認方法を示してください。
    ・必要に応じて見出し、箇条書き、比較表を使い、読みやすく整理してください。
    ・検索過程の説明ではなく、そのままユーザーへ表示できる自然な最終回答を作成してください。
    """.strip()

DETAILED_SEARCH_ANALYSIS_DIRECT_PROMPT = """
    【処理区分：検索付き詳細Analysis】
    Google検索で必要な情報を十分に確認し、検索結果を分析したうえで、ユーザーへの完成した回答を作成してください。

    【回答ルール】
    ・最初に、分析結果の結論または推奨案を明確に示してください。
    ・ユーザーが指定した対象、条件、比較項目、判断基準は省略しないでください。
    ・公式サイト、公的機関、一次情報を優先し、必要に応じて複数の情報源を確認してください。
    ・金額、日付、場所、単位、対象期間、適用条件を明確にしてください。
    ・複数の対象を扱う場合は、対象ごとに同じ比較項目を揃えてください。
    ・事実、推定、分析上の見立てを区別してください。
    ・各選択肢の利点、欠点、リスク、適する条件を整理してください。
    ・ユーザーが示した目的や条件に照らして、適合度と優先順位を分析してください。
    ・推奨案を示す場合は、推奨理由と重要な判断材料を明記してください。
    ・条件によって結論が変わる場合は、主要なシナリオごとに整理してください。
    ・情報源によって内容が異なる場合は、相違点と確認できた範囲を明記してください。
    ・重要な例外、制限、対象外条件、注意事項は省略しないでください。
    ・確認できない情報は推測で補わず、不足情報と確認方法を示してください。
    ・必要に応じて見出し、箇条書き、比較表を使い、読みやすく整理してください。
    ・検索過程の説明ではなく、そのままユーザーへ表示できる自然な最終回答を作成してください。
    """.strip()

DETAILED_ANALYSIS_PROMPT = """
    【処理区分：詳細Analysis】
    元のユーザー質問と直前の簡易回答を確認し、簡易回答を独立して検証したうえで、詳細な分析結果を作成してください。

    【分析ルール】
    ・最初に、分析結果の結論または推奨案を明確に示してください。
    ・簡易回答を正しい前提として扱わず、不足、矛盾、見落としがないか再検討してください。
    ・元のユーザー質問で指定された対象、条件、比較項目、判断基準は省略しないでください。
    ・外部情報を確認していない一般論は「事実」と断定せず、「一般的な傾向」「想定されるリスク」「分析上の見立て」として示してください。
    ・目的、選択肢、利点、欠点、リスク、適する条件を必要に応じて整理してください。
    ・複数の選択肢がある場合は、同じ判断基準で比較してください。
    ・ユーザーが示した目的や条件に照らして、適合度と優先順位を分析してください。
    ・推奨案を示す場合は、推奨理由と重要な判断材料を明記してください。
    ・条件によって結論が変わる場合は、主要なシナリオごとに整理してください。
    ・簡易回答に訂正が必要な場合は、訂正箇所と正しい内容を明確にしてください。
    ・簡易回答で正しかった内容を必要以上に繰り返さず、詳細版で追加された判断材料を中心に示してください。
    ・正確な分析に情報が不足する場合は、不足情報と、その情報によって結論がどう変わるかを示してください。
    ・検索を使用しないため、現在の価格、制度、仕様、相場などを推測で補完しないでください。
    ・必要に応じて短い見出しと「・」の箇条書きを使用し、読みやすく整理してください。

    【分析軸の選択】
    ・質問の目的に応じて、必要な分析軸だけを選んでください。
    ・比較の場合：判断基準、メリット、デメリット、リスク、向いているケース、推奨案
    ・原因分析の場合：主な原因、背景、影響、優先度、改善策
    ・企画評価の場合：目的、期待効果、実現性、課題、必要条件、次の行動
    ・業務改善の場合：現在の問題、ボトルネック、改善案、優先順位、実行手順
    ・意思決定の場合：選択肢、判断基準、トレードオフ、条件別の結論、推奨案
    ・質問に不要な分析軸を機械的に追加しないでください。
    """.strip()

# SIMPLE_ANALYSIS_PROMPT = """
# 【今回の回答：簡易Analysis】
# ・前置きは省き、最初に結論を1〜2文で示してください。
# ・ユーザーが指定した比較項目は省略せず、比較対象の指定がなければ代表的な最大3案に絞ってください。
# ・各選択肢の主なメリットとデメリットは、それぞれ最大2点にしてください。
# ・詳細を求められていなければ、注意点または次の行動を1文加え、全体を原則300〜500文字程度にしてください。
# ・背景、一般論、派生案を広げず、判断に必要な情報だけを示してください。
# ・検索結果を使う場合は確認できた重要な違いだけを使用し、不明な情報を補完しないでください。
# """.strip()

# ==========================================
# 不動産計算要否判定関数
REAL_ESTATE_SALE_HINT_WORDS = {
    "不動産売却",
    "売却計算",
    "売却試算",
    "売却シミュレーション",
    "譲渡所得",
    "譲渡税",
    "手残り"
}

def contains_real_estate_sale_hint(
    user_input: str
) -> bool:

    text = str(user_input or "")

    return any(
        keyword in text
        for keyword in REAL_ESTATE_SALE_HINT_WORDS
    )
# ==========================================

# ==========================================
# 🧮 Python計算関数群
# ==========================================
# ==========================================
# 🧮 計算共通関数
# ==========================================
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union
import calendar
import uuid

Number = Union[int, float, str, Decimal]

def normalize_japanese_number_text(
    value: str
) -> str:
    """
    日本語の金額表記を円単位の数値文字列へ変換する。

    対応例:
        "50,000,000円" -> "50000000"
        "5000万円" -> "50000000"
        "5,000万" -> "50000000"
        "1.5億円" -> "150000000"
        "30%" -> "0.3"

    「億」と「万」を組み合わせた
    「1億5000万円」のような表記にも対応する。
    """
    text = (
        str(value)
        .strip()
        .replace("　", "")
        .replace(" ", "")
        .replace(",", "")
        .replace("￥", "")
        .replace("¥", "")
        .replace("円", "")
    )

    if not text:
        raise ValueError(
            "数値が入力されていません"
        )

    # パーセント表記
    if text.endswith("%"):
        percent_text = text[:-1]

        if not percent_text:
            raise ValueError(
                "パーセントの数値が入力されていません"
            )

        return str(
            Decimal(percent_text)
            / Decimal("100")
        )

    total = Decimal("0")
    remaining_text = text

    # 億単位
    if "億" in remaining_text:
        oku_parts = remaining_text.split("億")

        if len(oku_parts) != 2:
            raise ValueError(
                f"数値形式を解釈できません: {value}"
            )

        oku_text = oku_parts[0]
        remaining_text = oku_parts[1]

        if not oku_text:
            oku_text = "1"

        total += (
            Decimal(oku_text)
            * Decimal("100000000")
        )

    # 万単位
    if "万" in remaining_text:
        man_parts = remaining_text.split("万")

        if len(man_parts) != 2:
            raise ValueError(
                f"数値形式を解釈できません: {value}"
            )

        man_text = man_parts[0]
        remaining_text = man_parts[1]

        if not man_text:
            man_text = "1"

        total += (
            Decimal(man_text)
            * Decimal("10000")
        )

    # 億・万より下の円単位
    if remaining_text:
        total += Decimal(
            remaining_text
        )

    return str(total)


def to_decimal(
    value: Number
) -> Decimal:
    """
    int、float、str、Decimalを
    安全にDecimalへ変換する。

    文字列の場合は、円、万円、億円、
    カンマ、パーセント表記にも対応する。
    """
    if value is None:
        raise ValueError(
            "数値にNoneは指定できません"
        )

    if isinstance(value, Decimal):
        decimal_value = value

    elif isinstance(value, bool):
        raise ValueError(
            "数値にboolは指定できません"
        )

    elif isinstance(value, int):
        decimal_value = Decimal(
            value
        )

    elif isinstance(value, float):
        decimal_value = Decimal(
            str(value)
        )

    elif isinstance(value, str):
        normalized_text = (
            normalize_japanese_number_text(
                value
            )
        )

        decimal_value = Decimal(
            normalized_text
        )

    else:
        raise TypeError(
            "数値はint、float、str、"
            "Decimalのいずれかで指定してください"
        )

    if not decimal_value.is_finite():
        raise ValueError(
            "無限大またはNaNは指定できません"
        )
    return decimal_value

def round_yen(value: Decimal) -> int:
    return int(
        value.quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP
        )
    ) 

def parse_date(
    value: Union[str, date, datetime]
) -> date:
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    return date.fromisoformat(
        str(value).strip()
    )

def add_years_safely(
    original_date: date,
    years: int
) -> date:
    """
    2月29日など、加算先の年に同日が存在しない場合は、
    その月の最終日へ補正する。
    """
    target_year = original_date.year + years
    target_month = original_date.month

    last_day = calendar.monthrange(
        target_year,
        target_month
    )[1]

    target_day = min(
        original_date.day,
        last_day
    )

    return date(
        target_year,
        target_month,
        target_day
    )

# 計算メモの保存期間の計算
def get_case_expiration_date(
    current_plan_type: str
) -> str:

    now = datetime.now(JST)

    if current_plan_type == "🆓 無料プラン":
        expires_at = now + timedelta(days=90)

    else:
        expires_at = now + timedelta(days=365)

    return expires_at.isoformat()

# 計算カテゴリー別のデフォルト名称決定
def get_default_case_name(
    case_type: str,
    property_usage: str = None
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

def make_json_safe(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)

    if isinstance(value, dict):
        return {key: make_json_safe(item) for key, item in value.items()}

    if isinstance(value, list):
        return [make_json_safe(item) for item in value]

    return value

# ==========================================
# DEBUG表示
# ==========================================
DEBUG_MODE = False
# DEBUG_MODE = True
# DEBUG_MODE = (
#     CURRENT_USER_ID
#     == ADMIN_USER_ID
# )
# 管理者：DEBUG表示あり
# テスター：DEBUG表示なし
# 一般ユーザー：DEBUG表示なし

def debug_text(
    title: str,
    value
):
    if not DEBUG_MODE:
        return

    st.write(title, value)


def debug_json(
    title: str,
    data
):
    if not DEBUG_MODE:
        return

    st.write(title)
    st.code(
        json.dumps(
            make_json_safe(data),
            ensure_ascii=False,
            indent=2,
            default=str
        ),
        language="json"
    )

# 計算メモの新規作成
def create_calculation_case(
    case_type: str,
    property_usage: str,
    case_data: dict,
    current_plan_type: str
) -> dict:

    try:
        case_id = (f"case_{uuid.uuid4().hex[:8]}")
        case_name = get_default_case_name(
            case_type=case_type,
            property_usage=property_usage
        )
        now_str = (datetime.now(JST).isoformat())
        case_record = {
            "user_id": CURRENT_USER_ID,
            "case_id": case_id,
            "case_name": case_name,
            "case_type": case_type,
            "case_status": "draft",
            "property_usage": property_usage,
            "case_data": make_json_safe(case_data),
            "created_at": now_str,
            "updated_at": now_str,
            "expires_at": (
                get_case_expiration_date(
                    current_plan_type
                )
            )
        }

        (
            supabase
            .table("calculation_cases")
            .insert(case_record)
            .execute()
        )

        st.session_state["active_calculation_case_id"] = case_id

        return {"success": True, "case_id": case_id}

    except Exception as e:

        st.error(
            f"計算案件作成エラー: "
            f"{type(e).__name__}: {e}"
        )

        print(
            f"計算案件作成エラー: "
            f"{type(e).__name__}: {e}"
        )

        return {"success": False, "case_id": None}

# 計算メモの既存案件の更新処理
def update_calculation_case(
    case_id: str,
    new_case_data: dict,
    case_name: str = None,
    case_status: str = None,
    property_usage: str = None
) -> bool:

    try:

        existing_res = (
            supabase
            .table("calculation_cases")
            .select("case_data")
            .eq("case_id", case_id)
            .limit(1)
            .execute()
        )

        if not existing_res.data:
            return False

        existing_case_data = (
            existing_res.data[0].get("case_data")
            or {}
        )

        merged_case_data = dict(existing_case_data)
        merged_case_data.update(new_case_data)

        # brokerage_feeが存在しない場合は、
        # 既存データの値も削除する
        if "brokerage_fee" not in new_case_data:
            merged_case_data.pop(
                "brokerage_fee",
                None
            )

        # debug_json(
        #     "DEBUG merged_case_data_before_update",
        #     merged_case_data
        # )

        update_data = {
            "case_data": make_json_safe(merged_case_data),
            "updated_at": datetime.now(JST).isoformat()
        }

        if case_name:
            update_data["case_name"] = case_name

        if case_status:
            update_data["case_status"] = case_status

        if property_usage:
            update_data["property_usage"] = property_usage

        (
            supabase
            .table("calculation_cases")
            .update(update_data)
            .eq("case_id", case_id)
            .execute()
        )

        return True

    except Exception as e:

        print(
            f"計算案件更新エラー: "
            f"{type(e).__name__}: {e}"
        )

        return False

# 計算メモの既存候補案件の検索
def get_calculation_case_candidates(
    case_type: str,
    user_input: str,
    limit: int = 5
) -> list:

    try:

        now_str = datetime.now(JST).isoformat()

        response = (
            supabase
            .table("calculation_cases")
            .select(
                "case_id,"
                "case_name,"
                "case_type,"
                "updated_at"
            )
            .eq("user_id", CURRENT_USER_ID)
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
                str(
                    case.get(
                        "case_name",
                        ""
                    )
                )
                .replace(" ", "")
                .replace("　", "")
                .lower()
                in normalized_input
            )
        ]

        return (
            name_matches
            if name_matches
            else candidates
        )

    except Exception as e:

        print(
            f"計算案件候補取得エラー: "
            f"{type(e).__name__}: {e}"
        )

        return []

# 既存案件が選択された場合にデータ読み出し
def get_calculation_case(
    case_id: str
) -> dict:

    try:

        response = (
            supabase
            .table("calculation_cases")
            .select("*")
            .eq("case_id", case_id)
            .limit(1)
            .execute()
        )

        if response.data:
            return response.data[0]

        return {}

    except Exception as e:

        print(
            f"計算案件取得エラー: "
            f"{type(e).__name__}: {e}"
        )

        return {}

# 計算メモの期限切れ案件の削除
def cleanup_expired_calculation_cases() -> int:

    try:

        now_str = datetime.now(JST).isoformat()

        delete_response = (
            supabase
            .table("calculation_cases")
            .delete()
            .lt("expires_at", now_str)
            .execute()
        )

        deleted_count = (
            len(delete_response.data)
            if delete_response.data
            else 0
        )

        return deleted_count

    except Exception as e:

        print(
            f"計算案件整理エラー: "
            f"{type(e).__name__}: {e}"
        )

        return 0

# 計算案件の名称変更
def extract_case_name_change(user_input: str):
    patterns = [
        # 案件名
        r"案件名を(.+?)に変更",
        r"案件名を(.+?)へ変更",
        r"案件名を(.+?)にして",
        r"案件名は(.+?)に変更",
        r"案件名は(.+?)へ変更",
        r"案件名は(.+?)にして",
        
        # 計算案件
        r"計算案件を(.+?)に変更",
        r"計算案件を(.+?)へ変更",
        r"計算案件は(.+?)に変更",
        r"計算案件は(.+?)へ変更",
        
        # 計算メモ
        r"計算メモを(.+?)に変更",
        r"計算メモを(.+?)へ変更",
        r"計算メモは(.+?)に変更",
        r"計算メモは(.+?)へ変更",
        
        # 名称変更
        r"案件名を(.+?)に名称変更",
        r"案件名を(.+?)へ名称変更",
        r"案件名は(.+?)に名称変更",
        r"案件名は(.+?)へ名称変更",
        
        r"計算案件を(.+?)に名称変更",
        r"計算案件を(.+?)へ名称変更",
        r"計算案件は(.+?)に名称変更",
        r"計算案件は(.+?)へ名称変更",
        
        r"計算メモを(.+?)に名称変更",
        r"計算メモを(.+?)へ名称変更",
        r"計算メモは(.+?)に名称変更",
        r"計算メモは(.+?)へ名称変更",
    ]

    for pattern in patterns:
        match = re.search(pattern, user_input)
        if match:
            new_name = (match.group(1).strip())

            # 念のため不要な末尾を除去
            new_name = re.sub(r"(に変更|へ変更|にして)$", "", new_name).strip()

            return new_name

    return None

# ==========================================
# 不動産売却計算 入力項目
# ==========================================

# 売却者区分：owner_type
# individual = 個人
# corporate = 法人

# 不動産用途：property_usage
# owner_occupied = 自宅
# investment = 投資用・賃貸用

# 売却価格：sale_price

# 土地取得費：land_acquisition_cost
# 購入時の土地価格

# 建物取得費：building_acquisition_cost
# 購入時の建物価格

# 建物構造：building_structure
# wood = 木造
# light_steel = 軽量鉄骨
# steel = 鉄骨造
# rc = RC造
# src = SRC造

# 建物取得年月：building_acquisition_date
# 減価償却計算の基準日

# 不動産取得年月：acquisition_date
# 長期譲渡・短期譲渡判定用

# 長期譲渡・短期譲渡：holding_period_type
# long_term = 長期譲渡
# short_term = 短期譲渡

# 購入時諸費用：acquisition_related_costs
# 取得費へ加算する
# 例
# ・購入時仲介手数料
# ・登記費用
# ・司法書士報酬
# ・不動産取得税
# ・購入契約関係費用

# ==========================================
# 任意入力項目
# ==========================================

# 売却時仲介手数料：brokerage_fee
# 未入力なら法定上限額で自動計算

# 譲渡費用：transfer_expenses
# 譲渡所得計算で控除する費用
# 例
# ・解体費
# ・測量費
# ・立退料
# ・売却広告費

# 税計算に含めない支出：other_cash_expenses
# 現金手残りだけ減らす
# 例
# ・抵当権抹消費用
# ・引越費用
# ・その他雑費

# ローン残債：loan_balance
# 現金手残り計算のみで控除

# 特別控除：special_deduction
# 例：居住用3000万円特別控除

# 建物未償却残高・建物簿価：building_tax_basis
# すでに減価償却後の建物金額
# この値がユーザーから明示された場合は、
# 建物取得費に対する減価償却を再計算しない

# ==========================================
# 自動計算項目
# ==========================================

# 建物減価償却累計額：accumulated_depreciation
# 未入力時は自動計算

# 建物簿価：building_tax_basis
# 建物取得費－減価償却累計額

# 実額取得費：actual_acquisition_basis
# 土地取得費
# ＋ 建物簿価
# ＋ 購入時諸費用

# 計算で使用した取得費：applied_acquisition_basis

# 特別控除前譲渡所得：capital_gain_before_deduction

# 課税譲渡所得：taxable_gain

# 税率：tax_rate

# 概算譲渡所得税：estimated_tax

# 税引前現金手残り：cash_before_tax

# 税引後現金手残り：cash_after_tax


# ==========================================
# 🏠 不動産計算
# ==========================================
def determine_individual_holding_type(
    acquisition_date: Union[str, date, datetime],
    sale_date: Union[str, date, datetime]
) -> str:
    """
    個人の土地建物譲渡について、
    売却年1月1日時点の所有期間が
    5年を超えるかで判定する。
    """
    acquired = parse_date(acquisition_date)
    sold = parse_date(sale_date)

    if sold < acquired:
        raise ValueError(
            "sale_dateがacquisition_dateより前です"
        )

    sale_year_start = date(
        sold.year,
        1,
        1
    )

    five_year_anniversary = add_years_safely(
        acquired,
        5
    )

    if five_year_anniversary < sale_year_start:
        return "long_term"

    return "short_term"

def calculate_real_estate_sale(
    *,
    owner_type: str,
    sale_price: Number,
    loan_balance: Number = 0,

    # 土地の税務上の取得費
    land_acquisition_cost: Number = 0,

    # 建物の取得価額と減価償却累計額
    building_acquisition_cost: Number = 0,
    accumulated_depreciation: Number = 0,

    # 建物未償却残高・建物簿価
    # 入力されている場合は減価償却を再計算せず、
    # この金額をそのまま建物の税務上の残高として使用する
    building_tax_basis: Optional[Number] = None,

    # 取得費に含める購入時経費等
    acquisition_related_costs: Number = 0,
    total_acquisition_cost: Number = 0,

    # 仲介手数料
    brokerage_fee: Optional[Number] = None,

    # 売却のために直接要した譲渡費用
    transfer_expenses: Number = 0,

    # 抵当権抹消など、現金手残りから控除する費用
    other_cash_expenses: Number = 0,

    # 個人の場合に使用
    acquisition_date: Optional[Union[str, date, datetime]] = None,
    sale_date: Optional[Union[str, date, datetime]] = None,

    holding_period_type: Optional[str] = None,

    # 該当する特例が確認できている場合のみ入力
    special_deduction: Number = 0,

    # 法人の場合のみ任意指定
    corporate_effective_tax_rate: Optional[Number] = None,

    # 取得費不明時の概算取得費を利用する場合
    use_deemed_acquisition_cost: bool = False,

    # 概算取得費率。通常は売却価額の5%
    deemed_acquisition_cost_rate: Number = "0.05"
    ) -> dict:
    """
    不動産売却の概算計算。

    owner_type:
        "individual" または "corporate"

    注意:
    ・個人の通常の土地建物譲渡を想定。
    ・法人税額は会社全体の所得等に左右されるため、
      実効税率が指定された場合だけ概算する。
    ・消費税、特例、損益通算、欠損金、圧縮記帳等は
      この関数では自動判定しない。
    """

    owner_type = owner_type.strip().lower()

    if owner_type not in {
        "individual",
        "corporate"
    }:
        raise ValueError("owner_typeはindividualまたはcorporateを指定してください")

    sale_price_d = to_decimal(sale_price)
    loan_balance_d = to_decimal(loan_balance)

    land_cost_d = to_decimal(land_acquisition_cost)
    building_cost_d = to_decimal(building_acquisition_cost)
    depreciation_d = to_decimal(accumulated_depreciation)
    acquisition_costs_d = to_decimal(acquisition_related_costs)
    transfer_expenses_d = to_decimal(transfer_expenses)

    # 仲介手数料が未入力なら法定上限額で試算
    if brokerage_fee is None:
        brokerage_fee_d = (sale_price_d * Decimal("0.03") + Decimal("60000")) * Decimal("1.10")
        brokerage_fee_method = ("statutory_max_estimate")
    else:
        brokerage_fee_d = to_decimal(brokerage_fee)
        brokerage_fee_method = ("specified")

    other_cash_expenses_d = to_decimal(other_cash_expenses)
    special_deduction_d = to_decimal(special_deduction)

    validation_values = {
        "sale_price": sale_price_d,
        "loan_balance": loan_balance_d,
        "land_acquisition_cost": land_cost_d,
        "building_acquisition_cost": building_cost_d,
        "accumulated_depreciation": depreciation_d,
        "acquisition_related_costs": acquisition_costs_d,
        "brokerage_fee": brokerage_fee_d,
        "transfer_expenses": transfer_expenses_d,
        "other_cash_expenses": other_cash_expenses_d,
        "special_deduction": special_deduction_d
    }
    
    for field_name, field_value in validation_values.items():
        if field_value < 0:
            raise ValueError(
                f"{field_name}は0以上にしてください"
            )

    if depreciation_d > building_cost_d:
        raise ValueError(
            "減価償却累計額が建物取得価額を超えています"
        )

    # 建物の税務上の未償却残高
    if building_tax_basis is not None:
        # ユーザーが建物未償却残高・建物簿価を明示した場合
        # すでに減価償却後の金額なので再計算しない
        building_tax_basis_d = to_decimal(
            building_tax_basis
        )

        if building_tax_basis_d < Decimal("0"):
            raise ValueError(
                "building_tax_basisは0以上にしてください"
            )

    else:
        # 建物未償却残高が未入力の場合だけ、
        # 建物取得価額から減価償却累計額を差し引く
        building_tax_basis_d = (
            building_cost_d
            - depreciation_d
        )

    total_acquisition_cost_d = to_decimal(total_acquisition_cost)
    if total_acquisition_cost_d > Decimal("0"):
        actual_acquisition_basis = (total_acquisition_cost_d)
    else:
        actual_acquisition_basis = (
            land_cost_d
            + building_tax_basis_d
            + acquisition_costs_d
        )

    deemed_rate_d = to_decimal(
        deemed_acquisition_cost_rate
    )
    if not (
        Decimal("0")
        <= deemed_rate_d
        <= Decimal("1")
    ):
        raise ValueError(
            "deemed_acquisition_cost_rateは"
            "0から1の範囲で指定してください"
        )

    # 取得費不明時などに使う概算取得費
    deemed_acquisition_basis = (
        sale_price_d
        * deemed_rate_d
    )

    if use_deemed_acquisition_cost:
        acquisition_basis = (
            deemed_acquisition_basis
        )
        acquisition_basis_method = (
            "deemed_5_percent"
        )
    else:
        acquisition_basis = (
            actual_acquisition_basis
        )
        acquisition_basis_method = "actual"

    # 特別控除前の譲渡損益
    capital_gain_before_deduction = (
        sale_price_d
        - acquisition_basis
        - brokerage_fee_d
        - transfer_expenses_d
    )

    # 特別控除は譲渡益を超えて控除しない
    applied_special_deduction = min(
        max(
            special_deduction_d,
            Decimal("0")
        ),
        max(
            capital_gain_before_deduction,
            Decimal("0")
        )
    )

    taxable_gain = max(
        capital_gain_before_deduction
        - applied_special_deduction,
        Decimal("0")
    )

    holding_type = None
    tax_rate = None
    estimated_tax = None
    tax_calculation_status = None

    if owner_type == "individual":
        if sale_date is not None:
            holding_type = (
                determine_individual_holding_type(
                    acquisition_date,
                    sale_date
                )
            )

        elif holding_period_type in {"long_term", "short_term"}:
            holding_type = holding_period_type

        else:
            holding_type = None

        if holding_type == "long_term":
            tax_rate = Decimal("0.20315")
        else:
            tax_rate = Decimal("0.3963")

        estimated_tax = (
            taxable_gain
            * tax_rate
        )

        tax_calculation_status = (
            "individual_estimated"
        )

    else:
        if corporate_effective_tax_rate is None:
            tax_calculation_status = (
                "corporate_tax_not_calculated"
            )
        else:
            tax_rate = to_decimal(
                corporate_effective_tax_rate
            )

            if not (
                Decimal("0")
                <= tax_rate
                <= Decimal("1")
            ):
                raise ValueError(
                    "corporate_effective_tax_rateは"
                    "0から1の範囲で指定してください"
                )

            estimated_tax = (
                taxable_gain
                * tax_rate
            )

            tax_calculation_status = (
                "corporate_effective_rate_estimate"
            )

    # 税引前の現金手残り
    cash_before_tax = (
        sale_price_d
        - loan_balance_d
        - brokerage_fee_d
        - transfer_expenses_d
        - other_cash_expenses_d
    )

    # 税額を計算できる場合だけ税引後を算出
    if estimated_tax is None:
        cash_after_tax = None
    else:
        cash_after_tax = (
            cash_before_tax
            - estimated_tax
        )

    return {
        "owner_type": owner_type,
        "holding_type": holding_type,
        "acquisition_basis_method": acquisition_basis_method,
        "sale_price": round_yen(sale_price_d),
        "loan_balance": round_yen(loan_balance_d),
        "land_acquisition_cost": round_yen(land_cost_d),
        "building_acquisition_cost": round_yen(building_cost_d),
        "accumulated_depreciation": round_yen(depreciation_d),
        "building_tax_basis": round_yen(building_tax_basis_d),
        "acquisition_related_costs": round_yen(acquisition_costs_d),
        "brokerage_fee": round_yen(brokerage_fee_d),
        "brokerage_fee_method": brokerage_fee_method,
        "actual_acquisition_basis": round_yen(actual_acquisition_basis),
        "deemed_acquisition_basis": round_yen(deemed_acquisition_basis),
        "applied_acquisition_basis": round_yen(acquisition_basis),
        "transfer_expenses": round_yen(transfer_expenses_d),
        "other_cash_expenses": round_yen(other_cash_expenses_d),
        "capital_gain_before_deduction": round_yen(capital_gain_before_deduction),
        "special_deduction": round_yen(applied_special_deduction),
        "taxable_gain": round_yen(taxable_gain),
        "tax_rate": (
            float(tax_rate)
            if tax_rate is not None
            else None
        ),
        "estimated_tax": (
            round_yen(estimated_tax)
            if estimated_tax is not None
            else None
        ),
        "cash_before_tax": round_yen(cash_before_tax),
        "cash_after_tax": (
            round_yen(cash_after_tax)
            if cash_after_tax is not None
            else None
        ),
        "tax_calculation_status": tax_calculation_status
    }

# ==========================================
# 🏠 不動産売却計算 呼び出し判定
# ==========================================

def extract_real_estate_sale_parameters(
    user_input: str,
    recent_history: str = "",
    calculation_pending: bool = False
) -> dict:
    """
    ユーザーの最新発言と直近履歴から、
    不動産売却計算に必要な条件をJSONで抽出する。

    この関数の役割:
    ・不動産売却計算の対象か判定する
    ・ユーザーが明示した条件だけを抽出する
    ・Geminiには計算させない
    ・金額や日付を推測させない

    正規化、不足項目判定、Python計算は、
    execute_real_estate_sale_calculation()側で行う。
    """

    default_result = {
        "should_calculate": False,
        "arguments": {},
        "extraction_status": "not_applicable",
        "in_tokens": 0,
        "out_tokens": 0,
        "cost": 0.0
    }

    if not user_input:
        return default_result

    extraction_prompt = f"""
    あなたは、不動産売却計算に必要な入力条件を
    構造化して抽出するシステムです。

    最新のユーザー発言と直近の会話から、
    calculate_real_estate_sale関数へ渡す条件を
    JSON形式で抽出してください。

    【最重要ルール】
    ・計算は行わないでください。
    ・ユーザーが明示していない情報を推測しないでください。
    ・一般的な費用、一般的な税率、一般的な日付を補完しないでください。
    ・AIが過去に推測した内容を、ユーザーが話した事実として使用しないでください。
    ・argumentsには、最新のユーザー発言で明示された条件だけを設定してください。
    ・直近の会話は発言の意味を理解するためだけに使用し、過去の金額、日付、構造、条件をargumentsへ再出力してはいけません。
    ・過去に確認済みの条件はPython側で保持するため、抽出処理では引き継いではいけません。
    ・条件が変更されている場合は、最新の条件を優先してください。
    ・値が確認できない項目はnullにしてください。
    ・キーを省略しないでください。
    ・JSON以外の説明文を出力しないでください。
    ・コードブロックの囲み記号を付けないでください。

    【金額の扱い】
    ・万円または億円の表記は、円単位の整数へ変換してください。
    ・5,000万円は50000000です。
    ・1.5億円は150000000です。
    ・1億5000万円は150000000です。
    ・金額が曖昧な場合はnullにしてください。

    【仲介手数料】
    ・ユーザーが仲介手数料の金額を明示した場合は、brokerage_feeへ円単位の整数で設定してください。
    ・ユーザーが仲介手数料の金額を明示していない場合は、brokerage_feeをnullにしてください。
    ・仲介手数料を自動計算する場合でも、AI側で計算してはいけません。nullのまま出力し、Python側の計算に任せてください。
    ・仲介手数料が不要または0円と明示された場合は、brokerage_feeを0にしてください。
    ・ユーザーが「仲介手数料は自動計算」、「仲介手数料を自動で」、「仲介手数料は計算して」などと明示した場合は、brokerage_fee を null にしてください。

    【取得費】
    ・次の表現は total_acquisition_cost として扱ってください。
        - 取得費
        - 総取得費
        - 合算簿価
        - 購入経費込の取得費

    例
    取得費: ○○円、総取得費: ○○円、合算簿価: ○○円
    ↓
    total_acquisition_costに設定してください。

    【建物取得価額】
    ・建物購入価格、建物取得額、建物価格は、building_acquisition_cost に設定してください。
    ・建物購入価格を、building_original_cost や total_acquisition_cost に設定してはいけません。
    ・total_acquisition_cost は、土地と建物などを合算した取得費総額が明示された場合だけ設定してください。

    【建物未償却残高・建物簿価】
    ・次の表現は building_tax_basis に設定してください。
    - 建物未償却残高
    - 建物の未償却残高
    - 建物簿価
    - 建物の簿価
    - 減価償却後の建物残高
    ・building_tax_basis は、すでに減価償却後の建物金額です。
    ・building_tax_basis を building_acquisition_cost に設定してはいけません。
    ・building_tax_basis を total_acquisition_cost に設定してはいけません。
    ・建物取得価額と建物未償却残高を混同してはいけません。

    【不動産用途】
    次の表現は property_usage として扱ってください。
    ・自宅
    ・居住用
    ・マイホーム
    ・自宅マンション
    → owner_occupied

    ・投資用
    ・投資用マンション
    ・収益物件
    ・賃貸用
    ・一棟マンション
    ・一棟アパート
    ・アパート経営
    ・マンション経営
    → investment

    用途が不明な場合は null にしてください。

    【重要】
    ・取得費が明示されている場合は、acquisition_related_costs を 0 や null にしてはいけません。
    ・土地取得費や建物取得費が不明であっても、総取得費や合算簿価が提示されている場合はacquisition_related_costs に設定してください。

    【税率の扱い】
    ・パーセントは0から1の小数へ変換してください。
    ・30%は0.30です。
    ・税率が明示されていない場合はnullにしてください。

    【日付の扱い】
    ・日付はYYYY-MM-DD形式にしてください。
    ・取得日、売却日については、年月まで分かる場合は月初日を補完してください。
    例
    2015年8月
    ↓
    2015-08-01

    2020年3月
    ↓
    2020-03-01

    ・取得年、売却年しか分からない場合はその年の1月1日を補完してください。
    例
    2015年
    ↓
    2015-01-01

    2027年
    ↓
    2027-01-01

    ・取得日または売却日が完全に不明な場合のみ null にしてください。
    ・「売却日は未定」「これから売る予定」のような表現で年月も分からない場合は null にしてください。
    ・ローン残債の基準日、返済日、借入残高の時点日、残高確認日などの日時は売却日として扱ってはいけません。
    ・sale_date に設定してよいのは、売却日であることが明示されている場合だけです。単に日付が出てきただけではsale_date に設定してはいけません。

    【保有期間区分】
    ・ユーザーが長期譲渡または5年超と明示した場合は、holding_period_typeをlong_termにしてください。
    ・ユーザーが短期譲渡または5年以下と明示した場合は、holding_period_typeをshort_termにしてください。
    ・取得日と売却日の両方が確認できる場合は、譲渡した年の1月1日時点の所有期間に基づいて判定してください。
    ・取得日または売却日が不明で、長期譲渡か短期譲渡かも明示されていない場合は、holding_period_typeをnullにしてください。
    ・日付が不明な場合に、長期または短期を推測してはいけません。

    【所有者区分】
    ・個人所有または個人名義の場合はindividualです。
    ・法人所有、会社所有または法人名義の場合はcorporateです。
    ・個人か法人か分からない場合はnullにしてください。

    【概算取得費】
    ・ユーザーが取得費不明として売却額の5%を使うことを明示した場合だけ、
    use_deemed_acquisition_costをtrueにしてください。
    ・ユーザーが明示していない場合はfalseにしてください。
    ・概算取得費率を明示していない場合は、
    deemed_acquisition_cost_rateをnullにしてください。

    【特別控除】
    ・ユーザーが適用する特別控除額を明示した場合だけ抽出してください。
    ・居住用不動産だからという理由だけで、
    3,000万円控除を自動適用してはいけません。
    ・適用の確認が取れていない場合はnullにしてください。

    【建物構造】
    次の表現は building_structure として扱ってください。

    ・木造 → wood
    ・軽量鉄骨造 → light_steel
    ・鉄骨造 → steel
    ・RC造 → rc
    ・SRC造 → src

    構造が不明な場合は null にしてください。


    【不動産売却計算に該当しない場合】
    ・should_calculateをfalseにしてください。
    ・argumentsの各値はnullにしてください。

    【現在の計算状態】
    不動産売却計算継続中: {calculation_pending}

    【計算継続中のルール】
    不動産売却計算継続中がTrueの場合、最新のユーザー発言は、不足項目への回答として優先的に解釈してください。
    以下のような発言は、不動産売却計算対象として扱い、should_calculate を true にしてください。

    ・金額のみの回答
    ・土地取得費
    ・建物取得費
    ・購入時諸費用
    ・建物構造
    ・取得年月
    ・取得日
    ・売却日
    ・長期譲渡
    ・短期譲渡

    計算継続中の場合は、単独では不動産売却に見えない短文でも、不足項目への回答として解釈してください。

    例
    木造 → building_structure = "wood"
    RC造 → building_structure = "rc"
    2018年購入 → building_acquisition_date
    8年前に購入 → building_acquisition_date
    長期譲渡 → holding_period_type = "long_term"
    短期譲渡 → holding_period_type = "short_term"

    【会話の継続ルール】
    直近の会話で不動産売却計算を行っており、「長期譲渡で計算して」「短期譲渡で計算して」のような回答があった場合は、should_calculate を true にしてください。
    その場合、holding_period_type を設定し、他の条件は直近の会話から引き継ぐ前提でarguments に null を入れて構いません。

    【直近の会話】
    {recent_history}

    【最新ユーザー発言】
    {user_input}

    【出力形式】
    {{
        "should_calculate": true,
        "arguments": {{
            "owner_type": null,
            "sale_price": null,
            "property_usage": null,
            "loan_balance": null,
            "land_acquisition_cost": null,
            "building_acquisition_cost": null,
            "building_tax_basis": null,
            "building_structure": null,
            "building_acquisition_date": null,
            "accumulated_depreciation": null,
            "acquisition_related_costs": null,
            "total_acquisition_cost": null,
            "brokerage_fee": null,
            "transfer_expenses": null,
            "other_cash_expenses": null,
            "acquisition_date": null,
            "sale_date": null,
            "holding_period_type": null,
            "special_deduction": null,
            "corporate_effective_tax_rate": null,
            "use_deemed_acquisition_cost": false,
            "deemed_acquisition_cost_rate": null
        }}
    }}
    """

    try:
        # extraction_model = genai.GenerativeModel(
        #     model_name=SEARCH_MODEL_NAME
        # )

        # extraction_response = (
        #     extraction_model.generate_content(
        #         extraction_prompt,
        #         generation_config={
        #             "temperature": 0,
        #             "max_output_tokens": 500,
        #             "response_mime_type":
        #                 "application/json"
        #         }
        #     )
        # )
        extraction_result = generate_ai_response(
            provider=BACKGROUND_PROVIDER,
            system_instruction="",
            user_prompt=extraction_prompt,
            response_format_json=True,
            model_name=SEARCH_MODEL_NAME
        )

        # raw_text = str(
        #     extraction_response.text
        #     or ""
        # ).strip()
        raw_text = str(extraction_result.get("text", "") or "").strip()

        if not raw_text:
            raise ValueError(
                "不動産売却条件の抽出結果が空です"
            )

        clean_text = (
            raw_text
            .replace("```json", "")
            .replace("```JSON", "")
            .replace("```", "")
            .strip()
        )

        extracted_data = json.loads(
            clean_text
        )

        if not isinstance(
            extracted_data,
            dict
        ):
            raise ValueError(
                "不動産売却条件の抽出結果が"
                "object形式ではありません"
            )

        should_calculate = bool(
            extracted_data.get(
                "should_calculate",
                False
            )
        )

        raw_arguments = (
            extracted_data.get(
                "arguments",
                {}
            )
        )

        if not isinstance(
            raw_arguments,
            dict
        ):
            raw_arguments = {}

        # in_tokens = 0
        # out_tokens = 0

        # if (
        #     hasattr(
        #         extraction_response,
        #         "usage_metadata"
        #     )
        #     and
        #     extraction_response.usage_metadata
        # ):
        #     in_tokens = int(
        #         extraction_response
        #         .usage_metadata
        #         .prompt_token_count
        #         or 0
        #     )

        #     out_tokens = int(
        #         extraction_response
        #         .usage_metadata
        #         .candidates_token_count
        #         or 0
        #     )
        in_tokens = int(extraction_result.get("in_tokens", 0) or 0)
        out_tokens = int(extraction_result.get("out_tokens", 0) or 0)
        # extraction_cost = (in_tokens * PRICE_BACKGROUND_IN + out_tokens * PRICE_BACKGROUND_OUT)
        extraction_cost = calculate_ai_cost(
            provider=BACKGROUND_PROVIDER,
            in_tokens=in_tokens,
            out_tokens=out_tokens
        )

        if not should_calculate:
            return {
                "should_calculate": False,
                "arguments": {},
                "extraction_status":
                    "not_applicable",
                "in_tokens": in_tokens,
                "out_tokens": out_tokens,
                "cost": extraction_cost
            }

        return {
            "should_calculate": True,
            "arguments": raw_arguments,
            "extraction_status": "extracted",
            "in_tokens": in_tokens,
            "out_tokens": out_tokens,
            "cost": extraction_cost
        }

    except (
        json.JSONDecodeError,
        ValueError,
        TypeError
    ) as extraction_error:
        print(
            "不動産売却条件の抽出エラー: "
            f"{type(extraction_error).__name__}: "
            f"{extraction_error}"
        )

        return {
            "should_calculate": True,
            "arguments": {},
            "extraction_status":
                "extraction_error",
            "in_tokens": 0,
            "out_tokens": 0,
            "cost": 0.0
        }

    except Exception as unexpected_error:
        print(
            "不動産売却条件抽出の予期しないエラー: "
            f"{type(unexpected_error).__name__}: "
            f"{unexpected_error}"
        )

        return {
            "should_calculate": True,
            "arguments": {},
            "extraction_status":
                "extraction_error",
            "in_tokens": 0,
            "out_tokens": 0,
            "cost": 0.0
        }

ACQUISITION_COMPONENT_FIELDS = {
    "land_acquisition_cost",
    "building_acquisition_cost",
    "acquisition_related_costs"
}

CONFIRMABLE_FIELDS = {
    "land_acquisition_cost",
    "building_acquisition_cost",
    "acquisition_related_costs",
}

REAL_ESTATE_SALE_ALLOWED_FIELDS = {
    "owner_type",
    "property_usage",
    "sale_price",
    "loan_balance",
    "loan_balance_confirmed",
    "land_acquisition_cost",
    "building_acquisition_cost",
    "building_tax_basis",
    "building_structure",
    "building_acquisition_date",
    "accumulated_depreciation",
    "acquisition_related_costs",
    "total_acquisition_cost",
    "brokerage_fee",
    "transfer_expenses",
    "other_cash_expenses",
    "acquisition_date",
    "sale_date",
    "holding_period_type",
    "special_deduction",
    "corporate_effective_tax_rate",
    "use_deemed_acquisition_cost",
    "deemed_acquisition_cost_rate"
}| {
    f"{field}_confirmed"
    for field in ACQUISITION_COMPONENT_FIELDS
}

REAL_ESTATE_NUMERIC_FIELDS = {
    "sale_price",
    "loan_balance",
    "land_acquisition_cost",
    "building_acquisition_cost",
    "building_tax_basis",
    "accumulated_depreciation",
    "acquisition_related_costs",
    "total_acquisition_cost",
    "brokerage_fee",
    "transfer_expenses",
    "other_cash_expenses",
    "special_deduction",
    "corporate_effective_tax_rate",
    "deemed_acquisition_cost_rate"
}

REAL_ESTATE_DATE_FIELDS = {
    "acquisition_date",
    "sale_date",
    "building_acquisition_date"
}

BUILDING_USEFUL_LIFE = {
    "wood": 22,
    "light_steel": 19,
    "steel": 34,
    "rc": 47,
    "src": 47
}

NON_BUSINESS_DEPRECIATION_RATE = {
    "wood": Decimal("0.031"),
    "light_steel": Decimal("0.036"),
    "steel": Decimal("0.025"),
    "rc": Decimal("0.015"),
    "src": Decimal("0.015")
}

# 建物未償却残高と理論簿価の差異警告基準
# 100万円を超える差異がある場合に警告する
BUILDING_TAX_BASIS_WARNING_THRESHOLD = Decimal("1000000")

def calculate_building_depreciation(
    building_original_cost,
    building_structure,
    building_acquisition_date,
    property_usage
) -> dict:

    original_cost = to_decimal(building_original_cost)

    useful_life = Decimal(BUILDING_USEFUL_LIFE[building_structure])

    acquired_date = parse_date(building_acquisition_date)

    today = datetime.now(JST).date()

    elapsed_days = (today - acquired_date).days

    elapsed_years = Decimal(str(elapsed_days / 365.25))

    if property_usage == "owner_occupied":
        depreciation_rate = NON_BUSINESS_DEPRECIATION_RATE[building_structure]
        accumulated_depreciation = (
            original_cost
            * Decimal("0.9")
            * depreciation_rate
            * elapsed_years
        )
        accumulated_depreciation = min(accumulated_depreciation, original_cost * Decimal("0.95"))

    else:
        annual_depreciation = (original_cost / useful_life)
        accumulated_depreciation = min(annual_depreciation * elapsed_years, original_cost)

    building_tax_basis = (original_cost - accumulated_depreciation)

    return {
        "accumulated_depreciation":round_yen(accumulated_depreciation),
        "building_tax_basis":round_yen(building_tax_basis)
    }

def normalize_real_estate_sale_arguments(
    arguments: dict,
    apply_defaults: bool = True
) -> dict:
    """
    Geminiが抽出した不動産売却計算用の引数を、
    calculate_real_estate_sale()へ安全に渡せる形へ整える。

    処理内容:
    ・許可されていないキーを除外
    ・null、空文字、不明表記を除外
    ・owner_typeをindividualまたはcorporateへ統一
    ・金額や税率をDecimalへ変換
    ・日付をYYYY-MM-DD形式へ統一
    ・真偽値をboolへ統一
    """
    if not isinstance(arguments, dict):
        raise TypeError(
            "argumentsはdict形式で指定してください"
        )

    normalized = {}

    ignored_values = {
        "",
        "null",
        "none",
        "不明",
        "未指定",
        "わからない",
        "分からない",
        "不詳"
    }

    for key, value in arguments.items():
        # calculate_real_estate_sale()に存在しない
        # 余分な引数は渡さない
        if key not in REAL_ESTATE_SALE_ALLOWED_FIELDS:
            continue

        # JSONのnullは未入力として扱う
        if value is None:
            continue

        # 空文字や不明表記も未入力として扱う
        if isinstance(value, str):
            cleaned_value = value.strip()

            if cleaned_value.lower() in ignored_values:
                continue

            value = cleaned_value

        # 個人・法人区分
        if key == "owner_type":
            owner_text = str(
                value
            ).strip().lower()

            owner_type_mapping = {
                "individual": "individual",
                "個人": "individual",
                "個人所有": "individual",
                "個人名義": "individual",
                "personal": "individual",

                "corporate": "corporate",
                "法人": "corporate",
                "法人所有": "corporate",
                "法人名義": "corporate",
                "会社": "corporate",
                "company": "corporate"
            }

            normalized_owner_type = (
                owner_type_mapping.get(
                    owner_text
                )
            )

            # 想定外の値は保存せず、
            # 後続の不足項目判定へ回す
            if normalized_owner_type is not None:
                normalized["owner_type"] = normalized_owner_type

            continue
            
        if key == "holding_period_type":

            holding_text = str(value).strip().lower()

            if holding_text in {
                "long_term",
                "長期",
                "長期譲渡",
                "5年超"
            }:
                normalized[key] = "long_term"

            elif holding_text in {
                "short_term",
                "短期",
                "短期譲渡",
                "5年以下"
            }:
                normalized[key] = "short_term"
            continue
        
        if key == "property_usage":
            property_usage_text = str(value).strip().lower()
            property_usage_mapping = {
                "owner_occupied": "owner_occupied",
                "自宅": "owner_occupied",
                "自宅用": "owner_occupied",
                "居住用": "owner_occupied",
                "マイホーム": "owner_occupied",
                "investment": "investment",
                "投資用": "investment",
                "賃貸用": "investment",
                "収益物件": "investment"
            }
            normalized_property_usage = property_usage_mapping.get(
                property_usage_text
            )
            if normalized_property_usage is not None:
                normalized["property_usage"] = normalized_property_usage
            continue

        # 金額、取得費率、法人実効税率
        if key in REAL_ESTATE_NUMERIC_FIELDS:
            try:
                normalized[
                    key
                ] = to_decimal(
                    value
                )

            except (
                ValueError,
                TypeError,
                ArithmeticError
            ):
                # 読み取れない数値は入れず、
                # 後続処理または計算エラーで確認する
                continue

            continue

        # 取得日・売却日
        if key in REAL_ESTATE_DATE_FIELDS:
            try:
                normalized_date = parse_date(
                    value
                )

                normalized[
                    key
                ] = normalized_date.isoformat()

            except (
                ValueError,
                TypeError
            ):
                # 年だけ、年月だけ、存在しない日付などは
                # 推測せず未入力として扱う
                continue

            continue

        # 概算取得費を使用するか
        if key == "use_deemed_acquisition_cost":
            if isinstance(value, bool):
                normalized[
                    key
                ] = value

                continue

            boolean_text = str(
                value
            ).strip().lower()

            true_values = {
                "true",
                "1",
                "yes",
                "y",
                "使用する",
                "使う",
                "利用する",
                "はい"
            }

            false_values = {
                "false",
                "0",
                "no",
                "n",
                "使用しない",
                "使わない",
                "利用しない",
                "いいえ"
            }

            if boolean_text in true_values:
                normalized[
                    key
                ] = True

            elif boolean_text in false_values:
                normalized[
                    key
                ] = False

            # 解釈できない場合は推測せず除外
            continue
    
        normalized[key] = value

    # 計算実行時だけ任意項目へ安全な初期値を設定
    if apply_defaults:
        normalized.setdefault(
            "loan_balance",
            Decimal("0")
        )

        normalized.setdefault(
            "total_acquisition_cost",
            Decimal("0")
        )

        normalized.setdefault(
            "transfer_expenses",
            Decimal("0")
        )

        normalized.setdefault(
            "other_cash_expenses",
            Decimal("0")
        )

        normalized.setdefault(
            "special_deduction",
            Decimal("0")
        )

        normalized.setdefault(
            "use_deemed_acquisition_cost",
            False
        )

        normalized.setdefault(
            "deemed_acquisition_cost_rate",
            Decimal("0.05")
        )

    return normalized

REAL_ESTATE_FIELD_LABELS = {
    "owner_type": "売却者が個人か法人か",
    "sale_price": "売却予定額または売却額",
    "loan_balance": "ローン残債（無ければ0円）",
    "land_acquisition_cost": "土地の取得価額（土地がない場合は0円）",
    "building_acquisition_cost": "建物の取得価額（建物がない場合は0円）",
    "building_tax_basis": "建物未償却残高または建物簿価",
    "acquisition_related_costs": "購入時諸費用（仲介手数料・登記費用・不動産取得税など）",
    "building_structure": "建物構造",
    "building_acquisition_date": "建物取得年月",
    "acquisition_date": "取得日",
    "sale_date": "売却日",
    "holding_period_type": "長期譲渡か短期譲渡か",
    "acquisition_basis":("税務上の取得費" "（土地・建物の取得価額など）"),
    "accumulated_depreciation":"建物の減価償却累計額",
    "corporate_effective_tax_rate":("法人の概算実効税率" "（税引後手残りも計算する場合）"),
    "brokerage_fee": "仲介手数料",
    "property_usage": "物件用途",
    "transfer_expenses": "譲渡費用",
    "use_deemed_acquisition_cost": "概算取得費を使用するか",
    "total_acquisition_cost": "総取得費",
}

def get_real_estate_sale_missing_fields(
    arguments: dict
) -> list:
    """
    不動産売却計算に必要な条件の不足を判定する。

    必須条件:
    ・所有者区分
    ・売却額
    ・個人の場合は取得日と売却日

    取得費:
    ・実額取得費を使う場合は、土地取得費または
      建物取得価額の少なくとも一方が必要
    ・取得費不明として概算取得費を使う場合は不要

    建物:
    ・建物取得価額が0円より大きく、
      減価償却累計額が明示されていない場合は確認対象

    法人:
    ・実効税率がなくても税引前手残りは計算可能
    ・したがって法人実効税率は必須項目にしない
    """
    if not isinstance(arguments, dict):
        raise TypeError(
            "argumentsはdict形式で指定してください"
        )

    missing_fields = []

    owner_type = arguments.get(
        "owner_type"
    )

    if owner_type not in {
        "individual",
        "corporate"
    }:
        missing_fields.append(
            "owner_type"
        )

    sale_price = arguments.get(
        "sale_price"
    )

    if sale_price is None:
        missing_fields.append(
            "sale_price"
        )
    else:
        try:
            if to_decimal(
                sale_price
            ) <= Decimal("0"):
                missing_fields.append(
                    "sale_price"
                )
        except (
            ValueError,
            TypeError,
            ArithmeticError
        ):
            missing_fields.append(
                "sale_price"
            )

    if owner_type == "individual":
        acquisition_date = arguments.get("acquisition_date")
        sale_date = arguments.get("sale_date")
        holding_period_type = arguments.get("holding_period_type")
        dates_are_complete = bool(acquisition_date and sale_date)
        holding_type_is_valid = (holding_period_type in {"long_term", "short_term"})
        if (not dates_are_complete and not holding_type_is_valid):
            missing_fields.append("holding_period_type")

    loan_balance_confirmed = bool(
        arguments.get(
            "loan_balance_confirmed",
            False
        )
    )

    if not loan_balance_confirmed:
        missing_fields.append(
            "loan_balance"
        )

    use_deemed_acquisition_cost = bool(
        arguments.get(
            "use_deemed_acquisition_cost",
            False
        )
    )

    if not use_deemed_acquisition_cost:
        total_acquisition_cost = to_decimal(arguments.get("total_acquisition_cost",Decimal("0")))

        if total_acquisition_cost <= Decimal("0"):
            for field in CONFIRMABLE_FIELDS:
                field_is_provided = False
                if (
                    field in arguments
                    and arguments.get(field) is not None
                ):
                    try:
                        field_amount = to_decimal(
                            arguments.get(field)
                        )
                        if field == "loan_balance":
                            field_is_provided = bool(
                                arguments.get(
                                    "loan_balance_confirmed",
                                    False
                                )
                            )
                        else:
                            field_is_provided = (
                                field_amount > Decimal("0")
                                or bool(
                                    arguments.get(
                                        f"{field}_confirmed",
                                        False
                                    )
                                )
                            )
                    except (
                        ValueError,
                        TypeError,
                        ArithmeticError
                    ):
                        field_is_provided = False
                
                if not field_is_provided:
                    missing_fields.append(field)

    building_cost = to_decimal(arguments.get("building_acquisition_cost",Decimal("0")))

    if (
        building_cost > Decimal("0")
        and "accumulated_depreciation"
        not in arguments
    ):

        building_original_cost = to_decimal(arguments.get("building_acquisition_cost", Decimal("0")))
        building_structure = arguments.get("building_structure")
        building_acquisition_date = arguments.get("building_acquisition_date")

        can_auto_calculate = (
            building_original_cost > Decimal("0")
            and building_structure
            and building_acquisition_date
        )

        if not can_auto_calculate:
            if (building_original_cost <= Decimal("0")):
                missing_fields.append("building_original_cost")
            if not building_structure: missing_fields.append("building_structure")
            if not building_acquisition_date: missing_fields.append("building_acquisition_date")

    # 重複を除き、追加順を維持
    return list(dict.fromkeys(missing_fields))

# 計算の不足条件項目の表示関数
def format_missing_fields_message(
    case_name: str,
    current_arguments: dict,
    missing_fields: list
) -> str:

    # debug_json(
    #     "DEBUG format_missing_fields_message_current_arguments",
    #     current_arguments
    # )

    missing_labels = [
        REAL_ESTATE_FIELD_LABELS.get(
            field,
            field
        )
        for field in missing_fields
    ]

    entered_conditions = []

    for key, value in current_arguments.items():

        if value is None:
            continue

        if key.endswith("_confirmed"):
            continue

        label = REAL_ESTATE_FIELD_LABELS.get(
            key,
            key
        )

        # 表示用変換
        if key == "owner_type":

            if value == "individual":
                value = "個人"

            elif value == "corporate":
                value = "法人"

        elif key == "holding_period_type":

            if value == "long_term":
                value = "長期譲渡所得"

            elif value == "short_term":
                value = "短期譲渡所得"
        
        elif key == "property_usage":

            if value == "investment":
                value = "投資用"

            elif value == "owner_occupied":
                value = "自宅"
        
        elif key == "use_deemed_acquisition_cost":
            value = (
                "使用する"
                if bool(value)
                else "使用しない"
            )
        
        elif key in REAL_ESTATE_NUMERIC_FIELDS:
            try:
                value = (
                    f"{int(value):,}円"
                )
            except Exception:
                pass

        elif isinstance(
            value,
            (int, float)
        ):
            try:
                value = f"{int(value):,}"
            except Exception:
                pass

        entered_conditions.append(
            f"・{label}: {value}"
        )

    entered_text = (
        "\n".join(entered_conditions)
        if entered_conditions
        else "なし"
    )

    missing_text = "\n".join(
        f"・{label}"
        for label in missing_labels
    )

    return (
        f"以下の確認が必要な項目について教えてください\n\n"
        f"【案件情報】\n"
        f"案件名：{case_name or '未選択'}\n\n"

        f"【確認が必要な項目】\n"
        f"{missing_text}\n\n"

        f"【入力済条件】\n"
        f"{entered_text}"
    )

def execute_real_estate_sale_calculation(
    extraction_result: dict
) -> dict:
    """
    Geminiが抽出・正規化した条件を使って、
    calculate_real_estate_sale()を実行する。

    戻り値のstatus:
        not_applicable:
            不動産売却計算の対象外

        extraction_error:
            Geminiによる条件抽出に失敗

        missing_fields:
            計算に必要な条件が不足

        calculation_error:
            Python計算時に入力エラー等が発生

        success:
            計算成功
    """
    missing_fields = []


    if not isinstance(
        extraction_result,
        dict
    ):
        return {
            "status": "extraction_error",
            "result": None,
            "missing_fields": [],
            "error": (
                "計算条件の抽出結果が"
                "dict形式ではありません"
            )
        }

    should_calculate = bool(
        extraction_result.get(
            "should_calculate",
            False
        )
    )

    if not should_calculate:
        return {
            "status": "not_applicable",
            "result": None,
            "missing_fields": [],
            "error": None
        }

    extraction_status = (
        extraction_result.get(
            "extraction_status",
            "extraction_error"
        )
    )

    if extraction_status == "extraction_error":
        return {
            "status": "extraction_error",
            "result": None,
            "missing_fields": [],
            "error": (
                "不動産売却の計算条件を"
                "正しく読み取れませんでした"
            )
        }

    arguments = extraction_result.get(
        "arguments",
        {}
    )

    if not isinstance(arguments, dict):
        return {
            "status": "extraction_error",
            "result": None,
            "missing_fields": [],
            "error": (
                "不動産売却の計算条件が"
                "dict形式ではありません"
            )
        }

    try:
        normalized_arguments = (
            normalize_real_estate_sale_arguments(
                arguments,
                apply_defaults=False
            )
        )

    except Exception as normalize_error:
        print(
            "不動産売却条件の正規化エラー: "
            f"{type(normalize_error).__name__}: "
            f"{normalize_error}"
        )

        return {
            "status": "extraction_error",
            "result": None,
            "missing_fields": [],
            "error": str(
                normalize_error
            )
        }
    
    # ==========================================
    # 建物未償却残高と理論簿価の差異確認
    # ==========================================
    building_tax_basis_warning = False
    theoretical_building_tax_basis = None
    building_tax_basis_difference = None

    input_building_tax_basis = (
        normalized_arguments.get(
            "building_tax_basis"
        )
    )

    building_acquisition_cost = (
        normalized_arguments.get(
            "building_acquisition_cost"
        )
    )

    building_structure = (
        normalized_arguments.get(
            "building_structure"
        )
    )

    building_acquisition_date = (
        normalized_arguments.get(
            "building_acquisition_date"
        )
    )

    property_usage = (
        normalized_arguments.get(
            "property_usage"
        )
    )

    can_compare_building_tax_basis = (
        input_building_tax_basis is not None
        and building_acquisition_cost is not None
        and building_structure
        and building_acquisition_date
    )

    if can_compare_building_tax_basis:

        theoretical_depreciation_result = (
            calculate_building_depreciation(
                building_original_cost=(
                    building_acquisition_cost
                ),
                building_structure=(
                    building_structure
                ),
                building_acquisition_date=(
                    building_acquisition_date
                ),
                property_usage=(
                    property_usage
                )
            )
        )

        theoretical_building_tax_basis = int(
            theoretical_depreciation_result.get(
                "building_tax_basis",
                0
            )
            or 0
        )

        input_building_tax_basis_amount = (
            to_decimal(
                input_building_tax_basis
            )
        )

        building_tax_basis_difference = abs(
            input_building_tax_basis_amount
            - to_decimal(
                theoretical_building_tax_basis
            )
        )

        building_tax_basis_warning = (
            building_tax_basis_difference
            > BUILDING_TAX_BASIS_WARNING_THRESHOLD
        )

    if (
        normalized_arguments.get(
            "building_tax_basis"
        )
        is None
        and
        to_decimal(
            normalized_arguments.get(
                "accumulated_depreciation",
                Decimal("0")
            )
        )
        <= Decimal("0")
    ):
        building_original_cost = (normalized_arguments.get("building_acquisition_cost"))
        building_structure = (normalized_arguments.get("building_structure"))
        building_acquisition_date = (normalized_arguments.get("building_acquisition_date"))
        property_usage = (normalized_arguments.get("property_usage"))

        if (
            building_original_cost
            and building_structure
            and building_acquisition_date
        ):

            depreciation_result = calculate_building_depreciation(
                    building_original_cost=building_original_cost,
                    building_structure=building_structure,
                    building_acquisition_date=building_acquisition_date,
                    property_usage=property_usage
                )
            
            if "depreciation_result" in locals():
                debug_json(
                    "depreciation_result",
                    depreciation_result
                )

            normalized_arguments["accumulated_depreciation"] = depreciation_result[
                    "accumulated_depreciation"
                ]

    try:
        print(
            f"🏠 計算不足項目: "
            f"{missing_fields}"
        )

        if "depreciation_debug" in locals():
            debug_json(
                "depreciation_debug",
                {
                    "acquisition_related_costs":
                        normalized_arguments.get(
                            "acquisition_related_costs"
                        ),

                    "acquisition_related_costs_confirmed":
                        normalized_arguments.get(
                            "acquisition_related_costs_confirmed"
                        ),

                    "building_original_cost":
                        normalized_arguments.get(
                            "building_original_cost"
                        ),

                    "building_acquisition_cost":
                        normalized_arguments.get(
                            "building_acquisition_cost"
                        ),

                    "building_structure":
                        normalized_arguments.get(
                            "building_structure"
                        ),

                    "building_acquisition_date":
                        normalized_arguments.get(
                            "building_acquisition_date"
                        ),

                    "property_usage":
                        normalized_arguments.get(
                            "property_usage"
                        ),

                    "accumulated_depreciation":
                        normalized_arguments.get(
                            "accumulated_depreciation"
                        ),

                    "total_acquisition_cost":
                        normalized_arguments.get(
                            "total_acquisition_cost"
                        )
                }
            )

        missing_fields = (
            get_real_estate_sale_missing_fields(
                normalized_arguments
            )
        )

        # st.write("merged_arguments")
        # st.code(
        #     json.dumps(
        #         make_json_safe(
        #             merged_arguments
        #         ),
        #         ensure_ascii=False,
        #         indent=2,
        #         default=str
        #     ),
        #     language="json"
        # )
        if "merged_arguments" in locals():
            debug_json(
                "merged_arguments",
                merged_arguments
            )
        
        debug_json(
            "real_estate_calculation_arguments",
            st.session_state.get(
                "real_estate_calculation_arguments",
                {}
            )
        )

        if missing_fields:
            return {
                "status": "missing_fields",
                "result": None,
                "missing_fields": missing_fields,
                "error": None
            }

        # 必須項目が揃ってから任意項目へ初期値を設定
        normalized_arguments = (
            normalize_real_estate_sale_arguments(
                normalized_arguments,
                apply_defaults=True
            )
        )

        if "missing_fields" in locals():
            debug_json(
                "missing_fields",
                missing_fields
            )

    except Exception as missing_check_error:
        print(
            "不動産売却の不足項目判定エラー: "
            f"{type(missing_check_error).__name__}: "
            f"{missing_check_error}"
        )

        return {
            "status": "calculation_error",
            "result": None,
            "missing_fields": [],
            "error": str(
                missing_check_error
            )
        }

    if missing_fields:
        return {
            "status": "missing_fields",
            "result": None,
            "missing_fields":
                missing_fields,
            "error": None
        }
    
    # print(
    #     f"🏠 不動産計算実行条件: "
    #     f"{calculation_arguments}"
    # )
    # calculate_real_estate_sale()に渡す値だけに限定
    calculation_function_fields = {
        "owner_type",
        "sale_price",
        "loan_balance",
        "land_acquisition_cost",
        "building_acquisition_cost",
        "building_tax_basis",
        "accumulated_depreciation",
        "acquisition_related_costs",
        "total_acquisition_cost",
        "brokerage_fee",
        "transfer_expenses",
        "other_cash_expenses",
        "acquisition_date",
        "sale_date",
        "holding_period_type",
        "special_deduction",
        "corporate_effective_tax_rate",
        "use_deemed_acquisition_cost",
        "deemed_acquisition_cost_rate"
    }

    calculation_arguments = {
        key: value
        for key, value in normalized_arguments.items()
        if (
            key in calculation_function_fields
            and value is not None
        )
    }

    # st.warning(f"{calculation_arguments}")
    print(f"🏠 不動産計算実行条件: " f"{calculation_arguments}")
    
    try:

        calculation_result = (
            calculate_real_estate_sale(
                **calculation_arguments
            )
        )
        calculation_result[
            "building_tax_basis_source"
        ] = (
            "user_provided"
            if input_building_tax_basis is not None
            else "calculated"
        )

        calculation_result[
            "theoretical_building_tax_basis"
        ] = theoretical_building_tax_basis

        calculation_result[
            "building_tax_basis_difference"
        ] = (
            round_yen(
                building_tax_basis_difference
            )
            if building_tax_basis_difference
            is not None
            else None
        )

        calculation_result[
            "building_tax_basis_warning"
        ] = building_tax_basis_warning

        st.session_state["debug_calculation_result"] = (
            make_json_safe(calculation_result)
        )

    except (
        ValueError,
        TypeError,
        ArithmeticError
    ) as calculation_error:
        print(
            "不動産売却計算エラー: "
            f"{type(calculation_error).__name__}: "
            f"{calculation_error}"
        )

        return {
            "status": "calculation_error",
            "result": None,
            "missing_fields": [],
            "error": str(
                calculation_error
            )
        }

    except Exception as unexpected_error:
        error_text = (
                f"{type(unexpected_error).__name__}: "
                f"{unexpected_error}"
            )
        print(
                f"🚨 不動産計算予期しないエラー: "
                f"{error_text}"
            )

        return {
            "status": "calculation_error",
            "result": None,
            "missing_fields": [],
            "error": error_text
        }

    if not isinstance(
        calculation_result,
        dict
    ):
        return {
            "status": "calculation_error",
            "result": None,
            "missing_fields": [],
            "error": (
                "不動産売却計算の結果が"
                "dict形式ではありません"
            )
        }

    return {
        "status": "success",
        "tool": "real_estate_sale",
        "result": calculation_result,
        "missing_fields": [],
        "error": None
    }

# 無料会員用計算結果表示
def format_real_estate_result_free(
    result: dict,
    case_name: str = ""
) -> str:

    owner_type = result.get(
        "owner_type"
    )

    holding_type = result.get(
        "holding_type"
    )

    sale_price = int(
        result.get(
            "sale_price",
            0
        ) or 0
    )

    brokerage_fee_method = result.get(
        "brokerage_fee_method"
    )

    loan_balance = int(
        result.get(
            "loan_balance",
            0
        ) or 0
    )

    acquisition_basis = int(
        result.get(
            "applied_acquisition_basis",
            0
        ) or 0
    )

    taxable_gain = int(
        result.get(
            "taxable_gain",
            0
        ) or 0
    )

    estimated_tax = int(
        result.get(
            "estimated_tax",
            0
        ) or 0
    )

    cash_before_tax = int(
        result.get(
            "cash_before_tax",
            0
        ) or 0
    )

    cash_after_tax = int(
        result.get(
            "cash_after_tax",
            0
        ) or 0
    )

    building_tax_basis_warning = bool(
        result.get(
            "building_tax_basis_warning",
            False
        )
    )

    ownership_label = (
        "個人"
        if owner_type == "individual"
        else "法人"
    )

    holding_label = (
        "長期譲渡所得"
        if holding_type == "long_term"
        else "短期譲渡所得"
    )

    lines = [
        f"計算結果は以下になりました。",
        f"【案件情報】",
        f"案件名：{case_name or '未選択'}",
        "",
        "【適用条件】",
        f"・所有者区分：{ownership_label}",
        f"・保有期間：{holding_label}",
        f"・売却価格：{sale_price:,}円",
        f"・ローン残債：{loan_balance:,}円",
        f"・取得費：{acquisition_basis:,}円",
        f"・売却時仲介手数料：{int(result.get('brokerage_fee',0)):,}円",
    ]
    if (brokerage_fee_method == "statutory_max_estimate"):
        lines.append("・仲介手数料は法定上限額で自動計算")

    if building_tax_basis_warning:
        lines.extend([
            "⚠️ 建物未償却残高の確認",
            "入力していただいた建物未償却残高と、",
            "建物取得価額・構造・取得年月から算出した簿価に差異がありました。",
            "",
            "今回は入力していただいた未償却残高を採用して計算しています。",
            ""
        ])

    lines.extend([
        "",
        "【税額】",
        f"・課税譲渡所得：{taxable_gain:,}円",
        f"・概算税額：{estimated_tax:,}円",
        "",
        "【最終手残り】",
        f"・税引前手残り：{cash_before_tax:,}円",
        f"・税引後手残り：{cash_after_tax:,}円",
        "",
        (
            "この結果は入力条件に基づく概算であり、"
            "実際の申告税額を確定するものではございません。"
        )
    ])

    return "\n".join(lines)

# スタンダート会員用計算結果表示
def format_real_estate_result_standard(
    result: dict,
    case_name: str = ""
) -> str:

    owner_type = result.get(
        "owner_type"
    )

    holding_type = result.get(
        "holding_type"
    )

    ownership_label = (
        "個人"
        if owner_type == "individual"
        else "法人"
    )

    holding_label = (
        "長期譲渡所得"
        if holding_type == "long_term"
        else "短期譲渡所得"
    )

    building_tax_basis_source = (
        result.get(
            "building_tax_basis_source"
        )
    )

    tax_rate = (
        result.get(
            "tax_rate"
        )
    )

    building_tax_basis_label = (
        "入力値"
        if building_tax_basis_source
        == "user_provided"
        else "自動計算"
    )

    brokerage_fee_method = result.get(
        "brokerage_fee_method"
    )

    building_tax_basis_warning = bool(
        result.get(
            "building_tax_basis_warning",
            False
        )
    )

    building_acquisition_cost = int(
        result.get(
            "building_acquisition_cost",
            0
        ) or 0
    )

    acquisition_lines = [
        "【取得費の内訳】",

        f"・土地取得費："
        f"{int(result.get('land_acquisition_cost',0)):,}円",
    ]

    if building_acquisition_cost > 0:
        acquisition_lines.append(
            f"・建物取得価額："
            f"{building_acquisition_cost:,}円"
        )
    
    acquisition_lines.extend([
        (
            f"・建物未償却残高："
            f"{int(result.get('building_tax_basis',0)):,}円"
            f"（{building_tax_basis_label}）"
        ),

        f"・購入時諸費用："
        f"{int(result.get('acquisition_related_costs',0)):,}円",

        f"・計算採用取得費："
        f"{int(result.get('applied_acquisition_basis',0)):,}円",

        ""
    ])

    lines = [

        "【案件情報】",
        f"案件名：{case_name}",
        "",

        "【適用条件】",
        f"・所有者区分：{ownership_label}",
        f"・保有期間：{holding_label}",
        f"・売却価格：{int(result.get('sale_price',0)):,}円",
        f"・ローン残債：{int(result.get('loan_balance',0)):,}円",
        ""
    ]

    lines.extend(acquisition_lines)
            
    lines.extend([
        "【売却費用】",
        f"・仲介手数料：{int(result.get('brokerage_fee',0)):,}円",
    ])

    if (brokerage_fee_method == "statutory_max_estimate"):
        lines.append("・仲介手数料は法定上限額で自動計算")

    lines.extend([
        f"・譲渡費用：{int(result.get('transfer_expenses',0)):,}円",
        "",
    
        "【譲渡所得】",
        (
            f"・特別控除前譲渡所得："
            f"{int(result.get('capital_gain_before_deduction',0)):,}円"
        ),
        (
            f"・特別控除："
            f"{int(result.get('special_deduction',0)):,}円"
        ),
        (
            f"・課税譲渡所得："
            f"{int(result.get('taxable_gain',0)):,}円"
        ),
        "",

        "【税額】",
        (
            f"・適用税率："
            f"{tax_rate * 100:.3f}%"
            if tax_rate is not None
            else "・適用税率：未計算"
        ),
        (
            f"・概算税額："
            f"{int(result.get('estimated_tax',0)):,}円"
        ),
        "",

        "【最終手残り】",
        (
            f"・税引前手残り："
            f"{int(result.get('cash_before_tax',0)):,}円"
        ),
        (
            f"・税引後手残り："
            f"{int(result.get('cash_after_tax',0)):,}円"
        ),
    ])

    if building_tax_basis_warning:
            lines.extend([
                "⚠️ 建物未償却残高の確認",
                "入力していただいた建物未償却残高と、",
                "建物取得価額・構造・取得年月から算出した簿価に差異がありました。",
                "",
                "今回は入力していただいた未償却残高を採用して計算しています。",
                ""
            ])

    lines.extend([
        "",
        (
            "この結果は入力条件に基づく概算であり、"
            "実際の申告税額を確定するものではございません。"
        )
    ])

    return "\n".join(lines)

def build_real_estate_calculation_context(
    execution_result: dict
) -> str:
    """
    不動産売却計算の実行結果から、
    最終回答用のプロンプトブロックを作成する。

    status:
        not_applicable
        missing_fields
        extraction_error
        calculation_error
        success

    計算対象外の場合は空文字を返すため、
    通常会話のプロンプトには何も追加されない。
    """
    status = execution_result.get(
        "status",
        "not_applicable"
    )

    # 通常会話では何も追加しない
    if status == "not_applicable":
        return ""

    # 必須条件が不足している場合
    if status == "missing_fields":
        missing_fields = execution_result.get(
            "missing_fields",
            []
        )

        missing_labels = [
            REAL_ESTATE_FIELD_LABELS.get(
                field,
                field
            )
            for field in missing_fields
        ]

        current_case_name = (
            st.session_state.get(
                "active_calculation_case_name",
                ""
            )
        )

        current_arguments = dict(
            st.session_state.get(
                "real_estate_calculation_arguments",
                {}
            )
            or {}
        )

        entered_conditions = []
        for key, value in current_arguments.items():
            if value is None:
                continue
            if key.endswith("_confirmed"):
                continue
            label = REAL_ESTATE_FIELD_LABELS.get(
                key,
                key
            )
            entered_conditions.append(
                f"・{label}: {value}"
            )

        entered_text = (
            "\n".join(entered_conditions)
            if entered_conditions
            else "なし"
        )
        
        if (missing_fields == ["holding_period_type"]):
            return """
            【Python不動産売却計算】

            売却日が未定のため、
            長期譲渡か短期譲渡かを確認したいです。

            【回答例】

            ・長期譲渡で計算して

            または

            ・短期譲渡で計算して

            【補足】

            一般的に取得から5年を超えている場合は
            長期譲渡です。
            """.strip()

        if missing_labels:
            missing_text = "\n".join(
                f"・{label}"
                for label in missing_labels
            )
        else:
            missing_text = (
                "・計算に必要な条件"
            )
        
        adjusted_labels = []
        for label in missing_labels:
            if label == "建物の減価償却累計額":
                adjusted_labels.append(
                    "建物の減価償却累計額\n"
                    "または\n"
                    "建物取得額・建物構造・建物取得年月"
                )

            else:
                adjusted_labels.append(label)
        missing_labels = adjusted_labels

        return f"""
        【案件情報】
        案件名：{current_case_name or "未選択"}

        【確認が必要な項目】
        {missing_text}

        【入力済条件】
        {entered_text}

        【回答ルール】
        ・不足している項目だけを確認してください。
        ・ユーザーが明示していない数値や日付を推測してはいけません。
        ・現在入力済みの条件は再質問してはいけません。
        """.strip()

    # Geminiによるパラメータ抽出に失敗した場合
    if status == "extraction_error":
        return """
        【Python不動産売却計算】

        ユーザーの入力条件を正しく構造化できなかったため、
        今回はPython計算を実行していません。

        【回答ルール】
        ・推測による計算は行わないでください。
        ・ユーザーへ、計算条件を整理して入力してもらうよう案内してください。
        ・一度にすべての条件を求めず、今回の会話で不足している主要条件だけを確認してください。
        ・基本的な確認項目は、売却額、売却者が個人か法人か、取得日、売却日です。
        ・取得費、ローン残債、売却費用などがすでに提示されている場合は、再入力を求めないでください。
        """.strip()

    # Python関数内でバリデーションエラー等が発生した場合
    if status == "calculation_error":
        error_message = str(
            execution_result.get(
                "error",
                "計算条件に問題があります"
            )
            or "計算条件に問題があります"
        )

        return f"""
        【Python不動産売却計算エラー】

        Python計算を実行しましたが、
        入力条件に問題があるため結果を確定できませんでした。

        【エラー内容】
        {error_message}

        【回答ルール】
        ・エラー内容を、ユーザー向けに分かりやすく説明してください。
        ・修正が必要な項目だけを確認してください。
        ・ユーザーが明示していない数値や日付を推測してはいけません。
        ・エラーが解消されるまで独自の概算結果を作ってはいけません。
        ・Pythonの内部処理やプログラムコードの説明は不要です。
        """.strip()

    # 想定外の状態では計算結果を使用しない
    if status != "success":
        return """
        【Python不動産売却計算】

        計算状態を確認できなかったため、
        今回は計算結果を使用できません。

        【回答ルール】
        ・独自に再計算してはいけません。
        ・ユーザーへ、条件を確認できなかったことを簡潔に伝えてください。
        """.strip()

    # 計算成功時
    result = execution_result.get(
        "result"
    )

    if not isinstance(result, dict):
        return """
        【Python不動産売却計算エラー】

        Python計算の結果を取得できませんでした。

        【回答ルール】
        ・独自に再計算してはいけません。
        ・計算結果を取得できなかったことだけを簡潔に伝えてください。
        ・存在しない数値を作ってはいけません。
        """.strip()

    result_json = json.dumps(
        result,
        ensure_ascii=False,
        indent=2
    )
    building_tax_basis_warning_text = ""

    if result.get(
        "building_tax_basis_warning",
        False
    ):
        input_basis = int(
            result.get(
                "building_tax_basis",
                0
            )
            or 0
        )

        theoretical_basis = int(
            result.get(
                "theoretical_building_tax_basis",
                0
            )
            or 0
        )

        basis_difference = int(
            result.get(
                "building_tax_basis_difference",
                0
            )
            or 0
        )

        building_tax_basis_warning_text = f"""
    ⚠️ 入力していただいた建物未償却残高と、建物取得価額・構造・取得年月から算出した簿価に差異がありました。
    今回は入力していただいた未償却残高を採用して計算しています。
    """.strip()

    estimated_tax = result.get(
        "estimated_tax"
    )

    cash_after_tax = result.get(
        "cash_after_tax"
    )

    owner_type = result.get(
        "owner_type"
    )

    brokerage_fee = result.get(
        "brokerage_fee"
    )

    transfer_expenses = result.get(
        "transfer_expenses"
    )

    cash_before_tax = result.get(
        "cash_before_tax"
    )

    tax_status = result.get(
        "tax_calculation_status"
    )

    # 法人で税額が計算されていない場合など
    if (
        estimated_tax is None
        or cash_after_tax is None
    ):
        tax_note = """
        ・税額が計算されていない場合、税引後手残りを独自に作ってはいけません。
        ・その場合は、税引前手残りを主要結果として示してください。
        ・法人の実効税率が未指定の場合は、会社全体の所得状況などにより税額が変わるため、今回の計算には含めていないと説明してください。
        """.strip()
    else:
        tax_note = """
        ・結果は、適用条件、取得費の内訳、税額、最終手残りの順で説明してください。
        ・税引前手残りと税引後手残りは、回答の最後に表示してください。
        ・税引前手残りを先に表示し、その後に税引後手残りを表示してください。
        """.strip()

    # 個人の場合の保有期間表示ルール
    if owner_type == "individual":
        holding_note = """
        ・holding_typeがlong_termの場合は「長期譲渡所得」と表示してください。
        ・holding_typeがshort_termの場合は「短期譲渡所得」と表示してください。
        ・適用税率は計算結果に記録されたtax_rateを使用してください。
        """.strip()
    else:
        holding_note = """
        ・法人には個人の長期譲渡所得、短期譲渡所得という表現を使用しないでください。
        """.strip()

    return f"""
    【Python不動産売却計算結果】

    以下はPythonで計算済みの確定出力です。

    {result_json}

    【計算結果の説明ルール】
    ・上記の数値を最優先してください。
    ・数値を変更してはいけません。
    ・独自に再計算して、別の結果を作ってはいけません。
    ・結果に存在しない数値を推測してはいけません。
    ・取得費とローン残債を混同してはいけません。
    ・課税対象となる譲渡所得と、実際の現金手残りを混同してはいけません。
    ・ローン残債は現金手残りには影響しますが、通常の譲渡所得の取得費ではありません。
    ・特別控除は、計算結果のspecial_deductionに記録された金額だけを使用してください。
    ・ユーザーが明示していない特例を追加適用してはいけません。
    ・金額は円単位の整数として受け取り、回答では読みやすいように円または万円で表示してください。
    ・万円表示へ直す場合も、元の計算結果と一致することを確認してください。
    ・最後に、この結果は入力条件に基づく概算であり、申告税額を確定するものではないことを短く伝えてください。
      その際の語尾や口調は、現在設定されている方言設定もしくは人格設定に従ってください。
    ・その説明が終わった時点で回答を終了してください。
    ・計算結果と無関係な追加の挨拶、締めの定型文、締めの定型文、締めの定型文、締めの定型文は入れない。
    ・brokerage_feeは仲介手数料です。
    ・仲介手数料が自動計算されている場合は、その金額も説明してください。
    ・税引前手残りには仲介手数料や譲渡費用が反映されていることを説明してください。
    ・brokerage_fee_method が statutory_max_estimate の場合は、「仲介手数料は未入力だったため法定上限額で試算しました」と説明してください。
    ・brokerage_fee_method が specified の場合は、「仲介手数料は入力値を使用しました」と説明してください。
    ・計算は既に完了しています。
    ・これから計算します、確認します、再計算します、少々お待ちください、処理中です等の表現は禁止です。
    ・結果を持っている前提で回答してください。
    ・追加条件が必要な場合以外は条件を再度確認してはいけません。
    ・結果が存在する場合は必ず結果を提示してください。
    ・取得費（applied_acquisition_basis）は、ユーザー向けには単に「取得費」と表示してください。

    【出力形式】
    必ずこの構造で出力すること。
    未入力項目は表示しないこと。

    【適用条件】
    ・項目名：値

    【取得費の内訳】
    ・項目名：値
    ・建物未償却残高の確認
    （以下の警告がある場合のみそのまま表示）
     {building_tax_basis_warning_text}
     警告文が空の場合は、この見出し自体を表示しないでください。

    【税額】
    ・項目名：値

    【最終手残り】
    ・項目名：値

    建物未償却残高がユーザー入力の場合でも、
    建物取得価額と減価償却累計額との関係が分かるように表示してください。

    building_tax_basis_source が user_provided の場合は、
    建物未償却残高に「入力値」と付記してください。

    building_tax_basis_source が calculated の場合は、
    建物未償却残高に「自動計算」と付記してください。
 
    最終手残りは必ず回答の最後に表示してください。

    【所有者区分の表示ルール】
    {holding_note}

    【内部確認情報】
    owner_type: {owner_type}
    tax_calculation_status: {tax_status}
    """.strip()

def build_case_rename_followup(
    case_id: str,
    new_case_name: str
) -> str:
    """
    案件名変更後に案件データを読み込み、
    条件不足なら不足項目を案内し、
    条件が揃っていれば現在条件で再計算結果を返す。
    """

    case_record = get_calculation_case(
        case_id
    )

    case_arguments = dict(
        case_record.get(
            "case_data",
            {}
        )
        or {}
    )
    debug_json(
        "DEBUG rename_case_arguments",
        case_arguments
    )

    # 案件データが取得できなかった場合
    if not case_arguments:
        return (
            f"案件名を「{new_case_name}」へ変更しました。\n\n"
            "この案件にはまだ計算に必要な条件が登録されていません。"
            "計算に必要な各条件を教えてください。"
        )

    extraction_result = {
        "should_calculate": True,
        "arguments": case_arguments,
        "extraction_status": "extracted",
        "in_tokens": 0,
        "out_tokens": 0,
        "cost": 0.0
    }

    execution_result = (
        execute_real_estate_sale_calculation(
            extraction_result
        )
    )

    calculation_status = (
        execution_result.get(
            "status",
            "calculation_error"
        )
    )

    # ======================================
    # 条件不足
    # ======================================
    if calculation_status == "missing_fields":

        missing_fields = (execution_result.get("missing_fields", []) or [])

        missing_labels = [
            REAL_ESTATE_FIELD_LABELS.get(
                field,
                field
            )
            for field in missing_fields
        ]

        missing_text = "\n".join(
            f"・{label}"
            for label in missing_labels
        )

        # 条件を保持して計算途中状態へ戻す
        st.session_state[
            "real_estate_calculation_arguments"
        ] = normalize_real_estate_sale_arguments(
            case_arguments,
            apply_defaults=False
        )

        st.session_state["real_estate_calculation_pending"] = True

        missing_message = format_missing_fields_message(
            case_name=new_case_name,
            current_arguments=st.session_state.get(
                "real_estate_calculation_arguments",
                {}
            ),
            missing_fields=missing_fields
        )

        return (
            f"案件名を"
            f"「{new_case_name}」"
            f"へ変更しました。\n\n"
            f"{missing_message}"
        )
        # return (
        #     f"案件名を"
        #     f"「{new_case_name}」"
        #     f"へ変更しました。\n\n"
        #     "この案件にはまだ計算に必要な条件が登録されていません。"
        #     "計算に必要な各条件を教えてください。"
        #     f"\n"
        #     f"【案件情報】\n"
        #     f"案件名：{new_case_name}\n\n"

        #     f"【確認が必要な項目】\n"
        #     f"{missing_text}\n\n"

        #     f"【入力済条件】\n"
        #     f"{entered_text}"
        # )

    # ======================================
    # 計算成功
    # ======================================
    if calculation_status == "success":

        result = dict(
            execution_result.get(
                "result",
                {}
            )
            or {}
        )

        # 最新条件を保持
        st.session_state[
            "real_estate_calculation_arguments"
        ] = normalize_real_estate_sale_arguments(
            case_arguments,
            apply_defaults=False
        )

        st.session_state[
            "real_estate_calculation_pending"
        ] = False

        if current_plan_type == "🆓 無料プラン":
            formatted_result = (
                format_real_estate_result_free(
                    result=result,
                    case_name=st.session_state.get(
                        "active_calculation_case_name",
                        ""
                    )
                )
            )
        else:
            formatted_result = (
                format_real_estate_result_standard(
                    result=result,
                    case_name=st.session_state.get(
                        "active_calculation_case_name",
                        ""
                    )
                )
            )

        return (
            f"案件名を"
            f"「{new_case_name}」"
            f"へ変更しました。\n\n"
            "現在保存されている条件での"
            f"{formatted_result}"
        )

    # ======================================
    # 計算エラー
    # ======================================
    error_message = str(
        execution_result.get(
            "error",
            ""
        )
        or ""
    ).strip()

    st.session_state[
        "real_estate_calculation_arguments"
    ] = case_arguments

    st.session_state[
        "real_estate_calculation_pending"
    ] = True

    if error_message:
        return (
            f"案件名を"
            f"「{new_case_name}」"
            f"へ変更しました。\n\n"
            "保存されている条件を確認しましたが、"
            "再計算できませんでした。\n"
            f"確認内容：{error_message}"
        )

    return (
        f"案件名を"
        f"「{new_case_name}」"
        f"へ変更しました。\n\n"
        "保存されている計算条件を確認できませんでした。"
    )
#================================================

# 仲介手数料を自動入力に変更判定関数
def should_reset_brokerage_fee(
    user_input: str
) -> bool:

    text = (
        str(user_input)
        .replace(" ", "")
        .replace("　", "")
    )

    return (
        "仲介手数料" in text
        and any(
            keyword in text
            for keyword in [
                "自動",
                "計算",
                "お任せ",
                "元に戻"
            ]
        )
    )
#================================================

# 改行表示変換関数
def display_message(
    speaker: str,
    content: str
):
    if DEBUG_MODE:
        if st.session_state.get("real_estate_calculation_pending", False):
            st.caption("🧮 DEBUG: 不動産計算モード")
    
    display_content = (clean_bold_markdown(content).replace("\n", "<br>"))

    st.markdown(f"{speaker}:<br>{display_content}", unsafe_allow_html=True)
#================================================

# 計算モード終了判定関数
def should_exit_real_estate_calculation(
    user_input: str
) -> bool:

    text = (
        str(user_input or "")
        .replace(" ", "")
        .replace("　", "")
        .strip()
    )

    return any(
        keyword in text
        for keyword in [
            "計算終了",
            "計算を終了",
            "計算やめる",
            "計算はやめる",
            "計算しなくていい",
            "別の話",
            "もう大丈夫",
            "もういい"
        ]
    )

    # exact_exit_phrases = {
    #     "ありがとう",
    #     "ありがとうございました",
    #     "計算終了",
    #     "計算終了して",
    #     "計算を終了して",
    #     "計算はやめる",
    #     "計算やめる",
    #     "計算しなくていい",
    #     "計算は不要",
    #     "もう大丈夫",
    #     "もういい",
    #     "もういいです",
    #     "終了",
    #     "終わり",
    #     "今回はやめる",
    #     "別の話をしたい",
    #     "別の話しよう"
        
    # }

    return text in exact_exit_phrases
#================================================

# 会話保存件数のカウント関数
def get_saved_chat_count() -> int:
    try:
        response = (
            supabase
            .table("saved_chats")
            .select("id", count="exact")
            .eq("user_id", CURRENT_USER_ID)
            .limit(1)
            .execute()
        )

        return int(response.count or 0)

    except Exception as e:
        print(
            "保存会話件数取得エラー: "
            f"{type(e).__name__}: {e}"
        )
        return 0
#================================================

# 会話保存関数
def save_saved_chat(
    title: str,
    summary: str,
    user_message: str,
    assistant_message: str,
    original_message_id: str
) -> bool:
    try:
        current_plan_code = st.session_state.get("current_user_plan_code", "free")
        save_limit = get_effective_saved_chat_limit(
            user_id=CURRENT_USER_ID,
            plan_code=current_plan_code
        )

        if save_limit <= 0:
            st.warning("会話保存はライトプラン以上で利用できます。")
            return False

        saved_chats_count = get_saved_chat_count()

        if saved_chats_count >= save_limit:
            st.warning(
                f"保存上限（{save_limit}件）に達しています。"
                "不要な保存済み会話を削除してから、"
                "もう一度お試しください。"
            )
            return False


        data = {
            "user_id": CURRENT_USER_ID,
            "title": title,
            "summary": "",
            "message_id": f"saved_{uuid.uuid4().hex[:8]}",
            "user_message": user_message,
            "assistant_message": assistant_message,
            "original_message_id": original_message_id
        }
        # debug_json(
        #     "DEBUG save_saved_chat_data",
        #     data
        # )

        result = (
            supabase
            .table("saved_chats")
            .insert(data)
            .execute()
        )
            
        debug_json(
            "DEBUG save_saved_chat_result",
            result.data
        )

        return True

    except Exception as e:
        st.error(
            f"save_saved_chat error: "
            f"{type(e).__name__}: {e}"
        )
        print(
            "会話保存エラー: "
            f"{type(e).__name__}: {e}"
        )

        return False
#================================================

# 保存した会話の読み込み関数
def get_saved_chats():
    try:
        response = (
            supabase
            .table("saved_chats")
            .select("*")
            .eq(
                "user_id",
                CURRENT_USER_ID
            )
            .order(
                "created_at",
                desc=True
            )
            .execute()
        )

        return (
            response.data
            if response.data
            else []
        )

    except Exception as e:

        print(
            f"保存会話取得エラー: "
            f"{type(e).__name__}: {e}"
        )

        return []
#================================================

# 会話タイトル作成関数
def create_saved_chat_title(
    user_message: str
) -> str:

    text = str(
        user_message or ""
    ).strip()

    if not text:
        return "保存した会話"

    return text[:20]
#================================================

# 保存されている会話の削除関数
def delete_saved_chat(
    chat_id: int
) -> bool:
    try:
        (
            supabase
            .table("saved_chats")
            .delete()
            .eq(
                "id",
                chat_id
            )
            .execute()
        )

        return True

    except Exception as e:
        print(
            f"保存会話削除エラー: "
            f"{type(e).__name__}: {e}"
        )

        return False
#================================================

def parse_summary_memory_blocks(summary_text: str):

    blocks = []

    current_title = None
    current_lines = []

    for line in summary_text.split("\n"):
        text = str(line).strip()
        if not text:
            continue
        if text.startswith("・") and text.endswith(":"):
            if current_title:
                blocks.append({"title": current_title, "content": "\n".join(current_lines)})

            current_title = (text.replace("・", "").replace(":", "").strip())
            current_lines = []
        else:
            current_lines.append(text)

    if current_title:
        blocks.append({"title": current_title, "content": "\n".join(current_lines)})

    return blocks
#================================================

# 計画ルーム用の計画一覧を取得する関数
def get_plan_projects(status: str = "active"):
    try:
        response = (
            supabase
            .table("plan_projects")
            .select("*")
            .eq("user_id", CURRENT_USER_ID)
            .eq("project_status", status)
            .order("updated_at", desc=True)
            .execute()
        )
        return (
            response.data
            if response.data
            else []
        )

    except Exception as e:
        print(
            f"計画取得エラー: "
            f"{type(e).__name__}: {e}"
        )
        return []
#================================================

# 計画の作成済件数取得関数
def get_plan_project_count(status: str) -> int:
    try:
        response = (
            supabase
            .rpc(
                "get_plan_project_count",
                {
                    "p_user_id": str(CURRENT_USER_ID),
                    "p_status": status
                }
            )
            .execute()
        )
        return int(response.data or 0)

    except Exception as e:
        print(
            "計画件数取得エラー: "
            f"{type(e).__name__}: {e}"
        )
        return 0
#================================================

# 計画の要約を集めるDB関数の呼び出し成関数
def get_plan_overall_summary(user_id: str) -> str:
    try:
        response = (
            supabase
            .rpc("get_plan_overall_summary", {"p_user_id": str(user_id)})
            .execute()
        )
        return str(response.data or "").strip()

    except Exception as e:
        print(
            "計画全体要約取得エラー: "
            f"{type(e).__name__}: {e}"
        )
        return ""
#================================================

# 計画の作成関数
def create_plan_project(project_name: str):
    try:
        response = (
            supabase
            .table("plan_projects")
            .insert({
                "user_id":CURRENT_USER_ID,
                "project_name": project_name,
                "project_status": "active",
                "project_summary": "",
                "decision_items": [],
                "considering_items": [],
                "pending_items": [],
                "next_actions": []
            })
            .execute()
        )
        return True

    except Exception as e:
        print(
            f"計画作成エラー: "
            f"{type(e).__name__}: {e}"
        )
        return False
#================================================

# 新規の計画作成ポップアップ関数
@st.dialog("新しい計画を作成")
def show_create_plan_dialog():
    new_project_name = st.text_input(
        "計画名",
        placeholder="計画名を入力してください",
        key="dialog_new_project_name"
    )

    create_plan = st.button(
        "計画を作成",
        # use_container_width=True
    )

    if create_plan:
        current_plan_code = st.session_state.get("current_user_plan_code", "free")
        plan_features = get_plan_features(current_plan_code)
        active_plan_limit = int(plan_features.get("plan_active_limit", 0))
        active_plan_count = get_plan_project_count("active")

        if (
            active_plan_limit <= 0
            or active_plan_count >= active_plan_limit
        ):
            st.warning(
                f"進行中の計画は最大"
                f"{active_plan_limit}件まで登録できます。\n\n"
                "既存の計画を完了済みに移動するか、削除してから、"
                "新しい計画を作成してください。"
            )
            return

        project_name = new_project_name.strip()

        if not project_name:
            st.warning("計画名を入力してください。")
            return

        if create_plan_project(project_name):
            st.session_state["newly_created_plan_name"] = project_name
            st.rerun()
        else:
            st.error("計画を作成できませんでした。")
#================================================

# 表示用の計画取得関数
def get_plan_project(project_name: str):
    try:
        response = (
            supabase
            .table("plan_projects")
            .select("*")
            .eq("user_id", CURRENT_USER_ID)
            .eq("project_name", project_name)
            .limit(1)
            .execute()
        )
        if response.data:
            return response.data[0]
        return {}

    except Exception as e:
        print(
            f"計画取得エラー: "
            f"{type(e).__name__}: {e}"
        )
        return {}
#================================================

# プラン表示更新関数
def update_plan_project(project_id: int, update_data: dict) -> bool:
    try:
        (
            supabase
            .table("plan_projects")
            .update(update_data)
            .eq("id", project_id)
            .execute()
        )
        return True

    except Exception as e:
        print(
            f"計画更新エラー: "
            f"{type(e).__name__}: {e}"
        )
        return False
#================================================

# 計画を削除する関数
def delete_plan_project(project_id: int) -> bool:
    try:
        (
            supabase
            .table("plan_projects")
            .delete()
            .eq("id", project_id)
            .eq("user_id", CURRENT_USER_ID)
            .execute()
        )
        return True

    except Exception as e:
        print(
            "計画削除エラー: "
            f"{type(e).__name__}: {e}"
        )
        return False
#================================================

# 計画の削除確認ダイアログ関数
@st.dialog("計画の削除確認")
def show_plan_delete_dialog(project_id: int, project_name: str):
    st.warning(
        f"「{project_name}」を削除します。\n\n"
        "削除した計画は元に戻せません。"
    )

    confirm_col, cancel_col = st.columns(2)

    with confirm_col:
        if st.button(
            "削除を確定",
            key=f"confirm_delete_{project_id}",
            # use_container_width=True
        ):
            if delete_plan_project(project_id):
                st.session_state["reset_active_plan_project"] = True
                st.rerun()
            else:
                st.error("計画の削除に失敗しました。")

    with cancel_col:
        if st.button(
            "キャンセル",
            key=f"cancel_delete_{project_id}",
            # use_container_width=True
        ):
            st.rerun()
#================================================

# 計画を完了にする関数
@st.dialog("計画を完了にする")
def show_plan_complete_dialog(project_id: int, project_name: str):
    st.info(
        f"「{project_name}」を完了済み計画へ移動します。\n\n"
        "完了後も、進行中の計画へ戻すことができます。"
    )

    complete_col, cancel_col = st.columns(2)

    with complete_col:
        if st.button(
            "完了にする",
            key=f"confirm_complete_{project_id}",
            use_container_width=True
        ):
            current_plan_code = st.session_state.get("current_user_plan_code", "free")
            plan_features = get_plan_features(current_plan_code)
            completed_plan_limit = int(plan_features.get("plan_completed_limit", 0))
            completed_plan_count = get_plan_project_count("completed")

            if (
                completed_plan_limit <= 0
                or completed_plan_count >= completed_plan_limit
            ):
                st.warning(
                    f"完了済みの計画は最大"
                    f"{completed_plan_limit}件まで保存できます。\n\n"
                    "不要な完了済み計画を削除してから、"
                    "この計画を完了済みに移動してください。"
                )
                return
            
            update_succeeded = update_plan_project(
                project_id=project_id,
                update_data={
                    "project_status": "completed",
                    "updated_at": datetime.now(JST).isoformat()
                }
            )

            if update_succeeded:
                st.session_state["reset_active_plan_project"] = True
                st.toast("完了済み計画へ移動しています...")
                st.rerun()
            else:
                st.error("計画を完了済みに移動できませんでした。")

    with cancel_col:
        if st.button(
            "キャンセル",
            key=f"cancel_complete_{project_id}",
            use_container_width=True
        ):
            st.rerun()
#================================================

# 計画ルームの会話から必要事項を抽出する関数
@st.dialog("計画を進行中へ戻す")
def show_plan_restore_dialog(project_id: int, project_name: str):
    st.info(f"「{project_name}」を進行中の計画へ戻します。")

    restore_col, cancel_col = st.columns(2)

    with restore_col:
        if st.button(
            "進行中へ戻す",
            key=f"confirm_restore_{project_id}",
            use_container_width=True
        ):
            current_plan_code = st.session_state.get("current_user_plan_code", "free")
            plan_features = get_plan_features(current_plan_code)
            active_plan_limit = int(plan_features.get("plan_active_limit", 0))
            active_plan_count = get_plan_project_count("active")

            if (
                active_plan_limit <= 0
                or active_plan_count >= active_plan_limit
            ):
                
                st.warning(
                    f"進行中の計画は最大"
                    f"{active_plan_limit}件まで登録できます。\n\n"
                    "既存の進行中計画を完了済みにするか、削除してから、"
                    "この計画を進行中へ戻してください。"
                )
                return

            update_succeeded = update_plan_project(
                project_id=project_id,
                update_data={
                    "project_status": "active",
                    "updated_at": datetime.now(JST).isoformat()
                }
            )

            if update_succeeded:
                st.session_state["reset_completed_plan_project"] = True
                st.toast("進行中の計画へ戻しています...")
                st.rerun()
            else:
                st.error("計画を進行中へ戻せませんでした。")

    with cancel_col:
        if st.button(
            "キャンセル",
            key=f"cancel_restore_{project_id}",
            use_container_width=True
        ):
            st.rerun()
#================================================

# 計画名を変更する関数
@st.dialog("計画名を変更")
def show_plan_rename_dialog(
    project_id: int,
    current_project_name: str
):
    new_project_name = st.text_input(
        "新しい計画名",
        value=current_project_name,
        key=f"rename_project_name_{project_id}"
    )

    rename_col, cancel_col = st.columns(2)

    with rename_col:
        if st.button(
            "変更する",
            key=f"confirm_rename_{project_id}",
            use_container_width=True
        ):
            renamed_project_name = new_project_name.strip()

            if not renamed_project_name:
                st.warning("計画名を入力してください。")
                return

            if renamed_project_name == current_project_name:
                st.info("計画名は変更されていません。")
                return

            update_succeeded = update_plan_project(
                project_id=project_id,
                update_data={
                    "project_name": renamed_project_name,
                    "updated_at": datetime.now(JST).isoformat()
                }
            )

            if update_succeeded:
                st.session_state["renamed_plan_name"] = (
                    renamed_project_name
                )
                st.toast("計画名を変更しています...")
                st.rerun()
            else:
                st.error("計画名を変更できませんでした。")

    with cancel_col:
        if st.button(
            "キャンセル",
            key=f"cancel_rename_{project_id}",
            use_container_width=True
        ):
            st.rerun()
#================================================

# 計画ルームの会話から必要事項を抽出する関数
def extract_plan_project_updates(
    selected_project: dict,
    user_message: str,
    assistant_message: str
) -> dict:
    """
    計画ルームの1会話から、
    計画概要・決定事項・検討中・保留事項・
    次にやることの最新状態を抽出する。
    """
    empty_result = {
        "project_summary": (selected_project.get("project_summary") or ""),
        "decision_items": (selected_project.get("decision_items") or []),
        "considering_items": (selected_project.get("considering_items") or []),
        "pending_items": (selected_project.get("pending_items") or []),
        "next_actions": (selected_project.get("next_actions") or [])
    }

    try:
        extraction_prompt = f"""
        あなたは計画情報を整理するシステムです。
        既存の計画情報と今回の会話を読み、計画の最新状態をJSONで出力してください。

        【重要】
        ・ユーザーが明示した内容を優先してください。
        ・AIが提案しただけの内容を、決定事項にしてはいけません。
        ・決定したことだけをdecision_itemsへ入れてください。
        ・まだ検討している内容はconsidering_itemsへ入れてください。
        ・当面判断しない内容はpending_itemsへ入れてください。
        ・具体的に実行する作業はnext_actionsへ入れてください。
        ・既存情報は、今回の会話で変更・削除されない限り維持してください。
        ・同じ内容を重複して追加してはいけません。
        ・該当する更新がない項目は、既存内容をそのまま返してください。
        ・ユーザーが明示していない事実を追加してはいけません。
        ・JSON以外の文章は出力しないでください。

        【計画名】
        {selected_project.get("project_name", "")}

        【現在の計画概要】
        {empty_result["project_summary"]}

        【現在の決定事項】
        {json.dumps(empty_result["decision_items"], ensure_ascii=False)}

        【現在の検討中】
        {json.dumps(empty_result["considering_items"], ensure_ascii=False)}

        【現在の保留事項】
        {json.dumps(empty_result["pending_items"], ensure_ascii=False)}

        【現在の次にやること】
        {json.dumps(empty_result["next_actions"], ensure_ascii=False)}

        【今回のユーザー発言】
        {user_message}

        【今回のAI回答】
        {assistant_message}

        【出力形式】
        {{
            "project_summary": "",
            "decision_items": [],
            "considering_items": [],
            "pending_items": [],
            "next_actions": []
        }}
        """

        extraction_result = generate_ai_response(
            provider=BACKGROUND_PROVIDER,
            system_instruction="",
            user_prompt=extraction_prompt,
            response_format_json=True,
            model_name=SEARCH_MODEL_NAME
        )

        raw_text = str(extraction_result.get("text", "") or "").strip()
        clean_text = (
            raw_text
            .replace("```json", "")
            .replace("```JSON", "")
            .replace("```", "")
            .strip()
        )
        extracted_data = json.loads(clean_text)
        if not isinstance(extracted_data, dict):
            return empty_result

        return {
            "project_summary": (
                str(
                    extracted_data.get(
                        "project_summary",
                        empty_result[
                            "project_summary"
                        ]
                    )
                    or ""
                ).strip()
            ),
            "decision_items": (
                extracted_data.get(
                    "decision_items",
                    empty_result[
                        "decision_items"
                    ]
                )
                or []
            ),
            "considering_items": (
                extracted_data.get(
                    "considering_items",
                    empty_result[
                        "considering_items"
                    ]
                )
                or []
            ),
            "pending_items": (
                extracted_data.get(
                    "pending_items",
                    empty_result[
                        "pending_items"
                    ]
                )
                or []
            ),
            "next_actions": (
                extracted_data.get(
                    "next_actions",
                    empty_result[
                        "next_actions"
                    ]
                )
                or []
            )
        }

    except Exception as e:
        print(
            "計画情報抽出エラー: "
            f"{type(e).__name__}: {e}"
        )

        return empty_result
#================================================

# 既存の計画書と未反映の会話をマージして、新しい計画書全文を作る関数
def generate_merged_plan_document(
    selected_project: dict,
    unreflected_messages: list
) -> dict:
    """
    既存の計画書と未反映の会話を統合し、
    最新の計画書全文を生成する。
    """
    existing_document = str(selected_project.get("plan_document", "") or "").strip()

    conversation_lines = []
    for message in unreflected_messages:
        role = str(message.get("role", "") or "")
        content = str(message.get("content", "") or "").strip()

        if not content:
            continue

        role_label = (
            "ユーザー"
            if role == "user"
            else "AIコンシェルジュ"
        )

        conversation_lines.append(f"{role_label}: {content}")

    conversation_text = (
        "\n\n".join(conversation_lines)
        if conversation_lines
        else "新しく反映する会話はありません。"
    )

    merge_prompt = f"""
    あなたは、会話内容をもとに計画書、設計書、仕様書、検討レポートなどを編集する専門家です。
    既存の計画書と、今回新しく追加された会話を統合し、現時点での最新の計画書全文を作成してください。

    【計画名】
    {selected_project.get("project_name", "")}

    【既存の計画書】
    {existing_document or "まだ計画書はありません。"}

    【今回新しく反映する会話】
    {conversation_text}

    【編集ルール】
    ・計画の種類や会話内容に合わせて、必要な項目名を自由に判断してください。
    ・「決定事項」「検討中」「保留」などの固定された項目へ無理に分類してはいけません。
    ・既存の計画書に有効な内容がある場合は維持してください。
    ・今回の会話で内容が変更された場合は、新しい内容へ更新してください。
    ・同じ内容が複数ある場合は重複を整理してください。
    ・単純な追記ではなく、計画書全体が自然につながるように再編集してください。
    ・ユーザーが明示していない内容を、決定済みの事実として追加してはいけません。
    ・AIコンシェルジュが提案しただけの内容は、ユーザーが同意していない限り、決定済みとして扱ってはいけません。
    ・会話そのものをそのまま書き写さず、計画書として分かりやすく整理してください。
    ・古い内容と新しい内容が矛盾する場合は、ユーザーの最新発言を優先してください。
    ・説明文、前置き、更新報告は不要です。指定されたJSON形式だけを出力してください。
    ・計画書内の【計画名】には、必ず「{selected_project.get("project_name", "")}」を使用してください。
    ・既存の計画書に別の計画名が記載されている場合は、現在の正式な計画名へ更新してください。

    【出力形式】
    ・タイトルと各項目名は、必ず次の形式にしてください。 **【項目名】**
    ・HTMLタグは使用しないでください。「<strong>」「<br>」なども出力しないでください。
    ・既存の計画書にHTMLタグが含まれている場合は、タグを除去してMarkdown形式へ修正してください。
    ・各項目の内容は、必ず次の形式にしてください。
    ・内容
    ・項目名の前には空行を入れてください。
    ・内容が複数ある場合は、1項目につき1行の箇条書きにしてください。
    ・すべての内容行は、行頭を「・」にしてください。
    ・箇条書きの入れ子を作らないでください。
    ・「1.」「2.」「-」「*」は使用しないでください。
    ・候補ごとの詳細も、独立した「・」の行として整理してください。
    ・「#」「##」「###」などのMarkdown見出しは使用しないでください。
    ・番号付きリストは使用しないでください。
    ・手順や優先順位も「・」で簡潔に表現してください。
    ・存在しない情報を埋めるために、「未定」「なし」などを大量に並べてはいけません。

    【出力例】
    **【計画概要】**
    ・計画の目的や全体像

    **【現在の設計方針】**
    ・設計方針の内容
    ・設計方針の内容

    **【今後の作業】**
    ・次に実施する作業

    【短い概要の作成ルール】
    ・計画の目的や対象が分かる短い概要を作成してください。
    ・進捗、決定事項、次の作業などの細かな状況は含めないでください。
    ・計画名をそのまま繰り返すだけの文章にしないでください。
    ・50文字以内を目安にしてください。

    【最終出力形式】
    必ず次のJSON形式だけで出力してください。
    {{
    "document": "更新後の計画書全文",
    "summary": "計画の短い概要"
    }}
    ・documentには、上記の出力形式に従った計画書全文を入れてください。
    ・summaryには、上記の短い概要の作成ルールに従った概要を入れてください。
    ・JSON以外の説明文やMarkdownのコードブロックは出力しないでください。
    """

    try:
        merge_start_time = time.time()
        merge_result = generate_ai_response(
            provider=BACKGROUND_PROVIDER,
            system_instruction="",
            user_prompt=merge_prompt,
            response_format_json=True,
            model_name=SUMMARY_MODEL_NAME
        )
        merge_processing_time = time.time() - merge_start_time

        merge_in_tokens = int(merge_result.get("in_tokens", 0) or 0)
        merge_out_tokens = int(merge_result.get("out_tokens", 0) or 0)
        merge_api_cost = calculate_ai_cost(
            provider=BACKGROUND_PROVIDER,
            in_tokens=merge_in_tokens,
            out_tokens=merge_out_tokens,
            is_chat=False
        )

        merge_text = str(merge_result.get("text", "") or "").strip()

        try:
            merge_output = json.loads(merge_text)
        except Exception:
            merge_output = {"document": merge_text, "summary": ""}

        merged_document = str(merge_output.get("document", "") or "").strip()
        project_summary = str(merge_output.get("summary", "") or "").strip()

        merged_document = re.sub(r"<br\s*/?>", "\n", merged_document, flags=re.IGNORECASE)
        merged_document = re.sub(r"<[^>]+>", "", merged_document)

        if not merged_document:
            merged_document = existing_document

        return {
            "document": merged_document,
            "summary": project_summary,
            "processing_time": merge_processing_time,
            "in_tokens": merge_in_tokens,
            "out_tokens": merge_out_tokens,
            "api_cost": merge_api_cost
        }

    except Exception as e:
        print(
            "計画書マージ生成エラー: "
            f"{type(e).__name__}: {e}"
        )

        return {
            "document": existing_document,
            "summary": str(
                selected_project.get("project_summary", "") or ""
            ).strip(),
            "processing_time": 0.0,
            "in_tokens": 0,
            "out_tokens": 0,
            "api_cost": 0.0
        }
#================================================

# 前回の反映後に追加された計画ルームの会話だけを取得する関数
def get_unreflected_plan_messages(project_id: int, last_reflected_at=None) -> list[dict]:
    """前回の計画反映後に追加された会話を、古い順で取得する。"""
    try:
        all_plan_messages = get_messages(
            CURRENT_USER_ID,
            chat_room="plan",
            plan_project_id=project_id
        )

        if not last_reflected_at:
            return all_plan_messages

        return [
            message
            for message in all_plan_messages
            if str(message.get("created_at", "") or "")
            > str(last_reflected_at)
        ]

    except Exception as e:
        st.error(
            "未反映会話取得エラー: "
            f"{type(e).__name__}: {e}"
        )
        return []
#================================================

# ポイント残高取得関数
def get_user_point_balance(
    user_id: str
) -> dict:
    default_balance = {
        "available_points": 0,
        "lifetime_earned_points": 0,
        "lifetime_used_points": 0,
        "lifetime_expired_points": 0
    }

    try:
        response = (
            supabase
            .table("user_point_balances")
            .select(
                "available_points,"
                "lifetime_earned_points,"
                "lifetime_used_points,"
                "lifetime_expired_points"
            )
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )

        if not response.data:
            return default_balance

        balance_data = response.data[0]

        return {
            "available_points": int(
                balance_data.get(
                    "available_points",
                    0
                ) or 0
            ),
            "lifetime_earned_points": int(
                balance_data.get(
                    "lifetime_earned_points",
                    0
                ) or 0
            ),
            "lifetime_used_points": int(
                balance_data.get(
                    "lifetime_used_points",
                    0
                ) or 0
            ),
            "lifetime_expired_points": int(
                balance_data.get(
                    "lifetime_expired_points",
                    0
                ) or 0
            )
        }

    except Exception as e:
        print(
            "ポイント残高取得エラー: "
            f"{type(e).__name__}: {e}"
        )
        return default_balance
#================================================

# ポイント獲得RPC呼び出し関数
def earn_points(
    user_id: str,
    points: int,
    reason_code: str,
    operation_id: str,
    description: str = "",
    reference_id: str = "",
    expires_at=None
) -> dict:
    default_result = {
        "result_status": "error",
        "current_balance": 0,
        "transaction_id": None
    }

    try:
        response = (
            supabase
            .rpc(
                "earn_user_points",
                {
                    "p_user_id": str(user_id),
                    "p_points": int(points),
                    "p_reason_code": str(reason_code),
                    "p_operation_id": str(operation_id),
                    "p_description": (
                        str(description)
                        if description
                        else None
                    ),
                    "p_reference_id": (
                        str(reference_id)
                        if reference_id
                        else None
                    ),
                    "p_expires_at": expires_at
                }
            )
            .execute()
        )

        if not response.data:
            return default_result

        result = response.data[0]

        return {
            "result_status": str(
                result.get(
                    "result_status",
                    "error"
                ) or "error"
            ),
            "current_balance": int(
                result.get(
                    "current_balance",
                    0
                ) or 0
            ),
            "transaction_id": (
                int(result["transaction_id"])
                if result.get("transaction_id") is not None
                else None
            )
        }

    except Exception as e:
        print(
            "ポイント獲得エラー: "
            f"{type(e).__name__}: {e}"
        )
        return default_result
#================================================

# ポイント消費RPC呼び出し関数
def use_points(
    user_id: str,
    points: int,
    reason_code: str,
    operation_id: str,
    description: str = "",
    reference_id: str = ""
) -> dict:
    default_result = {
        "result_status": "error",
        "current_balance": 0,
        "transaction_id": None
    }

    try:
        response = (
            supabase
            .rpc(
                "use_user_points",
                {
                    "p_user_id": str(user_id),
                    "p_points": int(points),
                    "p_reason_code": str(reason_code),
                    "p_operation_id": str(operation_id),
                    "p_description": (
                        str(description)
                        if description
                        else None
                    ),
                    "p_reference_id": (
                        str(reference_id)
                        if reference_id
                        else None
                    )
                }
            )
            .execute()
        )

        if not response.data:
            return default_result

        result = response.data[0]

        return {
            "result_status": str(
                result.get(
                    "result_status",
                    "error"
                ) or "error"
            ),
            "current_balance": int(
                result.get(
                    "current_balance",
                    0
                ) or 0
            ),
            "transaction_id": (
                int(result["transaction_id"])
                if result.get("transaction_id") is not None
                else None
            )
        }

    except Exception as e:
        print(
            "ポイント消費エラー: "
            f"{type(e).__name__}: {e}"
        )
        return default_result
#================================================

# ポイント失効RPC呼び出し関数
def expire_points(
    user_id: str,
    operation_id: str
) -> dict:
    default_result = {
        "result_status": "error",
        "expired_points": 0,
        "current_balance": 0,
        "transaction_id": None
    }

    try:
        response = (
            supabase
            .rpc(
                "expire_user_points",
                {
                    "p_user_id": str(user_id),
                    "p_operation_id": str(operation_id)
                }
            )
            .execute()
        )

        if not response.data:
            return default_result

        result = response.data[0]

        return {
            "result_status": str(
                result.get(
                    "result_status",
                    "error"
                ) or "error"
            ),
            "expired_points": int(
                result.get(
                    "expired_points",
                    0
                ) or 0
            ),
            "current_balance": int(
                result.get(
                    "current_balance",
                    0
                ) or 0
            ),
            "transaction_id": (
                int(result["transaction_id"])
                if result.get("transaction_id") is not None
                else None
            )
        }

    except Exception as e:
        print(
            "ポイント失効エラー: "
            f"{type(e).__name__}: {e}"
        )
        return default_result
#================================================

# ポイント商品を購入する関数
def purchase_point_product(
    user_id: str,
    product_code: str,
    operation_id: str
) -> dict:
    default_result = {
        "result_status": "error",
        "current_balance": 0,
        "transaction_id": None,
        "entitlement_code": "",
        "entitlement_expires_at": None
    }

    try:
        response = (
            supabase
            .rpc(
                "purchase_point_product",
                {
                    "p_user_id": str(user_id),
                    "p_product_code": str(product_code),
                    "p_operation_id": str(operation_id)
                }
            )
            .execute()
        )

        if not response.data:
            return default_result

        result = response.data[0]

        return {
            "result_status": str(
                result.get(
                    "result_status",
                    "error"
                ) or "error"
            ),
            "current_balance": int(
                result.get(
                    "current_balance",
                    0
                ) or 0
            ),
            "transaction_id": (
                int(result["transaction_id"])
                if result.get("transaction_id") is not None
                else None
            ),
            "entitlement_code": str(
                result.get(
                    "entitlement_code",
                    ""
                ) or ""
            ),
            "entitlement_expires_at": result.get(
                "entitlement_expires_at"
            )
        }

    except Exception as e:
        print(
            "ポイント商品購入エラー: "
            f"{type(e).__name__}: {e}"
        )
        return default_result 
#================================================

# 有料人格パスが有効かを取得する関数
def get_active_entitlement(
    user_id: str,
    entitlement_code: str
) -> dict:
    default_result = {
        "is_active": False,
        "entitlement_code": str(entitlement_code),
        "quantity": 0,
        "starts_at": None,
        "expires_at": None,
        "source_product_code": ""
    }

    try:
        response = (
            supabase
            .table("user_entitlements")
            .select(
                "entitlement_code,"
                "quantity,"
                "starts_at,"
                "expires_at,"
                "status,"
                "source_product_code"
            )
            .eq(
                "user_id",
                str(user_id)
            )
            .eq(
                "entitlement_code",
                str(entitlement_code)
            )
            .eq(
                "status",
                "active"
            )
            .limit(1)
            .execute()
        )

        if not response.data:
            return default_result

        entitlement = response.data[0]
        expires_at = entitlement.get("expires_at")

        if not expires_at:
            return default_result

        try:
            expiration_datetime = datetime.fromisoformat(
                str(expires_at).replace(
                    "Z",
                    "+00:00"
                )
            )

            now_datetime = datetime.now(
                expiration_datetime.tzinfo
            )

            if expiration_datetime <= now_datetime:
                return default_result

        except Exception:
            return default_result

        return {
            "is_active": True,
            "entitlement_code": str(
                entitlement.get(
                    "entitlement_code",
                    entitlement_code
                ) or entitlement_code
            ),
            "quantity": int(
                entitlement.get(
                    "quantity",
                    0
                ) or 0
            ),
            "starts_at": entitlement.get(
                "starts_at"
            ),
            "expires_at": expires_at,
            "source_product_code": str(
                entitlement.get(
                    "source_product_code",
                    ""
                ) or ""
            )
        }

    except Exception as e:
        print(
            "購入済み権利取得エラー: "
            f"{type(e).__name__}: {e}"
        )
        return default_result
#================================================

# 購入可能な人格パス商品を取得する関数
def get_point_products(
    product_category: str = ""
) -> list[dict]:
    try:
        query = (
            supabase
            .table("point_products")
            .select(
                "product_code,"
                "product_name,"
                "product_description,"
                "product_category,"
                "point_cost,"
                "entitlement_code,"
                "duration_days,"
                "quantity,"
                "display_order"
            )
            .eq("is_enabled", True)
            .eq("is_visible", True)
        )

        if product_category:
            query = query.eq(
                "product_category",
                product_category
            )

        response = (
            query
            .order("display_order")
            .execute()
        )

        return response.data or []

    except Exception as e:
        print(
            "ポイント商品取得エラー: "
            f"{type(e).__name__}: {e}"
        )
        return []
#================================================

# 有料人格パスの購入ダイアログ関数
@st.dialog("💎 有料人格パス")
def show_personality_pass_dialog():
    point_balance = get_user_point_balance(
        CURRENT_USER_ID
    )

    available_points = int(
        point_balance.get(
            "available_points",
            0
        ) or 0
    )

    st.markdown(
        f"**現在の保有ポイント："
        f"{available_points:,}pt**"
    )

    st.caption(
        "有料人格パスの有効期間中は、"
        "すべての💎付き人格を自由に利用できます。"
    )

    personality_products = get_point_products(
        "personality"
    )

    if not personality_products:
        st.info(
            "現在購入できる有料人格パスはありません。"
        )
        return

    for product in personality_products:
        product_code = str(
            product.get("product_code", "") or ""
        )

        product_name = str(
            product.get("product_name", "") or ""
        )

        product_description = str(
            product.get(
                "product_description",
                ""
            ) or ""
        )

        point_cost = int(
            product.get("point_cost", 0) or 0
        )

        st.markdown(f"**{product_name}**")

        if product_description:
            st.caption(product_description)

        if available_points < point_cost:
            st.button(
                f"{point_cost:,}ptで購入",
                key=f"buy_personality_{product_code}",
                disabled=True,
                use_container_width=True
            )

            st.caption(
                f"ポイントが"
                f"{point_cost - available_points:,}pt"
                f"不足しています。"
            )

        else:
            if st.button(
                f"{point_cost:,}ptで購入",
                key=f"buy_personality_{product_code}",
                use_container_width=True
            ):
                operation_id = (
                    f"point_purchase_"
                    f"{CURRENT_USER_ID}_"
                    f"{product_code}_"
                    f"{uuid.uuid4().hex}"
                )

                purchase_result = (
                    purchase_point_product(
                        user_id=CURRENT_USER_ID,
                        product_code=product_code,
                        operation_id=operation_id
                    )
                )

                result_status = str(
                    purchase_result.get(
                        "result_status",
                        "error"
                    ) or "error"
                )

                if result_status == "purchased":
                    st.session_state[
                        "point_purchase_success"
                    ] = {
                        "product_name": product_name,
                        "current_balance": int(
                            purchase_result.get(
                                "current_balance",
                                0
                            ) or 0
                        ),
                        "expires_at": (
                            purchase_result.get(
                                "entitlement_expires_at"
                            )
                        )
                    }

                    st.rerun()

                elif result_status == "insufficient_points":
                    st.warning(
                        "ポイントが不足しています。"
                    )

                elif result_status == "already_processed":
                    st.info(
                        "この購入処理はすでに完了しています。"
                    )

                elif result_status == "product_disabled":
                    st.warning(
                        "現在、この商品は購入できません。"
                    )

                elif result_status == "product_not_found":
                    st.error(
                        "購入商品を確認できませんでした。"
                    )

                else:
                    st.error(
                        "有料人格パスを購入できませんでした。"
                    )

        st.divider()
#================================================

# ポイント履歴取得関数
def get_point_transactions(user_id: str, limit: int = 50) -> list[dict]:
    try:
        safe_limit = max(1, min(int(limit), 100))

        response = (
            supabase
            .table("point_transactions")
            .select(
                "id,"
                "transaction_type,"
                "points,"
                "balance_after,"
                "reason_code,"
                "description,"
                "reference_id,"
                "operation_id,"
                "expires_at,"
                "created_at"
            )
            .eq("user_id", str(user_id))
            .order("created_at", desc=True)
            .limit(safe_limit)
            .execute()
        )

        return response.data or []

    except Exception as e:
        print(
            "ポイント履歴取得エラー: "
            f"{type(e).__name__}: {e}"
        )
        return []
#================================================

# 詳細処理の確認ダイアログ関数
@st.dialog("詳細回答の確認")
def show_detail_confirmation_dialog(detail_request: dict):
    detailed_processing_type = str(
        detail_request.get("detailed_processing_type", "") or ""
    ).strip()
    point_cost = int(detail_request.get("point_cost", 0) or 0)

    point_balance = get_user_point_balance(CURRENT_USER_ID)
    available_points = int(
        point_balance.get("available_points", 0) or 0
    )
    balance_after = max(0, available_points - point_cost)

    detail_type_labels = {
        "detailed_search": "詳細検索",
        "detailed_analysis": "詳細Analysis",
        "detailed_search_analysis": "検索付き詳細Analysis"
    }
    detail_type_label = detail_type_labels.get(
        detailed_processing_type,
        "詳細回答"
    )

    st.write(f"{detail_type_label}を実行しますか？")
    st.caption(
        "元の質問と簡易回答をもとに、"
        "より詳しい回答を作成します。"
    )

    point_col_1, point_col_2 = st.columns(2)

    with point_col_1:
        st.metric("必要ポイント", f"{point_cost:,}pt")

    with point_col_2:
        st.metric("現在のポイント", f"{available_points:,}pt")

    st.divider()
    st.markdown("##### 🎬 ポイントを増やす")

    reward_ad_status = check_reward_ad_eligibility(
        user_id=CURRENT_USER_ID,
        placement_code="detail_confirmation_reward"
    )

    reward_ad_result_status = str(
        reward_ad_status.get("result_status", "error") or "error"
    )
    placement_rewarded_count = int(
        reward_ad_status.get("placement_rewarded_count", 0) or 0
    )
    placement_daily_limit = int(
        reward_ad_status.get("placement_daily_limit", 10) or 10
    )
    cooldown_remaining_seconds = int(
        reward_ad_status.get("cooldown_remaining_seconds", 0) or 0
    )

    st.caption(
        f"動画広告を最後まで視聴すると、"
        f"{POINT_REWARDED_AD}pt獲得できます。"
    )

    st.caption(
        f"本日の視聴："
        f"{placement_rewarded_count} / "
        f"{placement_daily_limit}回"
    )

    if reward_ad_result_status == "cooldown_active":
        cooldown_minutes = cooldown_remaining_seconds // 60
        cooldown_seconds = cooldown_remaining_seconds % 60

        st.caption(
            f"次回視聴まで："
            f"{cooldown_minutes:02d}:"
            f"{cooldown_seconds:02d}"
        )

    elif reward_ad_result_status == "placement_daily_limit_reached":
        st.caption("この画面からの本日の視聴上限に達しています。")

    elif reward_ad_result_status == "total_daily_limit_reached":
        st.caption("本日の動画広告の視聴上限に達しています。")

    elif reward_ad_result_status == "error":
        st.caption("広告の視聴状況を確認できませんでした。")

    st.button(
        f"🎬 動画を視聴して{POINT_REWARDED_AD}pt獲得",
        key="watch_reward_ad_detail_confirmation",
        use_container_width=True,
        disabled=True,
        help="リワード広告はFlutter移植時に接続予定です。"
    )

    st.caption("現在は広告機能の準備中です。")
    st.divider()

    if available_points >= point_cost:
        st.info(f"処理後の残高は{balance_after:,}ptです。")

        cancel_col, start_col = st.columns(2)

        with cancel_col:
            if st.button(
                "キャンセル",
                key="cancel_detail_confirmation",
                use_container_width=True
            ):
                st.session_state["pending_detail_request"] = {}
                st.session_state["detail_confirmation_open"] = False
                st.session_state["detail_request_processing"] = False
                st.rerun()

        with start_col:
            if st.button(
                f"{point_cost:,}ptを使って開始",
                key="start_detail_processing",
                type="primary",
                use_container_width=True
            ):
                st.session_state["detail_confirmation_open"] = False
                st.session_state["detail_request_processing"] = True
                st.rerun()

    else:
        shortage_points = point_cost - available_points

        st.warning(
            f"ポイントが不足しています。"
            f"あと{shortage_points:,}pt必要です。"
        )

        if st.button(
            "閉じる",
            key="close_detail_confirmation",
            use_container_width=True
        ):
            st.session_state["pending_detail_request"] = {}
            st.session_state["detail_confirmation_open"] = False
            st.session_state["detail_request_processing"] = False
            st.rerun()
#================================================

# ポイント詳細・履歴ダイアログ関数
@st.dialog("ポイント詳細")
def show_point_detail_dialog():
    point_balance = get_user_point_balance(CURRENT_USER_ID)
    available_points = int(point_balance.get("available_points", 0) or 0)
    lifetime_earned_points = int(point_balance.get("lifetime_earned_points", 0) or 0)
    lifetime_used_points = int(point_balance.get("lifetime_used_points", 0) or 0)
    lifetime_expired_points = int(point_balance.get("lifetime_expired_points", 0) or 0)

    detail_tab, shop_tab = st.tabs([
        "詳細",
        "ショップ"
    ])

    with detail_tab:
        st.markdown(f"**保有ポイント：{available_points:,}pt**")
        balance_col, used_col, expired_col = st.columns(3)

        with balance_col:
            st.caption("累計獲得")
            st.markdown(f"**{lifetime_earned_points:,}pt**")

        with used_col:
            st.caption("累計使用")
            st.markdown(f"**{lifetime_used_points:,}pt**")

        with expired_col:
            st.caption("累計失効")
            st.markdown(f"**{lifetime_expired_points:,}pt**")

        active_entitlements = get_active_entitlements(CURRENT_USER_ID)
        active_entitlement_grants = (
            get_active_entitlement_grants(
                CURRENT_USER_ID
            )
        )
        if active_entitlements:
            st.divider()
            st.markdown("#### ✅ 利用中の機能")

            entitlement_labels = {
                "premium_personality": "有料人格パス",
                "ad_free": "広告OFF"
            }

            for entitlement in active_entitlements:
                entitlement_code = str(entitlement.get("entitlement_code", "") or "")

                entitlement_label = entitlement_labels.get(
                    entitlement_code,
                    entitlement_code
                )

                quantity = int(entitlement.get("quantity", 0) or 0)
                expires_at = entitlement.get("expires_at")

                formatted_expires_at = ""
                if expires_at:
                    try:
                        expiration_datetime = (
                            datetime.fromisoformat(
                                str(expires_at).replace(
                                    "Z",
                                    "+00:00"
                                )
                            )
                            .astimezone(JST)
                        )

                        formatted_expires_at = (
                            expiration_datetime.strftime("%Y年%m月%d日 %H:%M")
                        )

                    except Exception:
                        formatted_expires_at = str(expires_at)

                entitlement_detail = ""

                if entitlement_code == "ad_free":
                    entitlement_detail = ("通常広告を非表示")

                elif entitlement_code == "premium_personality":
                    entitlement_detail = ("すべての💎付き人格を利用可能")

                st.markdown(f"**{entitlement_label}**")
                if entitlement_detail:
                    st.caption(
                        f"{entitlement_detail}"
                        f"｜有効期限：{formatted_expires_at}"
                    )
                else:
                    st.caption(
                        f"有効期限：{formatted_expires_at}"
                    )
        
        if active_entitlement_grants:
            if not active_entitlements:
                st.divider()
                st.markdown("#### ✅ 利用中の機能")

            grant_labels = {
                "saved_chat_plus": "会話保存枠追加",
                "daily_chat_plus": "1日の会話上限追加"
            }

            for grant in active_entitlement_grants:
                entitlement_code = str(
                    grant.get("entitlement_code", "") or ""
                )

                entitlement_label = grant_labels.get(
                    entitlement_code,
                    entitlement_code
                )

                quantity = int(grant.get("quantity", 0) or 0)
                expires_at = grant.get("expires_at")
                formatted_expires_at = ""

                if expires_at:
                    try:
                        expiration_datetime = (
                            datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")
                            )
                            .astimezone(JST)
                        )

                        formatted_expires_at = (
                            expiration_datetime.strftime("%Y年%m月%d日 %H:%M")
                        )

                    except Exception:
                        formatted_expires_at = str(expires_at)

                if entitlement_code == "saved_chat_plus":
                    entitlement_detail = (f"保存上限＋{quantity}件")

                elif entitlement_code == "daily_chat_plus":
                    entitlement_detail = (f"1日の会話上限＋{quantity}回")

                else:
                    entitlement_detail = (f"追加数量：{quantity}")

                st.markdown(f"**{entitlement_label}**")

                st.caption(
                    f"{entitlement_detail}"
                    f"｜有効期限：{formatted_expires_at}"
                )

        st.divider()
        st.markdown("#### 🎬 ポイントを獲得")

        reward_ad_status = check_reward_ad_eligibility(
            user_id=CURRENT_USER_ID,
            placement_code="point_detail_reward"
        )

        reward_ad_result_status = str(
            reward_ad_status.get("result_status", "error") or "error"
        )

        placement_rewarded_count = int(
            reward_ad_status.get("placement_rewarded_count", 0) or 0
        )

        total_rewarded_count = int(
            reward_ad_status.get("total_rewarded_count", 0) or 0
        )

        placement_daily_limit = int(
            reward_ad_status.get("placement_daily_limit", 10) or 10
        )

        total_daily_limit = int(
            reward_ad_status.get("total_daily_limit", 20) or 20
        )

        cooldown_remaining_seconds = int(
            reward_ad_status.get("cooldown_remaining_seconds", 0) or 0
        )

        st.caption(
            "動画広告を最後まで視聴すると、"
            f"{POINT_REWARDED_AD}pt獲得できます。"
        )

        st.caption(
            f"この画面での本日の視聴："
            f"{placement_rewarded_count} / "
            f"{placement_daily_limit}回"
            f"　｜　全体："
            f"{total_rewarded_count} / "
            f"{total_daily_limit}回"
        )

        if reward_ad_result_status == "cooldown_active":
            cooldown_minutes = (cooldown_remaining_seconds // 60)
            cooldown_seconds = (cooldown_remaining_seconds % 60)

            st.caption(
                f"次回視聴まで："
                f"{cooldown_minutes:02d}:"
                f"{cooldown_seconds:02d}"
            )

        elif reward_ad_result_status == ("placement_daily_limit_reached"):
            st.caption("この画面からの本日の視聴上限に達しています。")

        elif reward_ad_result_status == ("total_daily_limit_reached"):
            st.caption("本日の動画広告の視聴上限に達しています。")

        elif reward_ad_result_status == "error":
            st.caption("広告の視聴状況を確認できませんでした。")

        st.button(
            f"🎬 動画を視聴して"
            f"{POINT_REWARDED_AD}pt獲得",
            key="watch_reward_ad_point_detail",
            use_container_width=True,
            disabled=True,
            help=("リワード広告はFlutter移植時に接続予定です。")
        )

        st.caption("現在は広告機能の準備中です。")
        st.divider()
        
        st.markdown("#### 📖 ポイント履歴")
        point_transactions = get_point_transactions(CURRENT_USER_ID, limit=50)

        if not point_transactions:
            st.caption("まだポイント履歴はありません。")
            return

        transaction_labels = {
            "earn": "獲得",
            "use": "使用",
            "expire": "失効",
            "adjust": "調整"
        }

        reason_labels = {
            "initial_registration": "初回登録",
            "rewarded_ad": "動画広告視聴",
            "point_product_purchase": "ポイント商品購入",
            "point_expiration": "有効期限切れ",
            "admin_adjustment": "運営による調整",
            "initial_test_reward": "テストポイント付与"
        }

        for transaction in point_transactions:
            transaction_type = str(transaction.get("transaction_type", "") or "")
            points = int(transaction.get("points", 0) or 0)
            balance_after = int(transaction.get("balance_after", 0) or 0)
            reason_code = str(transaction.get("reason_code", "") or "")
            description = str(transaction.get("description", "") or "").strip()
            created_at = transaction.get("created_at")

            formatted_created_at = ""

            if created_at:
                try:
                    created_datetime = (
                        datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
                        .astimezone(JST)
                    )

                    formatted_created_at = (
                        created_datetime.strftime("%Y/%m/%d %H:%M")
                    )

                except Exception:
                    formatted_created_at = str(created_at)

            type_label = transaction_labels.get(transaction_type, transaction_type)
            reason_label = reason_labels.get(reason_code, description or reason_code)

            point_text = (
                f"+{points:,}pt"
                if points > 0
                else f"{points:,}pt"
            )

            st.markdown(
                f"**{formatted_created_at}｜"
                f"{type_label} {point_text}**"
            )

            if reason_label:
                st.caption(
                    f"{reason_label}"
                    f"｜処理後残高：{balance_after:,}pt"
                )
            else:
                st.caption(f"処理後残高：{balance_after:,}pt")
        st.divider()

    with shop_tab:
        st.markdown(f"**保有ポイント：{available_points:,}pt**")

        st.markdown("#### 🛍️ ポイントで機能を購入")

        point_products = get_point_products()

        if not point_products:
            st.caption("現在購入できるポイント商品はありません。")

        else:
            for product in point_products:
                product_code = str(product.get("product_code", "") or "")
                product_name = str(product.get("product_name", "") or "")
                product_description = str(product.get("product_description", "") or "")
                point_cost = int(product.get("point_cost", 0) or 0)
                st.markdown(f"**{product_name}**")

                if product_description:
                    st.caption(product_description)

                can_purchase = (available_points >= point_cost)

                if st.button(
                    f"{point_cost:,}ptで購入",
                    key=f"buy_point_product_{product_code}",
                    disabled=not can_purchase,
                    use_container_width=True
                ):
                    operation_id = (
                        f"point_purchase_"
                        f"{CURRENT_USER_ID}_"
                        f"{product_code}_"
                        f"{uuid.uuid4().hex}"
                    )

                    purchase_result = purchase_point_product(
                        user_id=CURRENT_USER_ID,
                        product_code=product_code,
                        operation_id=operation_id
                    )

                    result_status = str(
                        purchase_result.get("result_status", "error") or "error"
                    )

                    if result_status == "purchased":
                        st.toast(f"✅ {product_name}を購入しました")
                        st.rerun()

                    elif result_status == "insufficient_points":
                        st.warning("ポイントが不足しています。")

                    elif result_status == "already_processed":
                        st.info("この購入処理はすでに完了しています。")

                    elif result_status == "product_disabled":
                        st.warning("現在、この商品は購入できません。")

                    elif result_status == "product_not_found":
                        st.error("購入商品を確認できませんでした。")

                    else:
                        st.error("ポイント商品を購入できませんでした。")

                if not can_purchase:
                    st.caption(
                        f"あと"
                        f"{point_cost - available_points:,}pt"
                        f"必要です。"
                    )

                st.divider()
        
#================================================

# 購入済み権利を取得する関数
def get_active_entitlements(user_id: str) -> list[dict]:
    try:
        now_iso = datetime.now(JST).isoformat()

        response = (
            supabase
            .table("user_entitlements")
            .select(
                "entitlement_code,"
                "quantity,"
                "starts_at,"
                "expires_at,"
                "status,"
                "source_product_code,"
                "updated_at"
            )
            .eq("user_id", str(user_id))
            .eq("status", "active")
            .gt("expires_at", now_iso)
            .order("expires_at", desc=False)
            .execute()
        )

        return response.data or []

    except Exception as e:
        print(
            "購入済み権利一覧取得エラー: "
            f"{type(e).__name__}: {e}"
        )
        return []
#================================================

# 基本上限と追加枠を合計する関数
def get_effective_saved_chat_limit(user_id: str, plan_code: str) -> int:
    
    plan_features = get_plan_features(plan_code)
    base_limit = int(plan_features.get("saved_chat_limit", 0) or 0)

    additional_limit = (
        get_active_entitlement_grant_total(
            user_id=user_id,
            entitlement_code="saved_chat_plus"
        )
    )

    return max(0, base_limit + additional_limit)
#================================================

# 追加枠の合計を取得する関数
def get_active_entitlement_grant_total(
    user_id: str,
    entitlement_code: str
) -> int:
    try:
        response = (
            supabase
            .rpc(
                "get_active_entitlement_grant_total",
                {
                    "p_user_id": str(user_id),
                    "p_entitlement_code": str(
                        entitlement_code
                    )
                }
            )
            .execute()
        )

        return int(response.data or 0)

    except Exception as e:
        print(
            "追加権利数量取得エラー: "
            f"{type(e).__name__}: {e}"
        )
        return 0
#================================================

# 実効会話上限を取得する関数
def get_effective_daily_chat_limit(user_id: str, plan_code: str) -> int:
    
    plan_features = get_plan_features(plan_code)
    base_limit = int(plan_features.get("daily_chat_limit", 0) or 0)

    additional_limit = (
        get_active_entitlement_grant_total(
            user_id=user_id,
            entitlement_code="daily_chat_plus"
        )
    )

    return max(0, base_limit + additional_limit)
#================================================

# 広告OFF権利の判定関数
def is_native_ad_enabled(user_id: str, plan_code: str) -> bool:
    
    plan_features = get_plan_features(plan_code)
    ad_free_by_default = bool(plan_features.get("ad_free_by_default", False))

    if ad_free_by_default:
        return False

    ad_free_entitlement = get_active_entitlement(
        user_id=user_id,
        entitlement_code="ad_free"
    )

    if ad_free_entitlement.get("is_active", False):
        return False

    return True
#================================================

# 購入単位の追加権利を取得する関数
def get_active_entitlement_grants(user_id: str) -> list[dict]:
    try:
        response = (
            supabase .table("user_entitlement_grants")
            .select(
                "id,"
                "entitlement_code,"
                "quantity,"
                "starts_at,"
                "expires_at,"
                "status,"
                "source_product_code,"
                "source_transaction_id,"
                "created_at"
            )
            .eq("user_id", str(user_id))
            .eq("status", "active")
            .order("expires_at", desc=False)
            .execute()
        )

        active_grants = []
        now_jst = datetime.now(JST)

        for grant in response.data or []:
            starts_at = grant.get("starts_at")
            expires_at = grant.get("expires_at")

            if not starts_at or not expires_at:
                continue

            try:
                starts_datetime = (
                    datetime.fromisoformat(str(starts_at).replace("Z", "+00:00"))
                    .astimezone(JST)
                )

                expires_datetime = (
                    datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                    .astimezone(JST)
                )

                if (starts_datetime <= now_jst and expires_datetime > now_jst):
                    active_grants.append(grant)

            except Exception as date_error:
                print(
                    "追加権利日時解析エラー: "
                    f"{type(date_error).__name__}: "
                    f"{date_error}"
                )

        return active_grants

    except Exception as e:
        print(
            "追加権利一覧取得エラー: "
            f"{type(e).__name__}: {e}"
        )
        return []
#================================================

# Python側からリワード広告RPCを呼ぶ関数
def check_reward_ad_eligibility(user_id: str, placement_code: str) -> dict:
    
    default_result = {
        "is_allowed": False,
        "result_status": "error",
        "placement_rewarded_count": 0,
        "total_rewarded_count": 0,
        "cooldown_remaining_seconds": 0,
        "placement_daily_limit": 10,
        "total_daily_limit": 20
    }

    try:
        response = (
            supabase
            .rpc(
                "check_reward_ad_eligibility",
                {
                    "p_user_id": str(user_id),
                    "p_placement_code": str(
                        placement_code
                    )
                }
            )
            .execute()
        )

        if not response.data:
            return default_result

        result = response.data[0]

        return {
            "is_allowed": bool(result.get("is_allowed", False)),
            "result_status": str(
                result.get("result_status", "error") or "error"
            ),
            "placement_rewarded_count": int(
                result.get("placement_rewarded_count", 0) or 0
            ),
            "total_rewarded_count": int(
                result.get("total_rewarded_count", 0) or 0
            ),
            "cooldown_remaining_seconds": int(
                result.get("cooldown_remaining_seconds", 0) or 0
            ),
            "placement_daily_limit": int(
                result.get("placement_daily_limit", 10) or 10
            ),
            "total_daily_limit": int(result.get("total_daily_limit", 20) or 20)
        }

    except Exception as e:
        print(
            "リワード広告視聴可否確認エラー: "
            f"{type(e).__name__}: {e}"
        )
        return default_result
#================================================

# 広告視聴開始を登録するPython関数
def start_reward_ad_view(
    user_id: str,
    ad_view_id: str,
    placement_code: str
) -> dict:
    default_result = {
        "result_status": "error",
        "ad_view_row_id": None,
        "ad_view_id": str(ad_view_id),
        "placement_code": str(placement_code),
        "placement_rewarded_count": 0,
        "total_rewarded_count": 0,
        "cooldown_remaining_seconds": 0
    }

    try:
        response = (
            supabase
            .rpc(
                "start_reward_ad_view",
                {
                    "p_user_id": str(user_id),
                    "p_ad_view_id": str(ad_view_id),
                    "p_placement_code": str(
                        placement_code
                    )
                }
            )
            .execute()
        )

        if not response.data:
            return default_result

        result = response.data[0]

        return {
            "result_status": str(result.get("result_status", "error") or "error"),
            "ad_view_row_id": (
                int(result["ad_view_row_id"])
                if result.get(
                    "ad_view_row_id"
                ) is not None
                else None
            ),
            "ad_view_id": str(
                result.get(
                    "ad_view_id",
                    ad_view_id
                ) or ad_view_id
            ),
            "placement_code": str(
                result.get(
                    "placement_code",
                    placement_code
                ) or placement_code
            ),
            "placement_rewarded_count": int(
                result.get(
                    "placement_rewarded_count",
                    0
                ) or 0
            ),
            "total_rewarded_count": int(
                result.get(
                    "total_rewarded_count",
                    0
                ) or 0
            ),
            "cooldown_remaining_seconds": int(
                result.get(
                    "cooldown_remaining_seconds",
                    0
                ) or 0
            )
        }

    except Exception as e:
        print(
            "リワード広告視聴開始エラー: "
            f"{type(e).__name__}: {e}"
        )
        return default_result
#================================================

# 広告視聴完了と5pt付与を呼び出すPython関数
def complete_reward_ad_view(user_id: str, ad_view_id: str) -> dict:
    
    default_result = {
        "result_status": "error",
        "reward_points": 0,
        "current_balance": 0,
        "transaction_id": None,
        "rewarded_at": None
    }

    try:
        response = (
            supabase
            .rpc(
                "complete_reward_ad_view",
                {
                    "p_user_id": str(user_id),
                    "p_ad_view_id": str(ad_view_id)
                }
            )
            .execute()
        )

        if not response.data:
            return default_result

        result = response.data[0]

        return {
            "result_status": str(
                result.get(
                    "result_status",
                    "error"
                ) or "error"
            ),
            "reward_points": int(
                result.get(
                    "reward_points",
                    0
                ) or 0
            ),
            "current_balance": int(
                result.get(
                    "current_balance",
                    0
                ) or 0
            ),
            "transaction_id": (
                int(result["transaction_id"])
                if result.get("transaction_id") is not None
                else None
            ),
            "rewarded_at": result.get(
                "rewarded_at"
            )
        }

    except Exception as e:
        print(
            "リワード広告視聴完了エラー: "
            f"{type(e).__name__}: {e}"
        )
        return default_result
#================================================

# 初回登録250ptの付与基盤関数
def grant_initial_registration_points(user_id: str) -> dict:
    
    normalized_user_id = str(user_id or "").strip()

    if not normalized_user_id:
        return {
            "result_status": "invalid_user_id",
            "current_balance": 0,
            "transaction_id": None
        }

    return earn_points(
        user_id=normalized_user_id,
        points=POINT_INITIAL_REGISTRATION,
        reason_code="initial_registration",
        operation_id=(
            f"initial_registration:"
            f"{normalized_user_id}"
        ),
        description="初回登録特典",
        reference_id=normalized_user_id,
        expires_at=None
    )
#================================================

# 処理区分別集計RPCを呼び出す関数
def get_user_processing_type_summary(
    user_id: str,
    start_at=None,
    end_at=None
) -> list:
    try:
        rpc_params = {"p_user_id": str(user_id)}

        if start_at is not None:
            rpc_params["p_start_at"] = (
                start_at.isoformat()
                if hasattr(start_at, "isoformat")
                else str(start_at)
            )

        if end_at is not None:
            rpc_params["p_end_at"] = (
                end_at.isoformat()
                if hasattr(end_at, "isoformat")
                else str(end_at)
            )

        response = (
            supabase
            .rpc("get_user_processing_type_total_summary", rpc_params)
            .execute()
        )

        return response.data or []

    except Exception as e:
        print(
            "処理区分別集計取得エラー: "
            f"{type(e).__name__}: {e}"
        )
        return []
#================================================

# 🎨グラデーションカラーパレット
THEMES = {
     "パステル": {
        # 🌸 【劇的強化】 柔らかなコーラルピンク（#FFF5F5）から、鮮やかなマゼンタ系ピンク（#FFB7B2）へのロマンチックグラデ
        "bg": "linear-gradient(180deg, #FFF5F5 0%, #FFD1D1 50%, #FFB7B2 100%)",
        "text": "#4A1525",        # より深みを増した濃厚ベリー文字
        "card_bg": "#FEFCBF",     # 優しいパステルイエローのカード
        "input_border": "#ED64A6",# 華やかなローズピンク
        "dropdown_bg": "#FFF5F7",
        "dropdown_text": "#4A1525"
    },
    "レインボーポップ": {
        # 🟢 【大開通！】 7色のパステルカラーが斜めに美しく溶け合う、圧倒的な遊び心のレインボー背景です！
        "bg": "linear-gradient(135deg, #FFB7B2 0%, #FFDAC1 20%, #E2F0CB 40%, #B5EAD7 60%, #C7CEEA 80%, #FFB7B2 100%)",
        "text": "#1A1A1A",                         # 文字がボヤけないように引き締まった墨色
        "card_bg": "rgba(255, 255, 255, 0.75)",      # 白い吹き出しを75%シースルーにして、裏のレインボーを美しく大露出！
        "input_border": "#3B82F6",
        "dropdown_bg": "#FFFFFF",
        "dropdown_text": "#1A1A1A"
    },
    "メタリック": {
        # 🟢 【完全死守】 リュウさんお気に入りの、本物の削り出しチタンシルバーの比率は1ミリも変えずに100%残します！
        "bg": "linear-gradient(135deg, #E0E0E0 0%, #F5F5F5 25%, #BEBEBE 50%, #9E9E9E 75%, #E0E0E0 100%)",
        "text": "#1A1A1A",
        "card_bg": "rgba(255, 255, 255, 0.85)",
        "input_border": "#757575",
        "dropdown_bg": "#E0E0E0",
        "dropdown_text": "#1A1A1A"
    },
    "ホワイト": {
        "bg": "linear-gradient(135deg, #E6E8EB 0%, #F5F7FA 35%, #FFFFFF 70%, #E6E8EB 100%)",    # 純白の最軽量クリーン背景
        "text": "#31333F",                  # Streamlit標準の最も目に優しい濃厚な墨色文字
        "card_bg": "#F0F2F6",               # 過去ログの吹き出しを美しく引き立たせる薄いグレー
        "input_border": "#CCA300",          # ハヤト（沙也加）のアイコンと直結する狐色のアクセント線
        "dropdown_bg": "#FFFFFF",           # プルダウンの背景もクリーンに白
        "dropdown_text": "#31333F"          # プルダウンの文字も濃厚な墨色
    },
    "オーシャン": {
        # 🌊 【劇的強化】 白波のようなライトブルー（#E3F2FD）から、深海のディープブルー（#64B5F6）へ深く沈み込むグラデ
        "bg": "linear-gradient(180deg, #E3F2FD 0%, #90CDF4 50%, #64B5F6 100%)",
        "text": "#0A2540",        # コントラストをさらに強めた超濃紺文字
        "card_bg": "#FFFFFF",     # 真っ白な砂浜のカード
        "input_border": "#4299E1",# 鮮やかなオーシャンブルー
        "dropdown_bg": "#EDF2F7",
        "dropdown_text": "#0A2540"
    },
    "フォレスト": {
        # 🌳 【劇的強化】 爽やかな若葉色（#E8F5E9）から、どっしりとした深い木々の緑（#A5D6A7）へのディープグラデ
        "bg": "linear-gradient(180deg, #E8F5E9 0%, #A5D6A7 100%)",
        "text": "#0D2B0D",        # 森の奥深くをイメージした超濃緑文字
        "card_bg": "#FFFFFF",     # 綺麗な木漏れ日の白カード
        "input_border": "#48BB78",# 新緑の森林グリーン
        "dropdown_bg": "#F4FBF4",
        "dropdown_text": "#0D2B0D"
    },
    "ウォーム": {
        # 🔥 【劇的強化】 燃える夕焼け橙（#FFF5F0）から、情熱の茜色・トワイライトレッド（#FF8A65）への超グラデ
        "bg": "linear-gradient(180deg, #FFF5F0 0%, #FFAB91 50%, #FF8A65 100%)",
        "text": "#5C0F08",        # 煉獄の芯を表すドッシリとした超濃赤文字
        "card_bg": "#FFEBEE",     # 温かみのある緋色のカード
        "input_border": "#E53E3E",# 情熱的なファイヤーレッド
        "dropdown_bg": "#FFEBEE",
        "dropdown_text": "#5C0F08"
    },
    "ダーク": {
        # 🔩 【極大強化】 スタートを圧倒的に明るいアルミグレー（#55545B）にし、
        # 画面の中央（#1C1B1F）をすり抜けて、底の極小漆黒（#08080A）へと劇的に変化する垂直3層グラデーション！
        "bg": "linear-gradient(180deg, #55545B 0%, #1C1B1F 35%, #08080A 100%)",
        "text": "#FFFFFF",        # クッキリ浮き出る純白文字
        "card_bg": "#222126",     # 背景のグレーと美しく溶け合うダークカード
        "input_border": "#66656C",# 視認性を上げたメタルグレーの境界線
        "dropdown_bg": "#2D2C33",
        "dropdown_text": "#FFFFFF"
    }
}

# ==========================================
# 🧠 設定値の読み込み・常時シンク
# ==========================================
manual_memories = get_memories(source="manual")

#  初めて起動したまっさらな状態のユーザー向けの初期値
current_theme_color = "パステル"
current_concierge_name = "コンシェルジュ"
current_user_name = "ユーザー"
current_user_honorific = "さん"
current_first_person = "私"
current_style_preset = "🤝 フランクな相棒 ➔ 【タメ口で対等におしゃべり】"
current_response_length = "普通"
# current_dialect = "標準語"
# current_user_instruction = ""
current_ai_avatar = "🧠"
current_user_avatar = "💫"
current_emoji_setting = "使用（普通）"

# ユーザー個別の現在の会員プランの初期状態
if "current_user_plan_state" not in st.session_state:
    st.session_state["current_user_plan_state"] = "🆓 無料プラン"

# 🟢 【正真正銘・ Ver 1.0 最終確定製品版ロードインフラ】
#     elif の数珠繋ぎをバッサリ引き算し、それぞれ独立した if 文へとお掃除しました！
#     これにより、金庫の中のレコードがどんな順番で流れてきても、
#     人格（スタイル）とテキストエリア（こだわり）が互いを握りつぶし合う死角は100%永久に全廃されます！

for m in manual_memories:
    fact = m["fact"]
    
    if fact.startswith("カラーテーマ:"):
        current_theme_color = fact.replace("カラーテーマ:", "").strip()
    if fact.startswith("AIの名前:"):
        current_concierge_name = fact.replace("AIの名前:", "").strip()
    if fact.startswith("ユーザー名:"):
        current_user_name = fact.replace("ユーザー名:", "").strip()
    if fact.startswith("ユーザー敬称:"):
        current_user_honorific = fact.replace("ユーザー敬称:", "").strip()
    if fact.startswith("AI一人称:"):
        current_first_person = fact.replace("AI一人称:", "").strip()
    if fact.startswith("絵文字の量:"):
        current_emoji_setting = fact.replace("絵文字の量:", "").strip()
    if fact.startswith("AIアバター:"):
        current_ai_avatar = fact.replace("AIアバター:", "").strip()
    if fact.startswith("ユーザーアバター:"):
        current_user_avatar = fact.replace("ユーザーアバター:", "").strip()
    # if fact.startswith("会員プラン:"):
    #     st.session_state["current_user_plan_state"] = fact.replace("会員プラン:", "").strip()
    if fact.startswith("人格:"):
        current_style_preset = fact.replace("人格:", "").strip()
    # if fact.startswith("応答方針:"):
    #     current_user_instruction = fact.replace("応答方針:", "").strip()
    if fact.startswith("会話長さ:"):
        current_response_length = (
            fact.replace(
                "会話長さ:",
                ""
            ).strip()
        )

    # if fact.startswith("方言:"):
    #     current_dialect = (
    #         fact.replace(
    #             "方言:",
    #             ""
    #         ).strip()
    #     )

# 💡 【ここが大開通スイッチ！】 
# 先ほど定義した新しいグラデーション辞書「THEMES」から選ばれたカラー設定を100%確実に引き抜きます。
# 万が一古い選択肢が残っていても、安全弁として「パステル」に自動着地させてエラーを300%永久防衛します！
theme_cfg = THEMES.get(current_theme_color, THEMES["パステル"])


# ★画面最適化CSS（スマホメニュー表示維持 & ドロップダウン選択肢の全階層テキスト完全強制補正）
st.markdown(f"""
<style>
/* 上部ツールバー非表示 */
[data-testid="stToolbar"] {{
    display: none !important;
}}

/* ==================================================================
    👑 【最上部グラデーション ＆ 最高級ラグジュアリー：Cinzel Decorative斜体】
    ヘッダーの背景をチャット画面のグラデーションと100%完全同調させ、
    さらにハネが美しく知的に伸びる世界最高峰のドレスアップフォントを斜体で召喚します。
    ================================================================== */
/* 1. 最高級フォント */
@import url('https://googleapis.com');

[data-testid="stHeader"] {{
    background: {theme_cfg["bg"]} !important; /* チャット画面と100%完全にシンクするグラデーション背景 */
    border-bottom: 1px solid {theme_cfg["input_border"]} !important; /* 下部に美しく繊細な境界線を走らせます */
    height: 3.5rem !important;
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    width: 100% !important;
    z-index: 9999 !important;
}}
    
/* 2. 空白スペースのド真ん中に、端のラインが知的に伸びて右へ美しく傾く極上のブランドエンブレムを固定配置 */
[data-testid="stHeader"]::after {{
    content: "Sync-Lnk // AI" !important;
    font-family: 'Cinzel Decorative', serif !important; /* 💡 大本命の Cinzel Decorative を適用 */
    color: {theme_cfg["text"]} !important;
    font-size: 1.5rem !important; /* 威風堂々とした存在感と視認性を完璧に両立させる黄金サイズ */
    font-weight: 700 !important;  /* 文字の骨組みをクッキリと太く際立たせます */
    font-style: italic !important; /* 💡 右上がりの美しい傾斜（斜体）を強制発動！ */
    position: absolute !important;
    left: 50% !important;
    top: 50% !important;
    transform: translate(-50%, -50%) !important; /* 縦横ドンピシャで中央揃え */
    white-space: nowrap !important;
    letter-spacing: 2px !important; /* 文字同士の間隔を少し広げて、圧倒的な品格を演出します */
}}

[data-testid="collapsedControl"] {{
    color: #4A90E2 !important;
    background-color: rgba(255, 255, 255, 0.9) !important;
    border-radius: 4px !important;
    padding: 4px !important;
    box-shadow: 0px 2px 4px rgba(0,0,0,0.1) !important;
    position: fixed !important;
    top: 0.5rem !important;
    left: 0.5rem !important;
    z-index: 999999 !important;
}}

    /* ==================================================================
       🎨 1. 【全体背景＆文字色】 ベタ塗りを廃止し、極上の高級グラデーションを全開通
       ================================================================== */
    html, body, .stApp, div[data-testid="stAppViewContainer"], section.main {{
        background: {theme_cfg["bg"]} !important; /* 💡 background-colorからbackgroundへ変更しグラデーションを完全解放！ */
        color: {theme_cfg["text"]} !important;
        max-width: 100vw !important;
        overflow-x: hidden !important;
        box-sizing: border-box !important;
    }}
    .main .block-container {{
        max-width: 100vw !important;
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
        padding-top: 4.5rem !important;
    }}

    /* ==================================================================
       🎨 2. 【ユーザー設定・口調指示エリア】 ダークモード＆新テーマでの白飛びを永久ガード
       ================================================================== */
    div[data-testid="stTextArea"] textarea {{
        color: {theme_cfg["text"]} !important;
        -webkit-text-fill-color: {theme_cfg["text"]} !important;
        background-color: {theme_cfg["card_bg"]} !important;
    }}

    /* Selectboxの選択肢文字色強制 */
    div[data-baseweb="select"] span,
    div[data-baseweb="popover"] span,
    div[data-baseweb="menu"] span {{
        color: {theme_cfg["dropdown_text"]} !important;
    }}
    
    /* Streamlit 1.6x系向け */
    div[role="listbox"] {{
        background-color: {theme_cfg["dropdown_bg"]} !important;
    }}
    div[role="option"] {{
        background-color: {theme_cfg["dropdown_bg"]} !important;
        color: {theme_cfg["dropdown_text"]} !important;
    }}
    div[role="option"] * {{
        color: {theme_cfg["dropdown_text"]} !important;
    }}

    /* ==================================================================
       🎨 3. 【チャット入力枠＆送信ボタン】 紙飛行機ボタンまで100%全自動カラー連動
       ================================================================== */
    div[data-testid="stChatInput"] {{
        max-width: 100% !important;
        box-sizing: border-box !important;
    }}
    div[data-testid="stChatInput"] > div {{
        border: 2px solid {theme_cfg["input_border"]} !important;
        border-radius: 12px !important;
        background-color: {theme_cfg["card_bg"]} !important;
    }}
    div[data-testid="stChatInput"] textarea {{
        color: {theme_cfg["text"]} !important;
    }}
    /* 右側の紙飛行機ボタン全体の配色をテーマの境界線カラーと文字色へ全自動シンク */
    div[data-testid="stChatInput"] button {{
        background-color: {theme_cfg["input_border"]} !important;
        color: {theme_cfg["text"]} !important;
        border-radius: 50% !important;
        transition: transform 0.2s ease, opacity 0.2s ease !important;
    }}
    div[data-testid="stChatInput"] button:hover {{
        transform: scale(1.08) !important;
        opacity: 0.9 !important;
    }}
  
    /* ==========================================
       通常ボタンとフォーム送信ボタン
       ========================================== */
    button[data-testid="stBaseButton-secondary"],
    button[data-testid="stBaseButton-secondaryFormSubmit"] {{
        background: {theme_cfg["card_bg"]} !important;
        background-color: {theme_cfg["card_bg"]} !important;
        color: {theme_cfg["text"]} !important;
        border: 1px solid {theme_cfg["input_border"]} !important;
        opacity: 1 !important;
    }}
    button[data-testid="stBaseButton-secondary"] p,
    button[data-testid="stBaseButton-secondary"] span,
    button[data-testid="stBaseButton-secondaryFormSubmit"] p,
    button[data-testid="stBaseButton-secondaryFormSubmit"] span {{
        color: {theme_cfg["text"]} !important;
        background: transparent !important;
        background-color: transparent !important;
        opacity: 1 !important;
    }}
    button[data-testid="stBaseButton-secondary"]:hover,
    button[data-testid="stBaseButton-secondaryFormSubmit"]:hover {{
        background: {theme_cfg["input_border"]} !important;
        background-color: {theme_cfg["input_border"]} !important;
        color: #ffffff !important;
        border-color: {theme_cfg["input_border"]} !important;
    }}
    button[data-testid="stBaseButton-secondary"]:hover p,
    button[data-testid="stBaseButton-secondary"]:hover span,
    button[data-testid="stBaseButton-secondaryFormSubmit"]:hover p,
    button[data-testid="stBaseButton-secondaryFormSubmit"]:hover span {{
        color: #ffffff !important;
        background: transparent !important;
    }}
    button[data-testid="stBaseButton-secondary"]:focus,
    button[data-testid="stBaseButton-secondary"]:active,
    button[data-testid="stBaseButton-secondaryFormSubmit"]:focus,
    button[data-testid="stBaseButton-secondaryFormSubmit"]:active {{
        background: {theme_cfg["input_border"]} !important;
        background-color: {theme_cfg["input_border"]} !important;
        color: #ffffff !important;
        border-color: {theme_cfg["input_border"]} !important;
        box-shadow: none !important;
    }}

    label {{
        color: {theme_cfg["text"]} !important;
    }}
    [data-testid="stMarkdownContainer"] p {{
        color: {theme_cfg["text"]} !important;
    }}
    hr {{
        border-color: {theme_cfg["input_border"]} !important;
    }}
    [data-testid="stExpander"] {{
        border: 1px solid {theme_cfg["input_border"]} !important;
        border-radius: 8px !important;
    }}
    div[data-baseweb="select"] {{
        border: 1px solid {theme_cfg["input_border"]} !important;
        border-radius: 8px !important;
    }}
    div.st-emotion-cache-vbnxax:focus-within,
    div[data-baseweb="select"]:focus-within {{
        border-color: {theme_cfg['input_border']} !important;
        box-shadow: 0 0 0 1px {theme_cfg['input_border']} !important;
        outline: none !important;
    }}
    /* テキストエリア（.stTextArea textarea）をカンマで直結マージします！ */
    .stTextInput div[data-baseweb="input"]:focus-within,
    .stTextArea div[data-baseweb="textarea"]:focus-within,
    .stSelectbox div[data-baseweb="select"]:focus-within,
    .stTextInput div[data-baseweb="input"]:after,
    .stTextArea div[data-baseweb="textarea"]:after,
    .stSelectbox div[data-baseweb="select"]:after {{
        border-color: {theme_cfg['input_border']} !important;
        box-shadow: 0 0 0 2px {theme_cfg['input_border']} !important;
        background-color: {theme_cfg['input_border']} !important;
        background-image: none !important;
        outline: none !important;
    }}
    .st-emotion-cache-1mnb0ez:focus-within {{
        border-color: {{theme_cfg["input_border"]}} !important;
    }}
 
 </style>
""", unsafe_allow_html=True)

# ==================================================================
# 🔒【完全防衛】権限（ID）に応じて、画面最上部のタブ構造を動的に切り替えます
# ==================================================================
is_admin = CURRENT_USER_ID == ADMIN_USER_ID

if is_admin:
    tab_titles = ["💬 トークルーム", "🧠 記憶ルーム", "📁 計画ルーム", "🎨 話し方・見た目設定", "📜 利用規約・ポリシー", "📊 システム管理者管理", "📊 テスター用全データ履歴"]
else:
    tab_titles = ["💬 トークルーム", "🧠 記憶ルーム", "📁 計画ルーム", "🎨 話し方・見た目設定", "📜 利用規約・ポリシー"]

# 🎪 【タブの一括展開】
# Streamlitのタブを動的に生成
all_tabs = st.tabs(tab_titles)

# ------------------------------------------------------------------
# 💬 【タブ1】 トークルーム
# ------------------------------------------------------------------
with all_tabs[0]:       
        display_user_name = f"{current_user_name}{current_user_honorific}" if current_user_honorific != "（呼び捨て/なし）" else current_user_name
       
        current_subscription = get_user_subscription(CURRENT_USER_ID)

        st.session_state["current_user_plan_code"] = (
            current_subscription["plan_code"]
        )
        st.session_state["current_user_plan_state"] = (
            current_subscription["plan_label"]
        )
        current_plan_type = st.session_state.get(
            "current_user_plan_state",
            "🆓 無料プラン"
        )
        current_plan_code = st.session_state.get("current_user_plan_code", "free")
        current_plan_features = get_plan_features(current_plan_code)
        daily_chat_limit = int(
            current_plan_features.get(
                "daily_chat_limit",
                PLAN_FEATURES["free"]["daily_chat_limit"]
            )
        )
        # ==========================================
        # プラン別制御
        # ==========================================
        response_length_prompt = ""
        # dialect_prompt = ""

        # current_plan_type = "スタンダード"
        # current_plan_type = "ライトプラン"

        if current_plan_type != "🆓 無料プラン":
            response_length_prompt = (
                RESPONSE_LENGTH_PROMPTS.get(
                    current_response_length,
                    ""
                )
            )
            # dialect_prompt = (
            #     DIALECT_PROMPTS.get(
            #         current_dialect,
            #         ""
            #     )
            # )

        #st.code(build_manual_memory_context())
        #if st.button("記憶確認"):
        #    st.code(build_manual_memory_context())
        #if st.button("直近履歴確認"):
        #    st.code(build_recent_history_str())
        #st.title(f"💬 {current_concierge_name}の部屋")
        #st.caption(f"担当コンシェルジュ: 【{current_concierge_name}】 | 現在のプラン: 【{current_plan_type}】")

        should_reload_messages = (
            st.session_state.cached_messages is None
            or st.session_state.force_message_reload
        )

        if should_reload_messages:
            loaded_messages = get_messages(CURRENT_USER_ID, chat_room="talk")

            if loaded_messages is None:
                db_available = False

                if st.session_state.cached_messages is None:
                    st.session_state.cached_messages = []

                st.error(
                    "データベース通信に失敗しました。"
                    "保存済みの会話履歴を取得できませんでした。"
                )
            else:
                db_available = True
                st.session_state.cached_messages = loaded_messages

            st.session_state.force_message_reload = False

        else:
            db_available = True

        all_messages = list(st.session_state.cached_messages or [])
        
        # all_messages = get_messages(CURRENT_USER_ID)
        # db_available = (all_messages is not None)

        # 🟢 【最終確定製品版：電波瞬断・ウェルカム画面暴発完全全廃ガードレール】
        #     ・本当に履歴が0件の新規ユーザーのみ ➔ ウェルカム文を表示
        #     ・電波瞬断エラー（None）の時 ➔ エラーメッセージを表示して停止
        
        if not db_available:
            st.error("データベースへの接続に失敗しました。電波環境の良い場所で、ページを再読み込み（リフレッシュ）してください。")
            all_messages = []

        elif (db_available and len(all_messages) == 0):
            welcome_text = (
                f"初めまして！今日からあなたの日常に寄り添うコンシェルジュとして、全力でお手伝いさせていただきます！今日からどうぞよろしくお願いいたします！✨\n\n"
                f"💬 **【はじめに】**\n"
                f"まずは上部の「話し方・見た目設定」タブを開いて、あなたのお好みの口調や呼び方を自由に設定してみてくださいね。設定が終わったら、この入力欄から何でも気軽に話しかけてください！\n\n"
                f"💡 **【アプリの特徴】**\n"
                f"あなたとのおしゃべりの歴史（記憶）は裏側で大切に保管されて、時間が経ってもあなたとの歴史を忘れないスマートな会話が楽しめます。\n\n"
                f"📜 詳しい使い方やプライバシー保護、利用上のルールについては、「利用規約」等のページを合わせてご確認ください。"
            )
            all_messages = [{"role": "assistant", "content": welcome_text}]

        db_count, db_max = get_usage_status(CURRENT_USER_ID)

        current_point_balance = get_user_point_balance(CURRENT_USER_ID)
        available_points = int(current_point_balance.get("available_points", 0) or 0)

        status_col, point_detail_col = st.columns([8, 2], vertical_alignment="center")

        with status_col:
            st.caption(
                f"{current_plan_type}"
                f"　｜　本日の会話：{db_count} / {db_max}回"
                f"　｜　保有ポイント：{available_points:,}pt"
            )

        with point_detail_col:
            if st.button(
                "ポイント詳細",
                key="open_point_detail_dialog",
                # use_container_width=True
            ):
                show_point_detail_dialog()

        pending_detail_request = dict(
            st.session_state.get("pending_detail_request", {}) or {}
        )
        detail_confirmation_open = bool(
            st.session_state.get("detail_confirmation_open", False)
        )

        if detail_confirmation_open and pending_detail_request:
            show_detail_confirmation_dialog(pending_detail_request)
            
        detail_request_processing = bool(
            st.session_state.get("detail_request_processing", False)
        )

        detail_request_ready = False

        if (detail_request_processing and pending_detail_request):
            detailed_processing_type = str(
                pending_detail_request.get("detailed_processing_type", "") or ""
            ).strip()

            detail_point_cost = int(pending_detail_request.get("point_cost", 0) or 0)

            detail_point_balance = (get_user_point_balance(CURRENT_USER_ID))

            detail_available_points = int(
                detail_point_balance.get("available_points", 0) or 0
            )

            valid_detail_types = {
                "detailed_search",
                "detailed_analysis",
                "detailed_search_analysis"
            }

            if (detailed_processing_type not in valid_detail_types):
                st.session_state["pending_detail_request"] = {}
                st.session_state["detail_request_processing"] = False
                st.error(
                    "詳細処理の種類を確認できませんでした。"
                    "簡易回答から、もう一度お試しください。"
                )

            elif detail_point_cost <= 0:
                st.session_state["pending_detail_request"] = {}
                st.session_state["detail_request_processing"] = False
                st.error(
                    "詳細処理のポイント設定を確認できませんでした。"
                )

            elif (detail_available_points < detail_point_cost):
                st.session_state["pending_detail_request"] = {}
                st.session_state["detail_request_processing"] = False
                shortage_points = (detail_point_cost - detail_available_points)

                st.warning(
                    f"詳細処理には"
                    f"{detail_point_cost:,}ポイント必要です。"
                    f"現在は{detail_available_points:,}ポイントのため、"
                    f"あと{shortage_points:,}ポイント必要です。"
                )

            else:
                detail_request_ready = True

        if detail_request_ready and detailed_processing_type == "detailed_analysis":
            original_message_id = str(
                pending_detail_request.get("original_message_id", "") or ""
            ).strip()

            original_user_message = str(
                pending_detail_request.get("original_user_message", "") or ""
            ).strip()

            simple_answer = str(
                pending_detail_request.get("simple_answer", "") or ""
            ).strip()

            detail_user_message = (
                "この質問について、重要な判断材料やリスク、"
                "結論の根拠を含めて詳しく分析して。"
            )

            # 元の簡易回答ごとに固定IDを使用し、
            # 二重生成・二重ポイント消費を防止
            detail_message_id = (
                f"detail_{original_message_id}_detailed_analysis"
            )

            detail_operation_id = (
                f"detail_points:{CURRENT_USER_ID}:"
                f"{original_message_id}:detailed_analysis"
            )

            if not original_message_id or not original_user_message or not simple_answer:
                st.session_state["pending_detail_request"] = {}
                st.session_state["detail_request_processing"] = False

                st.error(
                    "詳細分析に必要な元の質問または"
                    "簡易回答を確認できませんでした。"
                )
                st.rerun()

            # 同じ詳細回答がすでに保存されている場合は再実行しない
            existing_detail_response = (
                supabase
                .table("messages")
                .select("id, role, content, message_id")
                .eq("user_id", CURRENT_USER_ID)
                .eq("message_id", detail_message_id)
                .eq("role", "assistant")
                .limit(1)
                .execute()
            )

            if existing_detail_response.data:
                st.session_state["pending_detail_request"] = {}
                st.session_state["detail_request_processing"] = False

                st.info(
                    "この内容の詳細分析は、"
                    "すでに会話履歴へ保存されています。"
                )
                st.rerun()

            detail_start_time = time.time()

            try:
                with st.status(
                    "詳しい回答を作成しています...",
                    expanded=False
                ) as detail_status:

                    detail_result = generate_detailed_analysis_response(
                        style_preset=current_style_preset,
                        original_user_message=original_user_message,
                        simple_answer=simple_answer
                    )

                detail_elapsed = time.time() - detail_start_time

                if not detail_result.get("success", False):
                    raise RuntimeError(
                        detail_result.get(
                            "error_message",
                            "詳細Analysisに失敗しました。"
                        )
                    )

                detail_answer = str(detail_result.get("answer", "") or "").strip()
                detail_in_tokens = int(detail_result.get("in_tokens", 0) or 0)
                detail_out_tokens = int(detail_result.get("out_tokens", 0) or 0)
                detail_api_cost = float(detail_result.get("api_cost", 0.0) or 0.0)

                # 詳細化依頼を新しいユーザー会話として保存
                detail_user_saved = save_message(
                    role="user",
                    content=detail_user_message,
                    message_id=detail_message_id,
                    response_mode="analysis",
                    processing_type="detailed_analysis",
                    parent_message_id=original_message_id
                )

                if not detail_user_saved:
                    raise RuntimeError("詳細化依頼を保存できませんでした。")

                # 詳細回答を同じ新規会話へ保存
                detail_answer_saved = save_message(
                    role="assistant",
                    content=detail_answer,
                    message_id=detail_message_id,
                    response_mode="analysis",
                    processing_type="detailed_analysis",
                    parent_message_id=original_message_id
                )

                if not detail_answer_saved:
                    raise RuntimeError("詳細回答を保存できませんでした。")

                # 回答保存成功後にポイントを消費
                point_use_result = use_points(
                    user_id=CURRENT_USER_ID,
                    points=detail_point_cost,
                    reason_code="detailed_analysis",
                    operation_id=detail_operation_id,
                    description="検索なし詳細Analysis",
                    reference_id=detail_message_id
                )

                point_result_status = str(
                    point_use_result.get("result_status", "error") or "error"
                )

                point_consumed = point_result_status in {
                    "used",
                    "already_processed"
                }

                if not point_consumed:
                    detail_status.update(
                        label="詳細回答は作成されましたが、ポイント処理の確認が必要です",
                        state="error",
                        expanded=True
                    )

                add_permanent_tokens(
                    CURRENT_USER_ID,
                    "chat",
                    detail_in_tokens,
                    detail_out_tokens
                )

                save_system_audit_log(
                    user_id=CURRENT_USER_ID,
                    plan_type=current_plan_type,
                    event_type="CHAT_SUCCESS",
                    processing_time=detail_elapsed,
                    in_t=detail_in_tokens,
                    out_t=detail_out_tokens,
                    api_cost=detail_api_cost,
                    details=(
                        f"provider={detail_result.get('provider', '')}"
                        f" | model={detail_result.get('model_name', '')}"
                        f" | response_route=detailed_analysis_direct"
                        f" | 処理区分=detailed_analysis"
                        f" | 回答モード=analysis"
                        f" | point_cost={detail_point_cost}"
                        f" | point_status={point_result_status}"
                    ),
                    message_id=detail_message_id
                )

                st.session_state["pending_detail_request"] = {}
                st.session_state["detail_request_processing"] = False
                st.session_state.force_message_reload = True

                if point_consumed:
                    st.toast(
                        f"詳細分析が完了しました。"
                        f"{detail_point_cost}ポイントを使用しました。"
                    )
                else:
                    st.warning(
                        "詳細回答は保存されましたが、"
                        "ポイント消費結果を確認できませんでした。"
                        "管理者ログをご確認ください。"
                    )

                st.rerun()

            except Exception as detail_error:
                st.session_state["pending_detail_request"] = {}
                st.session_state["detail_request_processing"] = False

                error_text = (f"{type(detail_error).__name__}: {detail_error}")

                if "detail_status" in locals():
                    detail_status.update(
                        label="詳細回答を作成できませんでした",
                        state="error",
                        expanded=True
                    )

                print(f"詳細Analysis処理エラー: {error_text}")

                save_system_audit_log(
                    user_id=CURRENT_USER_ID,
                    plan_type=current_plan_type,
                    event_type="DETAILED_ANALYSIS_ERROR",
                    processing_time=time.time() - detail_start_time,
                    in_t=0,
                    out_t=0,
                    api_cost=0.0,
                    details=error_text[:500],
                    message_id=detail_message_id
                )

                st.error(
                    "詳細分析を完了できませんでした。"
                    "ポイントは消費されていません。"
                )
                st.rerun()
        
        typed_user_input = st.chat_input(
            f"{current_concierge_name}にメッセージを送信...",
            key="user_chat_input",
            disabled=detail_request_ready
        )
        if typed_user_input:
            user_input = typed_user_input
            if len(user_input) > MAX_INPUT_CHARS:
                increment_error_analytics("LIMIT_INPUT_CHARS_EXCEEDED", current_plan_type)
                err_msg = generate_personality_error_msg("ユーザーが1,000文字を超える超長文を送信しようとしました", current_user_instruction)
                # with st.chat_message("assistant", avatar=current_ai_avatar):
                # with st.chat_message("assistant"):
                # st.write(f"【{current_concierge_name}】: {err_msg}")
                st.markdown(f"{current_concierge_name}: {err_msg}")
            else:
                is_allowed, alert_code, db_count, db_max = (
                    check_and_update_limits(
                        CURRENT_USER_ID
                    )
                )
                if not is_allowed:
                    increment_error_analytics(alert_code, current_plan_type)
                    
                    if alert_code == "BURST_LIMIT":
                        reason_text = (
                        "連続送信が速すぎます。"
                        "少し間を空けてから送ってください。"
                    )

                    elif alert_code == "DAILY_LIMIT_EXCEEDED":
                        reason_text = (
                            f"本日の会話上限"
                            f"（{db_max}回）に達しました。"
                        )

                    elif alert_code == "LIMIT_CHECK_ERROR":
                        reason_text = (
                            "利用回数を確認できませんでした。"
                            "管理者ログを確認してください。"
                        )

                    else:
                        reason_text = (
                            "現在メッセージを送信できません。"
                            f"コード: {alert_code}"
                        )

                    # with st.chat_message("assistant", avatar=current_ai_avatar):
                    # with st.chat_message("assistant"):
                    # st.write(f"【{current_concierge_name}】: {reason_text}")
                    st.markdown(f"{current_concierge_name}: {reason_text}")
                    
                    # 制限接触ログの保存
                    save_system_audit_log(
                        user_id=CURRENT_USER_ID,
                        plan_type=current_plan_type,
                        event_type=str(alert_code),
                        processing_time=0.0,
                        in_t=0,
                        out_t=0,
                        api_cost=0.0,
                        details=str(reason_text)
                    )

                else:
                    # 「考え中...」をフリッカー無しで点滅表示
                    with st.spinner(f"{current_concierge_name}が言葉を紡いでいます..."):
                        
                        # with st.chat_message("user", avatar=current_user_avatar):
                        # with st.chat_message("user"):
                        # st.write(f"【{display_user_name}】: {clean_bold_markdown(user_input)}")
                        st.markdown(f"{display_user_name}: {clean_bold_markdown(user_input)}")

                        # メッセージIDの自動生成
                        import uuid
                        current_msg_id = f"msg_{uuid.uuid4().hex[:8]}"

                        # ==========================================
                        # 案件名称変更の検出と変更処理
                        # ==========================================
                        case_name_change = extract_case_name_change(
                            user_input
                        )

                        if case_name_change:

                            active_case_id = (
                                st.session_state.get(
                                    "active_calculation_case_id"
                                )
                            )

                            # ======================================
                            # 現在選択中の案件がある場合
                            # その案件名を直接変更
                            # ======================================
                            if active_case_id:

                                updated = update_calculation_case(
                                    case_id=active_case_id,
                                    case_name=case_name_change,
                                    new_case_data={}
                                )

                                if updated:

                                    st.session_state[
                                        "active_calculation_case_name"
                                    ] = case_name_change

                                    ai_reply = build_case_rename_followup(
                                        case_id=active_case_id,
                                        new_case_name=case_name_change
                                    )

                                else:

                                    ai_reply = (
                                        "案件名を変更できませんでした。"
                                        "案件情報を確認してください。"
                                    )
                                
                                all_messages.append({
                                    "role": "user",
                                    "content": user_input,
                                    "message_id": current_msg_id,
                                    "response_mode": "conversation",
                                    "chat_room": "talk",
                                    "created_at": datetime.now(JST).isoformat()
                                })

                                all_messages.append({
                                    "role": "assistant",
                                    "content": ai_reply,
                                    "message_id": current_msg_id,
                                    "response_mode": "conversation",
                                    "chat_room": "talk",
                                    "created_at": datetime.now(JST).isoformat()
                                })

                                # save_message(
                                #     "user",
                                #     user_input,
                                #     current_msg_id,
                                #     "conversation"
                                # )

                                save_message(
                                    "assistant",
                                    ai_reply,
                                    current_msg_id,
                                    "conversation",
                                )

                                display_message(
                                    current_concierge_name,
                                    ai_reply
                                )

                                st.session_state.force_message_reload = True

                                st.stop()

                            # ======================================
                            # 現在選択中の案件がない場合
                            # 名称変更対象の案件を選ばせる
                            # ======================================
                            rename_candidates = (
                                get_calculation_case_candidates(
                                    case_type="real_estate_sale",
                                    user_input=""
                                )
                            )

                            if not rename_candidates:

                                ai_reply = (
                                    "案件名を変更できる"
                                    "計算案件が見つかりませんでした。"
                                )

                                all_messages.append({
                                    "role": "user",
                                    "content": user_input,
                                    "message_id": current_msg_id,
                                    "response_mode": response_mode,
                                    "chat_room": "talk",
                                    "created_at": datetime.now(JST).isoformat()
                                })

                                all_messages.append({
                                    "role": "assistant",
                                    "content": ai_reply,
                                    "message_id": current_msg_id,
                                    "response_mode": response_mode,
                                    "chat_room": "talk",
                                    "created_at": datetime.now(JST).isoformat()
                                })

                                # save_message(
                                #     "user",
                                #     user_input,
                                #     current_msg_id,
                                #     "conversation"
                                # )

                                save_message(
                                    "assistant",
                                    ai_reply,
                                    current_msg_id,
                                    "conversation",
                                )

                                display_message(
                                    current_concierge_name,
                                    ai_reply
                                )

                                st.session_state.force_message_reload = True
                                st.stop()

                            # 案件選択待ちへ移行
                            st.session_state[
                                "pending_case_selection"
                            ] = True

                            st.session_state[
                                "pending_case_candidates"
                            ] = rename_candidates

                            # 通常の計算案件選択ではなく、
                            # 案件名変更のための選択であることを記録
                            st.session_state[
                                "pending_case_rename"
                            ] = True

                            st.session_state[
                                "pending_case_rename_name"
                            ] = case_name_change

                            # 計算条件は引き継がない
                            st.session_state[
                                "pending_case_arguments"
                            ] = {}

                            candidate_lines = []

                            for index, case in enumerate(
                                rename_candidates,
                                start=1
                            ):
                                updated_at = (
                                    str(
                                        case.get(
                                            "updated_at",
                                            ""
                                        )
                                    )
                                    .replace("T", " ")[:16]
                                )

                                candidate_lines.append(
                                    f"{index}. "
                                    f"{case.get('case_name', '案件名なし')}\n"
                                    f"最終更新: {updated_at}"
                                )

                            ai_reply = (
                                "どの案件の名称を変更しますか？\n\n"
                                + "\n\n".join(candidate_lines)
                                + "\n\n番号または案件名で選択してください。"
                            )

                            all_messages.append({
                                "role": "user",
                                "content": user_input,
                                "message_id": current_msg_id,
                                "response_mode": response_mode,
                                "chat_room": "talk",
                                "created_at": datetime.now(JST).isoformat()
                            })

                            all_messages.append({
                                "role": "assistant",
                                "content": ai_reply,
                                "message_id": current_msg_id,
                                "response_mode": response_mode,
                                "chat_room": "talk",
                                "created_at": datetime.now(JST).isoformat()
                            })

                            # save_message(
                            #     "user",
                            #     user_input,
                            #     current_msg_id,
                            #     "conversation"
                            # )

                            save_message(
                                "assistant",
                                ai_reply,
                                current_msg_id,
                                "conversation",
                            )

                            display_message(
                                current_concierge_name,
                                ai_reply
                            )

                            st.session_state.force_message_reload = True
                            st.stop()
                        

                        # ==========================================
                        # 新しい計算案件を開始する明示指示
                        # ==========================================
                        normalized_case_command = (
                            str(user_input or "")
                            .replace(" ", "")
                            .replace("　", "")
                            .lower()
                        )

                        start_new_real_estate_case = any(
                            keyword in normalized_case_command
                            for keyword in [
                                "新規案件",
                                "新規で",
                                "新しく計算",
                                "新しい案件",
                                "新規作成",
                                "別案件",
                                "別の案件",
                                "売却計算したい",
                                "売却試算したい",
                                "売却シミュレーションしたい",
                                "不動産売却計算したい"
                            ]
                        )
                        if start_new_real_estate_case:
                            candidates = []

                        if start_new_real_estate_case:
                            # 現在操作中の案件との関連付けを解除
                            st.session_state[
                                "active_calculation_case_id"
                            ] = None

                            st.session_state[
                                "active_calculation_case_name"
                            ] = ""

                            # 前案件の計算条件を破棄
                            st.session_state[
                                "real_estate_calculation_arguments"
                            ] = {}

                            st.session_state[
                                "real_estate_calculation_pending"
                            ] = False

                            # 前回の案件選択待ち状態も破棄
                            st.session_state[
                                "pending_case_selection"
                            ] = False

                            st.session_state[
                                "pending_case_candidates"
                            ] = []

                            st.session_state[
                                "pending_case_arguments"
                            ] = {}

                        # 計算案件の選択待ち処理
                        selected_case_resume_arguments = None
                        if st.session_state.get("pending_case_selection", False):

                            if should_exit_real_estate_calculation(user_input):
                                st.session_state["pending_case_selection"] = False
                                st.session_state["pending_case_candidates"] = []
                                st.session_state["pending_case_arguments"] = {}
                                st.session_state["pending_case_rename"] = False
                                st.session_state["pending_case_rename_name"] = ""
                                st.session_state["real_estate_calculation_pending"] = False
                                st.session_state["active_calculation_case_id"] = None
                                st.session_state["active_calculation_case_name"] = ""
                                
                                ai_reply = ("不動産計算を終了しました。")

                                all_messages.append({
                                    "role": "assistant",
                                    "content": ai_reply,
                                    "message_id": current_msg_id,
                                    "response_mode": "conversation",
                                    "chat_room": "talk",
                                    "created_at":
                                        datetime.now(JST).isoformat()
                                })

                                save_message(
                                    "assistant",
                                    ai_reply,
                                    current_msg_id,
                                    "conversation",
                                )

                                display_message(
                                    current_concierge_name,
                                    ai_reply
                                )

                                st.session_state.force_message_reload = True
                                st.stop()
                           
                            candidates = st.session_state.get("pending_case_candidates", [])
                            rename_selection_mode = bool(
                                st.session_state.get("pending_case_rename", False)
                            )
                            normalized_input = (
                                user_input
                                .strip()
                                .lower()
                                .translate(
                                    str.maketrans(
                                        "１２３４５６７８９０",
                                        "1234567890"
                                    )
                                )
                            )

                            selected_case = None
                            create_new_case_requested = False
                            new_case_number = len(candidates) + 1

                            if (
                                not rename_selection_mode
                                and normalized_input in {
                                str(new_case_number),
                                f"{new_case_number}番",
                                f"{new_case_number}番目"
                                }
                            ):
                                create_new_case_requested = True
                            else:
                                for index, case in enumerate(candidates, start=1):
                                    case_name = str(case.get("case_name", "") or "").strip()

                                    if normalized_input in {
                                        str(index),
                                        f"{index}番",
                                        f"{index}番目"
                                    }:
                                        selected_case = case
                                        break

                                    if (
                                        case_name
                                        and case_name.lower()
                                        in normalized_input
                                    ):
                                        selected_case = case
                                        break

                            selected_case_confirmed = False

                            if create_new_case_requested:

                                pending_arguments = dict(
                                    st.session_state.get(
                                        "pending_case_arguments",
                                        {}
                                    )
                                    or {}
                                )

                                # 前に操作していた案件の条件を破棄
                                st.session_state[
                                    "real_estate_calculation_arguments"
                                ] = {}
                                st.session_state[
                                    "real_estate_calculation_pending"
                                ] = False


                                # 今回ユーザーが案件選択前に入力した条件だけ引き継ぐ
                                new_case_data = {
                                    key: value
                                    for key, value
                                    in pending_arguments.items()
                                    if (
                                        value is not None
                                        and value != ""
                                    )
                                }

                                if "DEBUG new_case_data" in locals():
                                    debug_json(
                                        "DEBUG new_case_data",
                                        new_case_data
                                    )

                                property_usage = (
                                    new_case_data.get(
                                        "property_usage"
                                    )
                                )

                                if property_usage:
                                    new_case_data[
                                        "property_usage"
                                    ] = property_usage
                                else:
                                    new_case_data.pop(
                                        "property_usage",
                                        None
                                    )

                                create_result = create_calculation_case(
                                    case_type="real_estate_sale",
                                    property_usage=property_usage,
                                    case_data=new_case_data,
                                    current_plan_type=current_plan_type
                                )

                                if not create_result.get("success"):
                                    create_error_reply = (
                                        "新しい計算案件を作成できませんでした。"
                                        "入力内容を確認して、もう一度お試しください。"
                                    )

                                    all_messages.append({
                                        "role": "user",
                                        "content": user_input,
                                        "message_id": current_msg_id,
                                        "response_mode": response_mode,
                                        "chat_room": "talk",
                                        "created_at": datetime.now(JST).isoformat()
                                    })

                                    all_messages.append({
                                        "role": "assistant",
                                        "content": create_error_reply,
                                        "message_id": current_msg_id,
                                        "response_mode": response_mode,
                                        "chat_room": "talk",
                                        "created_at": datetime.now(JST).isoformat()
                                    })

                                    # save_message(
                                    #     "user",
                                    #     user_input,
                                    #     current_msg_id,
                                    #     "analysis"
                                    # )

                                    save_message(
                                        "assistant",
                                        create_error_reply,
                                        current_msg_id,
                                        "analysis",
                                    )

                                    display_message(
                                        current_concierge_name,
                                        create_error_reply
                                    )

                                    st.session_state.force_message_reload = True
                                    st.stop()

                                new_case_id = create_result.get("case_id")

                                new_case_name = get_default_case_name(
                                    case_type="real_estate_sale",
                                    property_usage=property_usage
                                )

                                st.session_state["active_calculation_case_id"] = new_case_id
                                st.session_state["active_calculation_case_name"] = new_case_name
                                st.session_state["real_estate_calculation_pending"] = False
                                st.session_state["real_estate_calculation_arguments"] = new_case_data
                                selected_case_resume_arguments = dict(new_case_data)
                                st.session_state["pending_case_selection"] = False
                                st.session_state["pending_case_candidates"] = []
                                st.session_state["pending_case_arguments"] = {}
                                selected_case_confirmed = True

                            elif selected_case:
                                # ======================================
                                # 案件名変更のための選択だった場合
                                # ======================================
                                if rename_selection_mode:

                                    selected_case_id = (
                                        selected_case.get(
                                            "case_id"
                                        )
                                    )

                                    new_case_name = str(
                                        st.session_state.get(
                                            "pending_case_rename_name",
                                            ""
                                        )
                                        or ""
                                    ).strip()

                                    updated = False

                                    if (
                                        selected_case_id
                                        and new_case_name
                                    ):
                                        updated = update_calculation_case(
                                            case_id=selected_case_id,
                                            case_name=new_case_name,
                                            new_case_data={}
                                        )

                                    if updated:

                                        # 選択した案件をアクティブ案件にする
                                        st.session_state[
                                            "active_calculation_case_id"
                                        ] = selected_case_id

                                        st.session_state[
                                            "active_calculation_case_name"
                                        ] = new_case_name

                                        ai_reply = build_case_rename_followup(
                                            case_id=selected_case_id,
                                            new_case_name=new_case_name
                                        )

                                    else:

                                        ai_reply = (
                                            "案件名を変更できませんでした。"
                                            "案件情報を確認してください。"
                                        )

                                    # 名称変更待ち状態を解除
                                    st.session_state[
                                        "pending_case_selection"
                                    ] = False

                                    st.session_state[
                                        "pending_case_candidates"
                                    ] = []

                                    st.session_state[
                                        "pending_case_arguments"
                                    ] = {}

                                    st.session_state[
                                        "pending_case_rename"
                                    ] = False

                                    st.session_state[
                                        "pending_case_rename_name"
                                    ] = ""

                                    all_messages.append({
                                        "role": "user",
                                        "content": user_input,
                                        "message_id": current_msg_id,
                                        "response_mode": response_mode,
                                        "chat_room": "talk",
                                        "created_at": datetime.now(JST).isoformat()
                                    })

                                    all_messages.append({
                                        "role": "assistant",
                                        "content": ai_reply,
                                        "message_id": current_msg_id,
                                        "response_mode": response_mode,
                                        "chat_room": "talk",
                                        "created_at": datetime.now(JST).isoformat()
                                    })

                                    # save_message(
                                    #     "user",
                                    #     user_input,
                                    #     current_msg_id,
                                    #     "conversation"
                                    # )

                                    save_message(
                                        "assistant",
                                        ai_reply,
                                        current_msg_id,
                                        "conversation",
                                    )

                                    display_message(
                                        current_concierge_name,
                                        ai_reply
                                    )

                                    st.session_state.force_message_reload = True
                                    st.stop()

                                # ======================================
                                # ここから下は既存の通常案件選択処理
                                # ======================================
                                selected_case_id = selected_case[
                                    "case_id"
                                ]

                                selected_case_name = selected_case[
                                    "case_name"
                                ]

                                # 以下、既存処理をそのまま続ける
                                selected_case_id = selected_case["case_id"]
                                selected_case_name = selected_case["case_name"]

                                st.session_state["active_calculation_case_id"] = selected_case_id
                                st.session_state["active_calculation_case_name"] = selected_case_name
                                
                                # debug_text(
                                #     "DEBUG selected_case_set_id",
                                #     st.session_state["active_calculation_case_id"]
                                # )

                                # debug_text(
                                #     "DEBUG selected_case_set_name",
                                #     st.session_state["active_calculation_case_name"]
                                # )

                                selected_case_data = (
                                    get_calculation_case(
                                        selected_case["case_id"]
                                    )
                                )
                                
                                restored_case_data = dict(
                                    selected_case_data.get(
                                        "case_data",
                                        {}
                                    )
                                    or {}
                                )

                                debug_json(
                                    "DEBUG restored_case_data",
                                    restored_case_data
                                )

                                pending_arguments = dict(
                                    st.session_state.get(
                                        "pending_case_arguments",
                                        {}
                                    )
                                    or {}
                                )

                                # 前に操作していた案件のセッション条件を破棄
                                st.session_state["real_estate_calculation_arguments"] = {}
                                st.session_state["real_estate_calculation_pending"] = False
                                # st.session_state["active_calculation_case_id"] = None
                                # st.session_state["active_calculation_case_name"] = ""
                                # debug_text(
                                #     "DEBUG cleared_case_id",
                                #     st.session_state["active_calculation_case_id"]
                                # )

                                # debug_text(
                                #     "DEBUG cleared_case_name",
                                #     st.session_state["active_calculation_case_name"]
                                # )

                                # 選択した案件を基準にする
                                merged_case_data = dict(restored_case_data)

                                # 案件選択前にユーザーが今回入力した条件だけ反映
                                for key, value in pending_arguments.items():
                                    if value is None:
                                        continue

                                    if value == "":
                                        continue

                                    merged_case_data[key] = value

                                if selected_case_name == "自宅売却":
                                    merged_case_data[
                                        "property_usage"
                                    ] = "owner_occupied"

                                if (
                                    merged_case_data.get(
                                        "property_usage"
                                    )
                                    == "owner_occupied"
                                ):
                                    merged_case_data[
                                        "owner_type"
                                    ] = "individual"

                                # 選択案件と今回入力分だけでセッションを作り直す
                                st.session_state[
                                    "real_estate_calculation_arguments"
                                ] = dict(
                                    merged_case_data
                                )

                                selected_case_resume_arguments = dict(
                                    merged_case_data
                                )

                                debug_json(
                                    "DEBUG selected_case_resume_arguments_after_restore",
                                    selected_case_resume_arguments
                                )
                                
                                # st.write("restored_case_data")
                                # st.code(
                                #     json.dumps(
                                #         restored_case_data,
                                #         ensure_ascii=False,
                                #         indent=2,
                                #         default=str
                                #     ),
                                #     language="json"
                                # )

                                # st.write("pending_arguments")
                                # st.code(
                                #     json.dumps(
                                #         pending_arguments,
                                #         ensure_ascii=False,
                                #         indent=2,
                                #         default=str
                                #     ),
                                #     language="json"
                                # )

                                # st.write("merged_case_data")
                                # st.code(
                                #     json.dumps(
                                #         merged_case_data,
                                #         ensure_ascii=False,
                                #         indent=2,
                                #         default=str
                                #     ),
                                #     language="json"
                                # )
  
                                st.session_state["pending_case_selection"] = False
                                st.session_state["pending_case_candidates"] = []
                                st.session_state["pending_case_arguments"] = {}

                                st.session_state.force_message_reload = True
                                selected_case_confirmed = True
                            
                            if not selected_case_confirmed:
                                candidate_names = "、".join(
                                    f"{index}. {case.get('case_name', '案件名なし')}"
                                    for index, case in enumerate(candidates, start=1)
                                )

                                retry_reply = (
                                    "案件を特定できませんでした。"
                                    f"「番号」または「案件名」で選んでください。\n\n"
                                    f"{candidate_names}"
                                )

                                if "response_mode" not in locals():
                                    response_mode = "conversation"

                                all_messages.append({
                                    "role": "user",
                                    "content": user_input,
                                    "message_id": current_msg_id,
                                    "response_mode": response_mode,
                                    "chat_room": "talk",
                                    "created_at": datetime.now(JST).isoformat()
                                })

                                all_messages.append({
                                    "role": "assistant",
                                    "content": retry_reply,
                                    "message_id": current_msg_id,
                                    "response_mode": response_mode,
                                    "chat_room": "talk",
                                    "created_at": datetime.now(JST).isoformat()
                                })

                                # save_message("user", user_input, current_msg_id, "analysis")
                                save_message("assistant", retry_reply, current_msg_id, "analysis")

                                display_message(
                                    current_concierge_name,
                                    retry_reply
                                )

                                st.session_state.force_message_reload = True
                                st.stop()
                                                
                        recent_messages = all_messages[-MAX_CONTEXT_MESSAGES:]

                        manual_memory_context = "\n".join([f"・{m['fact']}" for m in manual_memories]) if manual_memories else "なし"
                        current_time_str = datetime.now(JST).strftime("%Y-%m-%d %A %H:%M:%S")

                        recent_history_lines = []

                        #　直近の過去会話履歴の作成
                        for m in recent_messages:
                            role_name = (
                                display_user_name
                                if m.get("role") == "user"
                                else current_concierge_name
                            )

                            created_at = m.get("created_at", "")
                            time_label = (
                                created_at.replace("T", " ")[:16]
                                if created_at
                                else "時刻不明"
                            )

                            recent_history_lines.append(
                                f"[{time_label}] {role_name}: "
                                f"{m.get('content', '')}"
                            )

                        # 会話用直近会話履歴作成
                        recent_history_str = (
                            "\n".join(recent_history_lines)
                            if recent_history_lines
                            else "直近の会話履歴なし"
                        )
                        chat_recent_messages = (
                            recent_messages[-CHAT_CONTEXT_MESSAGES:]
                        )
                        chat_history_lines = (
                            recent_history_lines[-CHAT_CONTEXT_MESSAGES:]
                        )
                        chat_history_str = (
                            "\n".join(chat_history_lines)
                            if chat_history_lines
                            else "直近の会話履歴なし"
                        )

                        recent_context_message_ids = list(
                            {
                                str(message.get("message_id", "") or "").strip()
                                for message
                                in chat_recent_messages
                                if str(message.get("message_id", "") or "").strip()
                            }
                        )
                        # 会話種別＆検索判定用の直近会話履歴作成
                        previous_messages = recent_messages[:-1]

                        router_history_lines = []

                        for m in previous_messages[-2:]:
                            role_name = (
                                display_user_name
                                if m.get("role") == "user"
                                else current_concierge_name
                            )

                            router_history_lines.append(
                                f"{role_name}: {m.get('content', '')}"
                            )

                        recent_history_for_router = (
                            "\n".join(router_history_lines)
                            if router_history_lines
                            else "直近の会話履歴なし"
                        )

                        # 過去会話検索時間
                        search_elapsed = 0.0

                        # Google検索時間
                        search_execution_elapsed = 0.0

                        # ==========================================
                        # ルーター用 長期記憶作成
                        # ==========================================
                        summary_memories_for_router = (get_memories(source="summary"))
                        summary_memory_context_for_router = (
                            "\n".join(
                                [
                                    m["fact"]
                                    for m in summary_memories_for_router
                                ]
                            )
                            if summary_memories_for_router
                            else "なし"
                        )

                        calculation_pending = bool(st.session_state.get("real_estate_calculation_pending", False))

                        past_logs_context = []
                        search_elapsed = 0.0
                        requires_estimation = False

                        router_elapsed = 0.0

                        if is_micro_chat(user_input):
                            response_mode = "micro_chat"
                            route_source = "micro_chat"
                            need_search = False
                            route_confidence = 1.0
                            search_judge_in_t = 0
                            search_judge_out_t = 0
                            search_judge_cost = 0
                            requires_estimation = False

                        else:
                            router_start_time = time.time()
                            (
                                need_search,
                                response_mode,
                                route_confidence,
                                search_judge_in_t,
                                search_judge_out_t,
                                search_judge_cost,
                                requires_estimation
                            ) = classify_search_and_response_mode(
                                user_input=user_input,
                                recent_history_str=recent_history_for_router
                            )
                            router_elapsed = time.time() - router_start_time
                            route_source = "llm_router"
                            
                            # 通常会話・相談など、ユーザー固有の文脈が役立つ場合だけ
                            # 関連する過去会話を検索する
                            if response_mode in {"conversation", "support", "default"}:
                                keywords = (build_memory_search_query(user_input))
                                matched_keywords = filter_keywords_by_memory(
                                        keywords.split(),
                                        summary_memory_context_for_router
                                )
                                related_keywords = extract_related_memory_lines(
                                        matched_keywords,
                                        summary_memory_context_for_router
                                )
                          
                                debug_text("DEBUG keywords", keywords)
                                debug_text("DEBUG matched_keywords", matched_keywords)
                                debug_text("DEBUG related_keywords", related_keywords)

                                search_queries = (
                                    build_past_log_search_queries(
                                        original_keywords=keywords,
                                        related_memory_lines=related_keywords,
                                        max_queries=3
                                    )
                                )
                                # debug_json("DEBUG past_log_search_queries",search_queries)

                                search_start_time = time.time()

                                parallel_past_log_results = (
                                    search_past_logs_parallel(
                                        search_queries = search_queries,
                                        excluded_message_ids = recent_context_message_ids,
                                        max_workers=3
                                    )
                                )
                                # debug_json("DEBUG parallel_past_log_results", parallel_past_log_results)

                                past_logs_context = (
                                    merge_parallel_past_log_results(
                                        parallel_results=(parallel_past_log_results),
                                        final_conversation_count=3
                                    )
                                )
                                debug_json("DEBUG past_logs_context", past_logs_context)

                                search_elapsed = (time.time() - search_start_time)                          

                        
                        # debug_text("DEBUG requires_estimation", requires_estimation)

                        numeric_estimate_instruction = ""
                        if requires_estimation:
                            numeric_estimate_instruction = """
                            【数値試算のルール】
                            ・Pythonによる計算結果が提供されている場合は、その数値を正確に使用し、独自に再計算や補正をしないでください。
                            ・Pythonによる計算結果がない場合は、ユーザーが提示した情報と検索結果で確認できる事実だけを使用してください。
                            ・再現可能な単純計算ができる場合は、その結果を「単純計算による参考値」と明示してください。
                            ・確認できない料率、係数、相場、割合、契約条件を推測してはいけません。
                            ・正式な結果に必要な条件が不足している場合は、参考値と確定値を区別し、不足条件と確認方法を説明してください。
                            ・再現可能な計算ができない場合は、無理に数値を作らないでください。
                            ・冒頭の結果、計算式、内訳、まとめの数値を一致させてください。

                            回答順:
                            1. Python計算結果または再現可能な参考値
                            2. 計算方法と前提
                            3. 正式な結果との差が生じる要因
                            4. 正確な確認方法
                            """
                        # search_start_time = time.time()
                        
                        # enhanced_memory_search_query = (
                        #     f"{memory_search_query} "
                        #     f"{memory_related_keywords}"
                        # ).strip()
                        # enhanced_memory_search_query = []
                        # past_logs_context = search_past_logs_hybrid(user_input)
                        # past_logs_context = search_past_logs_hybrid(related_keywords_text)

                        # search_elapsed = time.time() - search_start_time

                        if need_search and response_mode == "analysis":
                            processing_type = "simple_search_analysis"

                        elif need_search:
                            processing_type = "simple_search"

                        elif response_mode == "analysis":
                            processing_type = "simple_analysis"

                        else:
                            processing_type = "normal_chat"

                        # 判定済みのresponse_modeと一緒にユーザー発言をDBへ保存

                        if not save_message(
                            role="user",
                            content=user_input,
                            message_id=current_msg_id,
                            response_mode=response_mode,
                            processing_type=processing_type
                        ):
                            st.stop()
                        
                        all_messages.append({
                            "role": "user",
                            "content": user_input,
                            "message_id": current_msg_id,
                            "response_mode": response_mode,
                            "processing_type": processing_type,
                            "chat_room": "talk",
                            "created_at": datetime.now(JST).isoformat()
                        })
                        st.session_state.force_message_reload = True
                        
                        if past_logs_context:
                            logs_text = []
                            for log in past_logs_context:
                                role_name = display_user_name if log.get("role") == "user" else current_concierge_name
                                raw_date = log.get("created_at", "")
                                clean_date = raw_date.replace("T", " ")[:16] if raw_date else "日時不明"
                                logs_text.append(f"・[{clean_date}] {role_name}: {log.get('content', '')}")
                            past_logs_str = "\n".join(logs_text)

                            # st.code(past_logs_str, language="text")

                        else:
                            past_logs_str = "該当する過去ログなし"

                        # ==========================================
                        # 独立したPython計算ツール判定
                        # ==========================================

                        tool_router_elapsed = 0.0
                        tool_route_confidence = 0.0
                        tool_router_in_t = 0
                        tool_router_out_t = 0
                        tool_router_cost = 0.0

                        pending_tool = (
                            "real_estate_sale"
                            if st.session_state.get(
                                "real_estate_calculation_pending",
                                False
                            )
                            else "none"
                        )
                        # debug_text(
                        #     "DEBUG real_estate_calculation_pending",
                        #     st.session_state.get(
                        #         "real_estate_calculation_pending",
                        #         False
                        #     )
                        # )

                        # debug_text(
                        #     "DEBUG pending_tool",
                        #     pending_tool
                        # )

                        # debug_json(
                        #     "DEBUG calculation_arguments",
                        #     st.session_state.get(
                        #         "real_estate_calculation_arguments",
                        #         {}
                        #     )
                        # )

                        #不動産計算キーワード有無判定
                        contains_real_estate_hint = (
                            contains_real_estate_sale_hint(user_input)
                        )


                        debug_text("DEBUG contains_real_estate_hint", contains_real_estate_hint)
                        debug_text("DEBUG user_input", user_input)
                        debug_text("DEBUG need_search", need_search)
                        debug_text("DEBUG response_mode", response_mode)

                        # ==========================================
                        # 計算ツール判定の実行制御
                        # ==========================================
                        # 不動産計算継続中
                        if pending_tool == "real_estate_sale":
                            calculation_tool = "real_estate_sale"
                            should_run_tool_router = False
                        
                        # 計算関連ワードがあれば優先
                        elif contains_real_estate_hint:
                            # debug_text("DEBUG entered_contains_calculation_hint", True)

                            should_run_tool_router = True
                     
                            tool_router_start_time = (time.time())

                            (
                                calculation_tool,
                                tool_route_confidence,
                                tool_router_in_t,
                                tool_router_out_t,
                                tool_router_cost
                            ) = classify_calculation_tool(
                                user_input=user_input,
                                recent_history_str=
                                    recent_history_for_router,
                                pending_tool=pending_tool
                            )
                            debug_text("DEBUG calculation_tool", calculation_tool)
                            debug_text("DEBUG tool_route_confidence", tool_route_confidence)

                            tool_router_elapsed = (time.time() - tool_router_start_time)

                        # 検索系質問
                        elif need_search:
                            calculation_tool = "none"
                            should_run_tool_router = False
                        
                        # # 計算がありそうな会話だけ判定
                        # elif response_mode in {
                        #     "analysis",
                        #     "default"
                        # }:
                        #     should_run_tool_router = True
                     
                        #     tool_router_start_time = (time.time())

                        #     (
                        #         calculation_tool,
                        #         tool_route_confidence,
                        #         tool_router_in_t,
                        #         tool_router_out_t,
                        #         tool_router_cost
                        #     ) = classify_calculation_tool(
                        #         user_input=user_input,
                        #         recent_history_str=
                        #             recent_history_for_router,
                        #         pending_tool=pending_tool
                        #     )

                        #     tool_router_elapsed = (time.time() - tool_router_start_time)

                        # 計算ヒントがない通常会話・分析
                        else:
                            calculation_tool = "none"
                            should_run_tool_router = False

                        # 案件選択が成功した場合は、
                        # 「1」を再判定せず不動産計算へ強制復帰する
                        if selected_case_resume_arguments is not None:
                            calculation_tool = "real_estate_sale"
                        
                        if "DEBUG selected_case_resume_arguments" in locals():
                            debug_json(
                                "DEBUG selected_case_resume_arguments",
                                selected_case_resume_arguments
                            )
                        
                        if should_run_tool_router:
                            save_system_audit_log(
                                user_id=CURRENT_USER_ID,
                                plan_type=current_plan_type,
                                event_type=(
                                    "CALCULATION_TOOL_ROUTER"
                                ),
                                processing_time=(
                                    tool_router_elapsed
                                ),
                                in_t=(
                                    tool_router_in_t
                                ),
                                out_t=(
                                    tool_router_out_t
                                ),
                                api_cost=(
                                    tool_router_cost
                                ),
                                details=(
                                    f"provider={BACKGROUND_PROVIDER}"
                                    f" | model={SEARCH_MODEL_NAME}"
                                    f" | tool={calculation_tool}"
                                    f" | pending={pending_tool}"
                                    f" | confidence={tool_route_confidence:.2f}"
                                    # f"ツール: {calculation_tool}"
                                    # f" | 継続中: {pending_tool}"
                                    # f" | 信頼度: "
                                    # f"{tool_route_confidence:.2f}"
                                ),
                                message_id=str(
                                    current_msg_id
                                )
                            )

                            if (
                                tool_router_in_t > 0
                                or tool_router_out_t > 0
                            ):
                                add_permanent_tokens(
                                    CURRENT_USER_ID,
                                    "calculation_tool_router",
                                    tool_router_in_t,
                                    tool_router_out_t
                                )

                        save_system_audit_log(
                            user_id=CURRENT_USER_ID,
                            plan_type=current_plan_type,
                            event_type="RESPONSE_ROUTER",
                            processing_time=router_elapsed,
                            in_t=search_judge_in_t,
                            out_t=search_judge_out_t,
                            api_cost=search_judge_cost,
                            details=(
                                f"provider={BACKGROUND_PROVIDER}"
                                f" | model={SEARCH_MODEL_NAME}"
                                f"検索要否: "
                                f"{'YES' if need_search else 'NO'}"
                                f" | 回答モード: {response_mode}"
                                f" | ルート: {route_source}"
                                f" | 信頼度: {route_confidence:.2f}"
                            ),
                            message_id=str(current_msg_id)
                        )

                        grounded_direct_response = False
                        grounded_response_route = ("main_chat_response")
                        search_model_name = GOOGLE_MODEL_NAME

                        if need_search:
                            search_config = (
                                build_grounded_response_config(
                                    processing_type=processing_type,
                                    style_preset=current_style_preset,
                                    recent_history=recent_history_for_router,
                                    user_input=user_input
                                )
                            )

                            search_query = search_config["prompt"]
                            search_model_name = (search_config["model_name"])
                            grounded_direct_response = bool(
                                search_config["use_direct_response"]
                            )
                            grounded_response_route = str(
                                search_config["response_route"]
                            )

                            search_execution_start = time.time()

                            search_response = google_search(
                                search_query,
                                model_name=search_model_name
                            )
                            search_execution_elapsed = (time.time() - search_execution_start)
                            search_result = (search_response.get("text", "なし"))
                            if CURRENT_USER_ID == ADMIN_USER_ID:
                                st.markdown("##### 🔎 Google検索結果デバッグ")
                                st.code(search_result, language="text")
                            search_in_tokens = int(search_response.get("in_tokens", 0))
                            search_out_tokens = int(search_response.get("out_tokens", 0))
                            # search_cost = (search_in_tokens * PRICE_GOOGLESEARCH_IN + search_out_tokens * PRICE_GOOGLESEARCH_OUT)
                            search_cost = calculate_ai_cost(
                                provider=GOOGLE_SEARCH_PROVIDER,
                                in_tokens=search_in_tokens,
                                out_tokens=search_out_tokens,
                                is_chat=(
                                    search_model_name
                                    == GROUNDED_RESPONSE_MODEL_NAME
                                )
                            )

                            save_system_audit_log(
                                user_id=CURRENT_USER_ID,
                                plan_type=current_plan_type,
                                event_type="SEARCH_EXECUTION",
                                processing_time=search_execution_elapsed,
                                in_t=search_in_tokens,
                                out_t=search_out_tokens,
                                api_cost=search_cost,
                                # details="Google Search Grounding",
                                details=(
                                    f"provider={GOOGLE_SEARCH_PROVIDER}"
                                    f" | model={search_model_name}"
                                    f" | Google Search Grounding"
                                    f" | 処理区分={processing_type}"
                                    f" | 回答モード={response_mode}"
                                ),
                                message_id=str(current_msg_id)
                            )

                            add_permanent_tokens(
                                CURRENT_USER_ID,
                                "search_execution",
                                search_in_tokens,
                                search_out_tokens
                            )

                            try:
                                supabase.table("search_logs").insert({
                                    "user_id": CURRENT_USER_ID,
                                    "search_query": user_input
                                    }).execute()
                            except Exception as e:
                                print(f"検索ログ取得エラー {CURRENT_USER_ID}: {e}")

                        else:
                            search_result = "なし"
                        
                        # ==========================================
                        # Python不動産売却計算
                        # ==========================================

                        calculation_extraction_result = {
                            "should_calculate": False,
                            "arguments": {},
                            "extraction_status":
                                "not_applicable",
                            "in_tokens": 0,
                            "out_tokens": 0,
                            "cost": 0.0
                        }

                        calculation_execution_result = {
                            "status": "not_applicable",
                            "result": None,
                            "missing_fields": [],
                            "error": None
                        }

                        calculation_pending = bool(
                            st.session_state.get("real_estate_calculation_pending", False)
                        )
                        debug_text(
                            "DEBUG exit_calculation_check",
                            should_exit_real_estate_calculation(user_input)
                        )

                        exit_calculation_mode = False
                        if (
                            calculation_pending
                            and should_exit_real_estate_calculation(user_input)
                        ):
                            st.session_state["real_estate_calculation_pending"] = False
                            calculation_pending = False
                            calculation_tool = "none"
                            exit_calculation_mode = True

                            debug_text("DEBUG exit_calculation_mode", True)

                        debug_text(
                            "DEBUG active_calculation_case_id",
                            st.session_state.get(
                                "active_calculation_case_id"
                            )
                        )

                        debug_text(
                            "DEBUG active_calculation_case_name",
                            st.session_state.get(
                                "active_calculation_case_name"
                            )
                        )

                        if "DEBUG calculation_pending" in locals():
                            debug_json(
                                "DEBUG calculation_pending",
                                calculation_pending
                            )

                        is_calculation_candidate = (
                            not exit_calculation_mode
                            and calculation_tool
                            == "real_estate_sale"
                        )

                        if is_calculation_candidate:
                            calculation_start_time = (
                                time.time()
                            )

                            if selected_case_resume_arguments is not None:
                                calculation_extraction_result = {
                                    "should_calculate": True,
                                    "arguments": dict(selected_case_resume_arguments),
                                    "extraction_status": "extracted",
                                    "in_tokens": 0,
                                    "out_tokens": 0,
                                    "cost": 0.0
                                }
                                
                                previous_arguments = {}
                                current_arguments = dict(selected_case_resume_arguments)

                                if "DEBUG selected_case_resume_arguments" in locals():
                                    debug_json(
                                        "DEBUG selected_case_resume_arguments",
                                        selected_case_resume_arguments
                                    )

                            else:
                                calculation_extraction_result = extract_real_estate_sale_parameters(
                                    user_input=user_input,
                                    recent_history="",
                                    calculation_pending=calculation_pending
                                )

                                if "DEBUG calculation_extraction_result" in locals():
                                    debug_json(
                                        "DEBUG calculation_extraction_result",
                                        calculation_extraction_result
                                    )

                                if calculation_pending:
                                    should_calculate_now = bool(
                                        calculation_extraction_result.get(
                                            "should_calculate",
                                            False
                                        )
                                    )

                                    if should_calculate_now:
                                        calculation_extraction_result[
                                            "should_calculate"
                                        ] = True

                                        if (
                                            calculation_extraction_result.get(
                                                "extraction_status"
                                            )
                                            == "not_applicable"
                                        ):
                                            calculation_extraction_result[
                                                "extraction_status"
                                            ] = "extracted"

                                    else:
                                        # 計算と無関係な会話なので
                                        # 計算モードだけ解除する
                                        st.session_state[
                                            "real_estate_calculation_pending"
                                        ] = False

                                active_calculation_case_id = (
                                    st.session_state.get(
                                        "active_calculation_case_id"
                                    )
                                )

                                previous_arguments = {}

                                if active_calculation_case_id:
                                    # 操作中案件のDB保存データを基準にする
                                    active_case = get_calculation_case(
                                        active_calculation_case_id
                                    )

                                    previous_arguments = dict(
                                        active_case.get(
                                            "case_data",
                                            {}
                                        )
                                        or {}
                                    )

                                    # DB保存後にセッションだけで保持している条件があれば上書き
                                    session_arguments = dict(
                                        st.session_state.get(
                                            "real_estate_calculation_arguments",
                                            {}
                                        )
                                        or {}
                                    )

                                    previous_arguments.update(session_arguments)

                                elif calculation_pending:
                                    previous_arguments = dict(
                                        st.session_state.get(
                                            "real_estate_calculation_arguments",
                                            {}
                                        )
                                        or {}
                                    )
                                
                                current_arguments = dict(
                                    calculation_extraction_result.get(
                                        "arguments",
                                        {}
                                    )
                                    or {}
                                )
                            
                            if (
                                current_arguments.get("acquisition_date")
                                and not current_arguments.get(
                                    "building_acquisition_date"
                                )
                            ):
                                current_arguments[
                                    "building_acquisition_date"
                                ] = current_arguments[
                                    "acquisition_date"
                                ]

                            if "DEBUG current_arguments" in locals():
                                debug_json(
                                    "DEBUG current_arguments",
                                    current_arguments
                                )

                            extraction_elapsed = (time.time() - calculation_start_time)

                            # st.write("calculation_extraction_result")
                            # st.code(
                            #     json.dumps(
                            #         calculation_extraction_result,
                            #         ensure_ascii=False,
                            #         indent=2,
                            #         default=str
                            #     ),
                            #     language="json"
                            # )

                            total_cost_expressions = {
                                "総取得費",
                                "取得費合計",
                                "合算簿価",
                                "購入経費込の取得費",
                                "土地建物合計"
                            }

                            total_cost_is_explicit = any(
                                expression in user_input
                                for expression in total_cost_expressions
                            )

                            # 通常の発言抽出時だけ、
                            # 「総取得費」と明示されていない値を除外する。
                            # 案件復元時は保存済みの総取得費をそのまま維持する。
                            if (
                                selected_case_resume_arguments is None
                                and not total_cost_is_explicit
                            ):
                                current_arguments.pop(
                                    "total_acquisition_cost",
                                    None
                                )

                            if "DEBUG previous_arguments" in locals():
                                debug_json(
                                    "DEBUG previous_arguments",
                                    previous_arguments
                                )

                            # 前回条件を今回条件で上書きする
                            # 同じ項目がある場合は最新発言を優先
                            merged_arguments = dict(previous_arguments)
                            for key, value in current_arguments.items():
                                if value is None:
                                    continue
                                if value == "":
                                    continue
                                # 数値項目で0なら前回値を維持
                                if (
                                    key in REAL_ESTATE_NUMERIC_FIELDS
                                    and str(value) == "0"
                                    and key in previous_arguments
                                    and key not in {
                                        "land_acquisition_cost",
                                        "building_acquisition_cost",
                                        "acquisition_related_costs"
                                    }
                                ):
                                    continue

                                merged_arguments[key] = value

                                if should_reset_brokerage_fee(user_input):
                                    merged_arguments.pop("brokerage_fee",None)

                                if (
                                    "acquisition_related_costs" not in current_arguments
                                    and merged_arguments.get("acquisition_related_costs") in {
                                        0,
                                        "0",
                                        Decimal("0")
                                    }
                                ):
                                    merged_arguments.pop("acquisition_related_costs", None)
                            
                            # 取得日から長期・短期を自動判定
                            if (
                                not merged_arguments.get("holding_period_type")
                                and merged_arguments.get("acquisition_date")
                            ):

                                try:
                                    acquisition_date = (
                                        merged_arguments.get(
                                            "acquisition_date"
                                        )
                                    )

                                    sale_date = (
                                        merged_arguments.get(
                                            "sale_date"
                                        )
                                        or datetime.now(JST).date().isoformat()
                                    )
                                    
                                    holding_period_type = (
                                        determine_individual_holding_type(
                                            acquisition_date,
                                            sale_date
                                        )
                                    )

                                    if holding_period_type:

                                        merged_arguments[
                                            "holding_period_type"
                                        ] = holding_period_type

                                except Exception:
                                    pass
                            
                            for field in CONFIRMABLE_FIELDS:
                                if (
                                    field in current_arguments
                                    and current_arguments.get(field) is not None
                                ):
                                    merged_arguments[f"{field}_confirmed"] = True
                            
                            if (
                                "loan_balance" in current_arguments
                                and current_arguments.get(
                                    "loan_balance"
                                ) is not None
                            ):
                                merged_arguments[
                                    "loan_balance_confirmed"
                                ] = True

                            for field in ACQUISITION_COMPONENT_FIELDS:
                                field_value = merged_arguments.get(field)
                                confirmed_field = f"{field}_confirmed"
                                if field_value is None:
                                    continue
                                try:
                                    field_amount = to_decimal(field_value)
                                except (
                                    ValueError,
                                    TypeError,
                                    ArithmeticError
                                ):
                                    continue
                                if (
                                    field_amount == Decimal("0")
                                    and not merged_arguments.get(
                                        confirmed_field,
                                        False
                                    )
                                ):
                                    merged_arguments.pop(field, None)

                            if (st.session_state.get("active_calculation_case_name") == "自宅売却" and calculation_pending):
                                merged_arguments["property_usage"] = "owner_occupied"
                                merged_arguments["owner_type"] = "individual"
                            
                            if (
                                current_arguments.get("building_acquisition_cost")
                                is not None
                                and current_arguments.get("total_acquisition_cost")
                                in {None, "", 0, "0"}
                            ):
                                merged_arguments["total_acquisition_cost"] = 0
                            
                            calculation_extraction_result["arguments"] = merged_arguments

                            # 総取得費は0円を含めて明示値を保持する
                            total_acquisition_cost_value = (
                                current_arguments.get(
                                    "total_acquisition_cost"
                                )
                            )

                            if total_acquisition_cost_value is not None:
                                merged_arguments[
                                    "total_acquisition_cost"
                                ] = total_acquisition_cost_value

                            if "merged_arguments" in locals():
                                debug_json(
                                    "DEBUG merged_arguments",
                                    merged_arguments
                                )

                            # st.write("DEBUG merged_arguments")
                            # st.code(
                            #     json.dumps(
                            #         make_json_safe(merged_arguments),
                            #         ensure_ascii=False,
                            #         indent=2,
                            #         default=str
                            #     ),
                            #     language="json"
                            # )

                            # st.write("previous_arguments")
                            # st.code(
                            #     json.dumps(
                            #         previous_arguments,
                            #         ensure_ascii=False,
                            #          indent=2,
                            #         default=str
                            #     ),
                            #     language="json"
                            # )
                            # st.write("current_arguments")
                            # st.code(
                            #     json.dumps(
                            #         merged_arguments,
                            #         ensure_ascii=False,
                            #         indent=2,
                            #         default=str
                            #     ),
                            #     language="json"
                            # )

                            # st.write("calculation_tool", calculation_tool)
                            # st.write("merged_arguments", merged_arguments)
                            # st.write(
                            #     "active_case",
                            #     st.session_state.get(
                            #         "active_calculation_case_id"
                            #     )
                            # )

                            # st.write(
                            #     "active_case",
                            #     st.session_state.get(
                            #         "active_calculation_case_id"
                            #     )
                            # )

                            if (
                                calculation_tool == "real_estate_sale"
                                and merged_arguments
                                and not st.session_state.get(
                                    "active_calculation_case_id"
                                )
                            ):
                                candidates = (
                                    get_calculation_case_candidates(
                                        case_type="real_estate_sale",
                                        user_input=user_input
                                    )
                                )

                                if not candidates:

                                    property_usage = (
                                        merged_arguments.get(
                                            "property_usage"
                                        )
                                    )
                                    if not property_usage:
                                        property_usage = "investment"

                                    create_result = (
                                        create_calculation_case(
                                            case_type="real_estate_sale",
                                            property_usage=property_usage,
                                            case_data=merged_arguments,
                                            current_plan_type=current_plan_type
                                        )
                                    )
                                    # st.write(create_result)

                                    if create_result.get("success"):

                                        st.session_state[
                                            "active_calculation_case_id"
                                        ] = (
                                            create_result.get(
                                                "case_id"
                                            )
                                        )
                                else:
                                    st.session_state["pending_case_candidates"] = candidates
                                    st.session_state["pending_case_selection"] = True
                                    
                                    pending_case_arguments = {
                                        key: value
                                        for key, value in current_arguments.items()
                                        if (
                                            value is not None
                                            and value != ""
                                        )
                                    }

                                    pending_case_arguments = {
                                        key: value
                                        for key, value
                                        in current_arguments.items()
                                        if (
                                            value is not None
                                            and value != ""
                                        )
                                    }

                                    st.session_state[
                                        "pending_case_arguments"
                                    ] = make_json_safe(
                                        pending_case_arguments
                                    )

                                    candidate_lines = []
                                    for i, case in enumerate(candidates, start=1):

                                        updated_at = (
                                            str(case.get("updated_at", ""))
                                            .replace("T", " ")[:16]
                                        )

                                        candidate_lines.append(
                                            f"{i}. {case.get('case_name', '')}\n"
                                            f"最終更新: {updated_at}"
                                        )

                                    new_case_number = len(candidates) + 1
                                    candidate_lines.append(f"{new_case_number}. 新しく追加")

                                    ai_reply = (
                                        "以前の計算案件が見つかりました。\n\n"
                                        + "\n\n".join(candidate_lines)
                                        + "\n\nどの案件を利用しますか？"
                                    )

                                    all_messages.append({
                                        "role": "assistant",
                                        "content": ai_reply,
                                        "message_id": current_msg_id,
                                        "response_mode": response_mode,
                                        "processing_type": processing_type,
                                        "chat_room": "talk",
                                        "created_at": datetime.now(JST).isoformat()
                                    })

                                    save_message(
                                        role="assistant",
                                        content=ai_reply,
                                        message_id=current_msg_id,
                                        response_mode=response_mode,
                                        processing_type=processing_type
                                    )

                                    display_message(
                                        current_concierge_name,
                                        ai_reply
                                    )

                                    st.session_state.force_message_reload = True
                                    st.stop()
                                    
                            elif (
                                calculation_tool == "real_estate_sale"
                                and merged_arguments
                                and st.session_state.get(
                                    "active_calculation_case_id"
                                )
                            ):
                                debug_json(
                                    "DEBUG case_update_arguments",
                                    merged_arguments
                                )
                                update_calculation_case(
                                    case_id=st.session_state["active_calculation_case_id"],
                                    case_name=st.session_state.get("active_calculation_case_name"),
                                    new_case_data=merged_arguments
                                )

                            # st.write("merged_arguments")
                            # st.code(
                            #     json.dumps(
                            #         merged_arguments,
                            #         ensure_ascii=False,
                            #         indent=2,
                            #         default=str
                            #     ),
                            #     language="json"
                            # )

                            calculation_execution_result = (
                                execute_real_estate_sale_calculation(
                                    calculation_extraction_result
                                )
                            )

                            if "DEBUG calculation_execution_result" in locals():
                                debug_json(
                                    "DEBUG calculation_execution_result",
                                    calculation_execution_result
                                )

                            calculation_elapsed = (
                                time.time()
                                - calculation_start_time
                            )

                            calculation_status = (
                                calculation_execution_result.get(
                                    "status",
                                    "calculation_error"
                                )
                            )

                            formatted_result = None

                            if calculation_status == "missing_fields":
                                missing_fields = (
                                    calculation_execution_result.get(
                                        "missing_fields",
                                        []
                                    )
                                )

                                st.session_state[
                                    "real_estate_calculation_arguments"
                                ] = normalize_real_estate_sale_arguments(
                                    merged_arguments,
                                    apply_defaults=False
                                )

                                st.session_state[
                                    "real_estate_calculation_pending"
                                ] = True

                                labels = [
                                    REAL_ESTATE_FIELD_LABELS.get(
                                        field,
                                        field
                                    )
                                    for field in missing_fields
                                ]

                                debug_json(
                                    "DEBUG missing_fields_current_arguments",
                                    st.session_state.get(
                                        "real_estate_calculation_arguments",
                                        {}
                                    )
                                )

                                ai_reply = format_missing_fields_message(
                                    case_name=st.session_state.get(
                                        "active_calculation_case_name",
                                        ""
                                    ),
                                    current_arguments=st.session_state.get(
                                        "real_estate_calculation_arguments",
                                        {}
                                    ),
                                    missing_fields=missing_fields
                                )

                                all_messages.append({
                                    "role": "assistant",
                                    "content": ai_reply,
                                    "message_id": current_msg_id,
                                    "response_mode": response_mode,
                                    "chat_room": "talk",
                                    "created_at": datetime.now(JST).isoformat()
                                })

                                save_message(
                                    role="assistant",
                                    content=ai_reply,
                                    message_id=current_msg_id,
                                    response_mode=response_mode
                                )

                                display_message(
                                    current_concierge_name,
                                    ai_reply
                                )
                                st.session_state.force_message_reload = True
                                st.stop()

                            if calculation_status == "missing_fields":
                                # 条件不足の場合は、
                                # 確認済み条件を次の会話まで保持
                                try:
                                    saved_arguments = (
                                        normalize_real_estate_sale_arguments(
                                            merged_arguments,
                                            apply_defaults=False
                                        )
                                    )
                                    
                                    if "DEBUG missing_saved_arguments" in locals():
                                        debug_json(
                                            "DEBUG missing_saved_arguments",
                                            saved_arguments
                                        )

                                except Exception:
                                    saved_arguments = (merged_arguments)

                                st.session_state[
                                    "real_estate_calculation_arguments"
                                ] = saved_arguments

                                st.session_state[
                                    "real_estate_calculation_pending"
                                ] = True

                                missing_fields = (
                                    calculation_execution_result.get(
                                        "missing_fields",
                                        []
                                    )
                                )

                                save_system_audit_log(
                                    user_id=CURRENT_USER_ID,
                                    plan_type=current_plan_type,
                                    event_type=(
                                        "CALCULATION_MISSING_FIELDS"
                                    ),
                                    processing_time=0.0,
                                    in_t=0,
                                    out_t=0,
                                    api_cost=0.0,
                                    details=(
                                        "tool=real_estate_sale"
                                        " | missing="
                                        + ",".join(
                                            missing_fields
                                        )
                                    ),
                                    message_id=str(
                                        current_msg_id
                                    )
                                )

                            elif calculation_status == "success":
                                # 計算に使用した最新条件を、次回の再計算用に保持
                                saved_arguments = dict(
                                    merged_arguments
                                )

                                try:
                                    normalized_saved_arguments = (
                                        normalize_real_estate_sale_arguments(
                                            merged_arguments,
                                            apply_defaults=False
                                        )
                                    )
                                    if normalized_saved_arguments:
                                        saved_arguments = (
                                            normalized_saved_arguments
                                        )

                                except Exception:
                                    pass

                                debug_json(
                                    "DEBUG saved_arguments",
                                    saved_arguments
                                )

                                st.session_state[
                                    "real_estate_calculation_arguments"
                                ] = saved_arguments

                                st.session_state[
                                    "real_estate_calculation_pending"
                                ] = True

                                result = dict(
                                    calculation_execution_result.get(
                                        "result",
                                        {}
                                    )
                                    or {}
                                )

                                # 成功時だけ固定表示を生成
                                case_name = st.session_state.get(
                                    "active_calculation_case_name",
                                    ""
                                )

                                if current_plan_type == "🆓 無料プラン":

                                    formatted_result = (
                                        format_real_estate_result_free(
                                            result=result,
                                            case_name=case_name
                                        )
                                    )
                                else:

                                    formatted_result = (
                                        format_real_estate_result_standard(
                                            result=result,
                                            case_name=case_name
                                        )
                                    )

                                save_system_audit_log(
                                    user_id=CURRENT_USER_ID,
                                    plan_type=current_plan_type,
                                    event_type=(
                                        "CALCULATION_SUCCESS"
                                    ),
                                    processing_time=0.0,
                                    in_t=0,
                                    out_t=0,
                                    api_cost=0.0,
                                    details=(
                                        "tool=real_estate_sale"
                                        f" | owner={result.get('owner_type')}"
                                        f" | holding={result.get('holding_type')}"
                                        f" | taxable_gain={result.get('taxable_gain')}"
                                        f" | tax={result.get('estimated_tax')}"
                                        f" | cash_after_tax={result.get('cash_after_tax')}"
                                    ),
                                    message_id=str(
                                        current_msg_id
                                    )
                                )

                            elif calculation_status == (
                                "calculation_error"
                            ):
                                # 入力値の修正を受け付けるため、
                                # 現在の条件を保持
                                try:
                                    saved_arguments = (
                                        normalize_real_estate_sale_arguments(
                                            merged_arguments
                                        )
                                    )
                                except Exception:
                                    saved_arguments = (
                                        merged_arguments
                                    )

                                st.session_state[
                                    "real_estate_calculation_arguments"
                                ] = saved_arguments

                                st.session_state[
                                    "real_estate_calculation_pending"
                                ] = True

                                save_system_audit_log(
                                    user_id=CURRENT_USER_ID,
                                    plan_type=current_plan_type,
                                    event_type=("CALCULATION_ERROR"),
                                    processing_time=0.0,
                                    in_t=0,
                                    out_t=0,
                                    api_cost=0.0,
                                    details=(
                                        "tool=real_estate_sale"
                                        f" | error={calculation_execution_result.get('error', '')}"
                                    )[:500],
                                    message_id=str(current_msg_id)
                                )

                            elif calculation_status == (
                                "extraction_error"
                            ):
                                # 抽出失敗時は以前の条件を消さず、
                                # 再入力を受け付ける
                                st.session_state[
                                    "real_estate_calculation_pending"
                                ] = True

                            else:
                                st.session_state[
                                    "real_estate_calculation_arguments"
                                ] = {}

                                st.session_state[
                                    "real_estate_calculation_pending"
                                ] = False

                            extraction_in_tokens = int(
                                calculation_extraction_result.get(
                                    "in_tokens",
                                    0
                                )
                                or 0
                            )

                            extraction_out_tokens = int(
                                calculation_extraction_result.get(
                                    "out_tokens",
                                    0
                                )
                                or 0
                            )

                            extraction_cost = float(
                                calculation_extraction_result.get(
                                    "cost",
                                    0.0
                                )
                                or 0.0
                            )

                            save_system_audit_log(
                                user_id=CURRENT_USER_ID,
                                plan_type=current_plan_type,
                                event_type=(
                                    "CALCULATION_EXTRACTION"
                                ),
                                processing_time=
                                    extraction_elapsed,
                                in_t=
                                    extraction_in_tokens,
                                out_t=
                                    extraction_out_tokens,
                                api_cost=
                                    extraction_cost,
                                details=(
                                    f"provider={BACKGROUND_PROVIDER}"
                                    f" | model={SEARCH_MODEL_NAME}"
                                    f" | tool=real_estate_sale"
                                    # "tool=real_estate_sale"
                                ),
                                message_id=str(
                                    current_msg_id
                                )
                            )

                            if formatted_result is not None:
                                # save_message(
                                #     "user",
                                #     user_input,
                                #     current_msg_id,
                                #     "conversation"
                                # )

                                save_message(
                                    "assistant",
                                    formatted_result,
                                    current_msg_id,
                                    "conversation",
                                )

                                # all_messages.append({
                                #         "role": "user",
                                #         "content": user_input,
                                #         "message_id": current_msg_id,
                                #         "response_mode": "conversation",
                                #         "created_at": datetime.now(
                                #             JST
                                #         ).isoformat()
                                # })

                                all_messages.append({
                                        "role": "assistant",
                                        "content": formatted_result,
                                        "message_id": current_msg_id,
                                        "response_mode": "conversation",
                                        "chat_room": "talk",
                                        "created_at": datetime.now(JST).isoformat()
                                })

                                st.session_state["force_message_reload"] = True

                                display_message(
                                    current_concierge_name,
                                    formatted_result
                                )

                                st.stop()

                            if (
                                extraction_in_tokens > 0
                                or extraction_out_tokens > 0
                            ):
                                add_permanent_tokens(
                                    CURRENT_USER_ID,
                                    "real_estate_extraction",
                                    extraction_in_tokens,
                                    extraction_out_tokens
                                )

                            # save_system_audit_log(
                            #     user_id=CURRENT_USER_ID,
                            #     plan_type=current_plan_type,
                            #     event_type=(
                            #         "REAL_ESTATE_CALCULATION"
                            #     ),
                            #     processing_time=(
                            #         calculation_elapsed
                            #     ),
                            #     in_t=extraction_in_tokens,
                            #     out_t=extraction_out_tokens,
                            #     api_cost=extraction_cost,
                            #     details=(
                            #         "不動産売却計算"
                            #         " | 状態: "
                            #         f"{calculation_status}"
                            #     ),
                            #     message_id=str(
                            #         current_msg_id
                            #     )
                            # )

                        calculation_prompt_block = (
                            build_real_estate_calculation_context(
                                calculation_execution_result
                            )
                        )

                        # st.write(
                        #     f"DEBUG status = "
                        #     f"{calculation_execution_result.get('status')}"
                        # )
                        # st.code(
                        #     build_real_estate_calculation_context(
                        #         calculation_execution_result
                        #     ),
                        #     language="text"
                        # )

                        # if calculation_prompt_block:
                        #     st.code(calculation_prompt_block, language="text")

                        if processing_type in {
                            "simple_analysis",
                            "simple_search_analysis"
                        }:
                            selected_mode_prompt = SIMPLE_ANALYSIS_PROMPT
                        else:
                            selected_mode_prompt = MODE_PROMPTS.get(
                                response_mode,
                                MODE_PROMPTS["default"]
                            )

                        short_history_lines = recent_history_lines[-2:]
                        short_history_str = "\n".join(
                            short_history_lines
                        )
                        if response_mode == "micro_chat":
                            use_recent_history = short_history_str
                        else:
                            use_recent_history = chat_history_str

                        summary_memories = get_memories(source="summary")

                        summary_memory_context = "\n".join(
                            [m["fact"] for m in summary_memories]
                        ) if summary_memories else "なし"

                        if is_micro_chat(user_input):
                            # 超軽量ルート
                            system_instruction = f"""
                            あなたの名前は「{current_concierge_name}」です。
                            対話相手の名前は「{display_user_name}」です。
                            一人称は「{current_first_person}」を使用してください。

                            【現在の人格】
                            {STYLE_PRESETS.get(current_style_preset, "")}

                            {response_length_prompt}

                            【直近の会話履歴】
                            {use_recent_history}

                            {selected_mode_prompt}
                            """

                        else:
                            reply_recent_history = use_recent_history
                            reply_past_logs = past_logs_str

                            # 🧠 お節介＆矛盾防止指示をドッキングしたシステム指示書
                            system_instruction = f"""
                            あなたの名前は「{current_concierge_name}」です。
                            対話相手の名前は「{display_user_name}」です。
                            一人称は「{current_first_person}」を使用してください。

                            【現在の人格】
                            {STYLE_PRESETS.get(current_style_preset, "")}

                            【話し方の決定ルール】
                            ・現在の人格に従って、口調、語尾、一人称、キャラクター性を自然に統一してください。
                            ・直近の会話履歴に含まれる過去のAIの話し方は模倣せず、会話の文脈だけを参照してください。
                            ・人格表現よりも、回答内容の正確さと現在の回答モードの目的を優先してください。

                            【ルールの優先順位】
                            1. 最新のユーザー発言と現在の回答モード
                            2. 確認できた事実と検索結果
                            3. 現在の人格と話し方
                            4. 記憶の要約と手動登録情報
                            5. 直近の会話履歴
                            6. 関連する過去の会話
                            7. 時間帯に応じた気遣い

                            ・下位の情報や演出を理由に、上位の目的、事実、指示を無視しないでください。

                            【現在の日本時間】
                            {current_time_str}

                            【記憶の要約】
                            {summary_memory_context}

                            【ユーザーが手動登録した基本情報】
                            {manual_memory_context}

                            【記憶参照ルール】
                            ・質問に関係する記憶だけを自然に使用し、無関係な情報を列挙しないでください。
                            ・【記憶の要約】と【ユーザーが手動登録した基本情報】を、ユーザー本人に関する事実の主な根拠としてください。
                            ・直近の会話履歴と関連する過去の会話は、記憶を補完する情報として使用してください。
                            ・過去の出来事や以前の会話について質問された場合は、【記憶の要約】に関連情報がないか必ず確認してください。
                            ・【記憶の要約】にある関連情報は、ユーザーにとって継続性や重要性の高い情報として、回答へ優先的に含めてください。
                            ・【直近の会話履歴】や【現在の発言に関連する過去の会話】にも関連情報がある場合は、【記憶の要約】の内容だけに限定せず、矛盾しない範囲ですべて統合してください。
                            ・情報が競合する場合は、ユーザーの発言日時が新しい内容を優先してください。
                            ・推測、解釈、AIの提案を、ユーザー本人の事実や記憶として扱わないでください。
                            ・根拠がない情報は創作せず、必要に応じて「まだ覚えていない」と伝えてください。
                            ・定期的または継続的に行っている活動は、文脈上自然な場合のみ趣味として扱って構いません。
                            ・特定の作品名、番組名、映画タイトルなどは、「趣味」ではなく「好きな作品」として扱ってください。
                            ・仕事、開発、勉強は、ユーザーが趣味だと明示しない限り趣味として扱わないでください。


                            【直近の会話履歴・古い順】
                            {reply_recent_history}

                            【現在の発言に関連する過去の会話】
                            {reply_past_logs}

                            【検索結果】
                            {search_result}

                            {calculation_prompt_block}

                            【履歴の利用ルール】
                            【履歴の利用ルール】
                            ・直近の会話履歴は、現在の話題と会話の流れを理解するために使用してください。
                            ・関連する過去の会話は補助情報として扱い、ユーザー本人の発言だけを事実の根拠にしてください。
                            ・過去の内容を不自然に列挙せず、最新のユーザー発言への回答に必要な部分だけを使用してください。

                            【会話の自然さルール】
                            ・ユーザーの発言をそのまま言い換えたり、単純に復唱したりして回答を始めないでください。
                            ・感想、共感、質問、考察、ツッコミなどから、人格に合った自然な導入を選んでください。
                            ・同じ導入、励まし、休息提案を短い間隔で繰り返さないでください。
                            ・毎回答を質問で終わらせず、感想や考察だけで自然に会話を続けても構いません。
                            ・会話の中心はユーザーとし、話題や考えを必要に応じて深掘りしてください。
                            ・AIが飲食、移動、睡眠、仕事などを実際に行ったかのように話してはいけません。
                            ・「お持ちします」などの演出的な表現は、物理的に実行した事実として扱わないでください。
                            ・最後の会話から3時間以内は、改めて挨拶をしないでください。

                            【質問への対応】
                            ・検索結果がある場合は、その内容を事実確認の主な根拠として使用してください。
                            ・検索結果とユーザーの記憶がある場合は、確認できた事実を基に、ユーザーの状況や好みに合わせて回答してください。
                            ・確認できない情報を推測で断定したり、作品名や固有情報を創作したりしないでください。
                            ・十分な根拠がない場合は、分からないことを明示し、必要に応じて確認方法や関連する質問を提示してください。

                            【時間帯に合わせた気遣い】
                            ・深夜（00:00〜02:00）、未明（02:00〜05:00）、早朝（05:00〜07:00）のみ、必要に応じて短い気遣いを加えてください。
                            ・夜勤や夜型生活の記憶がある場合は、生活時間を否定せず労う表現にしてください。
                            ・直近の会話で同じ時間帯への気遣いをしている場合は繰り返さないでください。
                            ・最新のユーザー発言への回答を優先し、気遣いが不要な場合は省略してください。

                            【時系列と事実の扱い】
                            ・過去の会話にある「今日」「昨日」「明日」は、その発言日時を基準に解釈し、現在日時と混同しないでください。
                            ・予定や意向は、ユーザーが実行したと明示するまで実行済みとして扱わないでください。
                            ・過去の予定を参照する場合は現在日時との整合性を確認し、未確認なら現在の状況を決めつけないでください。
                            ・ユーザーから訂正を受けた場合は、該当箇所だけを自然に訂正し、可能であれば元の質問や依頼への回答を続けてください。
                            ・ユーザーが明示していない感情、予定、経験、事情を決めつけないでください。
                            ・曖昧な発言は都合よく解釈せず、会話の文脈と日時を踏まえて判断してください。
                            
                            【専門作業の制限】
                            ・コード作成、画像生成、長文の執筆や翻訳など、会話支援の範囲を超える制作依頼は実行せず、現在の人格を保って簡潔に断ってください。
                            ・会話の一部として行う短い創作、昔話、寝物語、物語の続きは対応して構いません。

                            【出力形式】
                            ・情報量が多い場合は、見出し、箇条書き、適切な改行を使って読みやすく整理してください。
                            ・太字装飾記号は使用しないでください。

                            {selected_mode_prompt}
                            {numeric_estimate_instruction}
                            """

                        recent_messages = all_messages[-MAX_CONTEXT_MESSAGES:]

                        # st.code(system_instruction, language="text")
                    
                        try:
                            # ==========================================
                            # 通常のテキスト応答生成
                            # ==========================================
                            api_start_time = time.time()

                            if grounded_direct_response:
                                chat_result = {
                                    "text": search_result,
                                    "in_tokens": 0,
                                    "out_tokens": 0
                                }

                                chat_provider_used = GOOGLE_SEARCH_PROVIDER
                                chat_model_used = search_model_name
                                chat_route_name = grounded_response_route

                            elif processing_type == "simple_analysis":
                                simple_analysis_instruction = (
                                    build_simple_analysis_instruction(
                                        style_preset=current_style_preset,
                                        recent_history=recent_history_for_router
                                    )
                                )

                                chat_result = generate_ai_response(
                                    provider=CHAT_PROVIDER,
                                    system_instruction=simple_analysis_instruction,
                                    user_prompt=user_input,
                                    model_name=CHAT_MODEL_NAME
                                )

                                chat_provider_used = CHAT_PROVIDER
                                chat_model_used = CHAT_MODEL_NAME
                                chat_route_name = "lightweight_analysis_response"
                            else:
                                chat_result = generate_ai_response(
                                    provider=CHAT_PROVIDER,
                                    system_instruction=system_instruction,
                                    user_prompt=user_input,
                                    model_name=CHAT_MODEL_NAME
                                )
                                chat_provider_used = CHAT_PROVIDER
                                chat_model_used = CHAT_MODEL_NAME
                                chat_route_name = "main_chat_response"

                            debug_json("DEBUG chat_result", chat_result)

                            api_elapsed = (time.time() - api_start_time)

                            # 通常のテキストをそのまま回答として使用
                            ai_reply = str(chat_result.get("text", "") or "").strip()
                            # debug_text("DEBUG ai_reply", ai_reply)

                            # AIサーバーとの通信結果を確認
                            if not ai_reply:
                                st.error(
                                    "【システム通信エラー】"
                                    "AIサーバーとの接続が一時的に遮断されました。"
                                    "電波環境の良い場所で、"
                                    "もう一度メッセージを送信してください。"
                                )
                                st.stop()

                            # トークン数を取得して保存
                            in_t = int(chat_result.get("in_tokens", 0) or 0)
                            out_t = int(chat_result.get("out_tokens", 0) or 0)
                            add_permanent_tokens(CURRENT_USER_ID, "chat", in_t, out_t)

                            st.session_state.last_in_tokens = (in_t)
                            st.session_state.last_out_tokens = (out_t)
                            st.session_state.total_in_tokens += (in_t)
                            st.session_state.total_out_tokens += (out_t)

                            print("📡 AIテキスト応答確認: "f"{ai_reply[:15]}...")

                            clean_reply = clean_bold_markdown(ai_reply)
                            # with st.chat_message("assistant", avatar=current_ai_avatar):
                            # with st.chat_message("assistant"):
                            # st.write(f"【{current_concierge_name}】: {clean_reply}")
                            # st.markdown(f"{current_concierge_name}: {clean_reply}")

                            all_messages.append({
                                "role": "assistant",
                                "content": ai_reply,
                                "message_id": current_msg_id,
                                "response_mode": response_mode,
                                "processing_type": processing_type,
                                "chat_room": "talk",
                                "created_at": datetime.now(JST).isoformat()
                            })
                            
                            save_message(
                                role="assistant",
                                content=ai_reply,
                                message_id=current_msg_id,
                                response_mode=response_mode,
                                processing_type=processing_type
                            )
                            st.session_state.force_message_reload = True

                            # add_permanent_tokens(CURRENT_USER_ID, "chat_count", 1, 0)
                            # current_通_cost = (in_t * PRICE_LITE_IN) + (out_t * PRICE_LITE_OUT)
                            current_通_cost = calculate_ai_cost(
                                provider=CHAT_PROVIDER,
                                in_tokens=in_t,
                                out_tokens=out_t,
                                is_chat=True
                            )

                            # 要約処理の実行（スレッド起動）
                            async_thread = threading.Thread(
                                target=check_and_summarize_history,
                                args=(current_msg_id, current_plan_type)
                            )
                            async_thread.start()

                            # 5. チャットデータと、今2.0秒の間に合流した要約データをまとめて、Supabaseの新設詳細カラムへ1発で同時インサート！
                            save_system_audit_log(
                                user_id=CURRENT_USER_ID, 
                                plan_type=current_plan_type, 
                                event_type="CHAT_SUCCESS", 
                                processing_time=api_elapsed, 
                                in_t=in_t, 
                                out_t=out_t, 
                                api_cost=current_通_cost, 
                                # details=f"正常対話完了 (検索時間: {search_elapsed:.2f}秒)",
                                details=(
                                    f"provider={chat_provider_used}"
                                    f" | model={chat_model_used}"
                                    f" | response_route={chat_route_name}"
                                    f" | 処理区分={processing_type}"
                                    f" | 回答モード={response_mode}"
                                    f" | 過去会話検索時間="
                                    f"{search_elapsed:.2f}秒"
                                    f" | Google検索時間="
                                    f"{search_execution_elapsed:.2f}秒"
                                ),
                                message_id=str(current_msg_id),
                                search_time=float(search_elapsed)
                            )

                            # st.rerun()

                        except Exception as gemini_err:
                            error_detail = f"{type(gemini_err).__name__}: {str(gemini_err)}"
                            print(f"🚨 チャット処理エラー: {error_detail}")
                            increment_error_analytics("CHAT_PROCESSING_ERROR", current_plan_type)
                        
                            save_system_audit_log(
                                CURRENT_USER_ID,
                                current_plan_type,
                                "CHAT_PROCESSING_ERROR",
                                0.0,
                                0,
                                0,
                                0.0,
                                error_detail[:500],
                                message_id=str(current_msg_id if 'current_msg_id' in locals() else "")
                            )

        completed_detail_parent_ids = {
            str(message.get("parent_message_id", "") or "").strip()
            for message in all_messages
            if (
                message.get("role") == "assistant"
                and str(message.get("processing_type", "") or "").strip() in {
                    "detailed_search",
                    "detailed_analysis",
                    "detailed_search_analysis"
                }
                and str(message.get("parent_message_id", "") or "").strip()
            )
        }

        for index, msg in enumerate(reversed(all_messages)):
            message_id = str(msg.get("message_id", ""))

            paired_user_message = None
            paired_assistant_message = None
            paired_processing_type = ""

            if message_id:
                for search_msg in all_messages:
                    if (search_msg.get("message_id") == message_id):
                        if (search_msg.get("role") == "user"):
                            paired_user_message = (search_msg.get("content", ""))
                            if not paired_processing_type:
                                paired_processing_type = str(
                                    search_msg.get("processing_type", "") or ""
                                ).strip()
                        elif (search_msg.get("role") == "assistant"):
                            paired_assistant_message = (search_msg.get("content", ""))
                            if not paired_processing_type:
                                paired_processing_type = str(
                                    search_msg.get("processing_type", "") or ""
                                ).strip()

            role_label = (
                display_user_name
                if msg["role"] == "user"
                else current_concierge_name
            )

            display_message(role_label, msg["content"])

            if msg["role"] == "user":
                detail_target_type = (
                    DETAIL_PROCESSING_TYPE_MAP.get(paired_processing_type, "")
                )
                detail_point_cost = int(
                    DETAIL_POINT_COSTS.get(detail_target_type, 0) or 0
                )
                detail_button_label = (
                    DETAIL_BUTTON_LABELS.get(paired_processing_type, "")
                )

                detail_already_completed = (
                    message_id in completed_detail_parent_ids
                )

                can_request_detail = bool(
                    message_id
                    and paired_user_message
                    and paired_assistant_message
                    and detail_target_type
                    and detail_button_label
                    and detail_point_cost > 0
                    and not detail_already_completed
                    and not str(msg.get("parent_message_id", "") or "").strip()
                )

                if detail_already_completed:
                    st.caption("✅ 詳細回答を作成済みです")

                elif can_request_detail:
                    if st.button(
                        detail_button_label,
                        key=f"request_detail_{message_id}_{index}",
                        # use_container_width=True
                    ):
                        st.session_state["pending_detail_request"] = {
                            "original_message_id": message_id,
                            "original_user_message": paired_user_message,
                            "simple_answer": paired_assistant_message,
                            "simple_processing_type": paired_processing_type,
                            "detailed_processing_type": detail_target_type,
                            "point_cost": detail_point_cost
                        }

                        st.session_state["detail_confirmation_open"] = True
                        st.session_state["detail_request_processing"] = False
                        st.rerun()

                st.markdown(
                    """
                    <hr style="
                        border: none;
                        border-top: 1px dashed rgba(120,120,120,0.4);
                        margin-top: 15px;
                        margin-bottom: 15px;
                    ">
                    """,
                    unsafe_allow_html=True
                )

                MODE_LABELS = {
                    "micro_chat": "挨拶",
                    "analysis": "分析",
                    "conversation": "会話",
                    "support": "相談",
                    "factual": "質問",
                    "short_chat": "雑談",
                    "default": "その他"
                }

                col_spacer, col_save, col_mode = (st.columns([6, 2, 1]))
                with col_save:
                    col_star, col_text = st.columns([2, 5])
                    with col_star:
                        save_limit = get_effective_saved_chat_limit(
                            user_id=CURRENT_USER_ID,
                            plan_code=current_plan_code
                        )

                        if save_limit <= 0:
                            if st.button(
                                "⭐",
                                key=f"save_chat_free_{message_id}_{index}"
                            ):
                                st.toast(
                                    "ライトプラン以上、または会話保存枠の購入で利用できます"
                                )

                        else:
                            if (paired_user_message and paired_assistant_message):
                                if st.button(
                                    "⭐",
                                    key=f"save_chat_paid_{message_id}_{index}"
                                ):
                                    saved_chats_count = get_saved_chat_count()

                                    if saved_chats_count >= save_limit:
                                        st.toast(
                                            f"保存上限（{save_limit}件）に達しています。"
                                            "不要な保存済みの会話を削除してから"
                                            "やり直してください。"
                                        )

                                    else:
                                        save_succeeded = save_saved_chat(
                                            title=create_saved_chat_title(
                                                paired_user_message
                                            ),
                                            summary="",
                                            user_message=paired_user_message,
                                            assistant_message=paired_assistant_message,
                                            original_message_id=message_id
                                        )

                                        if save_succeeded:
                                            st.toast("✅ 会話を保存しました")
                    with col_text:
                        st.caption("会話保存")

                saved_response_mode = msg.get("response_mode", "")

                with col_mode:
                    if saved_response_mode:
                        st.caption(
                            f"🧠 "
                            f"{MODE_LABELS.get(saved_response_mode, saved_response_mode)}"
                        )
                    else:
                        st.caption("🧠 不明")
                
                st.write("")

with all_tabs[1]:
    memory_tabs = st.tabs(["🧠 AIの長期記憶","💾 保存した会話"])

    with memory_tabs[0]:
        # st.markdown("---")

        #　要約を取得・作成
        summary_memories_setting = get_memories(source="summary")
        summary_memory_context_setting = (
            "\n".join(
                [m["fact"] for m in summary_memories_setting]
            )
            if summary_memories_setting
            else "なし"
        )
        display_summary = summary_memory_context_setting.replace("【記憶の要約サマリー】","") 

        summary_memory_id = None
        if summary_memories_setting:
            summary_memory_id = (summary_memories_setting[0].get("id"))

        #　要約を表示
        st.markdown("##### 🧠 現在AIが覚えている長期記憶")
        if display_summary != "なし":
            #st.info(display_summary)
            #st.caption("  AIが長期記憶として覚えている内容です。")
            # st.markdown(display_summary.replace("\n"," \n"))

            memory_blocks = (parse_summary_memory_blocks(display_summary))

            for block in memory_blocks:
                with st.expander(f"{block['title']}", expanded=True):
                    st.markdown(block["content"])

                    # col_space, col_edit = st.columns([9, 1])
                    edit_key = (f"edit_memory_{block['title']}")
                    memory_room_edit_enabled = bool(
                        current_plan_features.get("memory_room_edit", False)
                    )

                    if not memory_room_edit_enabled:
                        if st.button("編集", key=edit_key):
                            st.toast("💎 記憶の編集はライトプラン以上で利用できます")
                    else:
                        if st.button("編集", key=edit_key):
                            st.session_state[
                                f"editing_{block['title']}"
                            ] = True
                    if st.session_state.get(f"editing_{block['title']}",False):
                        edited_text = st.text_area(
                            "内容を編集",
                            value=block["content"],
                            key=f"editor_{block['title']}"
                        )

                        col_save, col_cancel, col_spacer = st.columns([1, 1, 6])
                        with col_save:
                            if st.button("更新", key=f"save_memory_{block['title']}"):
                                if not memory_room_edit_enabled:
                                    st.warning("記憶の編集はライトプラン以上で利用できます。")
                                    st.session_state[f"editing_{block['title']}"] = False
                                    st.stop()

                                updated_blocks = []

                                for target_block in memory_blocks:
                                    if target_block["title"] == block["title"]:
                                        updated_blocks.append({
                                            "title": target_block["title"],
                                            "content": edited_text
                                        })
                                    else:
                                        updated_blocks.append(target_block)
                                
                                rebuilt_summary = ""
                                for rebuilt_block in updated_blocks:
                                    rebuilt_summary += (
                                        f"・{rebuilt_block['title']}:\n"
                                        f"{rebuilt_block['content']}\n\n"
                                    )
                                
                                rebuilt_summary = (
                                    "【記憶の要約サマリー】\n"
                                    + rebuilt_summary.strip()
                                )
                                
                                if summary_memory_id:
                                    if update_memory(summary_memory_id, rebuilt_summary):
                                        st.toast("✅ 記憶を更新しました")
                                        st.session_state[f"editing_{block['title']}"] = False
                                        st.rerun()

                            with col_cancel:
                                if st.button("キャンセル", key=f"cancel_memory_{block['title']}"):
                                    st.session_state[f"editing_{block['title']}"] = False
                                    st.rerun()
                
        else:
            st.caption("  まだ覚えている情報はありません。")
        

        st.divider()

        st.markdown("##### 🧠 長期記憶について")
        st.caption("  AIは会話の中から、長期的に役立つ情報を整理して記憶しています。")
        st.caption("  記憶量が増えるほど、過去の会話や好み、継続的な話題をより多く反映した会話が可能になります。")
        st.write("")
        st.caption(" 🆓 無料プラン：記憶量【小】、閲覧のみ")
        st.write("")
        st.caption(" 💎 ライトプラン：記憶量【中】、閲覧・編集可")
        st.caption("  より多くの情報を長期記憶として保持")
        st.write("")
        st.caption(" 👑 スタンダードプラン：記憶量【大】、閲覧・編集可")
        st.caption("  更に多くの情報を長期記憶として保持")

        st.divider()

    with memory_tabs[1]:
        st.markdown("##### 💬 保存されている会話")
        effective_saved_chat_limit = (
            get_effective_saved_chat_limit(
                user_id=CURRENT_USER_ID,
                plan_code=current_plan_code
            )
        )   
        if effective_saved_chat_limit <= 0:
            st.caption("ここで保存した会話を確認できます。")
            st.caption(" 💎 ライトプラン以上で利用できます。")

        else:
            st.caption("ライトプランは最大5件まで、スタンダードプランは最大10件まで保存できます。")

            saved_chats = get_saved_chats()

            if not saved_chats:
                st.caption("保存されている会話はありません")

            else:
                for chat in saved_chats:
                    title = str(chat.get("title", "保存した会話"))
                    created_at = str(chat.get("created_at", ""))
                    created_label = (created_at.replace("T", " ")[:16])
                    # summary = str(chat.get("summary", ""))
                    with st.expander(f" {title}　｜　{created_label}"):
                        # st.caption(summary)
                        # st.markdown(f"**{display_user_name}**")
                        display_message(display_user_name, chat.get("user_message", ""))
                        # st.write(chat.get("user_message", ""))
                        # st.markdown(f"**{current_concierge_name}**")
                        display_message(current_concierge_name, chat.get("assistant_message", ""))
                        # st.write(chat.get("assistant_message", ""))

                        if st.button("削除", key=f"delete_saved_chat_{chat['id']}"):
                            if delete_saved_chat(chat["id"]):
                                st.success("保存されている会話を削除しました")
                                st.rerun()

        st.divider()

with all_tabs[2]:
    plan_room_enabled = bool(current_plan_features.get("plan_room", False))

    if not plan_room_enabled:
        st.info("計画ルームはスタンダードプラン専用機能です。")

        st.markdown(
            """
            AIと一緒に継続的な計画を作成して管理することができます。\n\n

            ・決定事項\n
            ・検討中\n
            ・保留事項\n
            ・次にやること\n\n

            を整理しながら進められます。
            """
        )

    else:
        active_plan_limit = int(current_plan_features.get("plan_active_limit", 0))
        completed_plan_limit = int(current_plan_features.get("plan_completed_limit", 0))

        st.caption("AIと一緒に継続的な計画を作成して管理することができる専用ルームです。")
        plan_view_mode = st.radio(
            "",
            [
            "🚀 進行中の計画",
            "✅ 完了済み計画"
            ],
            horizontal=True,
            label_visibility="collapsed"
        )
        st.markdown("---")
        
        selected_project = {}

        if plan_view_mode == "🚀 進行中の計画":
            active_projects = (get_plan_projects(status="active"))

            # debug_json("DEBUG active_projects", active_projects)

            project_names = [
                project["project_name"]
                for project
                in active_projects
            ]

            if st.session_state.pop("reset_active_plan_project", False):
                st.session_state["active_plan_project"] = "選択してください"

            newly_created_plan_name = st.session_state.pop(
                "newly_created_plan_name",
                None
            )

            if newly_created_plan_name in project_names:
                st.session_state["active_plan_project"] = newly_created_plan_name
            
            renamed_plan_name = st.session_state.pop(
                "renamed_plan_name",
                None
            )

            if renamed_plan_name in project_names:
                st.session_state["active_plan_project"] = renamed_plan_name

            st.markdown("**進行中**")
            active_project = st.selectbox(
                "進行中",
                ["選択してください"] + project_names,
                key="active_plan_project",
                label_visibility="collapsed"
            )

            active_plan_count = get_plan_project_count("active")
            active_plan_limit_reached = (active_plan_count >= active_plan_limit)

            st.caption(
                f"進行中の計画："
                f"{active_plan_count} / {active_plan_limit}件"
            )

            if st.button(
                "➕ 新しい計画を作成",
                key="open_create_plan_dialog",
                disabled=active_plan_limit_reached
            ):
                show_create_plan_dialog()

            if active_plan_limit_reached:
                st.info(
                    "進行中の計画が上限に達しています。"
                    "新しい計画を作成するには、"
                    "既存の計画を完了済みにするか、削除してください。"
                )

            selected_project = {}
            if (active_project != "選択してください"):

                selected_project = (get_plan_project(active_project))

        else:
            completed_projects = get_plan_projects(status="completed")
            completed_project_names = [
                project["project_name"]
                for project in completed_projects
            ]

            completed_plan_count = get_plan_project_count("completed")
            st.caption(
                f"完了済みの計画："
                f"{completed_plan_count} / {completed_plan_limit}件"
            )

            if st.session_state.pop("reset_completed_plan_project", False):
                st.session_state["completed_plan_project"] = "選択してください"
            
            # completed_project = st.selectbox("完了済みの計画", ["選択してください"] + completed_project_names)
            st.markdown("**完了済みの計画**")
            completed_project = st.selectbox(
                "完了済みの計画",
                ["選択してください"] + completed_project_names,
                key="completed_plan_project",
                label_visibility="collapsed"
            )

            if completed_project != "選択してください":
                selected_project = get_plan_project(completed_project)

        st.markdown("---")

        if selected_project:
            with st.expander(f"📌 {selected_project['project_name']}", expanded=True):
                plan_document = str(selected_project.get("plan_document", "") or "").strip()
                if plan_document:
                    st.markdown(plan_document)

                else:
                    st.info(
                        "まだ計画書は作成されていません。\n\n"
                        "計画について会話した後、"
                        "「計画に反映」を実行すると、"
                        "ここに計画書が表示されます。"
                    )

        if selected_project:
            plan_messages = get_messages(
                CURRENT_USER_ID,
                chat_room="plan",
                plan_project_id=selected_project["id"]
            )

            unreflected_message_count = len(
                get_unreflected_plan_messages(
                    project_id=selected_project["id"],
                    last_reflected_at=selected_project.get("last_reflected_at")
                )
            )

            if unreflected_message_count >= 20:
                st.caption(
                    "💡 未反映の会話が10往復ほどあります。"
                    "「📝 計画に反映」で計画書を更新しておくと、"
                    "今後の会話を続けやすくなります。"
                )
            
            if plan_view_mode == "🚀 進行中の計画":
                plan_user_input = st.chat_input("この計画についての会話を入力してください")

                if plan_user_input:
                    plan_message_id = (f"plan_{uuid.uuid4().hex[:8]}")

                    user_saved = save_message(
                        role="user",
                        content=plan_user_input,
                        message_id=plan_message_id,
                        response_mode="analysis",
                        chat_room="plan",
                        plan_project_id=selected_project["id"]
                    )
                    if not user_saved:
                        st.error("計画ルームのユーザー発言を保存できませんでした。")
                        st.stop()

                    plan_history_lines = []
                    for message in plan_messages[-20:]:
                        role_name = (
                            display_user_name
                            if message.get("role") == "user"
                            else current_concierge_name
                        )
                        plan_history_lines.append(
                            f"{role_name}: "
                            f"{message.get('content', '')}"
                        )

                    plan_history_lines.append(f"{display_user_name}: {plan_user_input}")
                    plan_history_text = (
                        "\n".join(plan_history_lines)
                        if plan_history_lines
                        else "会話履歴なし"
                    )

                    plan_ai_instruction = f"""
                    あなたはAIコンシェルジュ「{current_concierge_name}」です。
                    計画ルームでは、選択中の計画について継続的に会話します。

                    【選択中の計画】
                    計画名:{selected_project.get("project_name", "")}

                    計画概要:{selected_project.get("project_summary", "") or "未設定"}

                    決定事項:{selected_project.get("decision_items", []) or []}

                    検討中:{selected_project.get("considering_items", []) or []}

                    保留事項:{selected_project.get("pending_items", []) or []}

                    次にやること:{selected_project.get("next_actions", []) or []}

                    【回答ルール】
                    ・選択中の計画を前提に回答してください。
                    ・ユーザーの最新の発言や質問へ直接回答してください。
                    ・通常の回答では、計画全体の総括や整理を毎回行わないでください。
                    ・「ここまでの内容を整理すると」などの前置きから回答を始めないでください。
                    ・計画全体を整理するのは、ユーザーが明示的に要約や整理を求めた場合だけにする。
                    ・まだ決まっていない内容を、決定事項として断定してはいけません。
                    ・ユーザーが明示していない内容を事実として追加してはいけません。
                    ・通常のトークルームの話題と混同しないでください。

                    【計画進行サポート】
                    ・回答後、計画を前へ進めるために有用な場合だけ、次に決めること、確認すること、実行することを1～3件提示してください。
                    ・次の行動がすでに明確な場合や、単純な確認への回答では、不要な提案を追加しないでください。
                    ・複数の課題がある場合は、優先順位が最も高いものを明確にしてください。
                    ・ユーザーへ過度に質問を重ねず、現在ある情報で進められる作業を先に提示してください。

                    【計画名変更ルール】
                    ・ユーザーが計画名の変更を明示的に指示した場合だけ、新しい計画名を抽出してください。
                    ・計画名について話題にしただけの場合や、候補を挙げただけの場合は変更しないでください。
                    ・ユーザーの明示的な指示がない限り、あなたの判断で計画名を変更してはいけません。

                    【話し方】
                    {STYLE_PRESETS.get(current_style_preset, "")}

                    【回答の長さ】
                    {response_length_prompt}

                    【出力形式】
                    必ず次のJSON形式だけで出力してください。
                    {{
                    "reply": "ユーザーへ表示する回答",
                    "requested_plan_name": null
                    }}

                    ・上記の計画名変更ルールに該当する場合は、requested_plan_nameへ新しい計画名を入れてください。
                    ・該当しない場合は、requested_plan_nameをnullにしてください。
                    ・replyには、通常の会話回答だけを入れてください。
                    ・JSON以外の説明文やMarkdownのコードブロックは出力しないでください。
                    """

                    plan_ai_start_time = time.time()
                    with st.spinner(f"{current_concierge_name}が考え中..."):
                        plan_ai_result = generate_ai_response(
                            provider=CHAT_PROVIDER,
                            system_instruction=plan_ai_instruction,
                            user_prompt=plan_history_text,
                            response_format_json=True,
                            model_name=CHAT_MODEL_NAME
                        )
                    plan_ai_processing_time = time.time() - plan_ai_start_time
                    plan_in_tokens = int(plan_ai_result.get("in_tokens", 0) or 0)
                    plan_out_tokens = int(plan_ai_result.get("out_tokens", 0) or 0)
                    plan_api_cost = calculate_ai_cost(
                        provider=CHAT_PROVIDER,
                        in_tokens=plan_in_tokens,
                        out_tokens=plan_out_tokens,
                        is_chat=True
                    )

                    plan_ai_text = str(plan_ai_result.get("text", "") or "").strip()

                    try:
                        plan_ai_data = json.loads(plan_ai_text)
                    except Exception:
                        plan_ai_data = {"reply": plan_ai_text, "requested_plan_name": None}

                    plan_ai_reply = str(plan_ai_data.get("reply", "") or "").strip()
                    requested_plan_name = str(
                        plan_ai_data.get("requested_plan_name", "") or ""
                    ).strip()

                    if (
                        requested_plan_name
                        and requested_plan_name
                        != selected_project["project_name"]
                    ):
                        rename_succeeded = update_plan_project(
                            project_id=selected_project["id"],
                            update_data={
                                "project_name": requested_plan_name,
                                "updated_at": datetime.now(JST).isoformat()
                            }
                        )

                        if rename_succeeded:
                            selected_project["project_name"] = requested_plan_name
                            st.session_state["renamed_plan_name"] = requested_plan_name
                        else:
                            st.warning(
                                "回答は作成できましたが、"
                                "計画名を変更できませんでした。"
                            )

                    if not plan_ai_reply:
                        plan_ai_reply = (
                            "うまく回答を作成できませんでした。"
                            "もう一度送ってみてください。"
                        )

                    assistant_saved = save_message(
                        role="assistant",
                        content=plan_ai_reply,
                        message_id=plan_message_id,
                        response_mode="analysis",
                        chat_room="plan",
                        plan_project_id=selected_project["id"]
                    )
                    if not assistant_saved:
                        st.error("AIの回答を保存できませんでした。")
                        st.stop()
                    
                    save_system_audit_log(
                        user_id=CURRENT_USER_ID,
                        plan_type=current_plan_type,
                        event_type="PLAN_CHAT_SUCCESS",
                        processing_time=plan_ai_processing_time,
                        in_t=plan_in_tokens,
                        out_t=plan_out_tokens,
                        api_cost=plan_api_cost,
                        details=(
                            f"chat_room=plan"
                            f"provider={CHAT_PROVIDER}"
                            f" | model={CHAT_MODEL_NAME}"
                            f" | project_id={selected_project['id']}"
                            f" | project_name={selected_project['project_name']}"
                        ),
                        message_id=str(plan_message_id)
                    )
                    st.rerun()
            
            # st.caption("※Flutter版では画面右側にジャンプボタンを表示予定")
            st.markdown("")
            if plan_view_mode == "🚀 進行中の計画":
                history_title_col, reflect_button_col, complete_button_col, delete_button_col = (
                    st.columns([3, 1, 1, 1])
                )

                with history_title_col:
                    st.markdown("##### 💬 会話履歴")

                with reflect_button_col:
                    reflect_plan = st.button(
                        "📝 計画に反映",
                        key=f"reflect_plan_{selected_project['id']}"
                    )

                with complete_button_col:
                    complete_plan = st.button(
                        "✅ 完了にする",
                        key=f"complete_plan_{selected_project['id']}",
                        use_container_width=True
                    )

                with delete_button_col:
                    active_delete = st.button(
                        "計画削除",
                        key=f"active_delete_{selected_project['id']}"
                    )

                restore_plan = False

            else:
                history_title_col, restore_button_col, delete_button_col = (
                    st.columns([4, 1, 1])
                )

                with history_title_col:
                    st.markdown("##### 💬 会話履歴")

                with restore_button_col:
                    restore_plan = st.button(
                        "↩️ 進行中へ戻す",
                        key=f"restore_plan_{selected_project['id']}",
                        use_container_width=True
                    )

                with delete_button_col:
                    active_delete = st.button(
                        "計画削除",
                        key=f"active_delete_{selected_project['id']}"
                    )

                reflect_plan = False
                complete_plan = False

            if complete_plan:
                show_plan_complete_dialog(
                    selected_project["id"],
                    selected_project["project_name"]
                )

            if restore_plan:
                show_plan_restore_dialog(
                    selected_project["id"],
                    selected_project["project_name"]
                )

            if active_delete:
                show_plan_delete_dialog(
                    selected_project["id"],
                    selected_project["project_name"]
                )
                
            if reflect_plan:          
                unreflected_messages = get_unreflected_plan_messages(
                    project_id=selected_project["id"],
                    last_reflected_at=selected_project.get("last_reflected_at")
                )

                if not unreflected_messages:
                    st.info("新しく計画へ反映する会話はありません。")

                else:
                    with st.spinner("会話内容を計画書へ反映しています..."):
                        merge_data = generate_merged_plan_document(
                            selected_project=selected_project,
                            unreflected_messages=unreflected_messages
                        )
                        merged_document = str(merge_data.get("document", "") or "").strip()
                        project_summary = str(merge_data.get("summary", "") or "").strip()

                        if not merged_document:
                            st.error("計画書を作成できませんでした。")
                            st.stop()

                        reflected_at = max(
                            str(message.get("created_at", "") or "")
                            for message in unreflected_messages
                            if message.get("created_at")
                        )

                        update_succeeded = update_plan_project(
                            project_id=selected_project["id"],
                            update_data={
                                "plan_document": merged_document,
                                "project_summary": (
                                    project_summary
                                    or selected_project.get("project_summary", "")
                                ),
                                "last_reflected_at": reflected_at,
                                "updated_at": datetime.now(JST).isoformat()
                            }
                        )

                        if update_succeeded:
                            reflection_message_id = str(
                                unreflected_messages[-1].get("message_id", "") or ""
                            )

                            save_system_audit_log(
                                user_id=CURRENT_USER_ID,
                                plan_type=current_plan_type,
                                event_type="PLAN_REFLECTION_SUCCESS",
                                processing_time=float(
                                    merge_data.get("processing_time", 0.0) or 0.0
                                ),
                                in_t=int(
                                    merge_data.get("in_tokens", 0) or 0
                                ),
                                out_t=int(
                                    merge_data.get("out_tokens", 0) or 0
                                ),
                                api_cost=float(
                                    merge_data.get("api_cost", 0.0) or 0.0
                                ),
                                details=(
                                    f"chat_room=plan"
                                    f" | operation=plan_reflection"
                                    f" | provider={BACKGROUND_PROVIDER}"
                                    f" | model={SUMMARY_MODEL_NAME}"
                                    f" | project_id={selected_project['id']}"
                                    f" | project_name={selected_project['project_name']}"
                                ),
                                message_id=reflection_message_id
                            )

                            st.success("計画書へ反映しました。")
                            # st.rerun()
                        else:
                            st.error("計画書の保存に失敗しました。")


            if not plan_messages:
                st.info("この計画には、まだ会話履歴がありません。")

            else:
                for message in reversed(plan_messages):
                    role = str(message.get("role", "") or "")
                    content = str(message.get("content", "") or "")

                    if not content:
                        continue

                    role_label = (
                        display_user_name
                        if role == "user"
                        else current_concierge_name
                    )

                    display_message(role_label,content)

                    if role == "user":
                        # st.markdown("<br>", unsafe_allow_html=True)
                        st.markdown("---")
                        st.markdown("<br>", unsafe_allow_html=True)            

# ------------------------------------------------------------------
# 🎨 【タブ2】 話し方・見た目設定
# ------------------------------------------------------------------
with all_tabs[3]:
    #st.write(f"#### 🎨 {current_concierge_name}のカスタマイズ")
    st.markdown("")
    st.markdown("📚AIの話し方・見た目・アプリのデザインを自分の好みに設定できます。")
    st.divider()

    with st.form("unified_settings_form"):
        if "settings_saved" not in st.session_state:
            st.session_state["settings_saved"] = False
        if "settings_saved_position" not in st.session_state:
            st.session_state["settings_saved_position"] = ""

        st.markdown("##### 🎨 アプリの外観＆カラー")
        st.markdown("**カラーテーマ（背景＆メッセージ枠）**")
        selected_color = st.selectbox(
            "",
            list(THEMES.keys()),
            index=(
                list(THEMES.keys()).index(current_theme_color)
                if current_theme_color in THEMES
                else 0
            ),
            label_visibility="collapsed"
        )
        # 上部設定保存ボタン
        top_save = st.form_submit_button(
            "💾 設定を保存",
            key="save_settings_top",
        )
        top_placeholder = st.empty()
        if (
            st.session_state.get("settings_saved")
            and
            st.session_state.get("settings_saved_position") == "top"
        ):
            top_placeholder.success("設定を登録しました")
            st.session_state["settings_saved"] = False

        st.divider()

        st.markdown("##### 👤 基本設定")
        honorific_options = ["さん", "様", "君", "ちゃん", "（呼び捨て/なし）"]
        default_honorific_idx = honorific_options.index(current_user_honorific) if current_user_honorific in honorific_options else 0
        preset_keys = list(STYLE_PRESETS.keys())
        default_preset_idx = preset_keys.index(current_style_preset) if current_style_preset in preset_keys else 0
        default_fp_idx = FIRST_PERSON_PRESETS.index(current_first_person) if current_first_person in FIRST_PERSON_PRESETS else 0

        # new_concierge_name = st.text_input("AIの名前", value=current_concierge_name)
        # new_user_name = st.text_input("あなたのお名前 / ニックネーム", value=current_user_name)
        # new_user_honorific = st.selectbox("AIからの呼び方（敬称）", honorific_options, index=default_honorific_idx)
        # new_first_person = st.selectbox("AIの一人称", FIRST_PERSON_PRESETS, index=default_fp_idx)
        st.markdown("**AIの名前**")
        new_concierge_name = st.text_input(
            "",
            value=current_concierge_name,
            label_visibility="collapsed"
        )

        st.markdown("**あなたのお名前 / ニックネーム**")
        new_user_name = st.text_input(
            "",
            value=current_user_name,
            label_visibility="collapsed"
        )

        st.markdown("**AIからの呼び方（敬称）**")
        new_user_honorific = st.selectbox(
            "",
            honorific_options,
            index=default_honorific_idx,
            label_visibility="collapsed"
        )

        st.markdown("**AIの一人称**")
        new_first_person = st.selectbox(
            "",
            FIRST_PERSON_PRESETS,
            index=default_fp_idx,
            label_visibility="collapsed"
        )

        default_length_idx = (
            RESPONSE_LENGTH_PRESETS.index(
                current_response_length
            )
            if current_response_length
            in RESPONSE_LENGTH_PRESETS
            else 1
        )
        st.markdown("---")
        st.markdown("##### 💬 会話設定")
        st.caption(
            "返事の長さや方言を設定できます。"
        )

        # AIの人格を選択
        st.markdown("**AIの人格・スタイル**")
        selected_preset = st.selectbox(
            "",
            DISPLAY_PRESETS,
            index=(
                DISPLAY_PRESETS.index(current_style_preset)
                if current_style_preset in DISPLAY_PRESETS
                else 0
            ),
            label_visibility="collapsed"
        )
        
        premium_personality_entitlement = (
            get_active_entitlement(
                CURRENT_USER_ID,
                "premium_personality"
            )
        )

        premium_personality_pass_active = bool(
            premium_personality_entitlement.get(
                "is_active",
                False
            )
        )

        premium_personality_enabled = bool(
            current_plan_features.get(
                "premium_personality",
                False
            )
            or premium_personality_pass_active
        )

        if premium_personality_pass_active:
            pass_expires_at = (
                premium_personality_entitlement.get(
                    "expires_at"
                )
            )
            formatted_pass_expires_at = ""

            if pass_expires_at:
                try:
                    pass_expiration_datetime = (
                        datetime.fromisoformat(
                            str(pass_expires_at).replace(
                                "Z",
                                "+00:00"
                            )
                        )
                        .astimezone(JST)
                    )

                    formatted_pass_expires_at = (
                        pass_expiration_datetime.strftime("%Y年%m月%d日 %H:%M")
                    )

                except Exception:
                    formatted_pass_expires_at = str(pass_expires_at)

            st.caption(
                f"💎 有料人格パス利用中"
                f"｜有効期限：{formatted_pass_expires_at}"
            )

        elif not current_plan_features.get("premium_personality", False):
            if selected_preset in PREMIUM_PRESETS:
                st.caption(
                    "💎付の人格を使用するには、ライトプラン以上への加入、"
                    "または有料人格パスの購入が必要です。"
                )
            else:
                st.caption(
                    "有料人格パスを購入すると、"
                    "すべての💎付き人格を自由に利用できます。"
                )

            if st.form_submit_button(
                "ポイントで有料人格パスを購入",
                key="request_personality_pass_dialog"
            ):
                st.session_state["open_personality_pass_dialog"] = True
            st.caption("")

        with st.expander("💬 人格ごとの会話サンプルを見る"):
            for personality, sample in PERSONALITY_SAMPLES.items():
                st.markdown(f" {personality}")
                st.markdown(sample)
                st.divider()
        
        st.caption("")
        # 絵文字3段階パーソナライズドロップダウン
        emoji_options = ["使用（多め）","使用（普通）","使用（少なめ）","無し"]
        default_emoji_idx = (
            emoji_options.index(current_emoji_setting)
            if current_emoji_setting in emoji_options
            else 1
        )
        st.markdown("**AIの発言内の絵文字の量**")
        new_emoji_setting = st.selectbox(
            "",
            emoji_options,
            index=default_emoji_idx,
            label_visibility="collapsed"
        )
        # new_emoji_setting = st.selectbox("AIの発言内の絵文字の量", emoji_options, index=default_emoji_idx)
        # st.caption("AIの発言内の絵文字の量")
        # new_emoji_setting = st.selectbox("",emoji_options,index=default_emoji_idx,label_visibility="collapsed")

        st.markdown("---")
        st.markdown("**🔒 拡張会話設定**")
        # st.markdown("##### 🔒 プレミアム会話設定")

        response_length_edit_enabled = bool(
            current_plan_features.get("response_length_edit", False)
        )
        st.markdown("**返事の長さ**")
        new_response_length = st.selectbox(
            "",
            RESPONSE_LENGTH_PRESETS,
            index=default_length_idx,
            disabled=not response_length_edit_enabled,
            label_visibility="collapsed"
        )

        if not response_length_edit_enabled:
            st.caption("💎 ライトプラン以上で利用可能")

        st.markdown("---")
        bottom_save = st.form_submit_button(
            "💾 設定を保存",
            key="save_settings_bottom"
        )
        bottom_placeholder = st.empty()
        if (
            st.session_state.get("settings_saved")
            and
            st.session_state.get("settings_saved_position") == "bottom"
        ):
            bottom_placeholder.success("設定を登録しました")
            st.session_state["settings_saved"] = False

        if top_save or bottom_save:
            response_length_to_save = (
                new_response_length
                if response_length_edit_enabled
                else "普通"
            )
            if (
                not premium_personality_enabled
                and selected_preset in PREMIUM_PRESETS
            ):
                target_placeholder = (
                    top_placeholder
                    if top_save
                    else bottom_placeholder
                )

                target_placeholder.warning(
                    "選択された人格は、💎 ライトプラン以上で利用できます。"
                    "人格を選び直してください。"
                )

            else:
                settings_dict = {
                    "カラーテーマ": selected_color,
                    "AIの名前": new_concierge_name,
                    "ユーザー名": new_user_name,
                    "ユーザー敬称": new_user_honorific,
                    "AI一人称": new_first_person,
                    "人格": selected_preset,
                    "会話長さ": response_length_to_save,
                    "絵文字の量": new_emoji_setting
                }
                target_placeholder = (
                    top_placeholder
                    if top_save
                    else bottom_placeholder
                )

                target_placeholder.info("設定登録中...")

                success =  save_all_user_settings(settings_dict)

                if success:
                    st.session_state.skip_message_reload = True
                    st.session_state["settings_saved"] = True
                    st.session_state["settings_saved_position"] = (
                        "top"
                        if top_save
                        else "bottom"
                    )

                    # target_placeholder.success("設定を登録しました")
                    st.rerun()
                else:
                    target_placeholder.error("設定の保存に失敗しました")

    if st.session_state.pop("open_personality_pass_dialog", False):
        show_personality_pass_dialog()
    
    st.divider()
    st.markdown("#### 🎬 動画を視聴してポイント獲得")

    settings_reward_status = (
        check_reward_ad_eligibility(
            user_id=CURRENT_USER_ID,
            placement_code="settings_reward"
        )
    )

    settings_reward_result = str(
        settings_reward_status.get("result_status", "error") or "error"
    )

    settings_placement_count = int(
        settings_reward_status.get("placement_rewarded_count", 0) or 0
    )

    settings_total_count = int(
        settings_reward_status.get("total_rewarded_count", 0) or 0
    )

    settings_placement_limit = int(
        settings_reward_status.get("placement_daily_limit", 10) or 10
    )

    settings_total_limit = int(
        settings_reward_status.get("total_daily_limit", 20) or 20
    )

    settings_cooldown_seconds = int(
        settings_reward_status.get("cooldown_remaining_seconds", 0) or 0
    )

    st.caption(
        "動画広告を最後まで視聴すると、"
        f"{POINT_REWARDED_AD}pt獲得できます。"
    )

    st.caption(
        f"この画面での本日の視聴："
        f"{settings_placement_count} / "
        f"{settings_placement_limit}回"
        f"　｜　全体："
        f"{settings_total_count} / "
        f"{settings_total_limit}回"
    )

    if settings_reward_result == "cooldown_active":
        cooldown_minutes = (settings_cooldown_seconds // 60)
        cooldown_seconds = (settings_cooldown_seconds % 60)

        st.caption(
            f"次回視聴まで："
            f"{cooldown_minutes:02d}:"
            f"{cooldown_seconds:02d}"
        )

    elif settings_reward_result == ("placement_daily_limit_reached"):
        st.caption("設定画面からの本日の視聴上限に達しています。")

    elif settings_reward_result == ("total_daily_limit_reached"):
        st.caption("本日の動画広告の視聴上限に達しています。")

    elif settings_reward_result == "error":
        st.caption("広告の視聴状況を確認できませんでした。")

    st.button(
        f"🎬 動画を視聴して"
        f"{POINT_REWARDED_AD}pt獲得",
        key="watch_reward_ad_settings",
        # use_container_width=True,
        disabled=True,
        help=(
            "リワード広告はFlutter移植時に"
            "接続予定です。"
        )
    )

    st.caption("現在は広告機能の準備中です。")

# ------------------------------------------------------------------
# 🎨 📜 利用規約・ポリシー
# ------------------------------------------------------------------
with all_tabs[4]:
    st.markdown("##### 📜 利用規約・プライバシーポリシー")
    st.caption("※本規約は、現在実施中のクローズドテスト、および将来の正式リリース運用を想定した共通のサービス利用基本規約です。")
    
    st.info(
        "⚖️ **【免責事項・利用上の注意】**\n"
        "1. 現在は**クローズドテスト版**です。テスターからのフィードバックをもとに、機能追加・変更・改善を継続的に行っています。\n"
        "2. **AI出力の性質：** 当アプリのコンシェルジュが紡ぐ言葉は、大規模言語モデルによって自律的に生成された回答であり、その正確性、完全性、医療的・技術的妥当性を100%保証するものではありません。専門的な判断を要する情報については、必ず専門家にご確認ください。\n"
        "3. **データの取扱（あなたとの思い出・記憶の仕組み）：** あなたとコンシェルジュとの会話履歴は、高度な長期記憶システムのために安全な通信保護のもとデータベースへ蓄積されます。プライバシーは厳重に管理されますが、テスト期間中のサービス品質向上や不具合解析のため、管理者がシステムログおよび会話履歴を確認・監査する場合があります。\n"
        "4. **禁止事項：** 嫌がらせ、公序良俗に反する表現の送信、またはシステムへの不正な負荷テスト等の行為は一律禁止といたします。発見した場合は管理者権限により事前の通知なく利用制限をかける場合があります。\n"
        "5. **サービスについて：** 本サービスはテスト運用中のため、予告なく機能変更・停止・データ削除が行われる場合があります。開発者はサービスの継続提供および保存データの完全な保持を保証しません。\n"
        "6. **個人情報の入力について：** 電話番号、クレジットカード番号、パスワードその他の機密情報は入力しないでください。利用者自身の判断で入力した情報については、利用者の責任で管理するものとします。\n"
    )

if is_admin:
    # ──────────────────────────────────────────
    # 📊 【管理者専用・タブ3】 システム管理者管理ダッシュボード
    # ──────────────────────────────────────────
    with all_tabs[5]:
        # st.write("### 📊 システム管理者専用ダッシュボード")
        st.markdown("**📊 システム管理者専用ダッシュボード**")
        admin_mode = st.radio(
            "表示する分析画面を選択してください", 
            ["👤 ユーザー別利用状況", "📈 全体アクティビティ・統計アナリティクス"], 
            horizontal=True, 
            key="admin_radio_mode"
        )
        st.divider()

        # 👤 画面①：ユーザー個別のカルテ表示および1メッセージ単位の詳細明細タイムライン
        if admin_mode == "👤 ユーザー別利用状況":
            # st.subheader("👤 ユーザー別・稼働状況およびタイムライン")
            st.markdown("**👤 ユーザー別・稼働状況およびタイムライン**")
            all_users = [ADMIN_USER_ID]
            try:
                user_res = supabase.table("user_token_stats").select("user_id").execute()
                if user_res.data: 
                    all_users = sorted(list({row["user_id"] for row in user_res.data if row.get("user_id")}))
            except Exception: 
                pass

            selected_audit_user = st.selectbox(
                "🔍 対象のユーザーIDを選択してください：",
                all_users,
                key="selected_audit_user"
            )

            previous_audit_user = st.session_state.get("previous_audit_user")

            if previous_audit_user != selected_audit_user:
                st.session_state["previous_audit_user"] = (selected_audit_user)
                st.session_state["audit_display_section"] = ""

            if "audit_display_section" not in st.session_state:
                st.session_state["audit_display_section"] = ""

            button_col1, button_col2, button_col3 = st.columns(3)

            if button_col1.button("👤 ユーザー設定", use_container_width=True):
                st.session_state["audit_display_section"] = ("user_settings")

            if button_col2.button("📊 利用・原価集計", use_container_width=True):
                st.session_state["audit_display_section"] = ("usage_summary")

            if button_col3.button("📈 処理区分別集計", use_container_width=True):
                st.session_state["audit_display_section"] = ("processing_summary")

            button_col4, button_col5 = st.columns(2)

            if button_col4.button("🏠 計算案件", use_container_width=True):
                st.session_state["audit_display_section"] = ("calculation_cases")

            if button_col5.button("💬 個別会話ログ", use_container_width=True):
                st.session_state["audit_display_section"] = ("conversation_logs")

            audit_display_section = st.session_state.get("audit_display_section", "")

            user_summary = {}

            if audit_display_section == "usage_summary":
                try:
                    user_summary_res = (
                        supabase
                        .rpc(
                            "get_user_audit_summary",{
                                "p_user_id": str(selected_audit_user)
                            }
                        )
                        .execute()
                    )

                    user_summary = (
                        user_summary_res.data[0]
                        if user_summary_res.data
                        else {}
                    )

                except Exception as e:
                    print(
                        "ユーザー監査集計取得エラー: "
                        f"{type(e).__name__}: {e}"
                    )
                    user_summary = {}

            normal_chat_count = int(user_summary.get("normal_chat_count", 0) or 0)
            plan_chat_count = int(user_summary.get("plan_chat_count", 0) or 0)
            plan_reflection_count = int(user_summary.get("plan_reflection_count", 0) or 0)

            total_active_days = int(user_summary.get("active_day_count", 0) or 0)
            total_cost_jpy = float(user_summary.get("total_cost", 0.0) or 0.0)
            
            normal_chat_cost = float(user_summary.get("normal_chat_cost", 0.0) or 0.0)
            plan_chat_cost = float(user_summary.get("plan_chat_cost", 0.0) or 0.0)
            plan_reflection_cost = float(user_summary.get("plan_reflection_cost", 0.0) or 0.0)

            normal_in_tokens = int(user_summary.get("normal_in_tokens", 0) or 0)
            normal_out_tokens = int(user_summary.get("normal_out_tokens", 0) or 0)
            plan_in_tokens = int(user_summary.get("plan_in_tokens", 0) or 0)
            plan_out_tokens = int(user_summary.get("plan_out_tokens", 0) or 0)
            plan_reflection_in_tokens = int(
                user_summary.get("plan_reflection_in_tokens", 0) or 0
            )
            plan_reflection_out_tokens = int(
                user_summary.get("plan_reflection_out_tokens", 0) or 0
            )

            normal_processing_time = float(user_summary.get("normal_processing_time", 0.0) or 0.0)
            plan_processing_time = float(user_summary.get("plan_processing_time", 0.0) or 0.0)
            plan_reflection_processing_time = float(
                user_summary.get(
                    "plan_reflection_processing_time",
                    0.0
                ) or 0.0
            )
            
            st.markdown("---")
            
            # st.markdown(f"#### 📋 ユーザー [ `{selected_audit_user}` ] の現在の設定およびプロフィール")
            
            # データベースから監査対象ユーザーの最新マニュアル設定情報を抽出
            audit_concierge_name = "コンシェルジュ"
            audit_user_name = "ユーザー"
            audit_user_honorific = "さん"
            audit_first_person = "私"
            audit_emoji_setting = "使用（普通）"
            audit_style_preset = "🤝 フランクな相棒 ➔ 【タメ口で対等におしゃべり】"
            audit_theme = "パステル"
            audit_plan = "🆓 無料プラン"

            audit_facts = []
            if audit_display_section == "user_settings":
                try:
                    selected_memory_table = (
                        "user_memories"
                        if selected_audit_user in [ADMIN_USER_ID, USUAL_USER_ID]
                        else "user_memories_tester"
                    )
                    u_memories = supabase.table(selected_memory_table).select("*").eq("user_id", selected_audit_user).execute()
                    if u_memories.data:
                        for m in u_memories.data:
                            fact = m.get("fact", "")
                            if m.get("source") == "manual":
                                if fact.startswith("AIの名前:"): audit_concierge_name = fact.replace("AIの名前:", "").strip()
                                elif fact.startswith("ユーザー名:"): audit_user_name = fact.replace("ユーザー名:", "").strip()
                                elif fact.startswith("カラーテーマ:"): audit_theme = fact.replace("カラーテーマ:", "").strip()
                                elif fact.startswith("ユーザー敬称:"): audit_user_honorific = fact.replace("ユーザー敬称:", "").strip()
                                elif fact.startswith("AI一人称:"): audit_first_person = fact.replace("AI一人称:", "").strip()
                                elif fact.startswith("絵文字の量:"): audit_emoji_setting = fact.replace("絵文字の量:", "").strip()
                                elif fact.startswith("人格:"): audit_style_preset = fact.replace("人格:", "").strip()
                                elif fact.startswith("会員プラン:"): audit_plan = fact.replace("会員プラン:", "").strip()
                            else: 
                                audit_facts.append(fact)
                except Exception: 
                    pass

            audit_real_instruction = "設定データなし"

            # リアルタイムKPI自動計算     
            total_chats = normal_chat_count + plan_chat_count
            start_date = "データなし"
            last_date = "データなし"
            avg_chats_per_day = (
                round(total_chats / total_active_days, 1)
                if total_active_days > 0
                else 0
            )
            avg_cost_per_chat = (
                round(total_cost_jpy / total_chats, 2)
                if total_chats > 0
                else 0.0
            )

            search_judge_count = 0
            search_judge_total_cost = 0.0
            search_judge_total_in = 0
            search_judge_total_out = 0
            search_count = 0
            search_exec_count = 0
            search_exec_total_cost = 0.0
            search_exec_total_in = 0
            search_exec_total_out = 0
            calc_total = 0
            calc_success = 0
            calc_missing = 0
            calc_error = 0
            calc_extract_cost = 0.0
            calc_extract_in = 0
            calc_extract_out = 0
            user_logs = []

            try:
                if audit_display_section == "usage_summary":
                    user_logs = (
                        supabase
                        .table("messages")
                        .select("created_at", "role")
                        .eq("user_id", selected_audit_user)
                        .execute()
                        .data
                    )
                
                if user_logs:
                    # 使用開始日・最終会話日・総稼働日数を計算
                    timestamps = [
                        datetime.fromisoformat(
                            m.get("created_at").replace("Z", "+00:00")
                        )
                        for m in user_logs
                        if m.get("created_at")
                    ]
                    if timestamps:
                        start_date = min(timestamps).strftime("%Y/%m/%d")
                        last_date = max(timestamps).strftime("%Y/%m/%d")

                    # system_audit_logsから検索コストを集計
                    judge_cost_res = (
                        supabase
                        .table("system_audit_logs")
                        .select("*")
                        .eq("user_id", selected_audit_user)
                        .eq("event_type", "RESPONSE_ROUTER")
                        .execute()
                    )

                    judge_rows = judge_cost_res.data or []

                    search_judge_count = len(judge_rows)

                    search_judge_total_cost = sum(
                        float(row.get("api_cost", 0) or 0)
                        for row in judge_rows
                    )

                    search_judge_total_in = sum(
                        int(row.get("in_tokens", 0) or 0)
                        for row in judge_rows
                    )

                    search_judge_total_out = sum(
                        int(row.get("out_tokens", 0) or 0)
                        for row in judge_rows
                    )
                    # 検索回数を取得
                    search_res = (
                        supabase
                        .table("search_logs")
                        .select("*")
                        .eq("user_id", selected_audit_user)
                        .execute()
                    )
                    search_count = len(
                        search_res.data or []
                    )

                    # google検索データ
                    search_exec_res = (
                        supabase
                        .table("system_audit_logs")
                        .select("*")
                        .eq("user_id", selected_audit_user)
                        .eq("event_type", "SEARCH_EXECUTION")
                        .execute()
                    )
                    search_exec_rows = search_exec_res.data or []
                    search_exec_count = len(search_exec_rows)
                    search_exec_total_cost = sum(
                        float(row.get("api_cost", 0) or 0)
                        for row in search_exec_rows
                    )
                    search_exec_total_in = sum(
                        int(row.get("in_tokens", 0) or 0)
                        for row in search_exec_rows
                    )
                    search_exec_total_out = sum(
                        int(row.get("out_tokens", 0) or 0)
                        for row in search_exec_rows
                    )

                    # python計算データを取得
                    calc_logs = (
                        supabase
                        .table("system_audit_logs")
                        .select("event_type")
                        .eq("user_id", selected_audit_user)
                        .in_(
                            "event_type",
                            [
                                "CALCULATION_SUCCESS",
                                "CALCULATION_MISSING_FIELDS",
                                "CALCULATION_ERROR"
                            ]
                        )
                        .execute()
                    )

                    calc_success = 0
                    calc_missing = 0
                    calc_error = 0

                    for row in (calc_logs.data or []):
                        event = row.get(
                            "event_type",
                            ""
                        )

                        if event == "CALCULATION_SUCCESS":
                            calc_success += 1

                        elif event == (
                            "CALCULATION_MISSING_FIELDS"
                        ):
                            calc_missing += 1

                        elif event == "CALCULATION_ERROR":
                            calc_error += 1

                    calc_total = (
                        calc_success
                        + calc_missing
                        + calc_error
                    )

                    calc_extract_res = (
                        supabase
                        .table("system_audit_logs")
                        .select(
                            "api_cost, in_tokens, out_tokens"
                        )
                        .eq(
                            "user_id",
                            selected_audit_user
                        )
                        .eq(
                            "event_type",
                            "CALCULATION_EXTRACTION"
                        )
                        .execute()
                    )

                    calc_extract_cost = sum(
                        float(
                            x.get(
                                "api_cost",
                                0
                            )
                            or 0
                        )
                        for x in (
                            calc_extract_res.data
                            or []
                        )
                    )

                    calc_extract_in = sum(
                        int(
                            x.get(
                                "in_tokens",
                                0
                            )
                            or 0
                        )
                        for x in (
                            calc_extract_res.data
                            or []
                        )
                    )

                    calc_extract_out = sum(
                        int(
                            x.get(
                                "out_tokens",
                                0
                            )
                            or 0
                        )
                        for x in (
                            calc_extract_res.data
                            or []
                        )
                    )

            except Exception as e:
                print(
                    f"統計取得エラー: "
                    f"{type(e).__name__}: {e}"
                )

            #  ユーザー設定情報、アクティビティ集計表示
            col_info1 = st.container()
            col_info2 = st.container()

            if audit_display_section == "user_settings":
                with col_info1:
                    has_long_memory = "あり" if len(audit_facts) > 0 else "なし"
                    st.markdown(
                        "<div style='background-color: rgba(2, 136, 209, 0.08); padding: 16px; border-radius: 8px; border-left: 5px solid #0288d1;'>"
                        "<h5 style='margin-top:0; color:#0288d1; font-weight:bold;'>🎨 【デザイン・外観・プラン設定】</h5>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>会員プラン：</b> {audit_plan}</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>現在のAI名称：</b> {audit_concierge_name}</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>カラーテーマ：</b> {audit_theme}</p>"
                        "<br>"
                        "<h5 style='color:#0288d1; font-weight:bold;'>👤 【ユーザー基本プロファイル】</h5>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>登録ユーザー名：</b> {audit_user_name}</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>AIからの呼び方：</b> {audit_user_honorific}</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>AIの一人称：</b> {audit_first_person}</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>絵文字の量：</b> {audit_emoji_setting}</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>人格：</b> {audit_style_preset}</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>長期記憶：</b> {has_long_memory}</p>"
                        # f"<p style='margin: 6px 0; font-size:14px;'>・<b>長期記憶有無：</b> {len(audit_facts)} 件</p>"
                        "<h5 style='color:#0288d1; font-weight:bold;'>📝 具体的な口調・振る舞いの指示</h5>"
                        f"<pre style='background-color: white; padding: 10px; border-radius: 4px; border: 1px solid #e0e0e0; white-space: pre-wrap; font-size:12px; color:#333;'>{audit_real_instruction }</pre>"
                        "</div>",
                        unsafe_allow_html=True
                    )

            if audit_display_section == "usage_summary":
                with col_info2:
                    st.markdown(
                        "<div style='background-color: rgba(16, 185, 129, 0.08); padding: 16px; border-radius: 8px; border-left: 5px solid #10b981;'>"
                        "<h5 style='margin-top:0; color:#10b981; font-weight:bold;'>📈 【アクティビティ・統計KPI】</h5>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>総会話回数：</b> {total_chats} 回</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>通常トーク：</b> {normal_chat_count} 回</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>計画ルーム：</b> {plan_chat_count} 回</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>計画反映：</b> {plan_reflection_count} 回</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>正式運用開始日：</b> {start_date}</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>最終会話日時：</b> {last_date}</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>総システム稼働日数：</b> {total_active_days} 日間</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>1日あたりの平均通数：</b> {avg_chats_per_day} 通/日</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>検索回数：</b> {search_count} 回</p>"
                        "<br>"
                        "<h5 style='color:#10b981; font-weight:bold;'>💰 【インフラ原価・サーバーコスト】</h5>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>累計消費コスト：</b> {total_cost_jpy:.4f} 円</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>通常トーク原価：</b> {normal_chat_cost:.4f} 円</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>計画ルーム原価：</b> {plan_chat_cost:.4f} 円</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>計画反映原価：</b> {plan_reflection_cost:.4f} 円</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>通常トーク入力：</b> {normal_in_tokens:,} t</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>通常トーク出力：</b> {normal_out_tokens:,} t</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>計画ルーム入力：</b> {plan_in_tokens:,} t</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>計画ルーム出力：</b> {plan_out_tokens:,} t</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>計画反映入力：</b> {plan_reflection_in_tokens:,} t</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>計画反映出力：</b> {plan_reflection_out_tokens:,} t</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>通常トーク処理時間：</b> {normal_processing_time:.2f} 秒</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>計画ルーム処理時間：</b> {plan_processing_time:.2f} 秒</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>計画反映処理時間：</b> {plan_reflection_processing_time:.2f} 秒</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>・<b>1会話あたりの平均原価：</b> {avg_cost_per_chat:.4f} 円/通</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>"
                        f"・<b>検索判定回数：</b> {search_judge_count} 回</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>"
                        f"・<b>検索判定入力：</b> {search_judge_total_in:,} t</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>"
                        f"・<b>検索判定出力：</b> {search_judge_total_out:,} t</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>"
                        f"・<b>検索判定コスト：</b> {search_judge_total_cost:.4f} 円</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>"
                        f"・<b>Google検索実行回数：</b> {search_exec_count} 回</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>"
                        f"・<b>Google検索入力：</b> {search_exec_total_in:,} t</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>"
                        f"・<b>Google検索出力：</b> {search_exec_total_out:,} t</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>"
                        f"・<b>Google検索コスト：</b> {search_exec_total_cost:.4f} 円</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>"
                        f"・<b>不動産計算利用：</b> {calc_total} 回</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>"
                        f"・<b>計算成功：</b> {calc_success} 回</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>"
                        f"・<b>条件不足：</b> {calc_missing} 回</p>"
                        f"<p style='margin: 6px 0; font-size:14px;'>"
                        f"・<b>計算エラー：</b> {calc_error} 回</p>"
                        "</div>",
                        unsafe_allow_html=True
                    )
            
            if audit_display_section == "processing_summary":
                st.markdown("##### 📊 処理区分別の利用・原価集計")
                processing_summary_period = st.selectbox(
                    "集計期間",
                    [
                        "全期間",
                        "直近7日",
                        "直近30日",
                        "今月"
                    ],
                    index=2,
                    key=(
                        "processing_summary_period_"
                        f"{selected_audit_user}"
                    )
                )
                processing_summary_now = datetime.now(JST)
                processing_summary_start_at = None
                processing_summary_end_at = None

                if processing_summary_period == "直近7日":
                    processing_summary_start_at = (
                        processing_summary_now
                        - timedelta(days=7)
                    )
                elif processing_summary_period == "直近30日":
                    processing_summary_start_at = (
                        processing_summary_now
                        - timedelta(days=30)
                    )
                elif processing_summary_period == "今月":
                    processing_summary_start_at = (
                        processing_summary_now.replace(
                            day=1,
                            hour=0,
                            minute=0,
                            second=0,
                            microsecond=0
                        )
                    )

                processing_type_summary = (
                    get_user_processing_type_summary(
                        selected_audit_user,
                        start_at=processing_summary_start_at,
                        end_at=processing_summary_end_at
                    )
                )

                if processing_type_summary:
                    processing_summary_rows = []

                    for row in processing_type_summary:
                        processing_type = str(
                            row.get(
                                "processing_type",
                                "unclassified"
                            ) or "unclassified"
                        ).strip()

                        processing_summary_rows.append({
                            "処理区分": (
                                PROCESSING_TYPE_LABELS.get(
                                    processing_type,
                                    processing_type
                                )
                            ),
                            "実行回数": int(row.get("execution_count", 0) or 0),
                            "入力token": int(row.get("total_in_tokens", 0) or 0),
                            "出力token": int(row.get("total_out_tokens", 0) or 0),
                            "ルーター原価": float(row.get("router_yen_cost", 0) or 0),
                            "検索原価": float(row.get("search_yen_cost", 0) or 0),
                            "回答原価": float(row.get("answer_yen_cost", 0) or 0),
                            "総原価": float(row.get("total_yen_cost", 0) or 0),
                            "平均原価": float(row.get("average_yen_cost", 0) or 0),
                            "最大原価": float(row.get("maximum_yen_cost", 0) or 0),
                            "平均処理時間": float(row.get("average_processing_time", 0) or 0)
                        })

                    processing_summary_df = pd.DataFrame(processing_summary_rows)
                    processing_type_display_order = {
                        "通常会話": 1,
                        "簡易検索": 2,
                        "簡易Analysis": 3,
                        "検索付き簡易Analysis": 4,
                        "詳細検索": 5,
                        "詳細Analysis": 6,
                        "検索付き詳細Analysis": 7,
                        "区分未設定": 99
                    }

                    processing_summary_df[
                        "_display_order"
                    ] = (
                        processing_summary_df["処理区分"]
                        .map(processing_type_display_order)
                        .fillna(98)
                    )

                    processing_summary_df = (
                        processing_summary_df
                        .sort_values(
                            "_display_order",
                            ascending=True
                        )
                        .drop(
                            columns=["_display_order"]
                        )
                        .reset_index(drop=True)
                    )

                    verification_types = {
                        "簡易検索",
                        "簡易Analysis",
                        "検索付き簡易Analysis"
                    }

                    verification_df = processing_summary_df[
                        processing_summary_df["処理区分"].isin(verification_types)
                    ]

                    if not verification_df.empty:
                        verification_count = int(verification_df["実行回数"].sum())
                        verification_total_cost = float(verification_df["総原価"].sum())
                        verification_average_cost = (
                            verification_total_cost
                            / verification_count
                            if verification_count > 0
                            else 0.0
                        )

                        kpi_col1, kpi_col2, kpi_col3 = st.columns(3)

                        kpi_col1.markdown(
                            f"**簡易機能の実行回数：{verification_count:,} 回**"
                        )

                        kpi_col2.markdown(
                            f"**簡易機能の総原価：¥ {verification_total_cost:.4f}**"
                        )

                        kpi_col3.markdown(
                            f"**簡易機能の平均原価：¥ {verification_average_cost:.4f} / 回**"
                        )

                        for target_type in [
                            "簡易検索",
                            "簡易Analysis",
                            "検索付き簡易Analysis"
                        ]:
                            target_rows = verification_df[
                                verification_df["処理区分"] == target_type
                            ]

                            if target_rows.empty:
                                continue

                            target_row = target_rows.iloc[0]

                            st.markdown(
                                f"**{target_type}："
                                f"{int(target_row['実行回数']):,} 回"
                                f"｜平均原価 ¥ {float(target_row['平均原価']):.4f}"
                                f"｜平均処理時間 {float(target_row['平均処理時間']):.2f} 秒**"
                            )

                    st.dataframe(
                        processing_summary_df,
                        column_config={
                            "処理区分": st.column_config.TextColumn("処理区分"),
                            "実行回数": st.column_config.NumberColumn(
                                "実行回数",
                                format="%d 回"
                            ),
                            "入力token": st.column_config.NumberColumn(
                                "入力token",
                                format="%d"
                            ),
                            "出力token": st.column_config.NumberColumn(
                                "出力token",
                                format="%d"
                            ),
                            "ルーター原価": st.column_config.NumberColumn(
                                "ルーター原価",
                                format="¥ %.4f"
                            ),
                            "検索原価": st.column_config.NumberColumn(
                                "検索原価",
                                format="¥ %.4f"
                            ),
                            "回答原価": st.column_config.NumberColumn(
                                "回答原価",
                                format="¥ %.4f"
                            ),
                            "総原価": st.column_config.NumberColumn(
                                "総原価",
                                format="¥ %.4f"
                            ),
                            "平均原価": st.column_config.NumberColumn(
                                "平均原価",
                                format="¥ %.4f"
                            ),
                            "最大原価": st.column_config.NumberColumn(
                                "最大原価",
                                format="¥ %.4f"
                            ),
                            "平均処理時間": (
                                st.column_config.NumberColumn(
                                    "平均処理時間",
                                    format="%.2f 秒"
                                )
                            )
                        },
                        hide_index=True,
                        use_container_width=True
                    )

                    if any(
                        str(
                            row.get("processing_type", "")
                            or ""
                        ).strip() == "unclassified"
                        for row in processing_type_summary
                    ):
                        st.caption(
                            "区分未設定には、処理区分の記録を"
                            "追加する前の過去ログが含まれます。"
                        )

                else:
                    st.info("処理区分別の集計データはありません。")

            if audit_display_section == "calculation_cases":
                # 計算メモ内容表示
                st.markdown("##### 📊 計算案件一覧")
                try:
                    case_res = (
                        supabase
                        .table("calculation_cases")
                        .select("*")
                        .eq(
                            "user_id",
                            selected_audit_user
                        )
                        .order(
                            "updated_at",
                            desc=True
                        )
                        .execute()
                    )

                    case_rows = case_res.data or []

                    st.caption(f"計算案件数: {len(case_rows)}件")

                    for case in case_rows:
                        with st.expander(f"{case.get('case_name', '案件名なし')}"):
                            st.write(
                                f"Case ID: "
                                f"{case.get('case_id', '')}"
                            )
                            st.write(
                                f"種別: "
                                f"{case.get('case_type', '')}"
                            )
                            st.write(
                                f"状態: "
                                f"{case.get('case_status', '')}"
                            )
                            st.write(
                                f"用途: "
                                f"{case.get('property_usage', '')}"
                            )
                            st.write(
                                f"作成日: "
                                f"{case.get('created_at', '')}"
                            )

                            st.write(
                                f"更新日: "
                                f"{case.get('updated_at', '')}"
                            )
                            st.write(
                                f"期限: "
                                f"{case.get('expires_at', '')}"
                            )

                            st.code(
                                json.dumps(
                                    case.get(
                                        "case_data",
                                        {}
                                    ),
                                    ensure_ascii=False,
                                    indent=2,
                                    default=str
                                ),
                                language="json"
                            )

                except Exception as e:

                    st.error(
                        f"計算案件取得エラー: "
                        f"{type(e).__name__}: {e}"
                    )

            # 🚀 【大開通】 1メッセージの塊（ブロック）の中にすべての内訳を並列露出させる詳細明細タイムライン
            if audit_display_section == "conversation_logs":
                st.markdown("##### ⏱️ このユーザーのタイムライン式システムログ（最新50件）")
                # show_timeline_logs = st.button(
                #     "システムログを表示",
                #     key=(
                #         "show_timeline_logs_"
                #         f"{selected_audit_user}"
                #     )
                # )
                
                try:
                    # 1. データベース（system_audit_logs）から直近50件の生データを抽出
                    # if show_timeline_logs:
                    log_res = (
                        supabase
                        .rpc(
                            "get_user_recent_audit_logs",
                            {
                                "p_user_id": str(selected_audit_user),
                                "p_message_limit": 50
                            }
                        )
                        .execute()
                    )

                    def compact_provider_details(details):
                        text = str(details or "")
                        provider_match = re.search(r"provider=([^|/\s]+)", text)
                        model_match = re.search(r"model=([^|/\s]+)", text)
                        provider = (
                            provider_match.group(1)
                            if provider_match
                            else ""
                        )
                        model = (
                            model_match.group(1)
                            if model_match
                            else ""
                        )
                        if model:
                            return model
                        return provider
                
                    if log_res.data:
                        # 🔑 【メッセージID完全紐付け・1会話全自動集約インフラ】
                        # 時計の時間や到着順を一切信用せず、共通の固有識別ID（message_id）を鍵にして、
                        # 別行で保存されたチャットと要約の数字を「1つの会話の塊」として100%完璧にグループ化（束ねる）します！
                        merged_logs = {}
                        
                        for log in log_res.data:
                            # データベースから固有の鍵をサルベージ（万が一古い過去ログでIDが無い行は、時間の分単位を仮の鍵にして白飛びを永久防衛）
                            msg_id = log.get("message_id")
                            created_at = log.get("created_at", "")
                            time_display = created_at.replace("T", " ")[:16] if "T" in created_at else created_at
                            
                            if not msg_id or msg_id == "None" or msg_id == "":
                                # 過去データ用フォールバック：分単位で丸めて部屋を作ります
                                msg_id = f"fallback_{created_at[:16]}"
                            
                            if msg_id not in merged_logs:
                                merged_logs[msg_id] = {
                                    "id": msg_id,
                                    "time": time_display,
                                    "user_plan": log.get("user_plan", "🆓 無料プラン"),
                                    "event_type": "",
                                    "user_message": "",
                                    "ai_message": "",
                                    "chat_time": 0.0, "chat_in": 0, "chat_out": 0,"chat_cost": 0.0,
                                    "reflection_time": 0.0, "reflection_in": 0, "reflection_out": 0,
                                    "reflection_cost": 0.0, "reflection_details": "",
                                    "sum_time": 0.0, "sum_in": 0, "sum_out": 0, "sum_cost": 0.0,
                                    "judge_time": 0.0, "judge_in": 0, "judge_out": 0, "judge_cost": 0.0, "judge_result": "",
                                    "tool_time": 0.0, "tool_in": 0, "tool_out": 0, "tool_cost": 0.0,
                                    "calc_time": 0.0, "calc_in": 0, "calc_out": 0, "calc_cost": 0.0,
                                    "search_time": 0.0, "search_in": 0, "search_out": 0,
                                    "search_exec_time": 0.0, "search_exec_in": 0, "search_exec_out": 0, "search_exec_cost": 0.0,
                                    "total_yen": 0.0, "total_time": 0.0, "processing_type": "unclassified",
                                    "judge_details": "", "chat_details": "", "summary_details": "",
                                    "tool_details": "", "calc_details": "", "search_exec_details": "",
                                    "calculation_result": ""
                                }
                            
                            action = log.get("action", log.get("event_type", ""))
                            cost = log.get("api_cost") if log.get("api_cost") is not None else 0.0
                            proc_time = log.get("processing_time") if log.get("processing_time") is not None else 0.0
                            in_t = log.get("in_tokens", 0)
                            out_t = log.get("out_tokens", 0)

                            # 各コンポーネントの同じメッセージIDの対応する数値をドッキング
                            if action == "SUMMARY_SUCCESS":
                                merged_logs[msg_id]["sum_time"] = proc_time
                                merged_logs[msg_id]["sum_in"] = in_t
                                merged_logs[msg_id]["sum_out"] = out_t
                                merged_logs[msg_id]["sum_cost"] = cost
                                merged_logs[msg_id]["summary_details"] = (
                                    log.get("details", "")
                                )

                            elif action == "RESPONSE_ROUTER":
                                merged_logs[msg_id]["judge_time"] = proc_time
                                merged_logs[msg_id]["judge_in"] = in_t
                                merged_logs[msg_id]["judge_out"] = out_t
                                merged_logs[msg_id]["judge_cost"] = cost
                                router_processing_type = (
                                    extract_processing_type(log.get("details", ""))
                                )
                                if router_processing_type != "unclassified":
                                    merged_logs[msg_id][
                                        "processing_type"
                                    ] = router_processing_type
                                merged_logs[msg_id]["judge_result"] = (
                                    log.get("details", "")
                                )
                                merged_logs[msg_id]["judge_details"] = (
                                    log.get("details", "")
                                )
                            
                            elif action == "CALCULATION_TOOL_ROUTER":
                                merged_logs[msg_id]["tool_time"] = proc_time
                                merged_logs[msg_id]["tool_in"] = in_t
                                merged_logs[msg_id]["tool_out"] = out_t
                                merged_logs[msg_id]["tool_cost"] = cost
                                merged_logs[msg_id]["tool_details"] = (
                                    log.get("details", "")
                                )

                            elif action == "CALCULATION_EXTRACTION":
                                merged_logs[msg_id]["calc_time"] = proc_time
                                merged_logs[msg_id]["calc_in"] = in_t
                                merged_logs[msg_id]["calc_out"] = out_t
                                merged_logs[msg_id]["calc_cost"] = cost
                                merged_logs[msg_id]["calc_details"] = (
                                    log.get("details", "")
                                )
                            
                            elif action == "CALCULATION_SUCCESS":
                                merged_logs[msg_id]["calculation_result"] = log.get("details", "")

                            elif action == ("CALCULATION_MISSING_FIELDS"):
                                merged_logs[msg_id]["calculation_result"] = log.get("details", "")

                            elif action == "CALCULATION_ERROR":
                                merged_logs[msg_id]["calculation_result"] = log.get("details", "")

                            elif action == "SEARCH_EXECUTION":
                                merged_logs[msg_id]["search_exec_in"] = in_t
                                merged_logs[msg_id]["search_exec_out"] = out_t
                                merged_logs[msg_id]["search_exec_cost"] = cost
                                merged_logs[msg_id]["search_exec_time"] = proc_time
                                merged_logs[msg_id]["search_exec_details"] = (
                                    compact_provider_details(log.get("details", ""))
                                )
                            elif action == "PLAN_REFLECTION_SUCCESS":
                                merged_logs[msg_id]["reflection_time"] = (
                                    log.get("processing_time", proc_time)
                                    if log.get("processing_time") is not None
                                    else proc_time
                                )
                                merged_logs[msg_id]["reflection_in"] = (
                                    log.get("in_tokens", in_t)
                                    if log.get("in_tokens") is not None
                                    else in_t
                                )
                                merged_logs[msg_id]["reflection_out"] = (
                                    log.get("out_tokens", out_t)
                                    if log.get("out_tokens") is not None
                                    else out_t
                                )
                                merged_logs[msg_id]["reflection_cost"] = cost
                                merged_logs[msg_id]["reflection_details"] = (
                                    compact_provider_details(
                                        log.get("details", "")
                                    )
                                )

                            elif action in ("CHAT_SUCCESS", "PLAN_CHAT_SUCCESS"):
                                merged_logs[msg_id]["event_type"] = action
                                merged_logs[msg_id]["chat_time"] = (
                                    log.get("chat_processing_time", proc_time)
                                    if log.get("chat_processing_time") is not None
                                    else proc_time
                                )
                                merged_logs[msg_id]["chat_in"] = (
                                    log.get("chat_in_tokens", in_t)
                                    if log.get("chat_in_tokens") is not None
                                    else in_t
                                )
                                merged_logs[msg_id]["chat_out"] = (
                                    log.get("chat_out_tokens", out_t)
                                    if log.get("chat_out_tokens") is not None
                                    else out_t
                                )
                                merged_logs[msg_id]["chat_cost"] = (cost)
                                chat_processing_type = (
                                    extract_processing_type(log.get("details", ""))
                                )
                                if chat_processing_type != "unclassified":
                                    merged_logs[msg_id][
                                        "processing_type"
                                    ] = chat_processing_type
                                merged_logs[msg_id]["search_time"] = (
                                    log.get("search_processing_time", 0.0)
                                    if log.get("search_processing_time") is not None
                                    else 0.0
                                )
                                merged_logs[msg_id]["search_in"] = (
                                    log.get("search_in_tokens", 0)
                                    if log.get("search_in_tokens") is not None
                                    else 0
                                )
                                merged_logs[msg_id]["search_out"] = (
                                    log.get("search_out_tokens", 0)
                                    if log.get("search_out_tokens") is not None
                                    else 0
                                )
                                merged_logs[msg_id]["chat_details"] = (
                                    compact_provider_details(
                                        log.get("details", "")
                                    )
                                )

                            # 1会話単位の、全体の総実費合計コスト集計
                            merged_logs[msg_id]["total_yen"] += cost
                            
                        st.markdown(
                            """
                            <style>
                            .st-key-compact_audit_logs table {
                                font-size: 0.82rem;
                                line-height: 1.2;
                            }

                            .st-key-compact_audit_logs table th,
                            .st-key-compact_audit_logs table td {
                                padding: 0.25rem 0.4rem !important;
                                vertical-align: middle;
                            }

                            .st-key-compact_audit_logs table p {
                                margin: 0 !important;
                                font-size: inherit;
                                line-height: 1.2;
                            }

                            .st-key-compact_audit_logs div[data-testid="stAlert"] {
                                padding: 0.45rem 0.75rem !important;
                                margin: 0.25rem 0 0.6rem 0 !important;
                            }

                            .st-key-compact_audit_logs div[data-testid="stAlert"] p {
                                margin: 0 !important;
                                font-size: 0.9rem !important;
                                line-height: 1.4 !important;
                            }

                            .st-key-compact_audit_logs div[data-testid="stMarkdownContainer"] {
                                margin-top: 0 !important;
                                margin-bottom: 0 !important;
                            }

                            .st-key-compact_audit_logs div[data-testid="stMarkdownContainer"] p {
                                margin-top: 0.2rem !important;
                                margin-bottom: 0.2rem !important;
                            }

                            .st-key-compact_audit_logs hr {
                                margin-top: 0.6rem !important;
                                margin-bottom: 0.6rem !important;
                            }

                            .st-key-compact_audit_logs div[data-testid="stExpanderDetails"] {
                                padding-top: 0.4rem !important;
                                padding-bottom: 0.4rem !important;
                            }

                            .st-key-compact_audit_logs div[data-testid="stVerticalBlock"] {
                                gap: 0.35rem !important;
                            }

                            .st-key-compact_audit_logs div[data-testid="stMarkdownContainer"] > p {
                                margin: 0.1rem 0 !important;
                                font-size: 0.82rem !important;
                                line-height: 1.2 !important;
                            }

                            .st-key-compact_audit_logs div[data-testid="stMarkdownContainer"] > hr {
                                margin: 0.35rem 0 !important;
                            }

                            .st-key-compact_audit_logs table {
                                margin-top: 0 !important;
                                margin-bottom: 0.25rem !important;
                            }

                            .st-key-compact_audit_logs div[data-testid="stExpanderDetails"] {
                                padding-top: 0.25rem !important;
                                padding-bottom: 0.25rem !important;
                            }

                            </style>
                            """,
                            unsafe_allow_html=True
                        )

                        # 詳細ログ専用コンテナ
                        with st.container(key="compact_audit_logs"):
                            # アコーディオン出力
                            for k, item in merged_logs.items():
                                
                                # 表示されている各処理時間を合計
                                item["total_time"] = sum([
                                    float(item.get("judge_time",0.0) or 0.0),
                                    float(item.get("search_exec_time",0.0) or 0.0),
                                    float(item.get("chat_time",0.0) or 0.0),
                                    float(item.get("reflection_time", 0.0) or 0.0),
                                    float(item.get("sum_time",0.0) or 0.0),
                                    float(item.get("search_time",0.0) or 0.0),
                                    float(item.get("tool_time",0.0) or 0.0),
                                    float(item.get("calc_time",0.0) or 0.0)
                                ])

                                msg_res = (
                                    supabase
                                    .table("messages")
                                    .select(
                                        "role,"
                                        "content,"
                                        "created_at,"
                                        "message_id,"
                                        "response_mode"
                                    )
                                    .eq("user_id", selected_audit_user)
                                    .eq("message_id", item["id"])
                                    .order("created_at", desc=False)
                                    .execute()
                                )

                                user_msg = ""
                                ai_msg = ""

                                for row in (msg_res.data or []):
                                    if row.get("role") == "user":
                                        user_msg = row.get("content", "")
                                    elif row.get("role") == "assistant":
                                        ai_msg = row.get("content", "")
                                
                                c_plan = item["user_plan"]
                                t_yen = item["total_yen"]
                                t_time = item["total_time"]
                                chat_component_name = (
                                    "📋 計画ルーム対話返答"
                                    if item.get("event_type") == "PLAN_CHAT_SUCCESS"
                                    else "💬 メインチャット対話返答"
                                )

                                if (not user_msg and not ai_msg):
                                    continue
                                
                                processing_type = str(
                                    item.get(
                                        "processing_type",
                                        "unclassified"
                                    ) or "unclassified"
                                ).strip()

                                processing_type_label = (
                                    PROCESSING_TYPE_LABELS.get(
                                        processing_type,
                                        processing_type
                                    )
                                )

                                with st.expander(
                                    f"🟢 [{item['time']}]"
                                    f"{processing_type_label}｜"
                                    f"{c_plan} ➔ "
                                    f"💰 総原価: {t_yen:.4f} 円 ||"
                                    f"⏱️ 総処理: {t_time:.2f} 秒"
                                ):
                                    st.markdown(
                                        '<div class="compact-audit-log">',
                                        unsafe_allow_html=True
                                    )
                                    st.markdown(f"""

                                    | ⚙️ 処理内訳コンポーネント | ⏱️ 処理時間 (秒) | 🪙 入力(In)token | 🪙 出力(Out)token |💰 原価 |🤖 Provider |
                                    | :--- | :---: | :---: | :---: |:---: |:---: |
                                    | 🔎 **Google検索の要否判定** | {item['judge_time']:.2f} 秒 | {item['judge_in']} t | {item['judge_out']} t | ¥{item['judge_cost']:.4f} | {item['judge_details']} |
                                    | 🌐 Google検索実行 | {item['search_exec_time']:.2f} 秒 | {item['search_exec_in']} t | {item['search_exec_out']} t | ¥{item['search_exec_cost']:.4f} | {item['search_exec_details']} |
                                    | **{chat_component_name}** | {item['chat_time']:.2f} 秒 | {item['chat_in']} t | {item['chat_out']} t | ¥{item['chat_cost']:.4f} | {item['chat_details']} |
                                    | 📝 **計画書への反映** | {item['reflection_time']:.2f} 秒 | {item['reflection_in']} t | {item['reflection_out']} t | ¥{item['reflection_cost']:.4f} | {item['reflection_details']} |
                                    | 🧠 **裏スレッド記憶の要約** | {item['sum_time']:.2f} 秒 | {item['sum_in']} t | {item['sum_out']} t | ¥{item['sum_cost']:.4f} | {item['summary_details']} |
                                    | 🔍 **過去会話・意味検索** | {item['search_time']:.2f} 秒 | {item['search_in']} t | {item['search_out']} t | ¥0.0000 | |
                                    | 🧮 **計算ツール判定** | {item['tool_time']:.2f} 秒 | {item['tool_in']} t | {item['tool_out']} t | ¥{item['tool_cost']:.4f} | {item['tool_details']} |
                                    | 🏠 **不動産条件抽出** | {item['calc_time']:.2f} 秒 | {item['calc_in']} t | {item['calc_out']} t | ¥{item['calc_cost']:.4f} | {item['calc_details']} |

                                    🔎 **【検索判定結果】** {item['judge_result']}

                                    👑 **【この1メッセージに対する総実費原価】** ¥ {t_yen:.4f} 円  ||  **【ユーザー総待機ラグ】** {t_time:.2f} 秒
                                    """)
                                    st.markdown(
                                        "</div>",
                                        unsafe_allow_html=True
                                    )
                                    st.markdown("---")

                                    st.markdown("**👤 ユーザー発言**")
                                    st.info(user_msg)
                                    if item.get(
                                        "calculation_result"
                                    ):
                                        # st.warning(
                                        #     "🏠 不動産計算結果\n\n"
                                        #     + item[
                                        #         "calculation_result"
                                        #     ]
                                        # )
                                        st.code(item["calculation_result"])

                                    st.markdown("**🧠 AI返答**")
                                    st.success(ai_msg)
                    else: 
                        st.caption("このユーザーのシステムログはまだデータベースに記録されていません。")
                
                except Exception as log_err:
                    st.error(f"ユーザーログの取得に失敗しました: {log_err}")

        # 📈 画面②：アプリ全体の統計アナリティクス画面
        elif admin_mode == "📈 全体アクティビティ・統計アナリティクス":
            st.subheader("📈 アプリ全体アクティビティ ＆ 機能統計（匿名集計）")
            with st.spinner("システムログからプラン別データを高度に集計中..."):
                try:
                    # audit_res = supabase.table("system_audit_logs").select("user_id, user_plan, event_type, total_yen_cost, created_at").execute()
                    audit_res = (
                        supabase
                        .rpc("get_system_audit_summary")
                        .execute()
                    )

                    activity_res = (
                        supabase
                        .rpc("get_system_audit_activity_summary")
                        .execute()
                    )

                    audit_data = audit_res.data if audit_res.data else []
                    activity_data = activity_res.data if activity_res.data else []

                    total_user_count = 0
                    total_app_cost = 0.0
                    total_app_chats = 0
                    
                    stats_matrix = {
                        "💬 総会話往復数（送信回数）": {"free": 0, "light": 0, "standard": 0},
                        "📋 計画ルーム会話数": {"free": 0, "light": 0, "standard": 0},
                        "📝 計画反映回数": {"free": 0, "light": 0, "standard": 0},
                        "📅 総アクティブ稼働日数": {"free": 0, "light": 0, "standard": 0},
                        "🚨 1日会話上限（ガードレール）の接触回数": {"free": 0, "light": 0, "standard": 0},
                        "🎨 キャラクター・口調変更の実行回数": {"free": 0, "light": 0, "standard": 0},
                        "🚫 制限緩和：追加検索タスクの制御回数": {"free": 0, "light": 0, "standard": 0},
                    }
                    user_active_dates = {}
                    
                    for log in audit_data:
                        plan = str(log.get("user_plan", "") or "")
                        action = str(log.get("event_type", "") or "")
                        event_count = int(log.get("event_count", 0) or 0)
                        total_cost = float(log.get("total_cost", 0.0) or 0.0)

                        total_app_cost += total_cost

                        p_key = "free"
                        if "ライト" in plan:
                            p_key = "light"
                        elif "スタンダード" in plan:
                            p_key = "standard"

                        if action == "CHAT_SUCCESS":
                            stats_matrix["💬 総会話往復数（送信回数）"][p_key] += event_count
                            total_app_chats += event_count
                        elif action == "PLAN_CHAT_SUCCESS":
                            stats_matrix["📋 計画ルーム会話数"][p_key] += event_count
                        elif action == "PLAN_REFLECTION_SUCCESS":
                            stats_matrix["📝 計画反映回数"][p_key] += event_count
                        elif action == "DAILY_LIMIT_EXCEEDED":
                            stats_matrix["🚨 1日会話上限（ガードレール）の接触回数"][p_key] += event_count
                        elif action == "SETTING_UPDATE_SUCCESS":
                            stats_matrix["🎨 キャラクター・口調変更の実行回数"][p_key] += event_count
                        elif action == "PROMPT_BLOCKED_SEARCH":
                            stats_matrix["🚫 制限緩和：追加検索タスクの制御回数"][p_key] += event_count

                    for activity in activity_data:
                        plan = str(activity.get("user_plan", "") or "")
                        unique_users = int(activity.get("unique_user_count", 0) or 0)
                        active_days = int(activity.get("active_day_count", 0) or 0)

                        if plan == "__ALL__":
                            total_user_count = unique_users
                            continue

                        p_key = "free"

                        if "ライト" in plan:
                            p_key = "light"
                        elif "スタンダード" in plan:
                            p_key = "standard"

                        stats_matrix["📅 総アクティブ稼働日数"][p_key] += active_days

                    col_m1, col_m2, col_m3 = st.columns(3)
                    col_m1.metric("総稼働ユーザー数", f"{total_user_count} 名")
                    col_m2.metric("全ユーザー総通常会話回数", f"{total_app_chats} 回")
                    col_m3.metric("総サーバー代実費 (全期間)", f"{total_app_cost:.4f} 円")
                    st.markdown("---")

                    analytics_rows = []
                    for item_name, plans in stats_matrix.items():
                        unit = "日" if "稼働日数" in item_name else "回"
                        analytics_rows.append({
                            "📋 分析項目（ユーザー需要のファクト）": item_name,
                            "🆓 無料プラン": f"{plans['free']:,} {unit}",
                            "💸 ライトプラン": f"{plans['light']:,} {unit}",
                            "👑 スタンダードプラン": f"{plans['standard']:,} {unit}"
                        })                     
                    import pandas as pd
                    st.dataframe(pd.DataFrame(analytics_rows), hide_index=True, use_container_width=True)
                except Exception as ana_err: 
                    st.error(f"データ集計中にエラーが発生しました: {ana_err}")

    # ==========================================
    # 🔍 タブ4：テスター会話ログリアルタイム監視室（クローズドテスト専用）
    # ==========================================
    with all_tabs[6]:
        # st.subheader("🔍 テスター全会話リアルタイム監視掲示板")
        # st.caption("※クローズドテストに参加している一般テスターとAIコンシェルジュの具体的な対話内容を、日付・時間スタンプ付きで遠隔監査するための専用画面です。本番リリース時は、このタブのブロック（数十行）を削除するだけで、一般ユーザーに対して完全に非表示にすることが可能です。")
                    
        tester_rows = []
        users = {}
        try:
            memories_res = (
                supabase
                .table("user_memories_tester")
                .select("user_id, fact")
                .execute()
            )

            USER_PROFILE = {
                "m.kawamura00": "40代女性",
                "yasusan_cw": "40代男性",
                "shigenoi": "40代女性",
                "kham1014": "40代男性",
                "pom_neko": "20代女性",
                "kumii_5451": "50代女性",
                "kotobayomi": "40代女性",
                "reirou": "30代男性",
                "yoimachigusa": "30代女性",
                "yong3127": "30代女性",
            }
            user_res = (
                supabase
                .table("user_token_stats")
                .select("user_id")
                .execute()
            )
            # msg_users_res = (
            #     supabase
            #     .table("messages")
            #     .select("user_id")
            #     .execute()
            # )

            all_user_ids = sorted(
                list(
                    set(
                        row["user_id"]
                        for row in user_res.data
                        if row.get("user_id")
                    )
                )
            )

            for row in memories_res.data:
                uid = row["user_id"]

                if uid not in users:
                    users[uid] = {
                        "ユーザーID": uid,
                        "AI名称": "",
                        "ユーザー名": "",
                        "呼び方": "",
                        "一人称": "",
                        "絵文字": "",
                        "人格": "",
                        "テーマ": ""
                    }

                fact = row.get("fact", "")

                if fact.startswith("AIの名前:"):
                    users[uid]["AI名称"] = fact.replace("AIの名前:", "").strip()

                elif fact.startswith("ユーザー名:"):
                    users[uid]["ユーザー名"] = fact.replace("ユーザー名:", "").strip()

                elif fact.startswith("ユーザー敬称:"):
                    users[uid]["呼び方"] = fact.replace("ユーザー敬称:", "").strip()

                elif fact.startswith("AI一人称:"):
                    users[uid]["一人称"] = fact.replace("AI一人称:", "").strip()

                elif fact.startswith("絵文字の量:"):
                    users[uid]["絵文字"] = fact.replace("絵文字の量:", "").strip()

                elif fact.startswith("人格:"):
                    users[uid]["人格"] = fact.replace("人格:", "").strip()

                elif fact.startswith("カラーテーマ:"):
                    users[uid]["テーマ"] = fact.replace("カラーテーマ:", "").strip()
            
            EXCLUDED_USERS = {
                CURRENT_USER_ID,
                USUAL_USER_ID
            }
            for uid in all_user_ids:
                if uid in EXCLUDED_USERS:
                    continue
                if uid not in users:
                    users[uid] = {
                        "ユーザーID": uid,
                        "AI名称": "未設定",
                        "ユーザー名": "未設定",
                        "呼び方": "",
                        "一人称": "",
                        "絵文字": "",
                        "人格": "",
                        "テーマ": ""
                    }

            tester_rows = list(users.values())

            st.markdown("""
            <style>
            [data-testid="stDataFrame"] table {
                font-size: 16px !important;
            }
            </style>
            """, unsafe_allow_html=True)

            st.markdown("### 🎨 テスター設定状況一覧")
            st.dataframe(
                pd.DataFrame(tester_rows),
                use_container_width=True,
                hide_index=True
            )

        except Exception as e:
            st.error(f"設定一覧取得エラー: {e}")

        usage_rows = []

        for uid in users.keys():

            try:

                msg_res = (
                    supabase
                    .table("messages")
                    .select("created_at, role")
                    .eq("user_id", uid)
                    .execute()
                )

                msgs = msg_res.data or []

                user_msgs = [
                    m for m in msgs
                    if m.get("role") == "user"
                ]

                total_chat = len(user_msgs)

                if msgs:

                    times = [
                        datetime.fromisoformat(
                            m["created_at"].replace("Z", "+00:00")
                        )
                        for m in msgs
                    ]

                    start_date = min(times)

                    last_date = max(times)

                    active_days = len(
                        set(t.date() for t in times)
                    )

                else:

                    start_date = None
                    last_date = None
                    active_days = 0

                cost_res = (
                    supabase
                    .table("system_audit_logs")
                    .select("api_cost")
                    .eq("user_id", uid)
                    .execute()
                )
                search_res = (
                    supabase
                    .table("search_logs")
                    .select("*")
                    .eq("user_id", uid)
                    .execute()
                )

                search_count = len(
                    search_res.data or []
                )

                total_cost = sum(
                    float(x.get("api_cost", 0) or 0)
                    for x in cost_res.data
                )

                avg_cost = (
                    round(total_cost / total_chat, 3)
                    if total_chat > 0
                    else 0
                )

                usage_rows.append({

                    "ユーザーID": uid,
                    "属性": USER_PROFILE.get(uid, "不明"),

                    "開始日":
                        start_date.strftime("%Y-%m-%d")
                        if start_date else "-",

                    "利用日数":
                        f"{active_days}日",

                    "最終利用":
                        last_date.strftime("%Y-%m-%d %H:%M")
                        if last_date else "-",

                    "総会話数":
                        f"{total_chat}回",

                    "累計コスト":
                        f"{round(total_cost, 2)}円",

                    "1会話コスト":
                        f"{avg_cost}円",

                    "会話進捗":
                        f"{total_chat}/20",

                    "利用日数進捗":
                        f"{active_days}/4",
                    "会話進捗":
                        f"{total_chat}/20",
                    "利用日数進捗":
                        f"{active_days}/4",
                    "検索回数":
                        f"{search_count}回"
                })

            except Exception as e:
                # print(uid, e)
                st.error(f"{uid}: {e}")

        st.markdown("### 📈 テスター利用状況一覧")

        st.dataframe(
            pd.DataFrame(usage_rows),
            use_container_width=True,
            hide_index=True
        )
        total_all_cost = sum(
            float(row["累計コスト"].replace("円", ""))
            for row in usage_rows
        )

        total_all_chats = sum(
            int(row["総会話数"].replace("回", ""))
            for row in usage_rows
        )

        overall_avg_cost = (
            total_all_cost / total_all_chats
            if total_all_chats > 0
            else 0
        )

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "全テスター累計コスト",
            f"{total_all_cost:.2f}円"
        )

        col2.metric(
            "全テスター総会話数",
            f"{total_all_chats}回"
        )

        col3.metric(
            "全体平均・1会話コスト",
            f"{overall_avg_cost:.3f}円"
        )

        # ──────────────────────────────────────────────────────────────────
        # 📊 【確定最終製品版】 テスター管理・分析の部屋（インデント完全修正型）
        # ──────────────────────────────────────────────────────────────────
        all_tester_logs = None
        try:
            # 1. データベースの user_token_stats テーブルからユーザー取得
            tester_users_res = supabase.table("user_token_stats").select("user_id").execute()
            
            # 🟢 直前で引っこ抜いた「tester_users_res.data」の名前を正確にスキャンして名簿を作成します
            if tester_users_res.data:
                user_list = sorted(list(set([u["user_id"] for u in tester_users_res.data if u.get("user_id")])))
            else:
                user_list = [CURRENT_USER_ID]
        except Exception as e_list:
            st.error(f"名簿取得エラー: {e_list}")
            print(f"⚠️ 名簿取得エラー: {e_list}")
            user_list = [CURRENT_USER_ID]

        if not user_list:
            user_list = [CURRENT_USER_ID]
        
        # 🎨 ユーザー切り替えプルダウンを最上部に美しく表示
        st.markdown("### 👥 テスター選択（管理者権限）")
        selected_target_user_id = st.selectbox(
            "テスターのIDを選択してください",
            options=user_list,
            index=user_list.index(CURRENT_USER_ID) if CURRENT_USER_ID in user_list else 0,
            key="admin_user_selector"
        )
        st.divider()

        if st.button(
            "📖 会話履歴を表示",
            key="show_user_logs_button"
        ):
            st.session_state["show_user_logs"] = True

        # プルダウンで選択肢したテスターのログを表示
        try:
            if (
                tester_users_res.data
                and st.session_state.get(
                    "show_user_logs",
                    False
                )
            ):

                selected_logs = (
                    supabase
                    .table("messages")
                    .select(
                        "role,"
                        "content,"
                        "created_at,"
                        "message_id,"
                        "response_mode"
                    )
                    .eq("user_id", selected_target_user_id)
                    .order("created_at", desc=True)
                    .limit(300)
                    .execute()
                )
                logs = selected_logs.data or []

                # grouped_logs = {}
                # for log in tester_users_res.data:
                #     uid = log.get("user_id", "unknown")
                #     if uid not in grouped_logs:
                #         grouped_logs[uid] = []
                #     grouped_logs[uid].append(log)

                selected_user_info = users.get(
                    selected_target_user_id,
                    {}
                )

                user_name = selected_user_info.get("ユーザー名", "")
                honorific = selected_user_info.get("呼び方", "")

                if not user_name or user_name == "未設定":
                    target_display_user_name = "私"
                else:
                    target_display_user_name = (
                        f"{user_name}{honorific}"
                        if honorific != "（呼び捨て/なし）"
                        else user_name
                    )

                target_ai_name = selected_user_info.get("AI名称", "")

                if not target_ai_name or target_ai_name == "未設定":
                    target_ai_name = "コンシェルジュ"
                
                # 💡 選ばれたターゲットテスターのデータだけを狙い撃ちで表示します！
                # if selected_target_user_id in grouped_logs:
                #     logs = grouped_logs[selected_target_user_id]
                if logs:
                    st.markdown(f"### 👤 テスターID: `{selected_target_user_id}`")
                        
                    # 該当テスターの会話の往復履歴を時系列に沿って表示
                    for l in logs:
                        role = l.get("role", "user")
                        content = l.get("content", "")
                        created_at = l.get("created_at", "")
                        clean_time = created_at.replace("T", " ")[:16]
                            
                        if role == "user":
                            st.markdown(
                                f"&nbsp;&nbsp;💫 `[{clean_time}]` "
                                f"**{target_display_user_name}**: 「{content}」"
                            )
                        else:
                            st.markdown(
                                f"&nbsp;&nbsp;🔮 `[{clean_time}]` "
                                f"**{target_ai_name}**: {content}"
                            )
                    st.markdown("---")
                else:
                    st.info(f"テスター `{selected_target_user_id}` による会話の足跡は、まだデータベースに記録されていません。")
            else:
                st.info("テスターによる会話の足跡は、まだデータベースに記録されていません。")
                
        except Exception as e:
            st.error(f"テスター会話ログのデータ抽出に失敗しました: {e}")
    
st.markdown("<br>", unsafe_allow_html=True)
st.caption("© 2026 Sync-Lnk // AI. All rights reserved.")