import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client

# ==========================================
# ⚙️ 設定・初期化
# ==========================================
st.set_page_config(page_title="My AI Concierge", page_icon="🤖", layout="wide")

MAX_CONTEXT_MESSAGES = 30  # 直近30件を保持

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

@st.cache_resource
def init_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# ★指定モデル: gemini-3.6-flash
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3.6-flash")

# ==========================================
# 🗄️ Supabase データベース操作関数
# ==========================================

def get_themes():
    res = supabase.table("themes").select("*").order("id", desc=False).execute()
    return res.data if res.data else []

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
    data = {
        "user_id": "default_user",
        "theme_id": theme_id,
        "role": role,
        "content": content
    }
    supabase.table("messages").insert(data).execute()

# --- 長期記憶 (user_memories) 関連 ---
def get_memories(theme_id=None, source=None):
    try:
        query = supabase.table("user_memories").select("*")
        if theme_id is None:
            query = query.filter("theme_id", "is", "null")
        else:
            query = query.eq("theme_id", theme_id)

        if source:
            query = query.eq("source", source)

        res = query.order("id", desc=False).execute()
        return res.data if res.data else []
    except Exception as e:
        print(f"記憶取得エラー: {e}")
        return []

def save_memory(fact: str, theme_id=None, category="基本情報", source="manual") -> bool:
    """記憶の保存（成功判定付き）"""
    try:
        data = {
            "user_id": "default_user",
            "category": category,
            "fact": fact,
            "source": source
        }
        if theme_id is not None:
            data["theme_id"] = theme_id

        supabase.table("user_memories").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"❌ 記憶保存エラー: {e}")
        return False

def delete_memory(memory_id: int) -> bool:
    """記憶の削除（成功判定付き）"""
    try:
        supabase.table("user_memories").delete().eq("id", memory_id).execute()
        return True
    except Exception as e:
        st.error(f"❌ 記憶削除エラー: {e}")
        return False

# ==========================================
# 🧠 記憶ロジック（自動要約 & 長期記憶の自動抽出）
# ==========================================

def check_and_summarize_history(theme_id: int, all_messages: list, current_summary: str) -> str:
    if len(all_messages) <= MAX_CONTEXT_MESSAGES:
        return current_summary

    old_messages = all_messages[:-MAX_CONTEXT_MESSAGES]
    formatted_old_text = "\n".join([f"{m['role']}: {m['content']}" for m in old_messages])

    prompt = f"""
    以下はこれまでの要約と溢れた会話ログです。統合した新しい要約を日本語300字程度で作成してください。
    【既存要約】: {current_summary if current_summary else "なし"}
    【過去ログ】: {formatted_old_text}
    """
    try:
        response = model.generate_content(prompt)
        new_summary = response.text.strip()
        update_theme_summary(theme_id, new_summary)
        return new_summary
    except Exception as e:
        st.error(f"要約更新エラー: {e}")
        return current_summary

def extract_and_save_long_term_memory(user_text: str, theme_id: int):
    prompt = f"""
    以下のユーザーの発言から、今後永久に保持すべき「ユーザーの属性・嗜好・重要データ」が含まれているか判定してください。
    含まれている場合は、簡潔な事実（1〜2文）として抽出してください。
    新情報がない場合は「NONE」とだけ返してください。

    ユーザーの発言: "{user_text}"
    """
    try:
        res = model.generate_content(prompt)
        text = res.text.strip()
        if text and text != "NONE" and "NONE" not in text:
            save_memory(fact=text, theme_id=None, category="AI自動抽出", source="auto")
    except Exception as e:
        print(f"長期記憶抽出エラー: {e}")

# ==========================================
# 🖥️ サイドバー & 画面切替
# ==========================================

st.sidebar.title("🤖 My AI Concierge")

app_mode = st.sidebar.radio("メニュー", ["💬 チャット", "⚙️ ユーザー設定"])

themes = get_themes()
if not themes:
    st.sidebar.warning("テーマが存在しません。")
    st.stop()

theme_options = {f"{t['icon']} {t['name']}": t['id'] for t in themes}
selected_theme_label = st.sidebar.selectbox("テーマ選択:", list(theme_options.keys()))
current_theme_id = theme_options[selected_theme_label]

# ==========================================
# ⚙️ 画面1: ユーザー設定画面
# ==========================================
if app_mode == "⚙️ ユーザー設定":
    st.title("⚙️ ユーザー設定 & 記憶管理")
    st.caption("AIコンシェルジュの設定や、全テーマ共通の長期記憶（プロフィール・自動学習）を管理します。")

    st.subheader("👤 基本設定")
    manual_memories = get_memories(theme_id=None, source="manual")

    current_concierge_name = "ハヤト"
    current_user_name = "ユーザー"
    current_user_instruction = "丁寧かつ簡潔に回答してください。"

    for m in manual_memories:
        if m["fact"].startswith("AIの名前:"):
            current_concierge_name = m["fact"].replace("AIの名前:", "").strip()
        elif m["fact"].startswith("ユーザー名:"):
            current_user_name = m["fact"].replace("ユーザー名:", "").strip()
        elif m["fact"].startswith("応答方針:"):
            current_user_instruction = m["fact"].replace("応答方針:", "").strip()

    with st.form("profile_form"):
        new_concierge_name = st.text_input("AIコンシェルジュの名前", value=current_concierge_name)
        new_user_name = st.text_input("あなたのお名前 / ニックネーム", value=current_user_name)
        new_instruction = st.text_area("AIへの口調・振る舞いの指示", value=current_user_instruction)

        submitted = st.form_submit_button("基本設定を保存")
        if submitted:
            success = True
            # 古い設定の削除
            for m in manual_memories:
                if any(m["fact"].startswith(prefix) for prefix in ["AIの名前:", "ユーザー名:", "応答方針:"]):
                    if not delete_memory(m["id"]):
                        success = False

            # 新しい設定の保存
            r1 = save_memory(f"AIの名前: {new_concierge_name}", theme_id=None, category="プロフィール", source="manual")
            r2 = save_memory(f"ユーザー名: {new_user_name}", theme_id=None, category="プロフィール", source="manual")
            r3 = save_memory(f"応答方針: {new_instruction}", theme_id=None, category="プロフィール", source="manual")

            if success and r1 and r2 and r3:
                st.success("基本設定を更新しました！")
                st.rerun()

    st.divider()

    st.subheader("🧠 AIが自動で学習した記憶（全テーマ共通）")
    st.caption("ハヤトが会話の中から自動的に覚えたあなたの属性や重要ファクトです。不要なものは削除できます。")

    auto_memories = get_memories(theme_id=None, source="auto")
    if auto_memories:
        for mem in auto_memories:
            col1, col2 = st.columns([5, 1])
            with col1:
                st.info(f"📌 {mem['fact']}")
            with col2:
                if st.button("削除", key=f"del_auto_{mem['id']}"):
                    if delete_memory(mem["id"]):
                        st.toast("記憶を削除しました。")
                        st.rerun()
    else:
        st.caption("まだ自動抽出された記憶はありません。会話を重ねるとここに自動蓄積されます。")

    st.divider()

    st.subheader("📝 手動で記憶を追加（全テーマ共通）")
    with st.form("add_manual_memory"):
        new_fact = st.text_input("ハヤトに常に覚えておいてほしい事実や前提")
        add_btn = st.form_submit_button("記憶を追加")
        if add_btn and new_fact:
            if save_memory(fact=new_fact, theme_id=None, category="手動登録", source="manual"):
                st.success("長期記憶を追加しました！")
                st.rerun()

# ==========================================
# 💬 画面2: メインチャット画面
# ==========================================
else:
    all_common_memories = get_memories(theme_id=None)
    concierge_name = "ハヤト"
    user_name = "ユーザー"

    manual_facts = []
    auto_facts = []

    for m in all_common_memories:
        if m["fact"].startswith("AIの名前:"):
            concierge_name = m["fact"].replace("AIの名前:", "").strip()
        elif m["fact"].startswith("ユーザー名:"):
            user_name = m["fact"].replace("ユーザー名:", "").strip()
        else:
            if m["source"] == "manual":
                manual_facts.append(m["fact"])
            else:
                auto_facts.append(m["fact"])

    st.title(f"{selected_theme_label}")
    st.caption(f"担当AIコンシェルジュ: **{concierge_name}** | 使用モデル: **gemini-3.6-flash**")

    current_summary = get_theme_summary(current_theme_id)
    with st.sidebar.expander("🧠 現在のテーマ記憶（要約）", expanded=False):
        if current_summary:
            st.info(current_summary)
        else:
            st.caption("会話が30件を超えると自動要約されます。")

    all_messages = get_messages(current_theme_id)

    for msg in all_messages:
        role_label = user_name if msg["role"] == "user" else concierge_name
        with st.chat_message(msg["role"]):
            st.write(f"**{role_label}**: {msg['content']}")

    if user_input := st.chat_input(f"{concierge_name}にメッセージを送信..."):
        with st.chat_message("user"):
            st.write(f"**{user_name}**: {user_input}")
        save_message(current_theme_id, "user", user_input)
        all_messages.append({"role": "user", "content": user_input})

        updated_summary = check_and_summarize_history(current_theme_id, all_messages, current_summary)
        extract_and_save_long_term_memory(user_input, current_theme_id)

        recent_messages = all_messages[-MAX_CONTEXT_MESSAGES:]

        system_instruction = f"""
        あなたの名前は「{concierge_name}」です。優秀で親切なAIコンシェルジュとして行動してください。
        対話相手のユーザー名は「{user_name}」です。

        【🌐 あなたが知っているユーザーの全般的な記憶（全テーマ共通・長期記憶）】
        ・設定プロフィール: {', '.join(manual_facts) if manual_facts else '特になし'}
        ・会話から覚えた記憶: {', '.join(auto_facts) if auto_facts else '特になし'}

        【📜 このテーマの流れ（中期記憶・要約）】
        {updated_summary if updated_summary else '（まだ要約はありません）'}
        """

        contents_for_gemini = [
            {"role": "user", "parts": [f"[システム指示・前提背景]\n{system_instruction}"]},
            {"role": "model", "parts": [f"承知いたしました。私、{concierge_name}が前提記憶を理解した上で対応いたします。"]}
        ]

        for m in recent_messages:
            role = "user" if m["role"] == "user" else "model"
            contents_for_gemini.append({"role": role, "parts": [m["content"]]})

        with st.chat_message("assistant"):
            with st.spinner(f"{concierge_name}が考え中..."):
                try:
                    response = model.generate_content(contents_for_gemini)
                    ai_reply = response.text
                    st.write(f"**{concierge_name}**: {ai_reply}")
                    save_message(current_theme_id, "assistant", ai_reply)
                except Exception as e:
                    st.error(f"Gemini API エラー: {e}")

        st.rerun()
