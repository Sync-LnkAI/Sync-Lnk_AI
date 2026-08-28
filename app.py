import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client
import re
import time

# ==========================================
# ⚙️ 設定・初期化
# ==========================================
st.set_page_config(page_title="My AI Concierge", page_icon="🤖", layout="wide")

MAX_CONTEXT_MESSAGES = 5  # 直近5件を保持

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY_PRO"]

@st.cache_resource
def init_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

CURRENT_USER_ID = "default_user"

genai.configure(api_key=GEMINI_API_KEY)
# ==========================================
# Geminiモデル設定
# ==========================================

CHAT_MODEL_NAME = "gemini-3.6-flash"
MEMORY_MODEL_NAME = "gemini-3.5-flash-lite"
SUMMARY_MODEL_NAME = "gemini-3.5-flash-lite"

# 通常チャット用
chat_model = genai.GenerativeModel(
    CHAT_MODEL_NAME
)

# 長期記憶抽出用
memory_model = genai.GenerativeModel(
    MEMORY_MODEL_NAME
)

# テーマ要約用
summary_model = genai.GenerativeModel(
    SUMMARY_MODEL_NAME
)

# Gemini 3.6 Flash
CHAT_INPUT_PRICE_PER_MILLION = 1.50
CHAT_OUTPUT_PRICE_PER_MILLION = 7.50

# Gemini 3.5 Flash-Lite
LITE_INPUT_PRICE_PER_MILLION = 0.30
LITE_OUTPUT_PRICE_PER_MILLION = 2.50

USD_TO_JPY = 150

# --- セッション状態の初期化 ---
if "last_in_tokens" not in st.session_state:
    st.session_state.last_in_tokens = 0
if "last_out_tokens" not in st.session_state:
    st.session_state.last_out_tokens = 0
if "total_in_tokens" not in st.session_state:
    st.session_state.total_in_tokens = 0
if "total_out_tokens" not in st.session_state:
    st.session_state.total_out_tokens = 0

# チャット
if "chat_in_tokens" not in st.session_state:
    st.session_state.chat_in_tokens = 0
if "chat_out_tokens" not in st.session_state:
    st.session_state.chat_out_tokens = 0
# 記憶抽出
if "memory_in_tokens" not in st.session_state:
    st.session_state.memory_in_tokens = 0
if "memory_out_tokens" not in st.session_state:
    st.session_state.memory_out_tokens = 0
# 要約
if "summary_in_tokens" not in st.session_state:
    st.session_state.summary_in_tokens = 0
if "summary_out_tokens" not in st.session_state:
    st.session_state.summary_out_tokens = 0

if "debug_logs" not in st.session_state:
    st.session_state.error_logs = []
if "conversation_count" not in st.session_state:
    st.session_state.conversation_count = 0

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
    "☀ ライドモード（白）": {"bg": "#ffffff", "card_bg": "#f8fafc", "input_border": "#0288d1", "text": "#0f172a", "dropdown_bg": "#ffffff", "dropdown_text": "#0f172a"},
    "🔷 ダークブルー（濃紺）": {"bg": "#101f33", "card_bg": "#1a2d47", "input_border": "#3b82f6", "text": "#ffffff", "dropdown_bg": "#1a2d47", "dropdown_text": "#ffffff"},
    "🌿 ナチュラルグリーン": {"bg": "#0f2e1b", "card_bg": "#194328", "input_border": "#10b981", "text": "#ffffff", "dropdown_bg": "#194328", "dropdown_text": "#ffffff"},
    "💜 ディープパープル": {"bg": "#211132", "card_bg": "#321b4a", "input_border": "#a855f7", "text": "#ffffff", "dropdown_bg": "#321b4a", "dropdown_text": "#ffffff"}
}

# 画面上の不要な  記号を除去する関数
def clean_bold_markdown(text: str) -> str:
    if not text:
        return text
    return text.replace("**", "")

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
    # user_id を追加してエラーを防止
    supabase.table("themes").insert({"user_id": "default_user", "name": name, "icon": icon_val}).execute()

def update_theme(theme_id: int, name: str, icon: str):
    icon_val = "" if icon == "なし" else icon
    supabase.table("themes").update({"name": name, "icon": icon_val}).eq("id", theme_id).execute()

def delete_theme(theme_id: int):
    # IDが1（メインテーマ）の場合は削除をブロック！
    if theme_id == 1:
        st.warning("「メインテーマ」は削除できません！")
        return

    supabase.table("messages").delete().eq("theme_id", theme_id).execute()
    supabase.table("themes").delete().eq("id", theme_id).execute()

def get_theme_summary(theme_id: int) -> str:
    try:
        res = supabase.table("themes").select("summary").eq("id", theme_id).execute()
        if res.data and res.data[0].get("summary"):
            return res.data[0]["summary"]
    except Exception:
        pass
    return ""

def update_theme_summary(theme_id: int, new_summary: str):
    try:
        supabase.table("themes").update({"summary": new_summary}).eq("id", theme_id).execute()
    except Exception as e:
        print(f"要約更新エラー: {e}")

def get_messages(theme_id: int):
    try:
        res = (
            supabase
            .table("messages")
            .select("*")
            .eq("theme_id", theme_id)
            .order("created_at", desc=False)
            .execute()
        )

        return res.data if res.data else []

    except Exception as e:
        st.error(f"メッセージ取得エラー: {e}")
        return []

def save_message(
    theme_id: int,
    role: str,
    content: str
) -> bool:
    try:
        embedding_data = get_embedding(
            content,
            task_type="RETRIEVAL_DOCUMENT"
        )

        data = {
            "user_id": CURRENT_USER_ID,
            "theme_id": theme_id,
            "role": role,
            "content": content,
            "embedding": embedding_data
        }

        supabase.table("messages").insert(data).execute()

        return True

    except Exception as e:
        st.error(f"メッセージ保存エラー: {e}")
        return False

def get_memories(theme_id=None, source=None):
    try:
        query = (
            supabase
            .table("user_memories")
            .select("*")
            .eq(
                "user_id",
                CURRENT_USER_ID
            )
        )

        if theme_id is None:
            query = query.filter(
                "theme_id",
                "is",
                "null"
            )
        else:
            query = query.eq(
                "theme_id",
                theme_id
            )

        if source:
            query = query.eq(
                "source",
                source
            )

        res = query.order(
            "id",
            desc=False
        ).execute()

        return res.data if res.data else []

    except Exception as e:
        print(f"記憶取得エラー: {e}")
        return []

def save_memory(
    fact: str,
    theme_id=None,
    category="基本情報",
    source="manual"
) -> bool:
    try:
        embedding_data = get_embedding(
            fact,
            task_type="RETRIEVAL_DOCUMENT"
        )

        data = {
            "user_id": CURRENT_USER_ID,
            "category": category,
            "fact": fact,
            "source": source,
            "embedding": embedding_data
        }

        if theme_id is not None:
            data["theme_id"] = theme_id

        supabase.table(
            "user_memories"
        ).insert(data).execute()

        return True

    except Exception as e:
        st.error(f"記憶保存エラー: {e}")
        return False

def delete_memory(memory_id: int) -> bool:
    try:
        (
            supabase
            .table("user_memories")
            .delete()
            .eq("id", memory_id)
            .execute()
        )

        return True

    except Exception as e:
        st.error(f"記憶削除エラー: {e}")
        return False

# テキストをベクトル（数値配列）に変換する関数
def get_embedding(
    text: str,
    task_type: str = "RETRIEVAL_DOCUMENT"  # デフォルトを大文字の正式名称にします
):
    """Embedding生成。保存時と検索時でtask_typeを分ける。"""
    if not text or not text.strip():
        return None

    try:
        # 引数で渡された文字を強制的に大文字に変換 (Googleの最新仕様に適合させます)
        formatted_task_type = task_type.upper()
        if formatted_task_type == "RETRIEVAL_QUERY":
            formatted_task_type = "RETRIEVAL_QUERY"
        elif formatted_task_type == "RETRIEVAL_DOCUMENT":
            formatted_task_type = "RETRIEVAL_DOCUMENT"

        # 404エラーを回避するため、モデル名と引数の構造をGoogle最新仕様にガチッと固定します
        response = genai.embed_content(
            model="text-embedding-004",  # models/ を外した形
            content=text.strip(),       # contents (複数形) に統一
            task_type=formatted_task_type
        )

        embedding = response.get("embedding")

        if not embedding:
            log_debug("Embeddingが空でした")
            return None

        return embedding

    except Exception as e:
        # 何か問題が起きた場合は、バグの原因をログに残します
        log_debug(f"⚠️ 大元のget_embedding内でエラーが発生しました: {e}")
        return None

# ベクトル検索（RAG）を行う関数
def search_past_logs(current_theme_id, query_text):
    try:
        # クエリテキストをベクトル化
        query_embedding = get_embedding(
            query_text,
            task_type="RETRIEVAL_QUERY"
        )
        
        if not query_embedding:
            return []

        # 【ここを追加！】IDが1（メイン）の場合は None にして全体検索にする！
        theme_filter = None if current_theme_id == 1 else current_theme_id

        # Supabaseのmatch_messages関数（RPC）を呼び出し
        response = supabase.rpc(
            "match_messages",
            {
                "query_embedding": query_embedding,
                "match_threshold": 0.3, # 類似度のしきい値（必要に応じて調整）
                "match_count": 5,        # 抽出する件数
                "filter_theme_id": theme_filter # ここを theme_filter に変更！
            }
        ).execute()

        return response.data if response.data else []

    except Exception as e:
        # エラー処理（ターミナル出力にする場合は下のコメントアウトを外してね）
        print(f"⚠️ 過去ログ検索エラー: {e}")
        return []

def search_similar_memories(
    memory_text: str,
    threshold: float = 0.88,
    match_count: int = 3
):
    """
    新しい記憶と意味が近い既存の長期記憶を検索する。

    threshold:
        0.88以上を類似候補とする。
        誤判定が多ければ0.90～0.93へ上げる。
        重複を見逃す場合は0.84～0.87へ下げる。
    """
    if not memory_text or not memory_text.strip():
        return []

    try:
        query_embedding = get_embedding(
            memory_text,
            task_type="RETRIEVAL_QUERY"
        )

        log_debug(
            f"Embedding型: {type(query_embedding)}"
        )

        log_debug(
            f"Embedding存在: {query_embedding is not None}"
        )
        
        if not query_embedding:
            log_debug(
                "類似記憶検索用Embeddingを生成できませんでした"
            )
            return []

        response = supabase.rpc(
            "match_user_memories",
            {
                "query_embedding": query_embedding,
                "match_threshold": threshold,
                "match_count": match_count,
                "filter_user_id": CURRENT_USER_ID
            }
        ).execute()

        results = (
            response.data
            if response.data
            else []
        )

        log_debug(
            f"類似記憶検索結果: {len(results)}件"
        )

        for result in results:
            similarity = float(
                result.get("similarity", 0)
            )

            fact = result.get(
                "fact",
                ""
            )

            log_debug(
                f"類似度={similarity:.3f} | {fact}"
            )

        return results

    except Exception as e:
        log_debug(
            f"類似記憶検索エラー: {e}"
        )
        return []

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

def get_managed_user_settings() -> dict:
    """
    設定画面で管理している項目と現在値を返す。
    設定値が変わると、ここから取得する内容も自動的に変わる。
    """
    return {
        "AIの名前": current_concierge_name,
        "ユーザー名": current_user_name,
        "ユーザー敬称": current_user_honorific,
        "AIの一人称": current_first_person,
        "口調プリセット": current_style_preset,
        "応答方針": current_user_instruction,
        "AIアバター": current_ai_avatar,
        "ユーザーアバター": current_user_avatar,
        "カラーテーマ": current_theme_color
    }

def get_managed_settings_text() -> str:
    """
    記憶抽出プロンプトへ渡すための表示用テキストを作る。
    """
    settings = get_managed_user_settings()

    return "\n".join(
        f"・{setting_name}: {setting_value}"
        for setting_name, setting_value in settings.items()
    )

def is_managed_setting_memory(memory_text: str) -> bool:
    """
    抽出された記憶が、設定画面で管理すべき内容か判定する。
    """
    if not memory_text:
        return False

    normalized = memory_text.strip().lower()

    # 設定項目を示す表現
    setting_field_patterns = [
        "ユーザー名",
        "ニックネーム",
        "呼び名",
        "呼ばれたい",
        "呼んでほしい",
        "敬称",
        "呼び捨て",
        "aiの名前",
        "コンシェルジュの名前",
        "aiの一人称",
        "一人称",
        "口調",
        "話し方",
        "応答方針",
        "会話スタイル",
        "敬語で",
        "タメ口で",
        "ため口で",
        "アバター",
        "カラーテーマ",
        "背景色"
    ]

    if any(
        pattern.lower() in normalized
        for pattern in setting_field_patterns
    ):
        return True

    # 現在の設定値と、それが設定変更表現と一緒に出ているか確認
    settings = get_managed_user_settings()

    setting_action_patterns = [
        "呼んで",
        "呼ばれたい",
        "にして",
        "設定して",
        "変更して",
        "使って",
        "話して"
    ]

    for setting_value in settings.values():
        value = str(setting_value).strip().lower()

        if not value:
            continue

        if (
            value in normalized
            and any(
                action in normalized
                for action in setting_action_patterns
            )
        ):
            return True

    return False

theme_cfg = COLOR_THEMES.get(current_theme_color, COLOR_THEMES["☀ ライドモード（白）"])

# ★画面最適化CSS（スマホメニュー表示維持 & ドロップダウン選択肢の全階層テキスト完全強制補正）
st.markdown(f"""
<style>
/* 上部ツールバー非表示 */
[data-testid="stToolbar"] {{
    display: none !important;
}}
/* Streamlit上部ヘッダー全体を非表示 */
[data-testid="stHeader"] {{
    display: none !important;
}}
    /* 1. 全体背景＆文字色 */
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
    /*p, span, h1, h2, h3, h4, h5, h6, label {{
        color: {theme_cfg["text"]} !important;
        word-break: break-word !important;
        overflow-wrap: anywhere !important;
    }}*/

    /* 2. 🎯 ドロップダウン（選択肢）のポップアップ要素を全子要素まで全網羅指定 */
    /*div[data-baseweb="select"] *,
    div[data-baseweb="popover"] *,
    div[data-baseweb="menu"] *,
    ul[role="listbox"] *,
    li[role="option"] * {{
        background-color: {theme_cfg["dropdown_bg"]} !important;
        color: {theme_cfg["dropdown_text"]} !important;
    }}*/

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
    /* Selectboxの選択肢文字色強制 */
    div[data-baseweb="select"] span,
    div[data-baseweb="popover"] span,
    div[data-baseweb="menu"] span {{
        color: {theme_cfg["dropdown_text"]} !important;
    }}
    
    /* サイドバー */
    section[data-testid="stSidebar"] {{
        background-color: {theme_cfg["card_bg"]} !important;
    }}

    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {{
        color: {theme_cfg["text"]} !important;
    }}
    section[data-testid="stSidebar"] button span {{
        color: {theme_cfg["text"]} !important;
    }}

    section[data-testid="stSidebar"] button p {{
        color: {theme_cfg["text"]} !important;
    }}

    /* Streamlit 1.6x系向け */
    div[role="listbox"] {{
        background-color: {theme_cfg["dropdown_bg"]} !important;
    }}

    div[role="option"] {{
        background-color: {theme_cfg["dropdown_bg"]} !important;
        color: {theme_cfg["dropdown_text"]} !important;
    }}

    div[role="option"] * {{
        color: {theme_cfg["dropdown_text"]} !important;
    }}
  
    /* ==========================================
   通常ボタンとフォーム送信ボタン
   ========================================== */

    /* 通常ボタンとフォーム送信ボタンの通常表示 */
    button[data-testid="stBaseButton-secondary"],
    button[data-testid="stBaseButton-secondaryFormSubmit"] {{
        background: {theme_cfg["card_bg"]} !important;
        background-color: {theme_cfg["card_bg"]} !important;
        color: {theme_cfg["text"]} !important;
        border: 1px solid {theme_cfg["input_border"]} !important;
        opacity: 1 !important;
    }}

    /* ボタン内の文字 */
    button[data-testid="stBaseButton-secondary"] p,
    button[data-testid="stBaseButton-secondary"] span,
    button[data-testid="stBaseButton-secondaryFormSubmit"] p,
    button[data-testid="stBaseButton-secondaryFormSubmit"] span {{
        color: {theme_cfg["text"]} !important;
        background: transparent !important;
        background-color: transparent !important;
        opacity: 1 !important;
    }}

/* ホバー時 */
button[data-testid="stBaseButton-secondary"]:hover,
button[data-testid="stBaseButton-secondaryFormSubmit"]:hover {{
    background: {theme_cfg["input_border"]} !important;
    background-color: {theme_cfg["input_border"]} !important;
    color: #ffffff !important;
    border-color: {theme_cfg["input_border"]} !important;
}}

/* ホバー時の文字 */
button[data-testid="stBaseButton-secondary"]:hover p,
button[data-testid="stBaseButton-secondary"]:hover span,
button[data-testid="stBaseButton-secondaryFormSubmit"]:hover p,
button[data-testid="stBaseButton-secondaryFormSubmit"]:hover span {{
    color: #ffffff !important;
    background: transparent !important;
}}

/* フォーカス・クリック時 */
button[data-testid="stBaseButton-secondary"]:focus,
button[data-testid="stBaseButton-secondary"]:active,
button[data-testid="stBaseButton-secondaryFormSubmit"]:focus,
button[data-testid="stBaseButton-secondaryFormSubmit"]:active {{
    background: {theme_cfg["input_border"]} !important;
    background-color: {theme_cfg["input_border"]} !important;
    color: #ffffff !important;
    border-color: {theme_cfg["input_border"]} !important;
    box-shadow: none !important;
}}
/* フォームラベル */
label {{
    color: {theme_cfg["text"]} !important;
}}

/* 設定画面の見出し */
[data-testid="stMarkdownContainer"] p {{
    color: {theme_cfg["text"]} !important;
}}
/* divider */
hr {{
    border-color: {theme_cfg["input_border"]} !important;
}}
/* Expander */
[data-testid="stExpander"] {{
    border: 1px solid {theme_cfg["input_border"]} !important;
    border-radius: 8px !important;
}}
div[data-baseweb="select"] {{
    border: 1px solid {theme_cfg["input_border"]} !important;
    border-radius: 8px !important;
}}
textarea,

section[data-testid="stSidebar"] {{
    border-right: 1px solid {theme_cfg["input_border"]} !important;
}}

</style>
""", unsafe_allow_html=True)

# ==========================================
# 🧠 AI要約＆自動抽出ロジック（高速化対応）
# ==========================================

def check_and_summarize_history(theme_id: int, all_messages: list, current_summary: str) -> str:
    # 古いログが5件以上溜まっていないなら要約しない（無駄呼び出し防止）
    old_messages_count = len(all_messages) - MAX_CONTEXT_MESSAGES
    if old_messages_count < 5: 
        return current_summary

    # 5件以上溜まったら要約を実行...
    if len(all_messages) <= MAX_CONTEXT_MESSAGES:
        return current_summary

    old_messages = all_messages[:-MAX_CONTEXT_MESSAGES]
    formatted_old_text = "\n".join([f"{m['role']}: {m['content']}" for m in old_messages])

    prompt = f"""
    以下はこれまでの要約と溢れた会話ログです。統合した新しい要約を日本語100字程度で作成してください。
    【既存要約】: {current_summary if current_summary else "なし"}
    【過去ログ】: {formatted_old_text}
    """
    try:
        log_debug("テーマ要約開始")

        start = time.time()

        response = summary_model.generate_content(
            prompt
        )

        elapsed = time.time() - start

        log_debug(
            f"テーマ要約完了: {elapsed:.2f}秒"
        )

        # 要約のトークン数を記録
        if (
            hasattr(response, "usage_metadata")
            and response.usage_metadata
        ):
            summary_in = (
                response.usage_metadata.prompt_token_count
            )

            summary_out = (
                response.usage_metadata.candidates_token_count
            )

            st.session_state.summary_in_tokens += summary_in
            st.session_state.summary_out_tokens += summary_out

            log_debug(
                f"要約トークン "
                f"In={summary_in} Out={summary_out}"
            )

        new_summary = response.text.strip()

        update_theme_summary(
            theme_id,
            new_summary
        )

        return new_summary

    except Exception as e:
        log_debug(
            f"テーマ要約エラー: {e}"
        )

        return current_summary

def extract_and_save_long_term_memory(
    user_text: str,
    theme_id: int
):
    cleaned_text = user_text.strip()

    if len(cleaned_text) < 8:
        return

    ignore_words = {
        "ありがとう", "ありがとう！", "了解", "了解です", "うん", "そうなんだ", "はい", "わかった"
    }

    if cleaned_text in ignore_words:
        return

    memory_keywords = [
        "好き", "嫌い", "飼っている", "飼い始めた", "始めた", "引っ越し", 
        "転職", "家族", "友人", "目標", "悩み", "趣味"
    ]

    if not any(keyword in cleaned_text for keyword in memory_keywords):
        log_debug("記憶候補キーワードなし。抽出をスキップ")
        return

    managed_settings_text = get_managed_settings_text()
    
    prompt = f"""
次のユーザー発言から、今後の会話で役立つ、
ユーザー自身についての情報または重要な出来事を
1件だけ抽出してください。

【設定画面で現在管理されている情報】
{managed_settings_text}

上記の設定画面で管理されている項目や、
その値を変更する依頼は長期記憶として保存しないでください。

保存対象:
・継続的に役立つユーザープロフィール
・継続的な好みや苦手なもの
・家族、友人、ペットなどの関係
・重要な生活上の出来事
・継続している悩みや目標
・最近始まった生活上の変化

保存しないもの:
・挨拶 / その場限りの質問 / 一般知識 / 根拠のない推測 / AIの回答内容
・ユーザー名やニックネームの設定 / ユーザーへの呼び方や敬称の設定
・AIの名前や一人称の設定 / 敬語やタメ口などの口調設定
・応答方針や会話スタイルの設定 / アバターやカラーテーマなどの画面設定
・上記の現在設定と同じ内容 / 上記の現在設定を変更する依頼

ルール:
・ユーザーが明言した内容だけを抽出してください。
・情報を補ったり、原因を推測したりしないでください。
・簡潔な1文にしてください。
・設定画面で管理すべき内容だけなら、必ずNONEを返してください。
・保存対象がなければNONEだけを返してください。

ユーザー発言:
"{cleaned_text}"
"""

    try:
        log_debug("長期記憶抽出開始")
        start = time.time()
        response = memory_model.generate_content(prompt)
        elapsed = time.time() - start

        log_debug(f"長期記憶抽出完了: {elapsed:.2f}秒")

        # トークン数の記録
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            memory_in = response.usage_metadata.prompt_token_count
            memory_out = response.usage_metadata.candidates_token_count
            st.session_state.memory_in_tokens += memory_in
            st.session_state.memory_out_tokens += memory_out
            log_debug(f"長期記憶抽出トークン In={memory_in} Out={memory_out}")

        extracted_memory = response.text.strip()

        # NONE 判定
        if not extracted_memory or "NONE" in extracted_memory.upper():
            log_debug("保存対象の長期記憶なし")
            return

        log_debug(f"長期記憶抽出結果: {extracted_memory}")

        # 1. 設定管理対象のチェック
        if is_managed_setting_memory(extracted_memory):
            log_debug(f"設定項目のため長期記憶保存をスキップ: {extracted_memory}")
            return

        # 2. 完全一致チェック（DB負荷軽減のためローカルで確認）
        existing_memories = get_memories(theme_id=None, source="auto")
        exact_duplicate = next(
            (m for m in existing_memories if m.get("fact", "").strip() == extracted_memory),
            None
        )
        if exact_duplicate:
            log_debug(f"完全一致する長期記憶があるため保存をスキップ: {extracted_memory}")
            return

        # ==================================================================
        # 【あなたの環境への適合】3. Embeddingによる類似記憶検索
        # ==================================================================
        # ※ 検索（クエリ）なので task_type="retrieval_query" を明示的に指定します
        similar_memories = search_similar_memories(
            memory_text=extracted_memory,
            threshold=0.88,
            match_count=3
        )

        if similar_memories:
            most_similar = similar_memories[0] # 1件目を取得
            existing_id = most_similar.get("id")
            existing_fact = most_similar.get("fact", "").strip()
            similarity = float(most_similar.get("similarity", 0))

            log_debug(f"類似記憶検知 (類似度: {similarity:.3f}): 「{existing_fact}」")

            # Gemini 3.5 Flash-Lite にコンテキスト判定（3択）をさせる
            judge_prompt = f"""
            あなたはユーザーの記憶データベースを整理するマネージャーです。
            「既存の記憶」と、新しく抽出された「新しい記憶」を比較し、適切なアクションを1つ選択してください。

            【既存の記憶】: {existing_fact}
            【新しい記憶】: {extracted_memory}

            【選択肢】
            - SKIP: 新しい記憶が、既存の記憶と重複しているか、既存の記憶の方が詳細な情報を含んでいる場合。
            - UPDATE: 新しい記憶によって、既存の記憶の内容が上書き・変更（修正）されるべき場合（情報が更新されたり矛盾する場合）。
            - MERGE: どちらも新しい情報を含んでおり、2つの事実を1つの自然な文章に統合・補完すべき場合。

            【出力フォーマット】
            必ず以下のJSONオブジェクトのみで返答してください。余計な説明、挨拶、マークダウン(```)などは一切含めないでください。
            {{"action": "SKIP" | "UPDATE" | "MERGE", "final_fact": "UPDATEまたはMERGEの場合に、新しく保存すべき統合・更新された文章（SKIPの場合は空欄）"}}
            """

            try:
                judge_response = memory_model.generate_content(
                    judge_prompt,
                    generation_config={"response_mime_type": "application/json"}
                )
                
                # トークン集計（記憶抽出用の枠に加算）
                if hasattr(judge_response, "usage_metadata") and judge_response.usage_metadata:
                    st.session_state.memory_in_tokens += judge_response.usage_metadata.prompt_token_count
                    st.session_state.memory_out_tokens += judge_response.usage_metadata.candidates_token_count

                result = json.loads(judge_response.text.strip())
                action = result.get("action")
                final_fact = result.get("final_fact", "").strip()

            except Exception as e:
                log_debug(f"Geminiによる記憶更新判定、またはJSONパースに失敗: {e}")
                return

            # アクションごとの分岐処理
            if action == "SKIP":
                log_debug(f"長期記憶保存スキップ (判定: SKIP)")
                return

            elif action == "UPDATE":
                try:
                    # 【適合】保存（ドキュメント）用なので task_type="retrieval_document" でベクトルを生成
                    new_embedding = get_embedding(final_fact, task_type="retrieval_document")
                    supabase.table("user_memories").update({
                        "fact": final_fact,
                        "embedding": new_embedding
                    }).eq("id", existing_id).execute()
                    log_debug(f"長期記憶を上書き更新しました (判定: UPDATE): 「{final_fact}」")
                except Exception as db_err:
                    log_debug(f"長期記憶の更新に失敗: {db_err}")
                return

            elif action == "MERGE":
                try:
                    # 【適合】保存用なので task_type="retrieval_document" でベクトルを生成
                    new_embedding = get_embedding(final_fact, task_type="retrieval_document")
                    supabase.table("user_memories").update({
                        "fact": final_fact,
                        "embedding": new_embedding
                    }).eq("id", existing_id).execute()
                    log_debug(f"長期記憶を1つに統合しました (判定: MERGE): 「{final_fact}」")
                except Exception as db_err:
                    log_debug(f"長期記憶の統合に失敗: {db_err}")
                return

        # 4. 類似記憶が全くなかった場合は、通常の新規保存
        saved = save_memory(
            fact=extracted_memory,
            theme_id=None,
            category="AI自動抽出",
            source="auto"
        )

        if saved:
            log_debug(f"新しい長期記憶を保存: {extracted_memory}")
        else:
            log_debug("長期記憶のDB保存に失敗")

    except Exception as e:
        log_debug(f"長期記憶抽出エラー: {e}")
        
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

st.sidebar.markdown("---")

sidebar_memories = get_memories(
    theme_id=None,
    source="auto"
)

with st.sidebar.expander(
    "🧠 長期記憶",
    expanded=False
):

    if sidebar_memories:

        for mem in sidebar_memories[-10:]:
            st.write(f"・{mem['fact']}")

    else:
        st.caption("長期記憶はまだありません")

current_summary = get_theme_summary(current_theme_id)
with st.sidebar.expander("📖 このテーマの記憶", expanded=False):
    if current_summary:
        st.info(clean_bold_markdown(current_summary))
    else:
        st.caption("会話が設定件数を超えると自動要約されます。")

# トークン消費量のリアルタイム表示（プレースホルダー化）
st.sidebar.markdown("---")
st.sidebar.subheader("📊 トークン消費状況")
token_container = st.sidebar.empty()  # ←★後から中身をリアルタイム書き換えできる枠を作成

from datetime import datetime

def log_debug(message):
    if "debug_logs" not in st.session_state:
        st.session_state.debug_logs = []

    timestamp = datetime.now().strftime("%H:%M:%S")

    st.session_state.debug_logs.append(
        f"[{timestamp}] {message}"
    )

    # 最大100件だけ保持
    if len(st.session_state.debug_logs) > 100:
        st.session_state.debug_logs = (
            st.session_state.debug_logs[-100:]
        )

# トークン表示を更新する関数
def render_token_info():
    with token_container.container():

        st.caption("【累計トークン】")

        st.write(
            f"💬 チャット\n"
            f"In: {st.session_state.chat_in_tokens:,}\n"
            f"Out: {st.session_state.chat_out_tokens:,}"
        )

        st.write(
            f"🧠 長期記憶抽出\n"
            f"In: {st.session_state.memory_in_tokens:,}\n"
            f"Out: {st.session_state.memory_out_tokens:,}"
        )

        st.write(
            f"📝 要約\n"
            f"In: {st.session_state.summary_in_tokens:,}\n"
            f"Out: {st.session_state.summary_out_tokens:,}"
        )

        total_in = (
            st.session_state.chat_in_tokens
            + st.session_state.memory_in_tokens
            + st.session_state.summary_in_tokens
        )

        total_out = (
            st.session_state.chat_out_tokens
            + st.session_state.memory_out_tokens
            + st.session_state.summary_out_tokens
        )
        chat_cost_usd = (
            (
                st.session_state.chat_in_tokens
                / 1_000_000
            )
            * CHAT_INPUT_PRICE_PER_MILLION
            +
            (
                st.session_state.chat_out_tokens
                / 1_000_000
            )
            * CHAT_OUTPUT_PRICE_PER_MILLION
        )

        memory_cost_usd = (
            (
                st.session_state.memory_in_tokens
                / 1_000_000
            )
            * LITE_INPUT_PRICE_PER_MILLION
            +
            (
                st.session_state.memory_out_tokens
                / 1_000_000
            )
            * LITE_OUTPUT_PRICE_PER_MILLION
        )

        summary_cost_usd = (
            (
                st.session_state.summary_in_tokens
                / 1_000_000
            )
            * LITE_INPUT_PRICE_PER_MILLION
            +
            (
                st.session_state.summary_out_tokens
                / 1_000_000
            )
            * LITE_OUTPUT_PRICE_PER_MILLION
        )

        total_cost_usd = (
            chat_cost_usd
            + memory_cost_usd
            + summary_cost_usd
        )

        chat_cost_jpy = chat_cost_usd * USD_TO_JPY
        memory_cost_jpy = memory_cost_usd * USD_TO_JPY
        summary_cost_jpy = summary_cost_usd * USD_TO_JPY
        total_cost_jpy = total_cost_usd * USD_TO_JPY

        st.divider()

        st.divider()

        st.text(f"総入力 : {total_in:,}")
        st.text(f"総出力 : {total_out:,}")

        st.text(
            f"チャット費用 : {chat_cost_jpy:.4f}円"
        )

        st.text(
            f"長期記憶抽出費用 : {memory_cost_jpy:.4f}円"
        )

        st.text(
            f"要約費用 : {summary_cost_jpy:.4f}円"
        )

        st.text(
            f"推定総コスト : {total_cost_jpy:.4f}円"
        )

        conversation_count = (
            st.session_state.conversation_count
        )

        avg_cost_jpy = (
            total_cost_jpy / conversation_count
            if conversation_count > 0
            else 0
        )

        st.text(
            f"会話回数 : {conversation_count:,}"
        )

        st.text(
            f"平均コスト : {avg_cost_jpy:.4f}円/回"
        )

# トークン表示
render_token_info()

with st.sidebar.expander(
    "🛠 開発者ログ",
     expanded=False
):

    if "debug_logs" in st.session_state and st.session_state.debug_logs:
        for log in reversed(
            st.session_state.debug_logs[-30:]
        ):
            st.text(log)

    else:
        st.caption("ログはまだありません")

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

        st.markdown("【🖼️ アバター（アイコン）設定】")
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
    st.caption(f"担当コンシェルジュ: 【{current_concierge_name}】 | モデル: 【{CHAT_MODEL_NAME}】")

    all_messages = get_messages(current_theme_id)

    # 過去ログ描画（名前表示から  を完全除去）
    for msg in all_messages:
        role_label = display_user_name if msg["role"] == "user" else current_concierge_name
        avatar_img = current_user_avatar if msg["role"] == "user" else current_ai_avatar

        with st.chat_message(msg["role"], avatar=avatar_img):
            st.write(f"【{role_label}】: {clean_bold_markdown(msg['content'])}")

    # チャット送信処理
    if user_input := st.chat_input(f"{current_concierge_name}にメッセージを送信..."):
        # ① 画面表示　ユーザーのメッセージを即時表示
        with st.chat_message("user", avatar=current_user_avatar):
            st.write(f"【{display_user_name}】: {clean_bold_markdown(user_input)}")

        # 過去ログ検索計測開始
        start = time.time()
        # 1. 今回の発言を保存する前に、過去ログを検索
        past_logs_context = search_past_logs(
            current_theme_id,
            user_input
        )
        log_debug(
            f"過去ログ検索結果: {len(past_logs_context)}件"
        )
        # 過去ログ検索時間表示
        log_debug(
            f"過去ログ検索 {time.time()-start:.2f}秒"
        )

        # 2. 検索結果を文字列化
        if past_logs_context:
            logs_text = []

            for log in past_logs_context:
                role_name = (
                    display_user_name
                    if log.get("role") == "user"
                    else current_concierge_name
                )

                logs_text.append(
                   f"・{role_name}: {log.get('content', '')}"
                )

            past_logs_str = "\n".join(logs_text)
        else:
            past_logs_str = "該当する過去ログなし"

        # 3. 過去検索完了後に今回の発言を保存
        save_message(
           current_theme_id,
           "user",
           user_input
        )

        all_messages.append({
            "role": "user",
            "content": user_input
        })

        recent_messages = all_messages[-MAX_CONTEXT_MESSAGES:]
        
        manual_memory_context = (
            "\n".join([f"・{fact}" for fact in manual_facts])
            if manual_facts
            else "なし"
        )

        auto_memory_context = (
             "\n".join([f"・{fact}" for fact in auto_facts[-5:]])
             if auto_facts
             else "なし"
        )

        short_summary = (
            current_summary[:150]
            if current_summary
            else "なし"
        )
        log_debug(
            f"長期記憶件数: {len(auto_facts)}"
        )
        for idx, memory in enumerate(auto_facts, start=1):
            log_debug(
            f"長期記憶[{idx}] {memory}"
        )

        # システム指示に関連情報を組み込む！
        system_instruction = f"""
        あなたの名前は「{current_concierge_name}」です。
        対話相手のユーザー名は「{display_user_name}」です。
        あなたの一人称は「{current_first_person}」を使用してください。

       【応答スタイル】
        {current_user_instruction}

        【ユーザーが手動登録した基本情報】
         {manual_memory_context}

        【AIが抽出した長期記憶】
        {auto_memory_context}

        【現在の発言に関連する過去の会話】
        {past_logs_str}

        【現在のテーマの会話要約】
        {current_summary}
        
        【記憶の利用ルール】
        ・記憶や過去ログは、現在の話題と自然な関連がある場合だけ使ってください。
        ・記憶にない内容を作らないでください。
        ・記憶と現在の状態の因果関係を断定しないでください。
        ・長期記憶と現在の話題に関連性が見られる場合は積極的に言及してください。
        ・ただし断定せず、確認質問の形で触れてください。
          例:
          「そういえば〜だったよね」
          「影響しているかもしれないけどどう？」
          「その後どうなった？」
        ・すべての回答で無理に過去の記憶を持ち出さないでください。
        ・ユーザーが明確に話していない感情や事情を決めつけないでください。
        ・回答では太字装飾記号を使わないでください。
        """
        contents_for_gemini = [
            {"role": "user", "parts": [f"[システム指示・前提背景]\n{system_instruction}"]},
            {"role": "model", "parts": [f"了解だよ、{display_user_name}。"]}
        ]

        for m in recent_messages:
            role = "user" if m["role"] == "user" else "model"
            contents_for_gemini.append({"role": role, "parts": [m["content"]]})

        # ② 即時「思考中...」表示 & 返答生成
        with st.chat_message("assistant", avatar=current_ai_avatar):
            with st.spinner(f"🤖 {current_concierge_name}が考え中..."):
                try:
                    log_debug(
                        f"送信トークン数:{len(str(contents_for_gemini))}"
                    )
                    log_debug(
                        f"プロンプト文字数={len(str(contents_for_gemini))}"
                    )
                    # チャット応答計測開始
                    start = time.time()
                    response = chat_model.generate_content(
                        contents_for_gemini
                    )
                    # チャット応答計測表示
                    log_debug(
                        f"チャットGemini回答: {time.time()-start:.2f}秒"
                    )

                    # ▼▼▼ トークン数をカウントして記録＆画面の即時更新 ▼▼▼
                    if hasattr(response, "usage_metadata") and response.usage_metadata:
                        in_t = response.usage_metadata.prompt_token_count
                        out_t = response.usage_metadata.candidates_token_count
                        log_debug(
                            f"チャットトークン In={in_t} Out={out_t}"
                        )
                        st.session_state.chat_in_tokens += in_t
                        st.session_state.chat_out_tokens += out_t

                        st.session_state.last_in_tokens = in_t
                        st.session_state.last_out_tokens = out_t

                        st.session_state.total_in_tokens += in_t
                        st.session_state.total_out_tokens += out_t
                   
                    # ▲▲▲ ここまで ▲▲▲
                    
                    ai_reply = response.text
                    st.session_state.conversation_count += 1
                    clean_reply = clean_bold_markdown(ai_reply)
                    st.write(f"【{current_concierge_name}】: {clean_reply}")
                    save_message(current_theme_id, "assistant", ai_reply)
                except Exception as e:
                    error_msg = f"Gemini API エラー: {e}"
                    
                    log_debug(error_msg)

                    st.error(error_msg)

        # ★計算した瞬間にサイドバー表示を即時リアルタイム書き換え！
        render_token_info()
        
        # ③ 非同期風に裏で要約更新・記憶抽出を実行
        check_and_summarize_history(current_theme_id, all_messages, current_summary)
        extract_and_save_long_term_memory(user_input, current_theme_id)

        st.rerun()
