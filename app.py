import streamlit as st
from supabase import create_client
import google.generativeai as genai

# --- ページ設定 ---
st.set_page_config(page_title="My AI Concierge", page_icon="🤖", layout="wide")

# --- Secrets（設定情報）の読み込み ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

# Supabase & Gemini 初期化
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

USER_ID = "default_user"

# --- DB操作関数 ---
def get_themes():
    try:
        res = supabase.table("themes").select("*").eq("user_id", USER_ID).order("created_at").execute()
        # テーマが1つも無ければ初期テーマを作成
        if not res.data:
            supabase.table("themes").insert({"user_id": USER_ID, "name": "メイン", "icon": "🏠"}).execute()
            res = supabase.table("themes").select("*").eq("user_id", USER_ID).order("created_at").execute()
        return res.data
    except Exception as e:
        st.error(f"テーマ取得エラー: {e}")
        return []

def add_theme(name, icon):
    if name:
        supabase.table("themes").insert({"user_id": USER_ID, "name": name, "icon": icon}).execute()
        st.rerun()

def update_theme(theme_id, new_name, new_icon):
    if new_name:
        supabase.table("themes").update({"name": new_name, "icon": new_icon}).eq("id", theme_id).execute()
        st.rerun()

def delete_theme(theme_id):
    supabase.table("messages").delete().eq("theme_id", theme_id).execute()
    supabase.table("themes").delete().eq("id", theme_id).execute()
    st.rerun()

def get_messages(theme_id):
    try:
        res = supabase.table("messages").select("*").eq("user_id", USER_ID).eq("theme_id", theme_id).order("created_at").execute()
        return res.data
    except Exception as e:
        st.error(f"ログ取得エラー: {e}")
        return []

def save_message(theme_id, role, content):
    supabase.table("messages").insert({
        "user_id": USER_ID,
        "theme_id": theme_id,
        "role": role,
        "content": content
    }).execute()

def delete_messages_by_keyword(theme_id, keyword):
    if keyword:
        # キーワードを含むメッセージを取得して削除
        res = supabase.table("messages").select("id").eq("user_id", USER_ID).eq("theme_id", theme_id).ilike("content", f"%{keyword}%").execute()
        ids_to_delete = [m["id"] for m in res.data]
        if ids_to_delete:
            supabase.table("messages").delete().in_("id", ids_to_delete).execute()
            st.success(f"キーワード「{keyword}」を含む会話を削除しました。")
            st.rerun()
        else:
            st.info("該当するメッセージが見つかりませんでした。")

def clear_all_messages(theme_id):
    supabase.table("messages").delete().eq("user_id", USER_ID).eq("theme_id", theme_id).execute()
    st.success("このテーマの会話履歴を全削除しました。")
    st.rerun()


# --- サイドバー表示 ---
st.sidebar.title("My AI Concierge")

themes = get_themes()
current_theme = None

if themes:
    theme_options = {f"{t['icon']} {t['name']}": t for t in themes}
    selected_label = st.sidebar.selectbox("テーマを選択してください:", list(theme_options.keys()))
    current_theme = theme_options[selected_label]

st.sidebar.divider()

# テーマ管理機能
if current_theme:
    with st.sidebar.expander("⚙️ テーマの管理（追加・編集・削除）"):
        st.subheader("＋ 新しいテーマ")
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
            update_theme(current_theme["id"], edit_name, edit_icon)

        st.divider()

        st.subheader("🗑️ テーマの削除")
        confirm_del_theme = st.checkbox("このテーマと全ログを削除する", key="chk_del_theme")
        if st.button("テーマ削除", key="btn_del_theme", type="primary", disabled=not confirm_del_theme):
            delete_theme(current_theme["id"])

    # データ管理・削除機能
    with st.sidebar.expander("🗑️ 会話ログの管理・削除"):
        st.subheader("キーワード削除")
        kw_input = st.text_input("削除したいキーワード", key="kw_del")
        if st.button("部分削除を実行", key="btn_kw_del"):
            delete_messages_by_keyword(current_theme["id"], kw_input)

        st.divider()

        st.subheader("全会話削除")
        confirm_del_all = st.checkbox("このテーマの会話を全消去", key="chk_del_all")
        if st.button("全会話クリア", key="btn_clear_all", type="primary", disabled=not confirm_del_all):
            clear_all_messages(current_theme["id"])


# --- メインチャット画面 ---
if current_theme:
    st.title(f"{current_theme['icon']} {current_theme['name']}")
    st.caption("My AI Concierge — あなた専用の完全個室AI相談室")

    # 過去ログ読み込み
    messages = get_messages(current_theme["id"])

    # チャット履歴表示
    for msg in messages:
        role_icon = "👤" if msg["role"] == "user" else "🤖"
        with st.chat_message(msg["role"], avatar=role_icon):
            st.markdown(msg["content"])

    # ユーザー入力
    if prompt := st.chat_input("ここに相談内容を入力してください..."):
        # 1. ユーザー発言を画面表示＆DB保存
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)
        save_message(current_theme["id"], "user", prompt)

        # 2. 直近30件の文脈を作成してGeminiへ送信（コスト＆レスポンス最適化）
        history_msgs = messages[-30:] if len(messages) > 30 else messages
        contents = []
        for m in history_msgs:
            contents.append({"role": m["role"], "parts": [m["content"]]})
        contents.append({"role": "user", "parts": [prompt]})

        # 3. AIの回答取得＆画面表示＆DB保存
        with st.chat_message("assistant", avatar="🤖"):
            with st.spinner("AIが思考中..."):
                try:
                    response = model.generate_content(contents)
                    ai_reply = response.text
                    st.markdown(ai_reply)
                    save_message(current_theme["id"], "model", ai_reply)
                except Exception as e:
                    st.error(f"AI通信エラー: {e}")
