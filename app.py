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
# ==========================================

st.title("個別相談ＡＩ")
st.caption("※Supabaseクラウド永久記憶モード")

# AIクライアントの初期化
client = genai.Client(api_key=API_KEY)

# 【新機能・クラウド版】起動時に、Supabaseから過去の会話履歴をすべて読み込んで復活させる
if "messages" not in st.session_state:
    st.session_state.messages = []
    try:
        # Supabaseの chat_history テーブルから古い順に全データを取得
        response = supabase.table("chat_history").select("role, content").order("created_at", desc=False).execute()
        data = response.data
        if data:
            for row in data:
                # roleがuserかassistantかを判別してセッションに格納
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

    # AIにこれまでの全履歴をセットにして送る
    chat_contents = []
    for msg in st.session_state.messages:
        role_name = "user" if msg["role"] == "user" else "model"
        chat_contents.append({"role": role_name, "parts": [{"text": msg["content"]}]})

    # AIの返答を取得
    try:
        response = client.models.generate_content(
            model='gemini-3.6-flash', # ご自身の環境で正常動作する指定
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

st.markdown(
    """
    <style>
    /* チャット内の見出し（###など）の大きさを指定 */
    .stChatMessage h1, .stChatMessage h2, .stChatMessage h3, .stChatMessage h4 {
        font-size: 18.5px !important;
        font-weight: bold !important;
        margin-top: 14px !important;
        margin-bottom: 6px !important;
    }
    /* 本文の中の太字（**の部分）を正しく太字として表示させる記述を追加 */
    .stChatMessage p strong {
        font-weight: bold !important;
        font-size: inherit !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)
