import streamlit as st
from supabase import create_client

# --- Supabase接続初期化 ---
supabase_url = st.secrets["SUPABASE_URL"]
supabase_key = st.secrets["SUPABASE_KEY"]
supabase = create_client(supabase_url, supabase_key)

USER_ID = "default_user"

# --- DB操作関数（エラー詳細表示版） ---
def get_themes():
    try:
        res = supabase.table("themes").select("*").eq("user_id", USER_ID).order("created_at").execute()
        return res.data
    except Exception as e:
        # エラーの本当の中身を画面に表示します
        st.error(f"🚨 Supabase接続エラーの詳細:\n{e}")
        return []

def add_theme(name, icon):
    if name:
        supabase.table("themes").insert({"user_id": USER_ID, "name": name, "icon": icon}).execute()
        st.success(f"テーマ「{icon} {name}」を作成しました！")
        st.rerun()

def update_theme(theme_id, new_name, new_icon):
    if new_name:
        supabase.table("themes").update({"name": new_name, "icon": new_icon}).eq("id", theme_id).execute()
        st.success("テーマ情報を更新しました！")
        st.rerun()

def delete_theme(theme_id):
    supabase.table("messages").delete().eq("theme_id", theme_id).execute()
    supabase.table("themes").delete().eq("id", theme_id).execute()
    st.warning("テーマと会話ログを削除しました。")
    st.rerun()


# --- サイドバーUI ---
st.sidebar.title("My AI Concierge")

themes = get_themes()

# 表示用のラベルを作成（例: "🏠 不動産"）
if themes:
    theme_options = {f"{t['icon']} {t['name']}": t for t in themes}
    selected_label = st.sidebar.selectbox("テーマを選択してください:", list(theme_options.keys()))
    current_theme = theme_options[selected_label]
else:
    current_theme = None
    st.sidebar.info("テーマを作成してください")

st.sidebar.divider()

# --- テーマ管理（追加・変更・削除） ---
with st.sidebar.expander("⚙️ テーマの管理（追加・編集・削除）"):

    # ① 新規テーマ作成
    st.subheader("＋ 新しいテーマを作成")
    col1, col2 = st.columns([1, 3])
    with col1:
        new_icon = st.text_input("アイコン", value="💬", key="new_icon")
    with col2:
        new_name = st.text_input("テーマ名", key="new_name")

    if st.button("作成", key="btn_add"):
        add_theme(new_name, new_icon)

    st.divider()

    # ② 選択中テーマの編集（名前・アイコン変更）
    if current_theme:
        st.subheader("✏️ テーマの編集")
        col_edit1, col_edit2 = st.columns([1, 3])
        with col_edit1:
            edit_icon = st.text_input("アイコン", value=current_theme.get("icon", "💬"), key="edit_icon")
        with col_edit2:
            edit_name = st.text_input("テーマ名", value=current_theme["name"], key="edit_name")

        if st.button("変更を保存", key="btn_update"):
            update_theme(current_theme["id"], edit_name, edit_icon)

        st.divider()

        # ③ 削除
        st.subheader("🗑️ テーマの削除")
        confirm_delete = st.checkbox("このテーマと会話ログを全削除する", key="chk_del")
        if st.button("テーマを削除", key="btn_del", type="primary", disabled=not confirm_delete):
            delete_theme(current_theme["id"])
