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

# プリセット定義
STYLE_PRESETS = {
    "🤝 フランク＆対等（相棒）": "フレンドリーで親しみやすく、敬語を使わずに丁寧かつ対等なタメ口でフランクに対話してください。",
    "💼 丁寧＆親切（プロフェッショナル）": "礼儀正しく丁寧な敬語（です・ます調）で、親切かつ正確に回答してください。",
    "🧠 論理的＆簡潔（アドバイザー）": "結論から述べ、箇条書きを活用して無駄なく論理的・簡潔に回答してください。",
    "🌟 超ポジティブ＆熱血（応援団）": "常にポジティブで情熱的に、ユーザーの味方として全力で応援・肯定しながら対話してください。",
    "✍️ カスタム（自由記述）": ""
}

FIRST_PERSON_PRESETS = ["私", "僕", "俺", "自分"]

THEME_ICON_CANDIDATES = ["なし", "💬", "💡", "🚀", "🎮", "📚", "💼", "🎨", "🎵", "🍔", "✈️", "🏋️"]

# 安全な絵文字アバター定義
AVATAR_PRESETS_AI = {
    "🤖 ロボット": "🤖",
    "👾 レトロドット": "👾",
    "🦊 きつね": "🦊",
    "🦉 ふくろう": "🦉",
    "🔮 魔法の水晶": "🔮"
}

AVATAR_PRESETS_USER = {
    "💫 キラキラ星": "💫",
    "🧑‍💻 エンジニア": "🧑‍💻",
    "🐉 ドラゴン": "🐉",
    "⚡ サンダー": "⚡",
    "👑 キング": "👑"
}

# カラーテーマ定義（デフォルト：ライドモード）
COLOR_THEMES = {
    "☀ ライドモード（白）": {"bg": "#ffffff", "card_bg": "#f8fafc", "input_border": "#0288d1", "text": "#0f172a", "dropdown_text": "#0f172a", "scrollbar": "#94a3b8", "scrollbar_hover": "#64748b"},
    "🔷 ダークブルー（濃紺）": {"bg": "#101f33", "card_bg": "#1a2d47", "input_border": "#3b82f6", "text": "#ffffff", "dropdown_text": "#ffffff", "scrollbar": "#3b82f6", "scrollbar_hover": "#60a5fa"},
    "🌿 ナチュラルグリーン": {"bg": "#0f2e1b", "card_bg": "#194328", "input_border": "#10b981", "text": "#ffffff", "dropdown_text": "#ffffff", "scrollbar": "#10b981", "scrollbar_hover": "#34d399"},
    "💜 ディープパープル": {"bg": "#211132", "card_bg": "#321b4a", "input_border": "#a855f7", "text": "#ffffff", "dropdown_text": "#ffffff", "scrollbar": "#a855f7", "scrollbar_hover": "#c084fc"}
}

# ==========================================
# 🗄️ Supabase データベース操作関数
# ==========================================

def get_themes():
    try:
        res = supabase.table("themes").select("*").order("id", desc=False).execute()
        return res.data if res.data else []
    except Exception as e:
        st.error(f"テーマ取得エラー: {e}")
        return []

def add_theme(name: str, icon: str):
    icon_val = "" if icon == "なし" else icon
    supabase.table("themes").insert({"name": name, "icon": icon_val, "summary": ""}).execute()

def update_theme(theme_id: int, name: str, icon: str):
    icon_val = "" if icon == "なし" else icon
    supabase.table("themes").update({"name": name, "icon": icon_val}).eq("id", theme_id).execute()

def delete_theme(theme_id: int):
    supabase.table("messages").delete().eq("theme_id", theme_id).execute()
    supabase.table("themes").delete().eq("id", theme_id).execute()

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
    try:
        supabase.table("user_memories").delete().eq("id", memory_id).execute()
        return True
    except Exception as e:
        st.error(f"❌ 記憶削除エラー: {e}")
        return False

# ==========================================
# 🧠 記憶保存値の読み込み設定
# ==========================================
manual_memories = get_memories(theme_id=None, source="manual")

current_theme_color = "☀ ライドモード（白）"
current_concierge_name = "ハヤト"
current_user_name = "リュウ"
current_user_honorific = "さん"
current_first_person = "私"
current_style_preset = "🤝 フランク＆対等（相棒）"
current_user_instruction = STYLE_PRESETS["🤝 フランク＆対等（相棒）"]
current_ai_avatar = "🤖"
current_user_avatar = "💫"

for m in manual_memories:
    fact = m["fact"]
    if fact.startswith("カラーテーマ:"):
        current_theme_color = fact.replace("カラーテーマ:", "").strip()
    elif fact.startswith("AIの名前:"):
        current_concierge_name = fact.replace("AIの名前:", "").strip()
    elif fact.startswith("ユーザー名:"):
        current_user_name = fact.replace("ユーザー名:", "").strip()
    elif fact.startswith("ユーザー敬称:"):
        current_user_honorific = fact.replace("ユーザー敬称:", "").strip()
    elif fact.startswith("AI一人称:"):
        current_first_person = fact.replace("AI一人称:", "").strip()
    elif fact.startswith("口調プリセット:"):
        current_style_preset = fact.replace("口調プリセット:", "").strip()
    elif fact.startswith("応答方針:"):
        current_user_instruction = fact.replace("応答方針:", "").strip()
    elif fact.startswith("AIアバター:"):
        current_ai_avatar = fact.replace("AIアバター:", "").strip()
    elif fact.startswith("ユーザーアバター:"):
        current_user_avatar = fact.replace("ユーザーアバター:", "").strip()

theme_cfg = COLOR_THEMES.get(current_theme_color, COLOR_THEMES["☀ ライドモード（白）"])

# ★画面最適化CSS（スマホメニュー復活 & ピンポイントUI消去 & スクロールバー太化）
st.markdown(f"""
<style>
    /* 1. 全体レイアウト & 横揺れ防止 */
    html, body, .stApp, div[data-testid="stAppViewContainer"], section.main {{
        background-color: {theme_cfg["bg"]} !important;
        color: {theme_cfg["text"]} !important;
        max-width: 100vw !important;
        overflow-x: hidden !important;
        box-sizing: border-box !important;
    }}
    .main .block-container {{
        max-width: 100vw !important;
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
        padding-top: 1rem !important;
    }}
    p, span, div, h1, h2, h3, h4, h5, h6, label {{
        color: {theme_cfg["text"]} !important;
        word-break: break-word !important;
        overflow-wrap: anywhere !important;
    }}

    /* 2. ドロップダウン（選択肢）＆入力欄の文字色補正 */
    div[data-baseweb="select"] * {{
        color: {theme_cfg["dropdown_text"]} !important;
        background-color: {theme_cfg["card_bg"]} !important;
    }}
    div[role="listbox"] li {{
        color: {theme_cfg["dropdown_text"]} !important;
        background-color: {theme_cfg["card_bg"]} !important;
    }}

    /* 3. チャット入力枠スタイル */
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

    /* 4. ピンポイント非表示（スマホメニューボタンは維持し、余計なバッジ・ボタンだけ削除） */
    #MainMenu {{visibility: hidden !important;}}
    footer {{display: none !important;}}
    div[data-testid="stDecoration"] {{display: none !important;}}
    div[data-testid="stStatusWidget"] {{display: none !important;}}
    div[data-testid="stToolbar"] {{display: none !important;}}
    div[data-testid="stViewerBadge"] {{display: none !important;}}
    a[href*="streamlit.io"] {{display: none !important;}}
    button[title="Manage app"] {{display: none !important;}}
    .stActionButton {{display: none !important;}}

    /* 5. ↕️ 内部スクロールバーのカスタマイズ（メイン・サイドバー両方を太く） */
    ::-webkit-scrollbar, 
    div[data-testid="stAppViewContainer"] ::-webkit-scrollbar, 
    section[data-testid="stSidebar"] ::-webkit-scrollbar {{
        width: 14px !important;
        height: 14px !important;
    }}
    ::-webkit-scrollbar-track, 
    div[data-testid="stAppViewContainer"] ::-webkit-scrollbar-track, 
    section[data-testid="stSidebar"] ::-webkit-scrollbar-track {{
        background: {theme_cfg["bg"]} !important;
    }}
    ::-webkit-scrollbar-thumb, 
    div[data-testid="stAppViewContainer"] ::-webkit-scrollbar-thumb, 
    section[data-testid="stSidebar"] ::-webkit-scrollbar-thumb {{
        background: {theme_cfg["scrollbar"]} !important;
        border-radius: 8px !important;
        border: 3px solid {theme_cfg["bg"]} !important;
    }}
    ::-webkit-scrollbar-thumb:hover, 
    div[data-testid="stAppViewContainer"] ::-webkit-scrollbar-thumb:hover, 
    section[data-testid="stSidebar"] ::-webkit-scrollbar-thumb:hover {{
        background: {theme_cfg["scrollbar_hover"]} !important;
    }}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 🧠 AI要約＆自動抽出ロジック（高速化対応）
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
        print(f"要約更新エラー: {e}")
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
# 🖥️ サイドバー & 画面ナビゲーション
# ==========================================

st.sidebar.title("🤖 My AI Concierge")

themes = get_themes()
if not themes:
    add_theme("メインテーマ", "💬")
    themes = get_themes()

theme_map = {f"{t['icon'] + ' ' if t['icon'] else ''}{t['name']}": t for t in themes}
selected_theme_label = st.sidebar.selectbox("テーマ選択:", list(theme_map.keys()))
current_theme = theme_map[selected_theme_label]
current_theme_id = current_theme["id"]

st.sidebar.divider()

app_mode = st.sidebar.radio("機能メニュー", ["💬 チャット", "📁 テーマ管理", "⚙️ ユーザー設定"], index=0)

# ==========================================
# 📁 画面1: テーマ管理画面
# ==========================================
if app_mode == "📁 テーマ管理":
    st.title("📁 テーマの作成・編集・削除")
    st.caption("会話のテーマを整理・カスタマイズできます。")

    st.subheader("➕ 新しいテーマを追加")
    with st.form("add_theme_form"):
        new_name = st.text_input("テーマ名")
        new_icon = st.selectbox("アイコン（「なし」も可能）", THEME_ICON_CANDIDATES)
        if st.form_submit_button("テーマを作成"):
            if new_name:
                add_theme(new_name, new_icon)
                st.success(f"テーマ「{new_name}」を作成しました！")
                st.rerun()

    st.divider()

    st.subheader("✏️ 既存テーマの編集・削除")
    for t in themes:
        with st.expander(f"{t['icon'] + ' ' if t['icon'] else ''}{t['name']}", expanded=False):
            edit_name = st.text_input("テーマ名変更", value=t['name'], key=f"name_{t['id']}")
            current_icon_idx = THEME_ICON_CANDIDATES.index(t['icon']) if t['icon'] in THEME_ICON_CANDIDATES else 0
            edit_icon = st.selectbox("アイコン変更", THEME_ICON_CANDIDATES, index=current_icon_idx, key=f"icon_{t['id']}")

            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("更新", key=f"update_{t['id']}"):
                    update_theme(t['id'], edit_name, edit_icon)
                    st.toast("テーマを更新しました！")
                    st.rerun()
            with col2:
                if st.button("削除", key=f"del_{t['id']}"):
                    if len(themes) <= 1:
                        st.error("最後の1つのテーマは削除できません。")
                    else:
                        delete_theme(t['id'])
                        st.toast("テーマを削除しました。")
                        st.rerun()

# ==========================================
# ⚙️ 画面2: ユーザー設定画面
# ==========================================
elif app_mode == "⚙️ ユーザー設定":
    st.title("⚙️ ユーザー設定 & 記憶管理")
    st.caption("AIの振る舞い・外観デザイン・全テーマ共通の記憶を管理します。")

    st.subheader("🎨 アプリの外観＆カラー")
    with st.form("color_form"):
        selected_color = st.selectbox("カラーテーマ（背景＆メッセージ枠）", list(COLOR_THEMES.keys()), index=list(COLOR_THEMES.keys()).index(current_theme_color) if current_theme_color in COLOR_THEMES else 0)
        if st.form_submit_button("カラー設定を保存"):
            for m in manual_memories:
                if m["fact"].startswith("カラーテーマ:"):
                    delete_memory(m["id"])
            save_memory(f"カラーテーマ: {selected_color}", theme_id=None, category="プロフィール", source="manual")
            st.success("カラーテーマを保存しました！")
            st.rerun()

    st.divider()

    st.subheader("👤 AIコンシェルジュ & プロフィール設定")

    honorific_options = ["さん", "様", "君", "ちゃん", "（呼び捨て/なし）"]
    default_honorific_idx = honorific_options.index(current_user_honorific) if current_user_honorific in honorific_options else 0

    preset_keys = list(STYLE_PRESETS.keys())
    default_preset_idx = preset_keys.index(current_style_preset) if current_style_preset in preset_keys else 0

    default_fp_idx = FIRST_PERSON_PRESETS.index(current_first_person) if current_first_person in FIRST_PERSON_PRESETS else 0

    with st.form("profile_form"):
        new_concierge_name = st.text_input("AIコンシェルジュの名前", value=current_concierge_name)
        new_user_name = st.text_input("あなたのお名前 / ニックネーム", value=current_user_name)
        new_user_honorific = st.selectbox("AIからの呼び方（敬称）", honorific_options, index=default_honorific_idx)
        new_first_person = st.selectbox("AIの一人称", FIRST_PERSON_PRESETS, index=default_fp_idx)

        st.markdown("**🖼️ アバター（アイコン）設定**")
        col_a, col_u = st.columns(2)
        with col_a:
            ai_avatar_sel = st.selectbox("AIのアバター", list(AVATAR_PRESETS_AI.keys()))
            ai_avatar_val = AVATAR_PRESETS_AI[ai_avatar_sel]
        with col_u:
            user_avatar_sel = st.selectbox("あなたのアバター", list(AVATAR_PRESETS_USER.keys()))
            user_avatar_val = AVATAR_PRESETS_USER[user_avatar_sel]

        selected_preset = st.selectbox("口調・振る舞いのスタイル", preset_keys, index=default_preset_idx)
        initial_instruction = STYLE_PRESETS[selected_preset] if selected_preset != "✍️ カスタム（自由記述）" else current_user_instruction
        new_instruction = st.text_area("具体的な口調・振る舞いの指示", value=initial_instruction)

        if st.form_submit_button("基本設定を保存"):
            for m in manual_memories:
                if any(m["fact"].startswith(p) for p in ["AIの名前:", "ユーザー名:", "ユーザー敬称:", "AI一人称:", "口調プリセット:", "応答方針:", "AIアバター:", "ユーザーアバター:"]):
                    delete_memory(m["id"])

            save_memory(f"AIの名前: {new_concierge_name}", source="manual")
            save_memory(f"ユーザー名: {new_user_name}", source="manual")
            save_memory(f"ユーザー敬称: {new_user_honorific}", source="manual")
            save_memory(f"AI一人称: {new_first_person}", source="manual")
            save_memory(f"口調プリセット: {selected_preset}", source="manual")
            save_memory(f"応答方針: {new_instruction}", source="manual")
            save_memory(f"AIアバター: {ai_avatar_val}", source="manual")
            save_memory(f"ユーザーアバター: {user_avatar_val}", source="manual")

            st.success("基本設定を更新しました！")
            st.rerun()

    st.divider()

    st.subheader("🧠 自動学習された長期記憶")
    auto_memories = get_memories(theme_id=None, source="auto")
    if auto_memories:
        for mem in auto_memories:
            st.info(f"📌 {mem['fact']}")
            if st.button("削除", key=f"del_auto_{mem['id']}"):
                delete_memory(mem["id"])
                st.toast("記憶を削除しました。")
                st.rerun()
    else:
        st.caption("自動抽出された記憶はまだありません。")

# ==========================================
# 💬 画面3: メインチャット画面
# ==========================================
else:
    all_common_memories = get_memories(theme_id=None)
    manual_facts = []
    auto_facts = []

    for m in all_common_memories:
        if not any(m["fact"].startswith(p) for p in ["AIの名前:", "ユーザー名:", "ユーザー敬称:", "AI一人称:", "口調プリセット:", "応答方針:", "AIアバター:", "ユーザーアバター:", "カラーテーマ:"]):
            if m["source"] == "manual":
                manual_facts.append(m["fact"])
            else:
                auto_facts.append(m["fact"])

    display_user_name = f"{current_user_name}{current_user_honorific}" if current_user_honorific != "（呼び捨て/なし）" else current_user_name

    theme_title = f"{current_theme['icon'] + ' ' if current_theme['icon'] else ''}{current_theme['name']}"
    st.title(theme_title)
    st.caption(f"担当コンシェルジュ: **{current_concierge_name}** | モデル: **gemini-3.6-flash**")

    current_summary = get_theme_summary(current_theme_id)
    with st.sidebar.expander("🧠 現在のテーマ記憶（要約）", expanded=False):
        if current_summary:
            st.info(current_summary)
        else:
            st.caption("会話が30件を超えると自動要約されます。")

    all_messages = get_messages(current_theme_id)

    # 過去ログ描画
    for msg in all_messages:
        role_label = display_user_name if msg["role"] == "user" else current_concierge_name
        avatar_img = current_user_avatar if msg["role"] == "user" else current_ai_avatar

        with st.chat_message(msg["role"], avatar=avatar_img):
            st.write(f"**{role_label}**: {msg['content']}")

    # 高速チャット送信処理
    if user_input := st.chat_input(f"{current_concierge_name}にメッセージを送信..."):
        # ① ユーザーのメッセージを即時表示＆保存
        with st.chat_message("user", avatar=current_user_avatar):
            st.write(f"**{display_user_name}**: {user_input}")
        save_message(current_theme_id, "user", user_input)
        all_messages.append({"role": "user", "content": user_input})

        recent_messages = all_messages[-MAX_CONTEXT_MESSAGES:]

        system_instruction = f"""
        あなたの名前は「{current_concierge_name}」です。優秀で親切なAIコンシェルジュとして行動してください。
        対話相手のユーザー名は「{display_user_name}」です。
        あなたの一人称は「{current_first_person}」を使用してください。

        【🗣️ 応答スタイル指示】
        {current_user_instruction}

        【🌐 あなたが知っているユーザーの全般的な記憶（全テーマ共通・長期記憶）】
        ・設定プロフィール: {', '.join(manual_facts) if manual_facts else '特になし'}
        ・会話から覚えた記憶: {', '.join(auto_facts) if auto_facts else '特になし'}

        【📜 このテーマの流れ（中期記憶・要約）】
        {current_summary if current_summary else '（まだ要約はありません）'}
        """

        contents_for_gemini = [
            {"role": "user", "parts": [f"[システム指示・前提背景]\n{system_instruction}"]},
            {"role": "model", "parts": [f"了解、{display_user_name}！{current_first_person}がしっかりサポートするよ！"]}
        ]

        for m in recent_messages:
            role = "user" if m["role"] == "user" else "model"
            contents_for_gemini.append({"role": role, "parts": [m["content"]]})

        # ② 即時「思考中...」表示 & 返答生成
        with st.chat_message("assistant", avatar=current_ai_avatar):
            with st.spinner(f"🤖 {current_concierge_name}が考え中..."):
                try:
                    response = model.generate_content(contents_for_gemini)
                    ai_reply = response.text
                    st.write(f"**{current_concierge_name}**: {ai_reply}")
                    save_message(current_theme_id, "assistant", ai_reply)
                except Exception as e:
                    st.error(f"Gemini API エラー: {e}")

        # ③ 非同期風に裏で要約更新・記憶抽出を実行
        check_and_summarize_history(current_theme_id, all_messages, current_summary)
        extract_and_save_long_term_memory(user_input, current_theme_id)

        st.rerun()
