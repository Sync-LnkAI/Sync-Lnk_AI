import streamlit as st
from google import genai
import os
from supabase import create_client, Client

# Supabaseの接続情報
SUPABASE_URL = "https://mulkgkhozkvjmjdlfzwu.supabase.co"
SUPABASE_KEY = "sb_publishable_HOdI0Fp8SMVLBDG_IJ-qiw_5rBl3Ces"

# クライアントの初期化
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 【重要】APIキー
API_KEY = "AQ.Ab8RN6JHvTGeeRAdCrrAWzh8SsmEUM6Iv0UGrFzgwr2YewsWxQ"
# ==========================================

st.title("個別相談ＡＩ")

# --- サイドバー（トピック切り替え機能） ---
st.sidebar.header("📁 相談トピック（テーマ）")

default_topics = [
    "📜 過去の会話ログ（全般）", 
    "🏠 不動産・資産形成", 
    "🚀 アプリ開発・販売戦略", 
    "💬 雑談・その他"
]

if "topic_list" not in st.session_state:
    st.session_state.topic_list = default_topics

selected_topic = st.sidebar.radio("トピックを選択してください:", st.session_state.topic_list)

st.sidebar.markdown("---")
new_topic_name = st.sidebar.text_input("➕ 新しいトピックを作成:")
if st.sidebar.button("トピックを追加"):
    if new_topic_name and new_topic_name not in st.session_state.topic_list:
        st.session_state.topic_list.append(new_topic_name)
        st.sidebar.success(f"「{new_topic_name}」を追加しました！")
        st.rerun()

st.caption(f"現在のトピック: **{selected_topic}** (※テスト用全件読み込みモード)")

client = genai.Client(api_key=API_KEY)

current_topic_key = f"messages_{selected_topic}"

# 制限を解除し、Supabaseから過去の会話を「制限なし（全件）」で古い順に取得
if current_topic_key not in st.session_state:
    st.session_state[current_topic_key] = []
    try:
        if selected_topic == "📜 過去の会話ログ（全般）":
            # 旧データ（topicがnull）も含めて古い順に全件取得
            response = supabase.table("chat_history") \
                .select("role, content") \
                .or_(f"topic.eq.{selected_topic},topic.is.null") \
                .order("created_at", desc=False) \
                .execute()
        else:
            # 選択中トピックのデータを古い順に全件取得
            response = supabase.table("chat_history") \
                .select("role, content") \
                .eq("topic", selected_topic) \
                .order("created_at", desc=False) \
                .execute()

        data = response.data
        if data:
            for row in data:
                st.session_state[current_topic_key].append({"role": row["role"], "content": row["content"]})
    except Exception as e:
        st.error(f"履歴読み込みエラー: {e}")

# メッセージ表示
for message in st.session_state[current_topic_key]:
    avatar = "🔵" if message["role"] == "user" else "🤖"
    with st.chat_message(message["role"], avatar=avatar):
        st.write(message["content"])

# ユーザーからの入力
if user_input := st.chat_input(f"【{selected_topic}】について入力..."):
    with st.chat_message("user", avatar="🔵"):
        st.write(user_input)
    st.session_state[current_topic_key].append({"role": "user", "content": user_input})

    try:
        supabase.table("chat_history").insert({
            "role": "user", 
            "content": user_input,
            "topic": selected_topic
        }).execute()
    except Exception as e:
        st.error(f"クラウド保存エラー(user): {e}")

    # 【テスト用設定】件数制限を解除し、全会話ログをそのままAIに送信
    chat_contents = []
    for msg in st.session_state[current_topic_key]:
        role_name = "user" if msg["role"] == "user" else "model"
        chat_contents.append({"role": role_name, "parts": [{"text": msg["content"]}]})

    try:
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=chat_contents,
        )
        ai_response = response.text
    except Exception as e:
        ai_response = f"エラーが発生しました: {e}"

    with st.chat_message("assistant", avatar="🤖"):
        st.write(ai_response)
    st.session_state[current_topic_key].append({"role": "assistant", "content": ai_response})

    try:
        supabase.table("chat_history").insert({
            "role": "assistant", 
            "content": ai_response,
            "topic": selected_topic
        }).execute()
    except Exception as e:
        st.error(f"クラウド保存エラー(assistant): {e}")

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
