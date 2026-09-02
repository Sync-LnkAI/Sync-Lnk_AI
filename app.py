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
st.set_page_config(page_title="My AI Concierge", page_icon="🤖", layout="wide")

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
ADMIN_USER_IDS = ["ryuudesu_master_1310", "your_real_admin_id"]

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
    st.session_state.debug_logs = []
if "conversation_count" not in st.session_state:
    st.session_state.conversation_count = 0

if "tokens_loaded" not in st.session_state:
    load_permanent_tokens(CURRENT_USER_ID)
    
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

def check_and_summarize_history(user_id_dummy: int, messages_list: list, summary_text_dummy: str) -> bool:
    """
    🔮 【ハヤトの長期記憶エンジン】
    会話履歴（messages_list）が一定のボリュームを超えた際、
    裏側の別スレッドで全自動でこれまでの雑談の核心を200文字に超要約し、
    次回のプロンプトを軽量化（サーバー代の原価を0円防衛）させるための心臓部です。
    """
    try:
        # 1. 現在の会話が十分に長くなっているか（例：直近の往復が少ない場合は要約をスキップしてコスト防衛）
        if len(messages_list) < 6:
            return True

        # 2. 最新の20文字制限に完全シンクさせたリュウさんの本物のオーナーIDをグローバルから強制抽出
        target_user_id = "ryuudesu_master_1310"

        # 3. 過去の会話を一本の美しい読みやすいテキストにドッキング
        conversation_text = ""
        for m in messages_list:
            role_label = "ユーザー" if m.get("role") == "user" else "コンシェルジュ"
            conversation_text += f"・{role_label}: {m.get('content', '')}\n"

        # 🧠 Google Gemini 3.5 Flash-Lite に対し、裏方用の冷徹な要約指示書（プロンプト）を組み立て
        summary_instruction = (
            "あなたは優秀な記憶整理システムです。以下の2人の会話ログを読み、"
            "今後の対話に必要な重要ファクト、ユーザーの趣味嗜好、約束事、これまでの流れの核心だけを"
            "【箇条書きで3行以内、合計200文字以内】で、余計な挨拶を一切排除してスマートに要約してください。"
        )

        contents_for_summary = [
            {"role": "user", "parts": [f"[指示書]\n{summary_instruction}\n\n[対象の会話ログ]\n{conversation_text}"]}
        ]

        # 🤖 裏方の要約専用モデル（SUMMARY_MODEL_NAME）へストレートに通電
        # ※ response.text のデータ構造のネジレを2026年最新仕様へ100%完全適合させています
        response = genai.GenerativeModel(model_name=SUMMARY_MODEL_NAME).generate_content(contents_for_summary)
        
        # 3.5 Flash-Lite の特殊なデータ構造から安全に文字を引っこ抜く防衛ライン
        if hasattr(response, "candidates") and response.candidates:
            new_summary = response.candidates[0].content.parts[0].text
        else:
            new_summary = response.text

        if not new_summary:
            return False

        # 📊 【Supabase連動】 要約した最新の記憶の残高を、user_memories（または専用テーブル）へ上書き保存（貯金）
        # ※ 既存の古い記憶があるかをチェック
        mem_check = supabase.table("user_memories").select("*").eq("user_id", target_user_id).execute()

        if mem_check.data:
            # 既存の記憶があれば、最新の要約データにアップデート
            supabase.table("user_memories").update({
                "summary": new_summary,
                "updated_at": datetime.now(JST).isoformat()
            }).eq("user_id", target_user_id).execute()
        else:
            # 記憶の器がまだなければ、新しくインサート
            supabase.table("user_memories").insert({
                "user_id": target_user_id,
                "summary": new_summary,
                "created_at": datetime.now(JST).isoformat(),
                "updated_at": datetime.now(JST).isoformat()
            }).execute()

        # 🪙 要約にかかった裏方の実費トークン消費も、user_token_statsテーブルへ完璧に永続保存（貯金）
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            in_t = response.usage_metadata.prompt_token_count
            out_t = response.usage_metadata.candidates_token_count
            add_permanent_tokens(target_user_id, "summary", in_t, out_t)

        return True

    except Exception as bg_err:
        # メインスレッド（リュウさんのおしゃべり画面）を絶対に巻き込んでフリーズさせないよう、
        # エラーはバックグラウンドのログに美しく逃がして安全弁を閉じます
        print(f"⚠️ バックグラウンド自動要約処理エラー: {type(bg_err).__name__}: {bg_err}")
        return False

# ==================================================================
# 📊 【新設】 ユーザー別＆全体システム監査ログ（Telemetry）永続保存関数
# ==================================================================
def save_system_audit_log(user_id: str, plan_type: str, event_type: str, processing_time: float, in_t: int, out_t: int, api_cost: float, details: str = ""):
    """
    🎯【個別カルテ ＆ 製品版全体分析の二面待ちデータ貯金箱】
    ユーザーの会話の中身（生文字）は一切保存せず、
    「処理秒数、トークン数、正確な実費コスト、イベント種別」の『数字と記号だけ』をDBへ永続保存します。
    """

    try:
        data = {
            "user_id": user_id,
            "user_plan": plan_type,
            "event_type": event_type,
            "processing_time": round(processing_time, 2),
            "in_tokens": in_t,
            "out_tokens": out_t,
            "api_cost": round(api_cost, 4),
            "details": details,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        supabase.table("system_audit_logs").insert(data).execute()

    except Exception as e:

        print(
            f"⚠️ システム監査ログ保存エラー: "
            f"{type(e).__name__}: {e}"
        )

        st.error(
            f"監査ログ保存エラー: "
            f"{type(e).__name__}: {e}"
        )

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

# ==========================================
# 🧠 設定値の読み込み・常時シンク
# ==========================================
manual_memories = get_memories(source="manual")

# 💡 初めて起動したまっさらな状態のユーザー向け初期値（デフォルト）
current_theme_color = "☀ ライドモード（白）"
current_concierge_name = "コンシェルジュ"
current_user_name = "ユーザー"
current_user_honorific = "さん"
current_first_person = "私"
current_style_preset = "🤝 フランク＆対等（相棒）"
current_user_instruction = STYLE_PRESETS["🤝 フランク＆対等（相棒）"]
current_ai_avatar = "🤖"
current_user_avatar = "💫"

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
        current_style_preset = fact.replace("口調プリセット:", "").strip()
    elif fact.startswith("応答方針:"):
        current_user_instruction = fact.replace("応答方針:", "").strip()
    elif fact.startswith("AIアバター:"):
        current_ai_avatar = fact.replace("AIアバター:", "").strip()
    elif fact.startswith("ユーザーアバター:"):
        current_user_avatar = fact.replace("ユーザーアバター:", "").strip()
    elif fact.startswith("会員プラン:"):
        st.session_state["current_user_plan_state"] = fact.replace("会員プラン:", "").strip()

theme_cfg = COLOR_THEMES.get(current_theme_color, COLOR_THEMES["☀ ライドモード（白）"])

# ★画面最適化CSS（スマホメニュー表示維持 & ドロップダウン選択肢の全階層テキスト完全強制補正）
st.markdown(f"""
<style>

/* ==================================================================
   🎯【スマホ用メニュー救済】上部ヘッダーの余分な隙間は隠し、
   左上のメニューボタン（矢印・三本線）「だけ」をピンポイントで画面に完全復活させます
   ================================================================== */
[data-testid="stHeader"] {{
    background-color: transparent !important; /* ヘッダーのグレーの背景を透明にして消し去ります */
    height: 3rem !important; /* ボタンが潰れない高さを確保 */
}}
/* 左上の展開ボタン本体を背景からドンと際立たせる色付け */
[data-testid="collapsedControl"] {{
    color: #4A90E2 !important; /* ボタンの文字（矢印）を綺麗なロイヤルブルーへ */
    background-color: rgba(255, 255, 255, 0.9) !important; /* 背景を白にして視認性を100%に */
    border-radius: 4px !important;
    padding: 4px !important;
    box-shadow: 0px 2px 4px rgba(0,0,0,0.1) !important; /* 押しやすそうな立体感をプラス */
    position: fixed !important;
    top: 0.5rem !important;
    left: 0.5rem !important;
    z-index: 999999 !important; /* 最前面へ強制浮上 */
}}

    /* 1. 全体背景＆文字色 */
    html, body, .stApp, div[data-testid="stAppViewContainer"], section.main {{
        background-color: {theme_cfg["bg"]} !important;
        color: {theme_cfg["text"]} !important;
        max-width: 95vw !important;
        overflow-x: hidden !important;
        box-sizing: border-box !important;
    }}
    .main .block-container {{
        max-width: 95vw !important;
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

# ==================================================================
# 🔒【完全防衛】権限（ID）に応じて、画面最上部のタブ構造を動的に切り替えます
# ==================================================================
is_admin = CURRENT_USER_ID in ADMIN_USER_IDS

if is_admin:
    # 👑【管理者専用画面】：管理者限定の3つの隠しタブを作成
    tab1, tab2, tab3 = st.tabs(["💬 おしゃべりの部屋", "🎨 キャラクター・見た目設定", "📊 システム管理者管理"])
    
    # ------------------------------------------------------------------
    # 💬 【管理者・タブ1】 おしゃべりの部屋
    # ------------------------------------------------------------------
    with tab1:       
        display_user_name = f"{current_user_name}{current_user_honorific}" if current_user_honorific != "（呼び捨て/なし）" else current_user_name
        #current_plan_type = st.session_state.get("current_user_plan_state", "🆓 無料プラン")
        current_plan_type = "💎 プレミアムプラン"

        st.title(f"💬 {current_concierge_name}の部屋")
        st.caption(f"担当コンシェルジュ: 【{current_concierge_name}】 | 現在のプラン: 【{current_plan_type}】")

        all_messages = get_messages(CURRENT_USER_ID)
        for msg in all_messages:
            role_label = display_user_name if msg["role"] == "user" else current_concierge_name
            avatar_img = current_user_avatar if msg["role"] == "user" else current_ai_avatar
            with st.chat_message(msg["role"], avatar=avatar_img):
                st.write(f"【{role_label}】: {clean_bold_markdown(msg['content'])}")
        
        st.components.v1.html("""
            <script>
                window.parent.document.querySelector('section.main').scrollTo({ top: 99999, behavior: 'smooth' });
            </script>
        """, height=0)

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
                    ⚠️【重要：気遣い・特定の話題の重複禁止ルール（人間らしさの優先）】
                    ・直近5往復の会話履歴（recent_messages）の中で、あなたがすでに一度上記の「深夜の労い（無理しないでね、等）」や「特定の固有名詞の話題」に自律的に言及している場合は、同じ日のその後のラリーで毎回クドクドと繰り返さないでください。
                    ・人間と同じように「その話はさっき触れたから、もう十分伝わっている」と脳内で仕分け、その後の返答ではあえてその話題には一切触れず、ユーザーの新しい言葉の核心だけに集中してスマートに相槌を打ってください。ただし、昨日以前の会話のログであれば、日を改めて新しく労うのは大歓迎です。
                    ・※例外として、ユーザー側から進んでその話題を継続して質問・言及してきた場合のみ、同様のテーマであっても優しく返事をして、会話を成り立たせてください。
                    【過去の事実と今日の事実の分離ルール】
                    ・ユーザーから「過去のあの日は〇〇だったよ」と指摘された際、あなたの「今日の返答」が正しい事実であるならば、自分の今日の言葉まで嘘だと誤認して自爆（平謝り）しないでください。
                    ・「過去のあの日（過去ログ）の事実」と「今日の正しい事実」は両方とも同時に成立すると理解し、過去と現在の時系列の辻褄を100%完璧に仕分けた上で、スマートかつ自然に過去の記憶だけを訂正しておしゃべりを広げてください。
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

                        current_通_cost = (in_t * PRICE_LITE_IN) + (out_t * PRICE_LITE_OUT)
                        save_system_audit_log(CURRENT_USER_ID, current_plan_type, "CHAT_SUCCESS", api_elapsed, in_t, out_t, current_通_cost, f"正常対話完了 (検索時間: {search_elapsed:.2f}秒)")

                    except Exception as gemini_err:
                        error_detail = (
                            f"{type(gemini_err).__name__}: "
                            f"{str(gemini_err)}"
                        )

                        print(f"🚨 チャット処理エラー: {error_detail}")

                        st.error(
                            f"チャット処理エラー: {error_detail}"
                        )

                        increment_error_analytics(
                            "CHAT_PROCESSING_ERROR",
                            current_plan_type
                        )
                        
                        save_system_audit_log(
                            CURRENT_USER_ID,
                            current_plan_type,
                            "CHAT_PROCESSING_ERROR",
                            0.0,
                            0,
                            0,
                            0.0,
                            error_detail[:500]
                        )

                    import threading
                    def background_async_tasks(msgs, s_text):
                        try: check_and_summarize_history(0, msgs, s_text)
                        except Exception as bg_err: print(f"⚠️ バックグラウンド非同期処理エラー: {bg_err}")

                    async_thread = threading.Thread(target=background_async_tasks, args=(recent_messages,  "なし"))
                    async_thread.start()
                    st.rerun()

        st.components.v1.html("""
            <script>
                setTimeout(function() {
                    window.parent.document.querySelector('section.main').scrollTo({ top: 99999, behavior: 'smooth' });
                }, 1000);
            </script>
        """, height=0)

    # ------------------------------------------------------------------
    # 🎨 【管理者・タブ2】 キャラクター・見た目設定画面
    # ------------------------------------------------------------------
    with tab2:
        st.write(f"### 🎨 {current_concierge_name}のカスタマイズ")
        st.caption("AIの見た目・口調・アプリのデザインを自分好みにリアルタイムに設定できます。")

        st.subheader("🎨 アプリの外観＆カラー")
        with st.form("color_form_tab_admin"):
            selected_color = st.selectbox("カラーテーマ（背景＆メッセージ枠）", list(COLOR_THEMES.keys()), index=list(COLOR_THEMES.keys()).index(current_theme_color) if current_theme_color in COLOR_THEMES else 0)
            if st.form_submit_button("カラー設定を保存"):
                save_or_update_user_setting("カラーテーマ", selected_color)
                st.toast("アプリのカラーを変更したよ！")
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

            if st.form_submit_button("基本設定を保存"):
                save_or_update_user_setting("AIの名前", new_concierge_name)
                save_or_update_user_setting("ユーザー名", new_user_name)
                save_or_update_user_setting("ユーザー敬称", new_user_honorific)
                save_or_update_user_setting("AI一人称", new_first_person)
                save_or_update_user_setting("口調プリセット", selected_preset)
                save_or_update_user_setting("応答方針", new_instruction)
                save_or_update_user_setting("AIアバター", ai_avatar_val)
                save_or_update_user_setting("ユーザーアバター", user_avatar_val)
                st.success("設定を更新したよ！")
                st.rerun()

    # ------------------------------------------------------------------
    # 🔒 【管理者・タブ3】 システム管理者管理画面
    # ------------------------------------------------------------------
    with tab3:
        st.write("### 📊 システム管理者専用ダッシュボード")
        admin_mode = st.radio("表示する分析画面を選択してください", ["👤 画面①：ユーザー個別・全利用状況監査カルテ", "📈 画面②：全体アクティビティ ＆ エラー・要望アナリティクス"], horizontal=True, key="admin_radio_mode")
        st.divider()

        if admin_mode == "👤 画面①：ユーザー個別・全利用状況監査カルテ":
            st.subheader("👤 ユーザー別・稼働状況 ＆ タイムライン監査")
            all_users = ["ryuudesu_master_1310"]
            try:
                user_res = supabase.table("user_token_stats").select("user_id").execute()
                if user_res.data: all_users = sorted(list({row["user_id"] for row in user_res.data if row.get("user_id")}))
            except Exception: pass

            selected_audit_user = st.selectbox("🔍 監査対象のユーザーID（UUID）を選択してください：", all_users)
            st.markdown("---")
            st.markdown(f"#### 📋 ユーザー [ `{selected_audit_user}` ] の現在の設定 ＆ プロフィール")
            
            audit_concierge_name, audit_user_name, audit_theme, audit_plan = "コンシェルジュ", "ユーザー", "☀ ライドモード（白）", "🆓 無料プラン"
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
                        else: audit_facts.append(fact)
            except Exception: pass

            col_info1, col_info2 = st.columns(2)
            col_info1.info(f"**【着せ替え・外観設定】**\n・現在のAIの名前： `{audit_concierge_name}`\n・アプリのカラーテーマ： `{audit_theme}`\n・現在の会員プラン： **`{audit_plan}`**")
            col_info2.info(f"**【ユーザー基本情報】**\n・登録ユーザー名： `{audit_user_name}`\n・自動抽出された過去の記憶： `{len(audit_facts)} 件`")

            st.markdown("##### ⏱️ このユーザーのタイムライン式システム監査ログ（最新50件）")
            try:
                log_res = supabase.table("system_audit_logs").select("*").eq("user_id", selected_audit_user).order("created_at", desc=True).limit(50).execute()
                if log_res.data:
                    for log in log_res.data:
                        c_at = datetime.fromisoformat(log["created_at"].replace("Z", "+00:00")).astimezone(JST).strftime("%H:%M:%S")
                        e_type = log.get("event_type", "EVENT")
                        p_time = log.get("processing_time", 0.0)
                        in_t, out_t = log.get("in_tokens", 0), log.get("out_tokens", 0)
                        cost = log.get("api_cost", 0.0)
                        details = log.get("details", "")
                        badge = "🟢" if "SUCCESS" in e_type or "RECEIVE" in e_type else "🔵" if "SEND" in e_type or "SEARCH" in e_type else "🚨"
                        st.markdown(f"{badge} **[{c_at}] {e_type}**\n- ⏱️ 処理時間: `{p_time}秒`  |  🧠 トークン: `In={in_t} / Out={out_t}`  |  💰 実費: `{cost:.4f}円`\n- 📋 詳細/文脈ファクト: *{details}*")
                        st.markdown("<hr style='margin: 0.3rem 0; border-color: rgba(0,0,0,0.05);' />", unsafe_allow_html=True)
                else: st.caption("このユーザーのシステム監査ログはまだありません。")
            except Exception as log_err: st.error(f"監査ログの取得に失敗しました: {log_err}")

        elif admin_mode == "📈 画面②：全体アクティビティ ＆ エラー・要望アナリティクス":
            st.subheader("📈 アプリ全体アクティビティ ＆ 機能要望・エラー統計（匿名集計）")
            with st.spinner("システム監査ログからプラン別データを高度に集計中..."):
                try:
                    audit_res = supabase.table("system_audit_logs").select("*").execute()
                    audit_data = audit_res.data if audit_res.data else []
                    total_users_set, total_app_cost, total_app_chats = set(), 0.0, 0
                    stats_matrix = {
                        "💬 総会話往復数（送信回数）": {"free": 0, "light": 0, "premium": 0},
                        "📅 総アクティブ稼働日数": {"free": 0, "light": 0, "premium": 0},
                        "🚨 1日会話上限（ガードレール）の接触回数": {"free": 0, "light": 0, "premium": 0},
                        "🎨 キャラなりきり・口調変更の実行回数": {"free": 0, "light": 0, "premium": 0},
                        "🚫 禁止：画像生成の無茶振り（コスト防衛）": {"free": 0, "light": 0, "premium": 0},
                        "🚫 禁止：コード生成の無茶振り（コスト防衛）": {"free": 0, "light": 0, "premium": 0},
                    }
                    user_active_dates = {}
                    for log in audit_data:
                        u_id, plan, e_type, cost, c_at_str = log.get("user_id", "unknown"), log.get("user_plan", "🆓 無料プラン"), log.get("event_type", ""), log.get("api_cost", 0.0), log.get("created_at", "")
                        total_users_set.add(u_id)
                        total_app_cost += cost
                        p_key = "free"
                        if "ライト" in plan: p_key = "light"
                        elif "プレミアム" in plan: p_key = "premium"

                        if e_type == "CHAT_SUCCESS":
                            stats_matrix["💬 総会話往復数（送信回数）"][p_key] += 1
                            total_app_chats += 1
                        elif e_type == "DAILY_LIMIT_EXCEEDED": stats_matrix["🚨 1日会話上限（ガードレール）の接触回数"][p_key] += 1
                        elif e_type == "SETTING_UPDATE_SUCCESS": stats_matrix["🎨 キャラなりきり・口調変更の実行回数"][p_key] += 1
                        elif e_type == "PROMPT_BLOCKED_IMAGE": stats_matrix["🚫 禁止：画像生成の無茶振り（コスト防衛）"][p_key] += 1
                        elif e_type == "PROMPT_BLOCKED_CODE": stats_matrix["🚫 禁止：コード生成の無茶振り（コスト防衛）"][p_key] += 1

                        if c_at_str:
                            try:
                                dt_jst = datetime.fromisoformat(c_at_str.replace("Z", "+00:00")).astimezone(JST)
                                if u_id not in user_active_dates: user_active_dates[u_id] = {"p_key": p_key, "dates": set()}
                                user_active_dates[u_id]["dates"].add(dt_jst.date().isoformat())
                            except Exception: pass

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
                except Exception as ana_err: st.error(f"データ集計中にエラーが発生しました: {ana_err}")

# ==================================================================
# 🆓👤【一般テスター・無料ユーザー画面】（管理者以外には隠す部屋）
# ==================================================================
else:
    # 💡 管理者以外のテスター画面には、タブ1（チャット）とタブ2（設定）の2つだけを対等に並べます
    tab1, tab2 = st.tabs(["💬 おしゃべりの部屋", "🎨 キャラクター・見た目設定"])
    
    # ------------------------------------------------------------------
    # 💬 【一般・タブ1】 おしゃべりの部屋
    # ------------------------------------------------------------------
    with tab1:
        display_user_name = f"{current_user_name}{current_user_honorific}" if current_user_honorific != "（呼び捨て/なし）" else current_user_name
        current_plan_type = st.session_state.get("current_user_plan_state", "🆓 無料プラン")

        st.title(f"💬 {current_concierge_name}の部屋")
        st.caption(f"担当コンシェルジュ: 【{current_concierge_name}】 | 現在のプラン: 【{current_plan_type}】")

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
                    ⚠️【重要：気遣い・特定の話題の重複禁止ルール（人間らしさの優先）】
                    ・直近5往復の会話履歴（recent_messages）の中で、あなたがすでに一度上記の「深夜の労い（無理しないでね、等）」や「特定の固有名詞の話題」に自律的に言及している場合は、同じ日のその後のラリーで毎回クドクドと繰り返さないでください。
                    ・人間と同じように「その話はさっき触れたから、もう十分伝わっている」と脳内で仕分け、その後の返答ではあえてその話題には一切触れず、ユーザーの新しい言葉の核心だけに集中してスマートに相槌を打ってください。ただし、昨日以前の会話のログであれば、日を改めて新しく労うのは大歓迎です。
                    ・※例外として、ユーザー側から進んでその話題を継続して質問・言及してきた場合のみ、同様のテーマであっても優しく返事をして、会話を成り立たせてください。
                    【過去の事実と今日の事実の分離ルール】
                    ・ユーザーから「過去のあの日は〇〇だったよ」と指摘された際、あなたの「今日の返答」が正しい事実であるならば、自分の今日の言葉まで嘘だと誤認して自爆（平謝り）しないでください。
                    ・「過去のあの日（過去ログ）の事実」と「今日の正しい事実」は両方とも同時に成立すると理解し、過去と現在の時系列の辻褄を100%完璧に仕分けた上で、スマートかつ自然に過去の記憶だけを訂正しておしゃべりを広げてください。
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

        st.components.v1.html("""
            <script>
                setTimeout(function() {
                    window.parent.document.querySelector('section.main').scrollTo({ top: 99999, behavior: 'smooth' });
                }, 1000);
            </script>
        """, height=0)

    # ------------------------------------------------------------------
    # 🎨 【一般・タブ2】 キャラクター・見た目設定画面
    # ------------------------------------------------------------------
    with tab2:
        st.write(f"### 🎨 {current_concierge_name}のカスタマイズ")
        st.caption("AIの見た目・口調・アプリのデザインを自分好みにリアルタイムに調教できます。")

        st.subheader("🎨 アプリの外観＆カラー")
        with st.form("color_form_tab_user"):
            selected_color = st.selectbox("カラーテーマ（背景＆メッセージ枠）", list(COLOR_THEMES.keys()), index=list(COLOR_THEMES.keys()).index(current_theme_color) if current_theme_color in COLOR_THEMES else 0)
            if st.form_submit_button("カラー設定を保存"):
                save_or_update_user_setting("カラーテーマ", selected_color)
                st.toast("アプリのカラーを変更したよ！")
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
            new_plan = st.selectbox("【デバッグ用】現在の会員プラン", plan_options, index=current_plan_idx)

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
                st.success("設定を更新したよ！")
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
