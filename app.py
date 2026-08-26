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

# 【コスト最適化】AIに一度に送る送信数を直近30件（15往復分）に制限！
MAX_CONTEXT_MESSAGES = 30 
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

# --- ⚙️【新規追加】データ整理・削除機能 ---
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 履歴データの整理・絞り込み削除")

# ① 条件指定（キーワード）絞り込み削除機能
delete_keyword = st.sidebar.text_input("🎯 消したい言葉（例: アプリ, コード）:", key="delete_kw_input")
if st.sidebar.button("指定した言葉を含む会話を削除"):
    if delete_keyword:
        try:
            # Supabaseからキーワードが含まれる会話だけを削除
            supabase.table("chat_history") \
                .delete() \
                .eq("topic", selected_topic) \
                .ilike("content", f"%{delete_keyword}%") \
                .execute()

            # 画面表示用のメモリデータからも削除
            current_topic_key = f"messages_{selected_topic}"
            if current_topic_key in st.session_state:
                st.session_state[current_topic_key] = [
                    msg for msg in st.session_state[current_topic_key] 
                    if delete_keyword.lower() not in msg["content"].lower()
                ]
            st.sidebar.success(f"「{delete_keyword}」を含む会話を削除しました！")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"削除エラー: {e}")
    else:
        st.sidebar.warning("消したい言葉を入力してください。")

# ② トピック丸ごと全削除（確認用チェック付き）
with st.sidebar.expander("⚠️ トピックの全履歴をリセット"):
    confirm_delete = st.checkbox("本当に全削除しますか？")
    if st.button("🗑️ このトピックを全削除"):
        if confirm_delete:
            try:
                supabase.table("chat_history").delete().eq("topic", selected_topic).execute()
                current_topic_key = f"messages_{selected_topic}"
                st.session_state[current_topic_key] = []
                st.success(f"「{selected_topic}」の全履歴を削除しました！")
                st.rerun()
            except Exception as e:
                st.error(f"全削除エラー: {e}")
        else:
            st.warning("確認チェックを入れてください。")

# --- メイン画面処理 ---
st.caption(f"現在のトピック: **{selected_topic}** (※コスト最適化：直近30件モード)")

client = genai.Client(api_key=API_KEY)
current_topic_key = f"messages_{selected_topic}"

# 起動時にSupabaseから選択されたトピックの過去ログを取得
if current_topic_key not in st.session_state:
    st.session_state[current_topic_key] = []
    try:
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

    # Supabaseへ保存
    try:
        supabase.table("chat_history").insert({
            "role": "user", 
            "content": user_input,
            "topic": selected_topic
        }).execute()
    except Exception as e:
        st.error(f"クラウド保存エラー(user): {e}")

    # 直近30件（15往復分）だけをAIに送信
    recent_messages = st.session_state[current_topic_key][-MAX_CONTEXT_MESSAGES:]

    chat_contents = []
    for msg in recent_messages:
        role_name = "user" if msg["role"] == "user" else "model"
        chat_contents.append({"role": role_name, "parts": [{"text": msg["content"]}]})

    # AIからの返答を取得
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

    # Supabaseへ保存
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
