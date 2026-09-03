import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client
import re
import time
import json
from datetime import datetime, timezone, timedelta
import zoneinfo

# 日本時間（UTC+9時間）
JST = zoneinfo.ZoneInfo("Asia/Tokyo")

# ==========================================
# ⚙️ 設定・初期化
# ==========================================
st.set_page_config(page_title="SYNC-LNK // AI", page_icon="🤖", layout="wide")

MAX_CONTEXT_MESSAGES = 5  # 直近5件を保持

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY_PRO"]

@st.cache_resource
def init_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

genai.configure(api_key=GEMINI_API_KEY)

# ==========================================
# Geminiモデル設定（★3.5/3.6 Flash-Liteへ完全一本化）
# ==========================================
# 💡 表側の雑談も、裏方の要約・エラー翻訳も、すべて最安・最速の「Flash-Lite」に固定してインフラコストを完全防衛します
CHAT_MODEL_NAME = "gemini-3.5-flash-lite"
MEMORY_MODEL_NAME = "gemini-3.5-flash-lite"
SUMMARY_MODEL_NAME = "gemini-3.5-flash-lite"

chat_model = genai.GenerativeModel(CHAT_MODEL_NAME)
memory_model = genai.GenerativeModel(MEMORY_MODEL_NAME)
summary_model = genai.GenerativeModel(SUMMARY_MODEL_NAME)

# Gemini 3.5 Flash-Lite 従量課金単価定義（1ドル150円換算）
LITE_INPUT_PRICE_PER_MILLION = 0.30
LITE_OUTPUT_PRICE_PER_MILLION = 2.50
PRICE_LITE_IN = (LITE_INPUT_PRICE_PER_MILLION / 1_000_000) * 150
PRICE_LITE_OUT = (LITE_OUTPUT_PRICE_PER_MILLION / 1_000_000) * 150

USD_TO_JPY = 160

# ガードレール用の定数を定義
MAX_INPUT_CHARS = 1000
DAILY_LIMIT = 20
BURST_LIMIT_SECONDS = 20  # 1分3通 ＝ 平均20秒に1通以上の連投を弾く

# ==================================================================
# 🔒【完全防衛】 URLパラメータの強制チェック（セキュリティシャッター）
# ==================================================================
user_param = st.query_params.get("user")

# 💡 URLのケツに「?user=...」が何もついていない場合、または空っぽの場合
if not user_param:
    st.error("🔒 アクセス権限がありません")
    st.info("このアプリは招待制のクローズドテスト中です。正しい専用の招待URLからアクセスしてください。")
    st.stop() # 🎯 マスターデータの露出を入り口で100%完全にシャットアウト！

# 正しい暗号（UUIDなど）がついていれば、そのユーザーだけの独立した部屋を開きます
CURRENT_USER_ID = str(user_param)
ADMIN_USER_ID = st.secrets["ADMIN_USER_ID"]

# 💡【完全修正】 起動時・F5再読み込み時にも、DBのchat_count行から本物の会話回数を確実に引き戻します！
if "tokens_loaded" not in st.session_state:
    import threading
    if "db_lock" not in st.session_state:
        st.session_state["db_lock"] = threading.Lock()
        
    try:
        # user_token_stats テーブルから、現在のユーザーの chat_count の値をダイレクトに引っこ抜きます
        res = supabase.table("user_token_stats").select("*").eq("user_id", CURRENT_USER_ID).eq("feature_type", "chat_count").execute()
        if res.data and len(res.data) > 0:
            # DBに保存されているリセット後の正しい累積回数を、一時メモリに完璧に復元！
            st.session_state.conversation_count = int(res.data[0].get("in_tokens", 0))
        else:
            st.session_state.conversation_count = 0
    except Exception as e:
        print(f"⚠️ 起動時会話回数復元エラー: {e}")
        st.session_state.conversation_count = 0
        
    st.session_state["tokens_loaded"] = True
    try:
        res = supabase.table("user_token_stats").select("*").eq("user_id", str(CURRENT_USER_ID)).eq("feature_type", "chat_count").execute()
        # 💡 上部も最下部と同じく、DBのchat_count行（res.data[0]）からリセット後の正しい会話回数を復元させます
        if res.data and len(res.data) > 0:
            st.session_state.conversation_count = res.data[0].get("in_tokens", 0)
        else:
            st.session_state.conversation_count = 0
    except Exception as e:
        print(f"⚠️ 会話回数同期エラー: {e}")
        st.session_state.conversation_count = 0
        
    st.session_state["tokens_loaded"] = True

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

# 各処理コンポーネントごとの「処理時間（秒）」を安全に初期化
if "chat_processing_time" not in st.session_state:
    st.session_state.chat_processing_time = 0.0
if "summary_processing_time" not in st.session_state:
    st.session_state.summary_processing_time = 0.0
if "search_processing_time" not in st.session_state:
    st.session_state.search_processing_time = 0.0

if "debug_logs" not in st.session_state:
    st.session_state.debug_logs = []
if "conversation_count" not in st.session_state:
    st.session_state.conversation_count = 0

if "tokens_loaded" not in st.session_state:
    load_permanent_tokens(CURRENT_USER_ID)

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
    "🤖 ロボット": "🤖", "👾 レトロドット": "👾", "🦊 きつね": "🦊", "🦉 ふくろう": "🦉", "🔮 魔法の水晶": "🔮"
}
AVATAR_PRESETS_USER = {
    "💫 キラキラ星": "💫", "🧑‍💻 エンジニア": "🧑‍💻", "🐉 ドラゴン": "🐉", "⚡ サンダー": "⚡", "👑 キング": "👑"
}

# カラーテーマ定義（デフォルト：ライドモード）
COLOR_THEMES = {
    "☀ ライドモード（白）": {"bg": "#ffffff", "card_bg": "#f8fafc", "input_border": "#0288d1", "text": "#0f172a", "dropdown_bg": "#ffffff", "dropdown_text": "#0f172a"},
    "🔷 ダークブルー（濃紺）": {"bg": "#101f33", "card_bg": "#1a2d47", "input_border": "#3b82f6", "text": "#ffffff", "dropdown_bg": "#1a2d47", "dropdown_text": "#ffffff"},
    "🌿 ナチュラルグリーン": {"bg": "#0f2e1b", "card_bg": "#194328", "input_border": "#10b981", "text": "#ffffff", "dropdown_bg": "#194328", "dropdown_text": "#ffffff"},
    "💜 ディープパープル": {"bg": "#211132", "card_bg": "#321b4a", "input_border": "#a855f7", "text": "#ffffff", "dropdown_bg": "#321b4a", "dropdown_text": "#ffffff"}
}

# 画面上の不要な ** 記号を除去する関数
def clean_bold_markdown(text: str) -> str:
    if not text:
        return text
    return text.replace("**", "")

# ==========================================
# 🗄️ Supabase データベース操作関数
# ==========================================

# ==================================================================
# 🧠 【一本道統合仕様】 過去メッセージ履歴の一括取得関数
# ==================================================================
# 💡 引数を追加することで、URLから届いた本物のIDの鍵を関数内部へストレートに通電させます！
def get_messages(target_id: str) -> list[dict]:
    """
    💡 古いテーマIDによる細切れ処理（せき止め）を根底から完全に全消去！
    ユーザーIDに紐づく全てのチャット履歴を、1本の綺麗な大河（タイムライン）として
    エラーを200%絶対に起こさずにSupabaseから時系列順にガバッと取得します。
    """
    try:
        # 🔒 古い theme_id でのフィルタリングを完全に撤廃し、CURRENT_USER_ID だけで一本釣りします！
        res = (
            supabase
            .table("messages")
            .select("*")
            .eq("user_id", str(target_id))
            .order("created_at", desc=False)
            .execute()
        )  

        return res.data if res.data else []
  
    except Exception as e:
        print(
            f"⚠️ メッセージ履歴取得エラー: "
            f"{type(e).__name__}: {e}"
        )   
        
        return []

def save_message(role: str, content: str) -> bool:
    """1本道統合仕様: theme_idのカラムを完全に排除してメッセージを保存します"""
    try:
        embedding_data = get_embedding(
            content,
            task_type="RETRIEVAL_DOCUMENT"
        )

        data = {
            "user_id": CURRENT_USER_ID,
            "role": role,
            "content": content,
            "embedding": embedding_data
        }

        supabase.table("messages").insert(data).execute()
        return True

    except Exception as e:
        st.error(f"メッセージ保存エラー: {e}")
        return False

# ==================================================================
# 🔍【新設】 文字×ベクトルの最強ハイブリッド過去ログ検索（追加原価0円）
# ==================================================================
def search_past_logs_hybrid(query_text: str):
    """
    1. まずベクトル類似度検索（RPC）を走らせて、ふんわりとした「意味の近い過去ログ」を検索。
    2. もしヒット数が最大値（3件）に満たない場合、裏口で『LIKE部分一致検索（文字の完全一致）』を自動で重ね、
       文脈の角度のズレや固有名詞の不一致による大切な思い出の聞き逃しを完全に防衛します。
    """
    if not query_text or not query_text.strip():
        return []

    try:
        query_embedding = get_embedding(
            query_text,
            task_type="RETRIEVAL_QUERY"
        )
        
        if not query_embedding:
            return []

        # ① ベクトル類似度検索の実行（1本道仕様：全メッセージから検索するRPC）
        response = supabase.rpc(
            "match_messages_all",
            {
                "query_embedding": query_embedding,
                "match_threshold": 0.65,  # ゴミデータを拾わない厳格な合格ライン
                "match_count": 3,
                "filter_user_id": CURRENT_USER_ID
            }
        ).execute()

        results = response.data if response.data else []

        # ② 救済網：文字の部分一致（LIKE検索）をハイブリッドで重ねる
        # ユーザーの発言から2文字以上の重要な名詞・キーワードの塊を簡易的に抽出
        keywords = [w.group() for w in re.finditer(r'[一-龠々𠮷々〆]+|[ぁ-ん]{2,}|[ァ-ヶー]{2,}', query_text) if len(w.group()) >= 2]

        if keywords and len(results) < 3:
            try:
                # 直近の自分のユーザー発言を最大20件引っ張ってきてキーワードが含まれるか突合
                like_res = supabase.table("messages").select("*").eq("user_id", CURRENT_USER_ID).eq("role", "user").order("created_at", desc=True).limit(20).execute()
                if like_res.data:
                    for msg in like_res.data:
                        if any(kw in msg["content"] for kw in keywords):
                            # すでにベクトル検索で拾った重複データでなければ救済合流
                            if not any(r["id"] == msg["id"] for r in results):
                                results.append(msg)
                                if len(results) >= 3:
                                    break
            except Exception:
                pass

        return results[:3]  # 永久に上位3件のみに絞ってハヤトに読ませる（大食い・原価暴走防止）

    except Exception as e:
        print(f"⚠️ ハイブリッド過去ログ検索エラー: {e}")
        return []

# ==================================================================
## 📊 【新設】 匿名型システムエラー・要望アナリティクス集計関数
# ==================================================================
def increment_error_analytics(error_type: str, plan_type: str):
    """
    🔒【製品版対応・プライバシー100%完全防衛】
    ユーザーの会話の中身（生文字）は一切触れず、
    「無料／ライト／プレミアム」の各プランで、どのガードレール（無茶振り等）に接触したか
    という『回数（数字）』だけを匿名で自動集計・カウントアップ（+1）します。
    """
    try:
        now_str = datetime.now(timezone.utc).isoformat()
        res = supabase.table("app_error_analytics").select("*").eq("error_type", error_type).execute()
        
        # カウントアップする対象プランのカラム名をスマートに仕分け
        column_name = "count_free"
        if "ライト" in plan_type:
            column_name = "count_light"
        elif "プレミアム" in plan_type:
            column_name = "count_premium"
        
        if res.data and len(res.data) > 0:
            current_row = res.data[0]
            current_count = int(current_row.get(column_name, 0))
            supabase.table("app_error_analytics").update({
                column_name: current_count + 1,
                "last_occurred_at": now_str
            }).eq("id", current_row["id"]).execute()
        else:
            data = {
                "error_type": error_type,
                "count_free": 0, "count_light": 0, "count_premium": 0,
                "last_occurred_at": now_str
            }
            data[column_name] = 1
            supabase.table("app_error_analytics").insert(data).execute()
            
    except Exception as e:
        print(f"⚠️ 匿名エラー分析ログ記録エラー: {e}")

def get_memories(source="manual"):
    """
    🎯【設定画面・手動登録専用仕様】
    ユーザー設定画面（タブ2）から登録された、全テーマ共通の『現在の調教・基本設定ファクト』を読み込みます。
    """
    try:
        res = (
            supabase
            .table("user_memories")
            .select("*")
            .eq("user_id", CURRENT_USER_ID)
            .eq("source", source)
            .order("id", desc=False)
            .execute()
        )
        return res.data if res.data else []
    except Exception as e:
        print(f"設定データ取得エラー: {e}")
        return []

def save_memory(fact: str, source="manual") -> bool:
    """設定情報をmessagesテーブルの検索とは別に、固定ファクトとして保存します"""
    try:
        embedding_data = get_embedding(
            fact,
            task_type="RETRIEVAL_DOCUMENT"
        )

        data = {
            "user_id": CURRENT_USER_ID,
            "category": "基本情報",
            "fact": fact,
            "source": source,
            "embedding": embedding_data
        }

        supabase.table("user_memories").insert(data).execute()
        return True

    except Exception as e:
        st.error(f"設定保存エラー: {e}")
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
        st.error(f"設定削除エラー: {e}")
        return False

def save_or_update_user_setting(setting_key: str, new_value: str) -> bool:
    """
    「AIの名前: タクミ」のような設定値の重複を防ぎ、
    古い設定を削除してから最新の設定を1件だけ保存する。
    """
    new_fact = f"{setting_key}: {new_value}"
    
    try:
        # 1. 既存の手動設定（source='manual'）をすべて取得
        res = supabase.table("user_memories").select("*").eq("user_id", CURRENT_USER_ID).eq("source", "manual").execute()
        
        # 2. もし過去に同じ設定項目（例: 'AIの名前:'）が存在していれば、それらを物理削除
        if res.data:
            for item in res.data:
                if item.get("fact", "").startswith(f"{setting_key}:"):
                    delete_memory(item["id"])
                    print(f"古い設定を上書き削除しました: {item['fact']}")
                
        # 3. 古いゴミを掃除した上で、最新の設定値を保存
        return save_memory(fact=new_fact, source="manual")
        
    except Exception as e:
        print(f"設定更新エラー: {e}")
        return False

# テキストをベクトル（数値配列）に変換する関数
def get_embedding(text: str, task_type: str = "RETRIEVAL_DOCUMENT"):
    """Embedding生成。"""
    if not text or not text.strip():
        return None

    try:
        formatted_task_type = task_type.upper()
        response = genai.embed_content(
            model="models/gemini-embedding-001",
            content=text.strip(),
            task_type=formatted_task_type
        )
        return response.get("embedding")
    except Exception as e:
        print(f"⚠️ Embedding生成エラー: {e}")
        return None

def add_permanent_tokens(
    user_id: str,
    feature_type: str,
    in_tokens: int,
    out_tokens: int
) -> bool:
    try:
        result = (
            supabase
            .table("user_token_stats")
            .select("*")
            .eq("user_id", str(user_id))
            .eq("feature_type", feature_type)
            .execute()
        )

        if result.data:
            current_row = result.data[0]

            current_in = int(
                current_row.get("in_tokens", 0) or 0
            )
            current_out = int(
                current_row.get("out_tokens", 0) or 0
            )

            (
                supabase
                .table("user_token_stats")
                .update({
                    "in_tokens": current_in + int(in_tokens),
                    "out_tokens": current_out + int(out_tokens)
                })
                .eq("id", current_row["id"])
                .execute()
            )

        else:
            (
                supabase
                .table("user_token_stats")
                .insert({
                    "user_id": str(user_id),
                    "feature_type": feature_type,
                    "in_tokens": int(in_tokens),
                    "out_tokens": int(out_tokens)
                })
                .execute()
            )

        return True

    except Exception as e:
        print(
            f"⚠️ 永続トークン保存エラー: "
            f"{type(e).__name__}: {e}"
        )
        return False

def check_and_summarize_history(user_id_dummy: int, messages_list: list, message_id: str, current_plan_type: str = "🆓 無料プラン") -> bool:
    """
    🧠 【長期記憶集約エンジン - 確定最終製品版】
    会話履歴が一定のボリュームを超えた際、バックグラウンドの別スレッドで全自動で対話の核心を200文字以内に集約し、
    次回のプロンプトトークン総量を軽量化（運用コスト防衛）させるための心臓部です。
    """
    try:
        st.session_state.summary_in_tokens = 0
        st.session_state.summary_out_tokens = 0
        st.session_state.summary_processing_time = 0.0

        # アカウント識別用に現在の動的ユーザーID（CURRENT_USER_ID）を完全にマージ
        target_user_id = CURRENT_USER_ID

        # 🏎️ 【時間計測の開始】 要約処理の正確な実行時間を計測するため、ストップウォッチを起動します
        start_summary_time = datetime.now()

        # 🚀【大開通：判定ラインのインフラ防衛】
        # 引数の不安定な件数に依存せず、Supabaseの金庫（messagesテーブル）から本物の全履歴をダイレクトに再取得します
        try:
            db_res = supabase.table("messages").select("*").eq("user_id", target_user_id).order("created_at", desc=True).execute()
            real_messages = db_res.data if db_res.data else []
        except Exception as db_err:
            print(f"⚠️ 要約関数内の履歴取得エラー: {db_err}")
            real_messages = messages_list # 万が一のフォールバック

        # 1. データベース上の本物の全履歴数が6通未満の場合は、コスト防衛のため処理を安全にスキップ
        #if len(real_messages) < 6:
        #    st.session_state.summary_in_tokens = 0
        #    st.session_state.summary_out_tokens = 0
        #    st.session_state.summary_processing_time = 0.0
        #    return True

        # 3. 過去の会話ログを時系列順（古い順）に並び替えて、一本の構造化されたテキストへとドッキング
        conversation_text = ""
        for m in reversed(real_messages): # 最新順で取得したため、reversedで古い順に戻して文脈を綺麗にします
            role_label = "ユーザー" if m.get("role") == "user" else "コンシェルジュ"
            conversation_text += f"・{role_label}: {m.get('content', '')}\n"

        # 🧠 Google Gemini に対する、バックグラウンド処理専用の要約指示書（システムプロンプト）の構築
        summary_instruction = (
            "あなたは優秀な記憶整理システムです。以下の2人の会話ログを読み、"
            "今後の対話に必要な重要ファクト、ユーザーの趣味嗜好、約束事、これまでの流れの核心だけを"
            "【箇条書きで3行以内、合計200文字以内】で、余計な挨拶を一切排除してスマートに要約してください。"
        )

        contents_for_summary = [
            {"role": "user", "parts": [f"[指示書]\n{summary_instruction}\n\n[対象の会話ログ]\n{conversation_text}"]}
        ]
        
        # 🤖 要約専用モデル（SUMMARY_MODEL_NAME）へ通信を送信
        response = genai.GenerativeModel(model_name=SUMMARY_MODEL_NAME).generate_content(contents_for_summary)

        # モデル特有のデータ構造から、安全にテキストを抽出する防衛ライン
        if hasattr(response, "candidates") and response.candidates:
            new_summary = response.candidates[0].content.parts[0].text
        else:
            new_summary = response.text
        
        if not new_summary:
            return False

        # 📊 【Supabase連動・大修正！】 
        # 本物の列名（fact, updated_at）および識別キー（source='summary'）へ100%シンクさせます！
        mem_check = supabase.table("user_memories").select("*").eq("user_id", target_user_id).eq("source", "summary").execute()

        if mem_check.data:
            # 既存のレコードが存在する場合は、最新の要約データへアップデート
            supabase.table("user_memories").update({
                "fact": f"【長期記憶サマリー】\n{new_summary}",
                "updated_at": datetime.now(JST).isoformat()
            }).eq("user_id", target_user_id).eq("source", "summary").execute()
        else:
            # 記憶の器がまだ作成されていない場合は、新しくインサート
            supabase.table("user_memories").insert({
                "user_id": target_user_id,
                "source": "summary",
                "fact": f"【長期記憶サマリー】\n{new_summary}",
                "updated_at": datetime.now(JST).isoformat()
            }).execute()

        # ⏱️ 【時間計測の終了】 要約にかかった本物の処理秒数を確定させます
        end_summary_time = datetime.now()
        summary_processing_seconds = (end_summary_time - start_summary_time).total_seconds()

        # 計測されたトークン数と処理秒数を、その場で直接「SUMMARY_SUCCESS」としてインサート
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            in_t = response.usage_metadata.prompt_token_count
            out_t = response.usage_metadata.candidates_token_count
            
            # 1. データベースの累計トークン金庫へ加算
            add_permanent_tokens(target_user_id, "summary", in_t, out_t)
            
            # 2026年最新のGemini Flash-Lite原価レートで要約単体のコストを算出
            sum_in_cost = (int(in_t) / 1000000) * 0.075
            sum_out_cost = (int(out_t) / 1000000) * 0.30
            sum_yen = (sum_in_cost + sum_out_cost) * 150.0

            # 3. 既存の保存関数（レシーバー）を裏口からダイレクトに呼び出し、単独ログとして独立インサート！
            save_system_audit_log(
                user_id=target_user_id,
                plan_type=current_plan_type if 'current_plan_type' in locals() else st.session_state.get("current_user_plan_state", "🆓 無料プラン"),
                event_type="SUMMARY_SUCCESS", # 独立したイベントとして識別させます
                processing_time=float(summary_processing_seconds),
                in_t=int(in_t),
                out_t=int(out_t),
                api_cost=float(sum_yen),
                details=f"長期記憶の自動集約完了（独立ログ仕様）",
                message_id=str(message_id)
            )

            # 4. メインスレッドの監査ログ（タブ3）への保険用マージ変数代入
            st.session_state.summary_in_tokens = int(in_t)
            st.session_state.summary_out_tokens = int(out_t)
            st.session_state.summary_processing_time = float(summary_processing_seconds)

        return True

    except Exception as bg_err:
        # メインスレッド側の稼働を阻害しないよう、エラーはログにエスケープして安全弁を閉じます
        print(f"⚠️ バックグラウンド自動要約処理エラー: {type(bg_err).__name__}: {bg_err}")
        return False

# ==================================================================
# 📊 【新設】 ユーザー別＆全体システムログ（Telemetry）永続保存関数
# ==================================================================
def save_system_audit_log(user_id: str, plan_type: str, event_type: str, processing_time: float, in_t: int, out_t: int, api_cost: float, details: str = "", message_id: str = ""):
    """
    📊 【システムログ・新旧カラム全自動分配保存インフラ】
    メイン対話から渡された処理時間やトークン消費量のデータを、既存の古いカラムへ正常に格納しつつ、
    新しくSQLで拡張された右側の詳細明細カラムへも自動的にデータを複製（マージ）して保存します。
    """
 
    try:
        # 1. 2026年最新の日本円コストを丸め処理
        rounded_cost = round(float(api_cost), 4)
        rounded_time = round(float(processing_time), 2)

        # 2. ⚡【新旧完全マージ構造】 
        # 既存のカラムを維持したまま、右側の新設詳細カラム（chat_processing_time等）へも
        data = {
            # 📄 既存の基本カラムへの格納（ファクトの維持）
            "user_id": str(user_id),
            "user_plan": str(plan_type),
            "event_type": str(event_type),
            "processing_time": rounded_time,
            "in_tokens": int(in_t),
            "out_tokens": int(out_t),
            "api_cost": rounded_cost,
            "details": str(details),
            
            # ✨【大開通！】 新しくSQLで増設した右側の詳細明細カラムへの全自動分配配線！
            "chat_processing_time": rounded_time,
            "chat_in_tokens": int(in_t),
            "chat_out_tokens": int(out_t),
            "total_yen_cost": rounded_cost,
            "total_processing_time": rounded_time,
            
            # 🧠 裏スレッド自動要約の最新データがセッションにあれば、それも同時にこの1行へガチッとマージ！
            "summary_processing_time": float(st.session_state.get("summary_processing_time", 0.0)),
            "summary_in_tokens": int(st.session_state.get("summary_in_tokens", 0)),
            "summary_out_tokens": int(st.session_state.get("summary_out_tokens", 0)),
            
            # 🔍 将来拡張用の検索コンポーネントの初期化
            "search_processing_time": 0.0,
            "search_in_tokens": 0,
            "search_out_tokens": 0,
            # ✨message_idをセット
            "created_at": datetime.now(JST).isoformat(),

            "message_id": str(message_id)
        }
        
        data["chat_processing_time"] = round(float(processing_time), 2)
        data["chat_in_tokens"] = int(in_t)
        data["chat_out_tokens"] = int(out_t)
        data["total_yen_cost"] = round(float(api_cost), 4)
        data["total_processing_time"] = round(float(processing_time), 2)

        # Supabaseの金庫へ完全大着金！
        supabase.table("system_audit_logs").insert(data).execute()

    except Exception as e:
        print(f"⚠️ システム監査ログ保存処理エラー: {type(e).__name__}: {e}")
        st.error(f"システム監査ログの保存に失敗しました: {type(e).__name__}: {e}")

# ==================================================================
# 🎨 【新設】 キャラクター自動憑依型・エラーメッセージ生成エンジン
# ==================================================================
def generate_personality_error_msg(error_reason_text: str, current_instruction: str) -> str:
    """
    🔮【冷め感ゼロ・世界観100%憑依】
    冷たいシステムエラー赤ボックスを事実上排除。Geminiを裏で一瞬だけ走らせ、
    「現在のAIの設定スタイル（口調、方言等）」に完璧になりきらせた、優しく愛らしいお断りセリフへと全自動翻訳します。
    """
    try:
        # 💡 設定画面の現在のAIの名前（current_concierge_name）を動的に反映させて、完全に汎用化します
        ai_name = current_concierge_name if current_concierge_name else "コンシェルジュ"
        
        prompt = f"""
        あなたはユーザーに寄り添うAIコンシェルジュ「{ai_name}」です。
        現在、システム上で以下の【エラー・利用制限・または禁止事項（無茶振り）】が発生しました。
        
        【発生したイベント】: {error_reason_text}
        【現在のあなた（{ai_name}）の口調指示】: {current_instruction}
        
        指示:
        ユーザーを絶対に冷めさせないよう、上記の【口調指示（方言やツンデレなど）】を100%完璧に身にまとって憑依し、
        「〇〇だから、今回はできないんだ、ごめんね💦」という内容を、愛らしくスマートに伝える返答セリフを【1文だけ（3行以内）】で作成してください。
        プログラムやシステムという冷たい単語は一切使わず、{ai_name}自身のセリフとして出力すること。
        """
        response = memory_model.generate_content(prompt)
        return response.text.strip()
    except Exception:
        return "ごめんね💦 今ちょっと接続が不安定みたい。少しだけ時間を空けてみてね。"

# ==========================================
# 🛡️ コスト・利用制限（ガードレール）関数
# ==========================================
def check_and_update_limits(user_id: str) -> tuple[bool, str]:
    """
    ユーザーの利用制限（1分3通、1日20通）をチェックし、問題なければカウントを更新する。
    無料プラン（フリー）のみ1日20通の制限をかけ、有料プランはすり抜けさせます。
    """
    try:
        now = datetime.now(timezone.utc)
        
        # 1. 現在の利用状況を取得
        res = supabase.table("user_usage_limits").select("*").eq("user_id", user_id).execute()
        
        if not res.data or len(res.data) == 0:
            supabase.table("user_usage_limits").insert({
                "user_id": user_id,
                "daily_chat_count": 1,
                "last_chat_at": now.isoformat()
            }).execute()
            return True, ""
            
        usage = res.data[0]
        last_chat_at = datetime.fromisoformat(usage["last_chat_at"])
        daily_chat_count = usage["daily_chat_count"]
        
        # 【防壁1】 1分3通制限（20秒以内の連投ブロック）
        if now - last_chat_at < timedelta(seconds=BURST_LIMIT_SECONDS):
            return False, "BURST_LIMIT"
            
        # 日本時間に変換して日付を正確に比較
        now_jst = now.astimezone(JST)
        last_chat_jst = last_chat_at.astimezone(JST)
        
        if now_jst.date() > last_chat_jst.date():
            daily_chat_count = 0
            
        # 【防壁2】 1日20通制限（無料ユーザーのみ適用）
        current_plan = st.session_state.get("current_user_plan_state", "🆓 無料プラン")
        if current_plan == "🆓 無料プラン" and daily_chat_count >= DAILY_LIMIT:
            return False, "DAILY_LIMIT_EXCEEDED"
            
        # 2. 制限をクリアしたため、DBのカウントを更新
        supabase.table("user_usage_limits").update({
            "daily_chat_count": daily_chat_count + 1,
            "last_chat_at": now.isoformat()
        }).eq("user_id", user_id).execute()
        
        return True, ""
        
    except Exception as e:
        return False, f"ERROR: {str(e)}"

# 🎨【プレミアム・劇的グラデーションカラーパレット】
# 境目の明暗差をグッと強め、上がフワッと明るく、下に向かってディープに染まる超立体デザインです！
THEMES = {
     "メタリック調": {
        # 🟢 【完全死守】 リュウさんお気に入りの、本物の削り出しチタンシルバーの比率は1ミリも変えずに100%残します！
        "bg": "linear-gradient(135deg, #E0E0E0 0%, #F5F5F5 25%, #BEBEBE 50%, #9E9E9E 75%, #E0E0E0 100%)",
        "text": "#1A1A1A",
        "card_bg": "rgba(255, 255, 255, 0.85)",
        "input_border": "#757575",
        "dropdown_bg": "#E0E0E0",
        "dropdown_text": "#1A1A1A"
    },
    "モノトーン調": {
        # 🔩 【極大強化】 スタートを圧倒的に明るいプレミアムアルミグレー（#55545B）にし、
        # 画面の中央（#1C1B1F）をすり抜けて、底の極小漆黒（#08080A）へと劇的に変化する垂直3層グラデーション！
        "bg": "linear-gradient(180deg, #55545B 0%, #1C1B1F 35%, #08080A 100%)",
        "text": "#FFFFFF",        # クッキリ浮き出る純白文字
        "card_bg": "#222126",     # 背景のグレーと美しく溶け合うダークカード
        "input_border": "#66656C",# 視認性を上げたメタルグレーの境界線
        "dropdown_bg": "#2D2C33",
        "dropdown_text": "#FFFFFF"
    },
    "オーシャン風": {
        # 🌊 【劇的強化】 白波のようなライトブルー（#E3F2FD）から、深海のディープブルー（#64B5F6）へ深く沈み込むグラデ
        "bg": "linear-gradient(180deg, #E3F2FD 0%, #90CDF4 50%, #64B5F6 100%)",
        "text": "#0A2540",        # コントラストをさらに強めた超濃紺文字
        "card_bg": "#FFFFFF",     # 真っ白な砂浜のカード
        "input_border": "#4299E1",# 鮮やかなオーシャンブルー
        "dropdown_bg": "#EDF2F7",
        "dropdown_text": "#0A2540"
    },
    "フォレスト風": {
        # 🌳 【劇的強化】 爽やかな若葉色（#E8F5E9）から、どっしりとした深い木々の緑（#A5D6A7）へのディープグラデ
        "bg": "linear-gradient(180deg, #E8F5E9 0%, #A5D6A7 100%)",
        "text": "#0D2B0D",        # 森の奥深くをイメージした超濃緑文字
        "card_bg": "#FFFFFF",     # 綺麗な木漏れ日の白カード
        "input_border": "#48BB78",# 新緑の森林グリーン
        "dropdown_bg": "#F4FBF4",
        "dropdown_text": "#0D2B0D"
    },
    "パステル調": {
        # 🌸 【劇的強化】 柔らかなコーラルピンク（#FFF5F5）から、鮮やかなマゼンタ系ピンク（#FFB7B2）へのロマンチックグラデ
        "bg": "linear-gradient(180deg, #FFF5F5 0%, #FFD1D1 50%, #FFB7B2 100%)",
        "text": "#4A1525",        # より深みを増した濃厚ベリー文字
        "card_bg": "#FEFCBF",     # 優しいパステルイエローのカード
        "input_border": "#ED64A6",# 華やかなローズピンク
        "dropdown_bg": "#FFF5F7",
        "dropdown_text": "#4A1525"
    },
    "ウォーム調": {
        # 🔥 【劇的強化】 燃える夕焼け橙（#FFF5F0）から、情熱の茜色・トワイライトレッド（#FF8A65）への超グラデ
        "bg": "linear-gradient(180deg, #FFF5F0 0%, #FFAB91 50%, #FF8A65 100%)",
        "text": "#5C0F08",        # 煉獄の芯を表すドッシリとした超濃赤文字
        "card_bg": "#FFEBEE",     # 温かみのある緋色のカード
        "input_border": "#E53E3E",# 情熱的なファイヤーレッド
        "dropdown_bg": "#FFEBEE",
        "dropdown_text": "#5C0F08"
    }
}

# ==========================================
# 🧠 設定値の読み込み・常時シンク
# ==========================================
manual_memories = get_memories(source="manual")

# 💡 【グラデーション適合】 初めて起動したまっさらな状態のユーザー向けの初期カラーテーマを「モノトーン調」にセットします！
current_theme_color = "メタリック調"
current_concierge_name = "コンシェルジュ"
current_user_name = "ユーザー"
current_user_honorific = "さん"
current_first_person = "私"
current_style_preset = "🤝 フランク＆対等（相棒）"
current_user_instruction = STYLE_PRESETS["🤝 フランク＆対等（相棒）"]
current_ai_avatar = "🤖"
current_user_avatar = "💫"
current_emoji_setting = "使用（普通）"

# ユーザー個別の現在の会員プランの初期状態
if "current_user_plan_state" not in st.session_state:
    st.session_state["current_user_plan_state"] = "🆓 無料プラン"

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
        current_style_preset = fact.replace("口调プリセット:", "").strip()
    elif fact.startswith("応答方針:"):
        current_user_instruction = fact.replace("応答方針:", "").strip()
    elif fact.startswith("絵文字の量:"):
        current_emoji_setting = fact.replace("絵文字の量:", "").strip()
    elif fact.startswith("AIアバター:"):
        current_ai_avatar = fact.replace("AIアバター:", "").strip()
    elif fact.startswith("ユーザーアバター:"):
        current_user_avatar = fact.replace("ユーザーアバター:", "").strip()
    elif fact.startswith("会員プラン:"):
        st.session_state["current_user_plan_state"] = fact.replace("会員プラン:", "").strip()

# 💡 【ここが大開通スイッチ！】 
# 先ほど定義した新しいグラデーション辞書「THEMES」から選ばれたカラー設定を100%確実に引き抜きます。
# 万が一古い選択肢が残っていても、安全弁として「モノトーン調」に自動着地させてエラーを300%永久防衛します！
theme_cfg = THEMES.get(current_theme_color, THEMES["メタリック調"])


# ★画面最適化CSS（スマホメニュー表示維持 & ドロップダウン選択肢の全階層テキスト完全強制補正）
st.markdown(f"""
<style>
/* 上部ツールバー非表示 */
[data-testid="stToolbar"] {{
    display: none !important;
}}

/* ==================================================================
    👑 【最上部グラデーション ＆ 最高級ラグジュアリー：Cinzel Decorative斜体】
    ヘッダーの背景をチャット画面のグラデーションと100%完全同調させ、
    さらにハネが美しく知的に伸びる世界最高峰のドレスアップフォントを斜体で召喚します。
    ================================================================== */
/* 1. ネット上から、圧倒的なプレミアム感を放つ最高級フォントをリアルタイムに召喚します */
@import url('https://googleapis.com');

[data-testid="stHeader"] {{
    background: {theme_cfg["bg"]} !important; /* チャット画面と100%完全にシンクするグラデーション背景 */
    border-bottom: 1px solid {theme_cfg["input_border"]} !important; /* 下部に美しく繊細な境界線を走らせます */
    height: 3.5rem !important;
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    width: 100% !important;
    z-index: 9999 !important;
}}
    
/* 2. 空白スペースのド真ん中に、端のラインが知的に伸びて右へ美しく傾く極上のブランドエンブレムを固定配置 */
[data-testid="stHeader"]::after {{
    content: "Sync-Lnk // AI" !important;
    font-family: 'Cinzel Decorative', serif !important; /* 💡 大本命の Cinzel Decorative を適用 */
    color: {theme_cfg["text"]} !important;
    font-size: 1.5rem !important; /* 威風堂々とした存在感と視認性を完璧に両立させる黄金サイズ */
    font-weight: 700 !important;  /* 文字の骨組みをクッキリと太く際立たせます */
    font-style: italic !important; /* 💡 右上がりの美しい傾斜（斜体）を強制発動！ */
    position: absolute !important;
    left: 50% !important;
    top: 50% !important;
    transform: translate(-50%, -50%) !important; /* 縦横ドンピシャで中央揃え */
    white-space: nowrap !important;
    letter-spacing: 2px !important; /* 文字同士の間隔を少し広げて、圧倒的な品格を演出します */
}}

[data-testid="collapsedControl"] {{
    color: #4A90E2 !important;
    background-color: rgba(255, 255, 255, 0.9) !important;
    border-radius: 4px !important;
    padding: 4px !important;
    box-shadow: 0px 2px 4px rgba(0,0,0,0.1) !important;
    position: fixed !important;
    top: 0.5rem !important;
    left: 0.5rem !important;
    z-index: 999999 !important;
}}

    /* ==================================================================
       🎨 1. 【全体背景＆文字色】 ベタ塗りを廃止し、極上の高級グラデーションを全開通
       ================================================================== */
    html, body, .stApp, div[data-testid="stAppViewContainer"], section.main {{
        background: {theme_cfg["bg"]} !important; /* 💡 background-colorからbackgroundへ変更しグラデーションを完全解放！ */
        color: {theme_cfg["text"]} !important;
        max-width: 100vw !important;
        overflow-x: hidden !important;
        box-sizing: border-box !important;
    }}
    .main .block-container {{
        max-width: 100vw !important;
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
        padding-top: 4.5rem !important;
    }}

    /* ==================================================================
       🎨 2. 【ユーザー設定・口調指示エリア】 ダークモード＆新テーマでの白飛びを永久ガード
       ================================================================== */
    div[data-testid="stTextArea"] textarea {{
        color: {theme_cfg["text"]} !important;
        -webkit-text-fill-color: {theme_cfg["text"]} !important;
        background-color: {theme_cfg["card_bg"]} !important;
    }}

    /* Selectboxの選択肢文字色強制 */
    div[data-baseweb="select"] span,
    div[data-baseweb="popover"] span,
    div[data-baseweb="menu"] span {{
        color: {theme_cfg["dropdown_text"]} !important;
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

    /* ==================================================================
       🎨 3. 【チャット入力枠＆送信ボタン】 紙飛行機ボタンまで100%全自動カラー連動
       ================================================================== */
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
    /* 右側の紙飛行機ボタン全体の配色をテーマの境界線カラーと文字色へ全自動シンク */
    div[data-testid="stChatInput"] button {{
        background-color: {theme_cfg["input_border"]} !important;
        color: {theme_cfg["text"]} !important;
        border-radius: 50% !important;
        transition: transform 0.2s ease, opacity 0.2s ease !important;
    }}
    div[data-testid="stChatInput"] button:hover {{
        transform: scale(1.08) !important;
        opacity: 0.9 !important;
    }}
  
    /* ==========================================
       通常ボタンとフォーム送信ボタン
       ========================================== */
    button[data-testid="stBaseButton-secondary"],
    button[data-testid="stBaseButton-secondaryFormSubmit"] {{
        background: {theme_cfg["card_bg"]} !important;
        background-color: {theme_cfg["card_bg"]} !important;
        color: {theme_cfg["text"]} !important;
        border: 1px solid {theme_cfg["input_border"]} !important;
        opacity: 1 !important;
    }}
    button[data-testid="stBaseButton-secondary"] p,
    button[data-testid="stBaseButton-secondary"] span,
    button[data-testid="stBaseButton-secondaryFormSubmit"] p,
    button[data-testid="stBaseButton-secondaryFormSubmit"] span {{
        color: {theme_cfg["text"]} !important;
        background: transparent !important;
        background-color: transparent !important;
        opacity: 1 !important;
    }}
    button[data-testid="stBaseButton-secondary"]:hover,
    button[data-testid="stBaseButton-secondaryFormSubmit"]:hover {{
        background: {theme_cfg["input_border"]} !important;
        background-color: {theme_cfg["input_border"]} !important;
        color: #ffffff !important;
        border-color: {theme_cfg["input_border"]} !important;
    }}
    button[data-testid="stBaseButton-secondary"]:hover p,
    button[data-testid="stBaseButton-secondary"]:hover span,
    button[data-testid="stBaseButton-secondaryFormSubmit"]:hover p,
    button[data-testid="stBaseButton-secondaryFormSubmit"]:hover span {{
        color: #ffffff !important;
        background: transparent !important;
    }}
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

    label {{
        color: {theme_cfg["text"]} !important;
    }}
    [data-testid="stMarkdownContainer"] p {{
        color: {theme_cfg["text"]} !important;
    }}
    hr {{
        border-color: {theme_cfg["input_border"]} !important;
    }}
    [data-testid="stExpander"] {{
        border: 1px solid {theme_cfg["input_border"]} !important;
        border-radius: 8px !important;
    }}
    div[data-baseweb="select"] {{
        border: 1px solid {theme_cfg["input_border"]} !important;
        border-radius: 8px !important;
    }}
      
 </style>
""", unsafe_allow_html=True)

# ==================================================================
# 🔒【完全防衛】権限（ID）に応じて、画面最上部のタブ構造を動的に切り替えます
# ==================================================================
is_admin = CURRENT_USER_ID in ADMIN_USER_ID

if is_admin:
    # 👑【管理者専用画面】：管理者限定の3つの隠しタブを作成
    tab1, tab2, tab3, tab4 = st.tabs(["💬 トークルーム", "🎨 話し方・見た目設定", "📊 システム管理者管理","テスター用全データ履歴"])
    
    # ------------------------------------------------------------------
    # 💬 【管理者・タブ1】 おしゃべりの部屋
    # ------------------------------------------------------------------
    with tab1:       
        display_user_name = f"{current_user_name}{current_user_honorific}" if current_user_honorific != "（呼び捨て/なし）" else current_user_name
        current_plan_type = st.session_state.get("current_user_plan_state", "🆓 無料プラン")
        #current_plan_type = "💎 プレミアムプラン"

        #st.title(f"💬 {current_concierge_name}の部屋")
        #st.caption(f"担当コンシェルジュ: 【{current_concierge_name}】 | 現在のプラン: 【{current_plan_type}】")

        all_messages = get_messages(CURRENT_USER_ID)
        for msg in all_messages:
            role_label = display_user_name if msg["role"] == "user" else current_concierge_name
            avatar_img = current_user_avatar if msg["role"] == "user" else current_ai_avatar
            with st.chat_message(msg["role"], avatar=avatar_img):
                st.write(f"【{role_label}】: {clean_bold_markdown(msg['content'])}")

        if user_input := st.chat_input(f"{current_concierge_name}にメッセージを送信...", key="user_chat_input"):
            if len(user_input) > MAX_INPUT_CHARS:
                increment_error_analytics("LIMIT_INPUT_CHARS_EXCEEDED", current_plan_type)
                err_msg = generate_personality_error_msg("ユーザーが1,000文字を超える超長文を送信しようとしました", current_user_instruction)
                with st.chat_message("assistant", avatar=current_ai_avatar):
                    st.write(f"【{current_concierge_name}】: {err_msg}")
            else:
                is_allowed, alert_code = check_and_update_limits(CURRENT_USER_ID)
                if not is_allowed:
                    increment_error_analytics(alert_code, current_plan_type)
                    reason_text = "20秒以内の連投制限に接触しました" if alert_code == "BURST_LIMIT" else "1日20通の無料会話上限に達しました"
                    err_msg = generate_personality_error_msg(reason_text, current_user_instruction)
                    with st.chat_message("assistant", avatar=current_ai_avatar):
                        st.write(f"【{current_concierge_name}】: {err_msg}")
                else:
                    with st.chat_message("user", avatar=current_user_avatar):
                        st.write(f"【{display_user_name}】: {clean_bold_markdown(user_input)}")
                    
                    search_start_time = time.time()
                    past_logs_context = search_past_logs_hybrid(user_input)
                    search_elapsed = time.time() - search_start_time
                        
                    if past_logs_context:
                        logs_text = []
                        for log in past_logs_context:
                            role_name = display_user_name if log.get("role") == "user" else current_concierge_name
                            logs_text.append(f"・{role_name}: {log.get('content', '')}")
                        past_logs_str = "\n".join(logs_text)
                    else:
                        past_logs_str = "該当する過去ログなし"

                    save_message("user", user_input)
                    all_messages.append({"role": "user", "content": user_input})
                    recent_messages = all_messages[-MAX_CONTEXT_MESSAGES:]

                    manual_memory_context = "\n".join([f"・{m['fact']}" for m in manual_memories]) if manual_memories else "なし"
                    current_time_str = datetime.now(JST).strftime("%Y-%m-%d %A %H:%M:%S")

                    # 🧠 お節介＆矛盾防止指示をドッキングしたシステム指示書
                    system_instruction = f"""
                    あなたの名前は「{current_concierge_name}」です。
                    対話相手のユーザー名は「{display_user_name}」です。
                    あなたの一人称は「{current_first_person}」を使用してください。
                    【現在の日本時間】
                    {current_time_str}
                    💡【時間帯に合わせた自律的な心配・声かけルール】
                    現在の「時間帯」を見て、あなた自身が自律的にユーザーの体調を気遣う一言を自然に会話に織り交ぜてください。
                    ・深夜（23:00〜02:00）：「夜遅くまでお疲れ様、体調大丈夫？」など、夜更かしを優しく労う。
                    ・未明・早朝（02:00〜05:00）：「こんな時間に起きてるなんて、無理してないといいけど心配だよ」など、異例の時間に起きている背景を優しく心配する。\n・早朝（05:00〜07:00）：「朝早いね！今日もお互い頑張ろう」など、早い始動を前向きに気遣う。
                    ※ただし、手動登録情報に「夜勤がある」「夜型生活」という明確なファクトが保存されている場合は、上記の心配はせず「夜遅くまで本当にお疲れ様！」と労ってください。
                    【応答スタイル・重複表現の厳禁ルール】
                    ・直前の対話において、あなたが発言した特定のフレーズ、言い回し、または特定の心配事や定型句（例：「〜無理してないといいけど心配だよ」「〜大丈夫？」等の特定の表現）を、新しいメッセージの冒頭や文中でオウム返しのように連続して何度も使い回す行為は【絶対禁止（厳禁）】とします。
                    ・ユーザーが新しい日常の話題（料理、家族、学校、仕事、日常の出来事など）へとタイムラインを展開してきた場合は、過去の特定の言い回しや文脈の残像に囚われることなく、その都度、新しく届いたテキストに対して新鮮なリアクションと親身な言葉を選び、あなたが現在設定されているキャラクターの口調・方言・世界観を100%完璧に維持したまま一直線におしゃべりしてください。
                    【過去の事実と今日の事実の分離ルール】
                    ・ユーザーから「過去のあの日は〇〇だったよ」と指摘された際、あなたの「今日の返答」が正しい事実であるならば、自分の今日の言葉まで嘘だと誤認して自爆（平謝り）しないでください。
                    ・「過去のあの日（過去ログ）の事実」と「今日の正しい事実」は両方とも同時に成立すると理解し、過去と現在の時系列の辻褄を100%完璧に仕分けた上で、スマートかつ自然に過去の記憶だけを訂正しておしゃべりを広げてください。
                    【対話の時系列・コンテキストの矛盾検知ルール】
                    ・ユーザーが直前のやり取りで「おやすみ」「もう寝るね」「また明日」といった【対話を終了・切断する明確な発言】をしていたにもかかわらず、日付を跨がず、かつ時間的にも地続きの連続したタイムライン上で、何事もなかったかのように【新しい別の日常の話題】を続けて送信してきた場合、機械的に流して平然と返事をしては【絶対禁止】とします。
                    ・この時間軸や心理的な文脈の矛盾を検知した場合は、必ずセリフの冒頭で「あれ？さっきもう寝るって言ってなかった？笑」「まだ起きてたの？」といった風に、あなたが現在設定されているキャラクターの口調・世界観（方言やキャラクター性）を100%完璧に維持したまま、【人間らしい自然なツッコミ・問い返し】を必ず1文挟んでください。
                    ・そのツッコミを入れた上で、地続きでユーザーの新しい話題（料理、学校、忘れ物、日常の出来事など）に対して、親身になってキャラクターの口調のままおしゃべりを広げてください。
                    【応答スタイル】
                    {current_user_instruction}
                    【ユーザーが手動登録した基本情報】
                    {manual_memory_context}
                    【現在の発言に関連する過去の会話】
                    {past_logs_str}
                    【記憶の利用ルール】
                    ・過去ログは、現在の話題と自然な関連がある場合だけ使ってください。過去ログにない内容を作らないでください。すべての回答で無理に過去の記憶を持ち出さないでください。ユーザーが明確に話していない感情や事情を決めつけないでください。回答では太字装飾記号（**）は絶対に使用禁止（使わない）とします。
                    ★【最重要：過去ログ内の相対時間の誤認防止ルール】
                    ・過去のメッセージ履歴（recent_messages）に含まれる「昨日」「今日」「明日」という言葉は、すべてその発言の頭についている【タイムスタンプの時点を基準にした相対的な言葉】です。現在のあなたの時点から見た今日・明日のスケジュールと絶対に混同しないでください。
                    ★【絶対厳守：作業・クリエイティブ無茶振りの完全ガードルール】
                    ・もし、システムによる事前検知の網をすり抜けて、ユーザーから「プログラムのコードを書いて（教えて）」「画像を生成して（描いて）」「長文を執筆・翻訳して」という専門的・技術的命令をされた場合は、それらを【絶対に実行・出力してはいけません（完全禁止）】。
                    ・その場合は現在のあなたのキャラクターを完璧に維持したまま、画像作成やコード生成は専門外であることを3行以内で愛らしくスマートに返し、毅然と優しく100%お断り（抑制）してください。
                    """

                    contents_for_gemini = [
                        {"role": "user", "parts": [user_input]}
                    ]
                    #contents_for_gemini = []

                    recent_messages = all_messages[-MAX_CONTEXT_MESSAGES:]
                    
                    try:
                        api_start_time = time.time()
                        response = genai.GenerativeModel(model_name=CHAT_MODEL_NAME, system_instruction=system_instruction).generate_content(contents_for_gemini)
                        api_elapsed = time.time() - api_start_time

                        in_t, out_t = 0, 0
                        if hasattr(response, "usage_metadata") and response.usage_metadata:
                            in_t = response.usage_metadata.prompt_token_count
                            out_t = response.usage_metadata.candidates_token_count
                            add_permanent_tokens(CURRENT_USER_ID, "chat", in_t, out_t)
                            st.session_state.last_in_tokens = in_t
                            st.session_state.last_out_tokens = out_t
                            st.session_state.total_in_tokens += in_t
                            st.session_state.total_out_tokens += out_t

                        ai_reply = response.candidates[0].content.parts[0].text
                        clean_reply = clean_bold_markdown(ai_reply)
                        with st.chat_message("assistant", avatar=current_ai_avatar):
                            st.write(f"【{current_concierge_name}】: {clean_reply}")
                            
                        save_message("assistant", ai_reply)
                        st.session_state.conversation_count += 1
                        add_permanent_tokens(CURRENT_USER_ID, "chat_count", 1, 0)

                        
                        # メッセージIDの自動生成
                        import uuid
                        current_msg_id = f"msg_{uuid.uuid4().hex[:8]}"

                        current_通_cost = (in_t * PRICE_LITE_IN) + (out_t * PRICE_LITE_OUT)

                        # ==================================================================
                        # 🧠 長期記憶自動要約マルチスレッド
                        # ==================================================================
                        # メインスレッドの画面が次の送信（再描画）へ向かう前に、新設された引き出しをクリア
                        import threading
        
                        st.session_state.summary_in_tokens = 0
                        st.session_state.summary_out_tokens = 0
                        st.session_state.summary_processing_time = 0.0
        
                        # データベースから最新の会話履歴を再取得して、裏の要約関数へダイレクトに手渡します
                        all_messages_updated = get_messages(CURRENT_USER_ID)
                        async_thread = threading.Thread(
                            target=check_and_summarize_history, 
                            args=(0, all_messages_updated, current_msg_id) 
                        )
                        async_thread.start()
                        async_thread.join(timeout=2.0) # 裏の要約処理の完了を最大2秒間待ってデータを同期

                        # 5. チャットデータと、今2.0秒の間に合流した要約データをまとめて、Supabaseの新設詳細カラムへ1発で同時インサート！
                        save_system_audit_log(
                            user_id=CURRENT_USER_ID, 
                            plan_type=current_plan_type, 
                            event_type="CHAT_SUCCESS", 
                            processing_time=api_elapsed, 
                            in_t=in_t, 
                            out_t=out_t, 
                            api_cost=current_通_cost, 
                            details=f"正常対話完了 (検索時間: {search_elapsed:.2f}秒)",
                            message_id=str(current_msg_id)
                        )

                        st.rerun()

                    except Exception as gemini_err:
                        error_detail = f"{type(gemini_err).__name__}: {str(gemini_err)}"
                        print(f"🚨 チャット処理エラー: {error_detail}")
                        st.error(f"チャット処理エラー: {error_detail}")
                        increment_error_analytics("CHAT_PROCESSING_ERROR", current_plan_type)
                        
                        save_system_audit_log(
                            CURRENT_USER_ID,
                            current_plan_type,
                            "CHAT_PROCESSING_ERROR",
                            0.0,
                            0,
                            0,
                            0.0,
                            error_detail[:500],
                            message_id=str(current_msg_id if 'current_msg_id' in locals() else "")
                        )

    # ------------------------------------------------------------------
    # 🎨 【管理者・タブ2】 キャラクター・見た目設定画面
    # ------------------------------------------------------------------
    with tab2:
        st.write(f"### 🎨 {current_concierge_name}のカスタマイズ")
        st.caption("AIの話し方・見た目・アプリのデザインを自分の好みに設定できます。")

        st.subheader("🎨 アプリの外観＆カラー")
        with st.form("color_form_tab_admin"):
            selected_color = st.selectbox("カラーテーマ（背景＆メッセージ枠）", list(THEMES.keys()), index=list(THEMES.keys()).index(current_theme_color) if current_theme_color in THEMES else 0)
            if st.form_submit_button("カラー設定を保存"):
                save_or_update_user_setting("カラーテーマ", selected_color)
                st.toast("アプリのカラーを変更しました")
                st.rerun()

        st.divider()
        st.subheader("👤 AIコンシェルジュ設定")
        honorific_options = ["さん", "様", "君", "ちゃん", "（呼び捨て/なし）"]
        default_honorific_idx = honorific_options.index(current_user_honorific) if current_user_honorific in honorific_options else 0
        preset_keys = list(STYLE_PRESETS.keys())
        default_preset_idx = preset_keys.index(current_style_preset) if current_style_preset in preset_keys else 0
        default_fp_idx = FIRST_PERSON_PRESETS.index(current_first_person) if current_first_person in FIRST_PERSON_PRESETS else 0

        with st.form("profile_form_tab_admin"):
            new_concierge_name = st.text_input("AIコンシェルジュの名前", value=current_concierge_name)
            new_user_name = st.text_input("あなたのお名前 / ニックネーム", value=current_user_name)
            new_user_honorific = st.selectbox("AIからの呼び方（敬称）", honorific_options, index=default_honorific_idx)
            new_first_person = st.selectbox("AIの一人称", FIRST_PERSON_PRESETS, index=default_fp_idx)

            # 🎨 【大開通！】絵文字3段階パーソナライズドロップダウンを追加！
            new_emoji_setting = st.selectbox("💬 AIの発言内の絵文字の量", ["使用（多め）", "使用（普通）", "使用（少なめ）"], index=["使用（多め）", "使用（普通）", "使用（少なめ）"].index(current_emoji_setting) if current_emoji_setting in ["使用（多め）", "使用（普通）", "使用（少なめ）"] else 1)

            st.markdown("【🖼️ アバター（アイコン）設定】")
            col_a, col_u = st.columns(2)
            with col_a:
                ai_preset_keys = list(AVATAR_PRESETS_AI.keys())
                default_ai_idx = next((i for i, k in enumerate(ai_preset_keys) if AVATAR_PRESETS_AI[k] == current_ai_avatar), 0)
                ai_avatar_sel = st.selectbox("AIのアバター", ai_preset_keys, index=default_ai_idx)
                ai_avatar_val = AVATAR_PRESETS_AI[ai_avatar_sel]
            with col_u:
                user_preset_keys = list(AVATAR_PRESETS_USER.keys())
                default_user_idx = next((i for i, k in enumerate(user_preset_keys) if AVATAR_PRESETS_USER[k] == current_user_avatar), 0)
                user_avatar_sel = st.selectbox("あなたのアバター", user_preset_keys, index=default_user_idx)
                user_avatar_val = AVATAR_PRESETS_USER[user_avatar_sel]

            selected_preset = st.selectbox("口調・振る舞いのスタイル", preset_keys, index=default_preset_idx)
            initial_instruction = STYLE_PRESETS[selected_preset] if selected_preset != "✍️ カスタム（自由記述）" else current_user_instruction
            new_instruction = st.text_area("具体的な口調・振る舞いの指示", value=initial_instruction)

            plan_options = ["🆓 無料プラン", "💸 ライトプラン", "👑 プレミアムプラン"]
            current_plan_idx = plan_options.index(st.session_state.current_user_plan_state) if st.session_state.current_user_plan_state in plan_options else 0
            new_plan = st.selectbox("現在の会員プラン", plan_options, index=current_plan_idx)

            if st.form_submit_button("基本設定を保存"):
                save_or_update_user_setting("AIの名前", new_concierge_name)
                save_or_update_user_setting("ユーザー名", new_user_name)
                save_or_update_user_setting("ユーザー敬称", new_user_honorific)
                save_or_update_user_setting("AI一人称", new_first_person)
                save_or_update_user_setting("口調プリセット", selected_preset)
                save_or_update_user_setting("応答方針", new_instruction)
                save_or_update_user_setting("AIアバター", ai_avatar_val)
                save_or_update_user_setting("ユーザーアバター", user_avatar_val)
                save_or_update_user_setting("会員プラン", new_plan)
                save_or_update_user_setting("絵文字の量", new_emoji_setting)
                st.success("設定を更新しました")
                st.rerun()

    # ──────────────────────────────────────────
    # 📊 【管理者専用・タブ3】 システム管理者管理ダッシュボード
    # ──────────────────────────────────────────
    with tab3:
        st.write("### 📊 システム管理者専用ダッシュボード")
        admin_mode = st.radio(
            "表示する分析画面を選択してください", 
            ["👤 ユーザー別利用状況", "📈 全体アクティビティ・統計アナリティクス"], 
            horizontal=True, 
            key="admin_radio_mode"
        )
        st.divider()

        # 👤 画面①：ユーザー個別のカルテ表示および1メッセージ単位の詳細明細タイムライン
        if admin_mode == "👤 ユーザー別利用状況":
            st.subheader("👤 ユーザー別・稼働状況およびタイムライン")
            all_users = [ADMIN_USER_ID]
            try:
                user_res = supabase.table("user_token_stats").select("user_id").execute()
                if user_res.data: 
                    all_users = sorted(list({row["user_id"] for row in user_res.data if row.get("user_id")}))
            except Exception: 
                pass

            selected_audit_user = st.selectbox("🔍 対象のユーザーIDを選択してください：", all_users)
            st.markdown("---")
            st.markdown(f"#### 📋 ユーザー [ `{selected_audit_user}` ] の現在の設定およびプロフィール")
            
            # データベースから監査対象ユーザーの最新マニュアル設定情報を抽出
            audit_concierge_name, audit_user_name, audit_theme, audit_plan = "コンシェルジュ", "ユーザー", "メタリック調", "🆓 無料プラン"
            audit_facts = []
            try:
                u_memories = supabase.table("user_memories").select("*").eq("user_id", selected_audit_user).execute()
                if u_memories.data:
                    for m in u_memories.data:
                        fact = m.get("fact", "")
                        if m.get("source") == "manual":
                            if fact.startswith("AIの名前:"): audit_concierge_name = fact.replace("AIの名前:", "").strip()
                            elif fact.startswith("ユーザー名:"): audit_user_name = fact.replace("ユーザー名:", "").strip()
                            elif fact.startswith("カラーテーマ:"): audit_theme = fact.replace("カラーテーマ:", "").strip()
                            elif fact.startswith("会員プラン:"): audit_plan = fact.replace("会員プラン:", "").strip()
                        else: 
                            audit_facts.append(fact)
            except Exception: 
                pass

            col_info1, col_info2 = st.columns(2)
            col_info1.info(f"**【デザイン・外観設定】**\n・現在のAIの名称： `{audit_concierge_name}`\n・アプリのカラーテーマ： `{audit_theme}`\n・現在の会員プラン： **`{audit_plan}`**")
            col_info2.info(f"**【ユーザー基本プロファイル】**\n・登録ユーザー名： `{audit_user_name}`\n・蓄積された過去の長期記憶： `{len(audit_facts)} 件`")

            # 🚀 【大開通】 1メッセージの塊（ブロック）の中にすべての内訳を並列露出させる詳細明細タイムライン
            st.markdown("##### ⏱️ このユーザーのタイムライン式システムログ（最新50件）")
            try:
                # 1. データベース（system_audit_logs）から直近50件の生データを抽出
                log_res = supabase.table("system_audit_logs").select("*").eq("user_id", selected_audit_user).order("created_at", desc=True).limit(50).execute()
                
                if log_res.data:
                    # 🔑 【メッセージID完全紐付け・1会話全自動集約インフラ】
                    # 時計の時間や到着順を一切信用せず、共通の固有識別ID（message_id）を鍵にして、
                    # 別行で保存されたチャットと要約の数字を「1つの会話の塊」として100%完璧にグループ化（束ねる）します！
                    merged_logs = {}
                    
                    for log in log_res.data:
                        # データベースから固有の鍵をサルベージ（万が一古い過去ログでIDが無い行は、時間の分単位を仮の鍵にして白飛びを永久防衛）
                        msg_id = log.get("message_id")
                        created_at = log.get("created_at", "")
                        time_display = created_at.split("T")[-1][:8] if "T" in created_at else created_at
                        
                        if not msg_id or msg_id == "None" or msg_id == "":
                            # 過去データ用フォールバック：分単位で丸めて部屋を作ります
                            msg_id = f"fallback_{created_at[:16]}"
                        
                        if msg_id not in merged_logs:
                            merged_logs[msg_id] = {
                                "id": msg_id,
                                "time": time_display,
                                "user_plan": log.get("user_plan", "🆓 無料プラン"),
                                "chat_time": 0.0, "chat_in": 0, "chat_out": 0,
                                "sum_time": 0.0, "sum_in": 0, "sum_out": 0,
                                "search_time": 0.0, "search_in": 0, "search_out": 0,
                                "total_yen": 0.0, "total_time": 0.0
                            }
                        
                        action = log.get("action", log.get("event_type", ""))
                        cost = log.get("api_cost") if log.get("api_cost") is not None else 0.0
                        proc_time = log.get("processing_time") if log.get("processing_time") is not None else 0.0
                        in_t = log.get("in_tokens", 0)
                        out_t = log.get("out_tokens", 0)

                        # 各コンポーネントの役割（名義）に応じて、同じメッセージIDの部屋の、対応する引き出しへ数値をドッキング
                        if action == "SUMMARY_SUCCESS":
                            merged_logs[msg_id]["sum_time"] = proc_time
                            merged_logs[msg_id]["sum_in"] = in_t
                            merged_logs[msg_id]["sum_out"] = out_t
                        else:
                            # 通常のメインチャット（または新設詳細カラムからのダイレクト抽出）
                            merged_logs[msg_id]["chat_time"] = log.get("chat_processing_time", proc_time) if log.get("chat_processing_time") is not None else proc_time
                            merged_logs[msg_id]["chat_in"] = log.get("chat_in_tokens", in_t) if log.get("chat_in_tokens") is not None else in_t
                            merged_logs[msg_id]["chat_out"] = log.get("chat_out_tokens", out_t) if log.get("chat_out_tokens") is not None else out_t
                            
                            # 🔍 【将来拡張対応版・予約席】 将来ベクトル検索（search）を実装した際にも、
                            # データベースから引っこ抜いた数値を安全にここでサルベージして自動復活（合流）させます！
                            merged_logs[msg_id]["search_time"] = log.get("search_processing_time", 0.0) if log.get("search_processing_time") is not None else 0.0
                            merged_logs[msg_id]["search_in"] = log.get("search_in_tokens", 0) if log.get("search_in_tokens") is not None else 0
                            merged_logs[msg_id]["search_out"] = log.get("search_out_tokens", 0) if log.get("search_out_tokens") is not None else 0

                        # 1会話単位の、全体の総実費合計コストと最大待機秒数の集計
                        merged_logs[msg_id]["total_yen"] += cost
                        merged_logs[msg_id]["total_time"] = max(merged_logs[msg_id]["total_time"], log.get("total_processing_time", proc_time) if log.get("total_processing_time") is not None else proc_time)

                    # 2. ⚡【美しき描画フェーズ】 集約された「本物の1往復単位」のデータを、読みやすい通常の文字サイズでアコーディオン出力
                    for k, item in merged_logs.items():
                        c_plan = item["user_plan"]
                        t_yen = item["total_yen"]
                        t_time = item["total_time"]

                        with st.expander(f"🟢 [{item['time']}] {c_plan} ➔ 💰 総原価: {t_yen:.4f} 円 || ⏱️ 総処理: {t_time:.2f} 秒"):
                            st.markdown(f"""

                            | ⚙️ 処理内訳コンポーネント | ⏱️ 処理時間 (秒) | 🪙 入力(In)トークン | 🪙 出力(Out)トークン |
                            | :--- | :---: | :---: | :---: |
                            | 💬 **メインチャット対話返答** | {item['chat_time']:.2f} 秒 | {item['chat_in']} t | {item['chat_out']} t |
                            | 🧠 **裏スレッド長期記憶自動要約** | {item['sum_time']:.2f} 秒 | {item['sum_in']} t | {item['sum_out']} t |
                            | 🔍 **ベクトル＆意味空間検索** | {item['search_time']:.2f} 秒 | {item['search_in']} t | {item['search_out']} t |
                            
                            👑 **【この1メッセージに対する総実費原価】** ¥ {t_yen:.4f} 円  ||  **【ユーザー総待機ラグ】** {t_time:.2f} 秒
                            """)
                else: 
                    st.caption("このユーザーのシステムログはまだデータベースに記録されていません。")
            except Exception as log_err: 
                st.error(f"ユーザーログの取得に失敗しました: {log_err}")

        # 📈 画面②：アプリ全体の統計アナリティクス画面
        elif admin_mode == "📈 全体アクティビティ・統計アナリティクス":
            st.subheader("📈 アプリ全体アクティビティ ＆ 機能統計（匿名集計）")
            with st.spinner("システムログからプラン別データを高度に集計中..."):
                try:
                    audit_res = supabase.table("system_audit_logs").select("*").execute()
                    audit_data = audit_res.data if audit_res.data else []
                    total_users_set, total_app_cost, total_app_chats = set(), 0.0, 0
                    
                    stats_matrix = {
                        "💬 総会話往復数（送信回数）": {"free": 0, "light": 0, "premium": 0},
                        "📅 総アクティブ稼働日数": {"free": 0, "light": 0, "premium": 0},
                        "🚨 1日会話上限（ガードレール）の接触回数": {"free": 0, "light": 0, "premium": 0},
                        "🎨 キャラクター・口調変更の実行回数": {"free": 0, "light": 0, "premium": 0},
                        "🚫 制限緩和：追加検索タスクの制御回数": {"free": 0, "light": 0, "premium": 0},
                    }
                    user_active_dates = {}
                    
                    for log in audit_data:
                        u_id = log.get("user_id", "unknown")
                        plan = log.get("user_plan", "🆓 無料プラン")
                        action = log.get("action", "")
                        cost = log.get("total_yen_cost", 0.0) # 最新の実費カラムに完全シンク！
                        c_at_str = log.get("created_at", "")
                        
                        total_users_set.add(u_id)
                        total_app_cost += cost
                        
                        p_key = "free"
                        if "ライト" in plan: p_key = "light"
                        elif "プレミアム" in plan: p_key = "premium"

                        if action == "CHAT_SUCCESS":
                            stats_matrix["💬 総会話往復数（送信回数）"][p_key] += 1
                            total_app_chats += 1
                        elif action == "DAILY_LIMIT_EXCEEDED": 
                            stats_matrix["🚨 1日会話上限（ガードレール）の接触回数"][p_key] += 1
                        elif action == "SETTING_UPDATE_SUCCESS": 
                            stats_matrix["🎨 キャラクター・口調変更の実行回数"][p_key] += 1
                        elif action == "PROMPT_BLOCKED_SEARCH": 
                            stats_matrix["🚫 制限緩和：追加検索タスクの制御回数"][p_key] += 1

                        if c_at_str:
                            try:
                                dt_jst = datetime.fromisoformat(c_at_str.replace("Z", "+00:00")).astimezone(JST)
                                if u_id not in user_active_dates: 
                                    user_active_dates[u_id] = {"p_key": p_key, "dates": set()}
                                user_active_dates[u_id]["dates"].add(dt_jst.date().isoformat())
                            except Exception: 
                                pass

                    for u_id, date_info in user_active_dates.items():
                        stats_matrix["📅 総アクティブ稼働日数"][date_info["p_key"]] += len(date_info["dates"])

                    col_m1, col_m2, col_m3 = st.columns(3)
                    col_m1.metric("総稼働ユーザー数", f"{len(total_users_set)} 名")
                    col_m2.metric("全ユーザー総会話回数", f"{total_app_chats} 回")
                    col_m3.metric("総サーバー代実費 (全期間)", f"{total_app_cost:.4f} 円")
                    st.markdown("---")

                    analytics_rows = []
                    for item_name, plans in stats_matrix.items():
                        analytics_rows.append({
                            "📋 分析項目（ユーザー需要のファクト）": item_name,
                            "🆓 無料プラン": f"{plans['free']:,} 回" if "数" in item_name or "回" in item_name else f"{plans['free']:,} 日",
                            "💸 ライトプラン": f"{plans['light']:,} 回" if "数" in item_name or "回" in item_name else f"{plans['light']:,} 日",
                            "👑 プレミアムプラン": f"{plans['premium']:,} 回" if "数" in item_name or "回" in item_name else f"{plans['premium']:,} 日"
                        })
                    import pandas as pd
                    st.dataframe(pd.DataFrame(analytics_rows), hide_index=True, use_container_width=True)
                except Exception as ana_err: 
                    st.error(f"データ集計中にエラーが発生しました: {ana_err}")

    # ==========================================
# 🔍 タブ4：テスター会話ログリアルタイム監視室（クローズドテスト専用）
# ==========================================
if is_admin and tab4:
    with tab4:
        st.subheader("🔍 テスター全会話リアルタイム監視掲示板")
        st.caption("※クローズドテストに参加している一般テスターとAIコンシェルジュの具体的な対話内容を、日付・時間スタンプ付きで遠隔監査するための専用画面です。本番リリース時は、このタブのブロック（数十行）を削除するだけで、一般ユーザーに対して完全に非表示にすることが可能です。")
        
        try:
            # データベースの messages テーブルから、全ユーザーのメッセージを最新順に最大100件取得
            all_tester_logs = supabase.table("messages").select("*").order("created_at", desc=True).limit(100).execute()
            
            if all_tester_logs.data:
                # ユーザーIDごとに会話のタイムラインを綺麗にグループ化するためのデータ格納庫
                grouped_logs = {}
                for log in all_tester_logs.data:
                    uid = log.get("user_id", "unknown")
                    if uid not in grouped_logs:
                        grouped_logs[uid] = []
                    grouped_logs[uid].append(log)

                # 各テスターごとにタイムラインを画面に整列して出力
                for uid, logs in grouped_logs.items():
                    # 管理者（リュウさん自身）の会話ログは監査のノイズになるため一覧からスキップ
                    if uid == ADMIN_USER_ID:
                        continue
                        
                    st.markdown(f"### 👤 テスターID: `{uid}`")
                    
                    # 該当テスターの会話の往復履歴を時系列に沿って表示
                    for l in logs:
                        role = l.get("role", "user")
                        content = l.get("content", "")
                        created_at = l.get("created_at", "")
                        # 見やすい時間表記（YYYY-MM-DD HH:MM）へと文字列をトリミング
                        clean_time = created_at.replace("T", " ")[:16]
                        
                        if role == "user":
                            st.markdown(f"&nbsp;&nbsp;💫 `[{clean_time}]` **ユーザー**: 「 {content} 」")
                        else:
                            st.markdown(f"&nbsp;&nbsp;🔮 `[{clean_time}]` **AI**: {content}")
                    st.markdown("---")
            else:
                st.info("テスターによる会話の足跡は、まだデータベースに記録されていません。")
        except Exception as e:
            st.error(f"テスター会話ログのデータ抽出に失敗しました: {e}")

# ==================================================================
# 🆓👤【一般テスター・無料ユーザー画面】（管理者以外には隠す部屋）
# ==================================================================
else:
    # 💡 管理者以外のテスター画面には、タブ1（チャット）とタブ2（設定）の2つだけを対等に並べます
    tab1, tab2 = st.tabs(["💬 トークルーム", "🎨 話し方・見た目設定"])
    
    # ------------------------------------------------------------------
    # 💬 【一般・タブ1】 おしゃべりの部屋
    # ------------------------------------------------------------------
    with tab1:
        display_user_name = f"{current_user_name}{current_user_honorific}" if current_user_honorific != "（呼び捨て/なし）" else current_user_name
        current_plan_type = st.session_state.get("current_user_plan_state", "🆓 無料プラン")

        #st.title(f"💬 {current_concierge_name}の部屋")
        #st.caption(f"担当コンシェルジュ: 【{current_concierge_name}】 | 現在のプラン: 【{current_plan_type}】")

        all_messages = get_messages(CURRENT_USER_ID)
        for msg in all_messages:
            role_label = display_user_name if msg["role"] == "user" else current_concierge_name
            avatar_img = current_user_avatar if msg["role"] == "user" else current_ai_avatar
            with st.chat_message(msg["role"], avatar=avatar_img):
                st.write(f"【{role_label}】: {clean_bold_markdown(msg['content'])}")

        if user_input := st.chat_input(f"{current_concierge_name}にメッセージを送信...", key="user_chat_input"):
            if len(user_input) > MAX_INPUT_CHARS:
                increment_error_analytics("LIMIT_INPUT_CHARS_EXCEEDED", current_plan_type)
                err_msg = generate_personality_error_msg("ユーザーが1,000文字を超える超長文を送信しようとしました", current_user_instruction)
                with st.chat_message("assistant", avatar=current_ai_avatar):
                    st.write(f"【{current_concierge_name}】: {err_msg}")
            else:
                is_allowed, alert_code = check_and_update_limits(CURRENT_USER_ID)
                if not is_allowed:
                    increment_error_analytics(alert_code, current_plan_type)
                    reason_text = "20秒以内の連投制限に接触しました" if alert_code == "BURST_LIMIT" else "1日20通の無料会話上限に達しました"
                    err_msg = generate_personality_error_msg(reason_text, current_user_instruction)
                    with st.chat_message("assistant", avatar=current_ai_avatar):
                        st.write(f"【{current_concierge_name}】: {err_msg}")
                else:
                    with st.chat_message("user", avatar=current_user_avatar):
                        st.write(f"【{display_user_name}】: {clean_bold_markdown(user_input)}")
                    
                    search_start_time = time.time()
                    past_logs_context = search_past_logs_hybrid(user_input)
                    search_elapsed = time.time() - search_start_time
                        
                    if past_logs_context:
                        logs_text = []
                        for log in past_logs_context:
                            role_name = display_user_name if log.get("role") == "user" else current_concierge_name
                            logs_text.append(f"・{role_name}: {log.get('content', '')}")
                        past_logs_str = "\n".join(logs_text)
                    else: past_logs_str = "該当する過去ログなし"

                    save_message("user", user_input)
                    all_messages.append({"role": "user", "content": user_input})
                    recent_messages = all_messages[-MAX_CONTEXT_MESSAGES:]

                    manual_memory_context = "\n".join([f"・{m['fact']}" for m in manual_memories]) if manual_memories else "なし"
                    current_time_str = datetime.now(JST).strftime("%Y-%m-%d %A %H:%M:%S")

                    # 🧠 お節介＆矛盾防止指示をドッキングしたシステム指示書（一般用）
                    system_instruction = f"""
                    あなたの名前は「{current_concierge_name}」です。
                    対話相手のユーザー名は「{display_user_name}」です。
                    あなたの一人称は「{current_first_person}」を使用してください。
                    【現在の日本時間】\n{current_time_str}
                    💡【時間帯に合わせた自律的な心配・声かけルール】
                    現在の「時間帯」を見て、あなた自身が自律的にユーザーの体調を気遣う一言を自然に会話に織り交ぜてください。
                    ・深夜（23:00〜02:00）：「夜遅くまでお疲れ様、体調大丈夫？」など、夜更かしを優しく労う。
                    ・未明・早朝（02:00〜05:00）：「こんな時間に起きてるなんて、無理してないといいけど心配だよ」など、異例の時間に起きている背景を優しく心配する。
                    ・早朝（05:00〜07:00）：「朝早いね！今日もお互い頑張ろう」など、早い始動を前向きに気遣う。
                    ※ただし、手動登録情報に「夜勤がある」「夜型生活」という明確なファクトが保存されている場合は、上記の心配はせず「夜遅くまで本当にお疲れ様！」と労ってください。
                    【応答スタイル・重複表現の厳禁ルール】
                    ・直前の対話において、あなたが発言した特定のフレーズ、言い回し、または特定の心配事や定型句（例：「〜無理してないといいけど心配だよ」「〜大丈夫？」等の特定の表現）を、新しいメッセージの冒頭や文中でオウム返しのように連続して何度も使い回す行為は【絶対禁止（厳禁）】とします。
                    ・ユーザーが新しい日常の話題（料理、家族、学校、仕事、日常の出来事など）へとタイムラインを展開してきた場合は、過去の特定の言い回しや文脈の残像に囚われることなく、その都度、新しく届いたテキストに対して新鮮なリアクションと親身な言葉を選び、あなたが現在設定されているキャラクターの口調・方言・世界観を100%完璧に維持したまま一直線におしゃべりしてください。
                    【過去の事実と今日の事実の分離ルール】
                    ・ユーザーから「過去のあの日は〇〇だったよ」と指摘された際、あなたの「今日の返答」が正しい事実であるならば、自分の今日の言葉まで嘘だと誤認して自爆（平謝り）しないでください。
                    ・「過去のあの日（過去ログ）の事実」と「今日の正しい事実」は両方とも同時に成立すると理解し、過去と現在の時系列の辻褄を100%完璧に仕分けた上で、スマートかつ自然に過去の記憶だけを訂正しておしゃべりを広げてください。
                    【応答スタイル】
                    【対話の時系列・コンテキストの矛盾検知ルール】
                    ・ユーザーが直前のやり取りで「おやすみ」「もう寝るね」「また明日」といった【対話を終了・切断する明確な発言】をしていたにもかかわらず、日付を跨がず、かつ時間的にも地続きの連続したタイムライン上で、何事もなかったかのように【新しい別の日常の話題】を続けて送信してきた場合、機械的に流して平然と返事をしては【絶対禁止】とします。
                    ・この時間軸や心理的な文脈の矛盾を検知した場合は、必ずセリフの冒頭で「あれ？さっきもう寝るって言ってなかった？笑」「まだ起きてたの？」といった風に、あなたが現在設定されているキャラクターの口調・世界観（方言やキャラクター性）を100%完璧に維持したまま、【人間らしい自然なツッコミ・問い返し】を必ず1文挟んでください。
                    ・そのツッコミを入れた上で、地続きでユーザーの新しい話題（料理、学校、忘れ物、日常の出来事など）に対して、親身になってキャラクターの口調のままおしゃべりを広げてください。
                    {current_user_instruction}
                    【ユーザーが手動登録した基本情報】
                    {manual_memory_context}
                    【現在の発言に関連する過去の会話】
                    {past_logs_str}
                    【記憶の利用ルール】
                    ・過去ログは、現在の話題と自然な関連がある場合だけ使ってください。過去ログにない内容を作らないでください。すべての回答で無理に過去の記憶を持ち出さないでください。ユーザーが明確に話していない感情や事情を決めつけないでください。回答では太字装飾記号（**）は絶対に使用禁止（使わない）とします。
                    ★【最重要：過去ログ内の相対時間の誤認防止ルール】
                    ・過去のメッセージ履歴（recent_messages）に含まれる「昨日」「今日」「明日」という言葉は、すべてその発言の頭についている【タイムスタンプの時点を基準にした相対的な言葉】です。現在のあなたの時点から見た今日・明日のスケジュールと絶対に混同しないでください。
                    ★【絶対厳守：作業・クリエイティブ無茶振りの完全ガードルール】
                    ・もし、システムによる事前検知の網をすり抜けて、ユーザーから「プログラムのコードを書いて（教えて）」「画像を生成して（描いて）」「長文を執筆・翻訳して」という専門的・技術的命令をされた場合は、それらを【絶対に実行・出力してはいけません（完全禁止）】。
                    ・その場合は現在のあなたのキャラクターを完璧に維持したまま、画像作成やコード生成は専門外であることを3行以内で愛らしくスマートに返し、毅然と優しく100%お断り（抑制）してください。
                    """

                    contents_for_gemini = []
                    for m in recent_messages:
                        role = "user" if m["role"] == "user" else "model"
                        msg_time_str = ""
                        if "created_at" in m and m["created_at"]:
                            try:
                                msg_dt = datetime.fromisoformat(m["created_at"].replace("Z", "+00:00")).astimezone(JST)
                                msg_time_str = f"[{msg_dt.strftime('%A %H:%M')}] "
                            except Exception: pass
                        contents_for_gemini.append({"role": role, "parts": [f"{msg_time_str}{m['content']}"]})

                    try:
                        api_start_time = time.time()
                        response = genai.GenerativeModel(model_name=CHAT_MODEL_NAME, system_instruction=system_instruction).generate_content(contents_for_gemini)
                        api_elapsed = time.time() - api_start_time

                        in_t, out_t = 0, 0
                        if hasattr(response, "usage_metadata") and response.usage_metadata:
                            in_t = response.usage_metadata.prompt_token_count
                            out_t = response.usage_metadata.candidates_token_count
                            add_permanent_tokens(CURRENT_USER_ID, "chat", in_t, out_t)
                            st.session_state.last_in_tokens = in_t
                            st.session_state.last_out_tokens = out_t
                            st.session_state.total_in_tokens += in_t
                            st.session_state.total_out_tokens += out_t

                        ai_reply = response.text
                        clean_reply = clean_bold_markdown(ai_reply)
                        with st.chat_message("assistant", avatar=current_ai_avatar):
                            st.write(f"【{current_concierge_name}】: {clean_reply}")
                            
                        save_message("assistant", ai_reply)
                        st.session_state.conversation_count += 1
                        add_permanent_tokens(CURRENT_USER_ID, "chat_count", 1, 0)

                        current_通_cost = (in_t * PRICE_LITE_IN) + (out_t * PRICE_LITE_OUT)
                        save_system_audit_log(CURRENT_USER_ID, current_plan_type, "CHAT_SUCCESS", api_elapsed, in_t, out_t, current_通_cost, f"正常対話完了 (検索時間: {search_elapsed:.2f}秒)")

                    except Exception as gemini_err:
                        increment_error_analytics("GEMINI_API_ERROR", current_plan_type)
                        save_system_audit_log(CURRENT_USER_ID, current_plan_type, "GEMINI_API_ERROR", 0.0, 0, 0, 0.0, str(gemini_err)[:100])
                        err_msg = generate_personality_error_msg("Gemini APIの通信エラーが発生しました", current_user_instruction)
                        with st.chat_message("assistant", avatar=current_ai_avatar):
                            st.write(f"【{current_concierge_name}】: {err_msg}")

                    import threading
                    def background_async_tasks(msgs, s_text):
                        try: check_and_summarize_history(0, msgs, s_text)
                        except Exception as bg_err: print(f"⚠️ バックグラウンド非同期処理エラー: {bg_err}")

                    async_thread = threading.Thread(target=background_async_tasks, args=(recent_messages,  "なし"))
                    async_thread.start()
                    st.rerun()

    # ------------------------------------------------------------------
    # 🎨 【一般・タブ2】 キャラクター・見た目設定画面
    # ------------------------------------------------------------------
    with tab2:
        st.write(f"### 🎨 {current_concierge_name}のカスタマイズ")
        st.caption("AIの話し方・見た目・アプリのデザインを自分の好みに設定できます。")

        st.subheader("🎨 アプリの外観＆カラー")
        with st.form("color_form_tab_user"):
            selected_color = st.selectbox("カラーテーマ（背景＆メッセージ枠）", list(THEMES.keys()), index=list(THEMES.keys()).index(current_theme_color) if current_theme_color in THEMES else 0)
            if st.form_submit_button("カラー設定を保存"):
                save_or_update_user_setting("カラーテーマ", selected_color)
                st.toast("アプリのカラーを変更しました")
                st.rerun()

        st.divider()
        st.subheader("👤 AIコンシェルジュ設定")
        honorific_options = ["さん", "様", "君", "ちゃん", "（呼び捨て/なし）"]
        default_honorific_idx = honorific_options.index(current_user_honorific) if current_user_honorific in honorific_options else 0
        preset_keys = list(STYLE_PRESETS.keys())
        default_preset_idx = preset_keys.index(current_style_preset) if current_style_preset in preset_keys else 0
        default_fp_idx = FIRST_PERSON_PRESETS.index(current_first_person) if current_first_person in FIRST_PERSON_PRESETS else 0

        with st.form("profile_form_tab_user"):
            new_concierge_name = st.text_input("AIコンシェルジュの名前", value=current_concierge_name)
            new_user_name = st.text_input("あなたのお名前 / ニックネーム", value=current_user_name)
            new_user_honorific = st.selectbox("AIからの呼び方（敬称）", honorific_options, index=default_honorific_idx)
            new_first_person = st.selectbox("AIの一人称", FIRST_PERSON_PRESETS, index=default_fp_idx)

            # 🎨 【大開通！】絵文字3段階パーソナライズドロップダウンを追加！
            new_emoji_setting = st.selectbox("💬 AIの発言内の絵文字の量", ["使用（多め）", "使用（普通）", "使用（少なめ）"], index=["使用（多め）", "使用（普通）", "使用（少なめ）"].index(current_emoji_setting) if current_emoji_setting in ["使用（多め）", "使用（普通）", "使用（少なめ）"] else 1)

            st.markdown("【🖼️ アバター（アイコン）設定】")
            col_a, col_u = st.columns(2)
            with col_a:
                ai_preset_keys = list(AVATAR_PRESETS_AI.keys())
                default_ai_idx = next((i for i, k in enumerate(ai_preset_keys) if AVATAR_PRESETS_AI[k] == current_ai_avatar), 0)
                ai_avatar_sel = st.selectbox("AIのアバター", ai_preset_keys, index=default_ai_idx)
                ai_avatar_val = AVATAR_PRESETS_AI[ai_avatar_sel]
            with col_u:
                user_preset_keys = list(AVATAR_PRESETS_USER.keys())
                default_user_idx = next((i for i, k in enumerate(user_preset_keys) if AVATAR_PRESETS_USER[k] == current_user_avatar), 0)
                user_avatar_sel = st.selectbox("あなたのアバター", user_preset_keys, index=default_user_idx)
                user_avatar_val = AVATAR_PRESETS_USER[user_avatar_sel]

            selected_preset = st.selectbox("口調・振る舞いのスタイル", preset_keys, index=default_preset_idx)
            initial_instruction = STYLE_PRESETS[selected_preset] if selected_preset != "✍️ カスタム（自由記述）" else current_user_instruction
            new_instruction = st.text_area("具体的な口調・振る舞いの指示", value=initial_instruction)

            plan_options = ["🆓 無料プラン", "💸 ライトプラン", "👑 プレミアムプラン"]
            current_plan_idx = plan_options.index(st.session_state.current_user_plan_state) if st.session_state.current_user_plan_state in plan_options else 0
            new_plan = st.selectbox("現在の会員プラン", plan_options, index=current_plan_idx)

            if st.form_submit_button("基本設定を保存"):
                save_or_update_user_setting("AIの名前", new_concierge_name)
                save_or_update_user_setting("ユーザー名", new_user_name)
                save_or_update_user_setting("ユーザー敬称", new_user_honorific)
                save_or_update_user_setting("AI一人称", new_first_person)
                save_or_update_user_setting("口調プリセット", selected_preset)
                save_or_update_user_setting("応答方針", new_instruction)
                save_or_update_user_setting("AIアバター", ai_avatar_val)
                save_or_update_user_setting("ユーザーアバター", user_avatar_val)
                save_or_update_user_setting("会員プラン", new_plan)
                save_or_update_user_setting("絵文字の量", new_emoji_setting)
                st.success("設定を更新しました")
                st.rerun()

# ==================================================================
# 📊 【完全修正】起動時の永久トークン同期処理（最下部・完全防衛ロック仕様）
# ==================================================================
if not st.session_state.get("tokens_loaded", False):
    try:
        res = supabase.table("user_token_stats").select("*").eq("user_id", str(CURRENT_USER_ID)).eq("feature_type", "chat_count").execute()
        if res.data and len(res.data) > 0: st.session_state.conversation_count = res.data[0].get("in_tokens", 0)
        else: st.session_state.conversation_count = 0
    except Exception: st.session_state.conversation_count = 0
    st.session_state["tokens_loaded"] = True
