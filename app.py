import streamlit as st
from google import genai
import os
from supabase import create_client, Client

# Supabaseの接続情報
SUPABASE_URL = "https://mulkgkhozkvjmjdlfzwu.supabase.co"
SUPABASE_KEY = "sb_publishable_HOdI0Fp8SMVLBDG_IJ-qiw_5rBl3Ces"

# クライアント（通信用ロボット）の初期化
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 【重要】あなたのAPIキー
API_KEY = "AQ.Ab8RN6JHvTGeeRAdCrrAWzh8SsmEUM6Iv0UGrFzgwr2YewsWxQ"

# 【バランス調整】AIに送る直近の会話数（100件＝50往復分）
# これにより、過去の細かい物件情報や新しい変更点もAIがしっかり記憶・理解します
MAX_CONTEXT_MESSAGES = 100 
# ==========================================

st.title("個別相談ＡＩ")
st.caption("※Supabaseクラウド永久記憶（コンテキスト100件拡張モード）")

# AIクライアントの初期化
client = genai.Client(api_key=API_KEY)

# 起動時に、Supabaseから直近の会話履歴（最大200件）を取得して画面に復元
if "messages" not in st.session_state:
    st.session_state.messages = []
    try:
        # 直近200件を取得（古い順に並べ替え）
        response = supabase.table("chat_history") \
            .select("role, content") \
            .order("created_at", desc=True) \
            .limit(200) \
            .execute()

        data = response.data
        if data:
            # 取得したデータを古い順（時系列順）に戻してセッションに格納
            for row in reversed(data):
                st.session_state.messages.append({"role": row["role"], "content": row["content"]})
    except Exception as e:
        st.error(f"クラウドからの履歴読み込みエラー: {e}")

# 過去の会話を画面に表示
for message in st.session_state.messages:
    avatar = "🔵" if message["role"] == "user" else "🤖"
    with st.chat_message(message["role"], avatar=avatar):
        st.write(message["content"])

# ユーザーからの入力
if user_input := st.chat_input("AIに相談したいことを入力してください..."):
    # ユーザーの入力を表示
    with st.chat_message("user", avatar="🔵"):
        st.write(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})

    # Supabase（クラウド）へユーザーの発言を保存
    try:
        supabase.table("chat_history").insert({"role": "user", "content": user_input}).execute()
    except Exception as e:
        st.error(f"クラウド保存エラー(user): {e}")

    # 【記憶拡張】直近100件（50往復）の文脈をまるごとAIに送る
    recent_messages = st.session_state.messages[-MAX_CONTEXT_MESSAGES:]

    chat_contents = []
    for msg in recent_messages:
        role_name = "user" if msg["role"] == "user" else "model"
        chat_contents.append({"role": role_name, "parts": [{"text": msg["content"]}]})

    # AIの返答を取得
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=chat_contents,
        )
        ai_response = response.text
    except Exception as e:
        ai_response = f"エラーが発生しました: {e}"

    # AIの返答を表示
    with st.chat_message("assistant", avatar="🤖"):
        st.write(ai_response)
    st.session_state.messages.append({"role": "assistant", "content": ai_response})

    # Supabase（クラウド）へAIの返答を保存
    try:
        supabase.table("chat_history").insert({"role": "assistant", "content": ai_response}).execute()
    except Exception as e:
        st.error(f"クラウド保存エラー(assistant): {e}")

# フォントサイズ調整などの装飾（CSS）
st.markdown(
    """
    <style>
    .stChatMessage h1, .stChatMessage h2, .stChatMessage h3, .stChatMessage h4 {
        font-size: 18.5px !important;
        font-weight: bold !important;
        margin-top: 14px !important;
        margin-bottom: 6px !important;
    }
    .stChatMessage p strong {
        font-weight: bold !important;
        font-size: inherit !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)
