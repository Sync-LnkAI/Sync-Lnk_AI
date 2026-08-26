import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client

# ==========================================
# ⚙️ 設定・初期化
# ==========================================
st.set_page_config(page_title="My AI Concierge", page_icon="🤖", layout="wide")

# 将来の課金プランや設定変更を見据えた【文脈メッセージ上限】の設定
MAX_CONTEXT_MESSAGES = 30  # 直近30件を保持（超えた分は自動要約）

# Secretsの読み込み
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

@st.cache_resource
def init_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# Geminiの初期化
genai.configure(api_key=GEMINI_API_KEY)
# ノートの仕様通り gemini-3.6-flash を指定
model = genai.GenerativeModel("gemini-3.6-flash")

import time

def generate_with_retry(contents, retries=3, delay=2):
    """503エラー等の一次通信障害時に自動リトライする関数"""
    for i in range(retries):
        try:
            return model.generate_content(contents)
        except Exception as e:
            if "503" in str(e) and i < retries - 1:
                time.sleep(delay)  # 2秒待って再試行
                continue
            raise e

USER_ID = "default_user"

# ==========================================
# 🗄️ Supabase データベース操作関数
# ==========================================

def get_themes():
    """全テーマ一覧を取得（無ければ初期作成）"""
    try:
        res = supabase.table("themes").select("*").order("id", desc=False).execute()
        if not res.data:
            supabase.table("themes").insert({"user_id": USER_ID, "name": "メイン", "icon": "🏠", "summary": ""}).execute()
            res = supabase.table("themes").select("*").order("id", desc=False).execute()
        return res.data
    except Exception as e:
        st.error(f"テーマ取得エラー: {e}")
        return []

def add_theme(name: str, icon: str):
    if name:
        supabase.table("themes").insert({"user_id": USER_ID, "name": name, "icon": icon, "summary": ""}).execute()
        st.rerun()

def update_theme(theme_id: int, new_name: str, new_icon: str):
    if new_name:
        supabase.table("themes").update({"name": new_name, "icon": new_icon}).eq("id", theme_id).execute()
        st.rerun()

def delete_theme(theme_id: int):
    supabase.table("messages").delete().eq("theme_id", theme_id).execute()
    supabase.table("themes").delete().eq("id", theme_id).execute()
    st.rerun()

def get_theme_summary(theme_id: int) -> str:
    res = supabase.table("themes").select("summary").eq("id", theme_id).execute()
    if res.data and res.data[0].get("summary"):
        return res.data[0]["summary"]
    return ""

def update_theme_summary(theme_id: int, new_summary: str):
    supabase.table("themes").update({"summary": new_summary}).eq("id", theme_id).execute()

def get_messages(theme_id: int):
    res = supabase.table("messages").select("*").eq("theme_id", theme_id).order("created_at", desc=False).execute()
    return res.data if res.data else []

def save_message(theme_id: int, role: str, content: str):
    # ロールは user または model で統一
    normalized_role = "user" if role == "user" else "model"
    data = {
        "user_id": USER_ID,
        "theme_id": theme_id,
        "role": normalized_role,
        "content": content
    }
    supabase.table("messages").insert(data).execute()

def delete_messages_by_keyword(theme_id: int, keyword: str):
    if keyword:
        res = supabase.table("messages").select("id").eq("theme_id", theme_id).ilike("content", f"%{keyword}%").execute()
        ids = [m["id"] for m in res.data]
        if ids:
            supabase.table("messages").delete().in_("id", ids).execute()
            st.success(f"キーワード「{keyword}」を含むメッセージを削除しました。")
            st.rerun()
        else:
            st.info("該当するメッセージが見つかりませんでした。")

def clear_all_messages(theme_id: int):
    supabase.table("messages").delete().eq("theme_id", theme_id).execute()
    supabase.table("themes").update({"summary": ""}).eq("id", theme_id).execute()
    st.success("会話履歴と要約記憶を全削除しました。")
    st.rerun()

# ==========================================
# 🧠 自動要約ロジック（エラー回避ガード付き）
# ==========================================

def check_and_summarize_history(theme_id: int, all_messages: list, current_summary: str) -> str:
    if len(all_messages) <= MAX_CONTEXT_MESSAGES:
        return current_summary

    old_messages = all_messages[:-MAX_CONTEXT_MESSAGES]
    formatted_old_text = "\n".join([f"{'ユーザー' if m['role']=='user' else 'AI'}: {m['content']}" for m in old_messages])

    prompt = f"""
    以下はこれまでの会話の【既存の要約】と、新しく溢れた【過去の会話ログ】です。
    文脈・重要データ・ユーザーの指示や前提条件を損なわないよう、これらを統合した【新しい要約】を日本語300〜400文字程度で作成してください。

    【既存の要約】:
    {current_summary if current_summary else "（まだ要約はありません）"}

    【過去の会話ログ】:
    {formatted_old_text}
    """

    try:
        summary_response = model.generate_content(prompt)
        new_summary = summary_response.text.strip()
        update_theme_summary(theme_id, new_summary)
        return new_summary
    except Exception as e:
        # 要約失敗時もエラー停止させず旧要約を保持
        return current_summary

# ==========================================
# 🖥️ サイドバー（テーマ選択・管理）
# ==========================================

st.sidebar.title("My AI Concierge")

themes = get_themes()
if not themes:
    st.stop()

# テーマ選択
theme_options = {f"{t.get('icon', '💬')} {t['name']}": t for t in themes}
selected_label = st.sidebar.selectbox("テーマを選択してください:", list(theme_options.keys()))
current_theme = theme_options[selected_label]
current_theme_id = current_theme["id"]

st.sidebar.divider()

# 1. テーマの管理機能（追加・編集・削除）
with st.sidebar.expander("⚙️ テーマの管理（追加・編集・削除）"):
    st.subheader("＋ 新しいテーマを作成")
    col1, col2 = st.columns([1, 3])
    new_icon = col1.text_input("アイコン", value="💬", key="new_icon")
    new_name = col2.text_input("テーマ名", key="new_name")
    if st.button("作成", key="btn_add"):
        add_theme(new_name, new_icon)

    st.divider()

    st.subheader("✏️ テーマの編集")
    col_e1, col_e2 = st.columns([1, 3])
    edit_icon = col_e1.text_input("アイコン", value=current_theme.get("icon", "💬"), key="edit_icon")
    edit_name = col_e2.text_input("テーマ名", value=current_theme["name"], key="edit_name")
    if st.button("変更を保存", key="btn_update"):
        update_theme(current_theme_id, edit_name, edit_icon)

    st.divider()

    st.subheader("🗑️ テーマの削除")
    confirm_del_theme = st.checkbox("このテーマと全ログを削除する", key="chk_del_theme")
    if st.button("テーマ削除", key="btn_del_theme", type="primary", disabled=not confirm_del_theme):
        delete_theme(current_theme_id)

# 2. 会話ログ削除機能
with st.sidebar.expander("🗑️ 会話ログの管理・削除"):
    st.subheader("キーワード指定削除")
    kw_input = st.text_input("削除キーワード", key="kw_del")
    if st.button("キーワード削除を実行", key="btn_kw_del"):
        delete_messages_by_keyword(current_theme_id, kw_input)

    st.divider()

    st.subheader("全会話消去")
    confirm_del_all = st.checkbox("会話と要約記憶を全クリア", key="chk_del_all")
    if st.button("全会話クリア", key="btn_clear_all", type="primary", disabled=not confirm_del_all):
        clear_all_messages(current_theme_id)

# 3. 現在のテーマ記憶（要約）の確認
current_summary = get_theme_summary(current_theme_id)
with st.sidebar.expander("🧠 現在のテーマ記憶（要約）", expanded=False):
    if current_summary:
        st.info(current_summary)
    else:
        st.caption("※会話が30件を超えると自動でここに中期記憶（要約）が追加されます。")

# ==========================================
# 💬 メインチャット画面
# ==========================================

st.title(f"{current_theme.get('icon', '💬')} {current_theme['name']}")
st.caption("My AI Concierge — あなた専用の完全個室AI相談室")

# Supabaseからメッセージを取得
all_messages = get_messages(current_theme_id)

# 画面表示
for msg in all_messages:
    avatar_icon = "👤" if msg["role"] == "user" else "🤖"
    with st.chat_message(msg["role"], avatar=avatar_icon):
        st.write(msg["content"])

# ユーザー入力エリア
if user_input := st.chat_input("メッセージを入力してください..."):
    # 1. ユーザー入力の表示＆保存
    with st.chat_message("user", avatar="👤"):
        st.write(user_input)
    save_message(current_theme_id, "user", user_input)

    # メッセージリストを即時更新
    all_messages.append({"role": "user", "content": user_input})

    # 2. 要約のチェック＆自動更新
    updated_summary = check_and_summarize_history(current_theme_id, all_messages, current_summary)

    # 3. Gemini通信コンテキストの構築
    recent_messages = all_messages[-MAX_CONTEXT_MESSAGES:]

    # システム前提指示
    system_prompt = "あなたは優秀で親切なAIコンシェルジュです。"
    if updated_summary:
        system_prompt += f"\n\n【これまでの対話の背景・重要記憶要約】:\n{updated_summary}"

    contents_for_gemini = []
    # システムプロンプトを先頭に設定
    contents_for_gemini.append({"role": "user", "parts": [f"[前提情報]\n{system_prompt}"]})
    contents_for_gemini.append({"role": "model", "parts": ["承知いたしました。これまでの背景と要約を理解して対応します。"]})

    # 直近30件の会話を追加（ロール関係を正しく維持）
    for m in recent_messages:
        r = "user" if m["role"] == "user" else "model"
        contents_for_gemini.append({"role": r, "parts": [m["content"]]})

    # 4. Geminiからの回答取得＆保存
    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner("思考中..."):
            try:
                response = model.generate_content(contents_for_gemini)
                ai_reply = response.text
                st.write(ai_reply)

                # AI回答の保存
                save_message(current_theme_id, "model", ai_reply)
            except Exception as e:
                st.error(f"Gemini API 通信エラー: {e}")

    # 5. 画面更新
    st.rerun()
