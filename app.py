import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client

# ==========================================
# ⚙️ 設定・初期化
# ==========================================
st.set_page_config(page_title="My AI Concierge", page_icon="🤖", layout="wide")

# 1. 将来の課金プランや設定変更を見据えた【文脈メッセージ上限】の設定
MAX_CONTEXT_MESSAGES = 30  # 現在は直近30件を保持（超えた分は自動要約）

# Supabase & Gemini API 設定（st.secrets から取得）
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

@st.cache_resource
def init_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# Geminiの初期化 (Gemini 3.6 / gemini-1.5-pro などお使いのモデル名を指定)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-pro")  # ご利用中のモデル名

# ==========================================
# 🗄️ Supabase データベース操作関数
# ==========================================

def get_themes():
    """全テーマ一覧を取得"""
    res = supabase.table("themes").select("*").order("id", desc=False).execute()
    return res.data if res.data else []

def get_theme_summary(theme_id: int) -> str:
    """指定されたテーマの要約を取得"""
    res = supabase.table("themes").select("summary").eq("id", theme_id).execute()
    if res.data and res.data[0].get("summary"):
        return res.data[0]["summary"]
    return ""

def update_theme_summary(theme_id: int, new_summary: str):
    """指定されたテーマの要約を更新"""
    supabase.table("themes").update({"summary": new_summary}).eq("id", theme_id).execute()

def get_messages(theme_id: int):
    """指定されたテーマの全メッセージを取得"""
    res = supabase.table("messages").select("*").eq("theme_id", theme_id).order("created_at", desc=False).execute()
    return res.data if res.data else []

def save_message(theme_id: int, role: str, content: str):
    """メッセージをSupabaseへ保存"""
    data = {
        "user_id": "default_user",
        "theme_id": theme_id,
        "role": role,
        "content": content
    }
    supabase.table("messages").insert(data).execute()

# ==========================================
# 🧠 自動要約ロジック（30件超過時に連動発動）
# ==========================================

def check_and_summarize_history(theme_id: int, all_messages: list, current_summary: str) -> str:
    """
    メッセージ件数が MAX_CONTEXT_MESSAGES (30件) を超えている場合、
    古いメッセージと既存の要約を結合して新しい要約を生成・保存します。
    """
    if len(all_messages) <= MAX_CONTEXT_MESSAGES:
        return current_summary

    # 直近 MAX_CONTEXT_MESSAGES 件より前の「溢れた古いメッセージ」を抽出
    old_messages = all_messages[:-MAX_CONTEXT_MESSAGES]

    # 古いメッセージをテキスト化
    formatted_old_text = "\n".join([f"{m['role']}: {m['content']}" for m in old_messages])

    prompt = f"""
    以下はこれまでの会話の【既存の要約】と、新しく溢れた【過去の会話ログ】です。
    文脈・重要データ・ユーザーの指示や前提条件を損なわないよう、これらを統合した【新しい要約】を日本語300〜400文字程度で作成してください。

    【既存の要約】:
    {current_summary if current_summary else "（まだ要約はありません）"}

    【過去の会話ログ】:
    {formatted_old_text}
    """

    try:
        # Geminiで要約を作成
        summary_response = model.generate_content(prompt)
        new_summary = summary_response.text.strip()

        # Supabaseの該当テーマの summary カラムを更新
        update_theme_summary(theme_id, new_summary)
        return new_summary
    except Exception as e:
        st.error(f"要約の更新中にエラーが発生しました: {e}")
        return current_summary

# ==========================================
# 🖥️ サイドバー（テーマ選択・管理）
# ==========================================

st.sidebar.title("💬 My AI Concierge")

themes = get_themes()
if not themes:
    st.sidebar.warning("テーマが存在しません。Supabaseを確認してください。")
    st.stop()

# テーマ選択肢の作成
theme_options = {f"{t['icon']} {t['name']}": t['id'] for t in themes}
selected_theme_label = st.sidebar.selectbox("テーマを選択してください:", list(theme_options.keys()))
current_theme_id = theme_options[selected_theme_label]

# 現在のテーマの「要約」を表示（デバッグ・確認用アコーディオン）
current_summary = get_theme_summary(current_theme_id)
with st.sidebar.expander("🧠 現在のテーマ記憶（要約）", expanded=False):
    if current_summary:
        st.info(current_summary)
    else:
        st.caption("※会話が30件を超えると自動でここに要約が記録されます。")

# ==========================================
# 💬 メインチャット画面
# ==========================================

st.title(f"{selected_theme_label}")

# Supabaseから全メッセージを取得
all_messages = get_messages(current_theme_id)

# 画面に過去ログを表示
for msg in all_messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# ユーザー入力
if user_input := st.chat_input("メッセージを入力してください..."):
    # 1. ユーザーの入力内容を表示＆Supabaseへ保存
    with st.chat_message("user"):
        st.write(user_input)
    save_message(current_theme_id, "user", user_input)

    # 2. メッセージリストを最新化
    all_messages.append({"role": "user", "content": user_input})

    # 3. 30件を超えていたら自動要約を実行・更新（テーマ別）
    updated_summary = check_and_summarize_history(current_theme_id, all_messages, current_summary)

    # 4. Geminiへ渡すコンテキストの作成
    # ①【要約プロンプト】+ ②【直近30件の生の会話ログ】
    recent_messages = all_messages[-MAX_CONTEXT_MESSAGES:]

    # プロンプトの組み立て
    system_instruction = "あなたは優秀なAIコンシェルジュです。"
    if updated_summary:
        system_instruction += f"\n\n【これまでの会話の前提・背景要約】:\n{updated_summary}"

    # Gemini用の会話履歴（ChatHistory）を構築
    contents_for_gemini = []
    # システム指示/要約を先頭に追加
    contents_for_gemini.append({"role": "user", "parts": [f"[システム前提情報]\n{system_instruction}"]})
    contents_for_gemini.append({"role": "model", "parts": ["承知いたしました。前提文脈を理解して回答します。"]})

    # 直近の生の会話（最大30件）を追加
    for m in recent_messages:
        role = "user" if m["role"] == "user" else "model"
        contents_for_gemini.append({"role": role, "parts": [m["content"]]})

    # 5. Geminiから回答を取得
    with st.chat_message("assistant"):
        with st.spinner("思考中..."):
            try:
                response = model.generate_content(contents_for_gemini)
                ai_reply = response.text
                st.write(ai_reply)

                # 6. AIの回答をSupabaseへ保存
                save_message(current_theme_id, "assistant", ai_reply)

            except Exception as e:
                st.error(f"Gemini API エラー: {e}")

    # 画面リロードして最新状態を確定
    st.rerun()
