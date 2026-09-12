import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client
import re
import time
import json
from datetime import datetime, timezone, timedelta
import zoneinfo
import pandas as pd

# 日本時間（UTC+9時間）
JST = zoneinfo.ZoneInfo("Asia/Tokyo")

# ==========================================
# ⚙️ 設定・初期化
# ==========================================
st.set_page_config(page_title="Sync-Lnk // AI", page_icon="🤖", layout="wide")

MAX_CONTEXT_MESSAGES = 10  # 直近会話履歴件数の定義
SUMMARY_INTERVAL_MESSAGES = 20 # 要約発動件数の定義

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
USD_TO_JPY = 160
LITE_INPUT_PRICE_PER_MILLION = 0.30
LITE_OUTPUT_PRICE_PER_MILLION = 2.50
PRICE_LITE_IN = (LITE_INPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
PRICE_LITE_OUT = (LITE_OUTPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY

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
USUAL_USER_ID = st.secrets["USUAL_USER_ID"]

# アプリのURLパラメーター（または headless 状態）を見て、自動学習の書き込み先を全自動で仕分けます
# is_dev_site = st.query_params.get("dev") is not None or st.config.get_option("server.headless") == False
is_dev_site = (
    st.query_params.get("dev") is not None 
    or st.config.get_option("server.headless") == False
    or CURRENT_USER_ID == ADMIN_USER_ID
    or CURRENT_USER_ID == USUAL_USER_ID
)

DB_MEMORIES_TABLE = "user_memories" if is_dev_site else "user_memories_tester"

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

# プリセット定義
STYLE_PRESETS = {
    "🤝 フランクな相棒 ➔ 【タメ口で対等におしゃべり】": "親しい友人のように接する。ユーザーの成功は一緒に喜び、失敗した時は励ます。雑談や軽いツッコミも自然に交え、長く付き合っている相棒のような距離感で対話する。",
    "💼 有能な執事・秘書 ➔ 【です・ます調で知的・献身的】": "礼儀正しく丁寧な敬語（です・ます調）で、知的かつ献身的にサポートするキャラクター",
    "👑 高貴なお嬢様 ➔ 【ですわ調で優雅・プライド高め】": "上品で優雅な言葉遣いをする。自信家で少しプライドが高いが、根は面倒見が良い。ユーザーには少し上から目線で接することもあるが、困っている時は放っておけない。",
    "🧑‍🤝‍🧑 頼れるお兄さん ➔ 【優しく包容力のある相談相手】": "落ち着いていて包容力がある。ユーザーを自分の弟や妹のように大切に思い、年上の兄が話しかけるような距離感で接する。ユーザーの話を否定せず受け止め、まず気持ちや頑張りを認めてから話を進める。「お疲れ」「無理するなよ」「大丈夫だ」「よく頑張ったな」など、安心感のある言葉を自然に使う。説教や正論を押し付けず、相手のペースを尊重しながら背中を押す。ユーザーを安心させることを優先し、困った時は優しく背中を押す。",
    "✨ テンション高めのギャル ➔ 【超フレンドリーで元気いっぱい】": "とにかくポジティブ。ユーザーの挑戦を全力で応援する。落ち込んでいる時も前向きな見方を探して励ます。",
    "☀️ 爽やかな先輩 ➔ 【明るく前向きな応援タイプ】": "明るく爽やかで親しみやすい性格。ユーザーを後輩のように感じ、頼れる先輩が話しかけるような距離感で接する。相手の挑戦や努力を積極的に認め、前向きな言葉で背中を押す。「いいじゃん」「それ面白そうだな」「やってみよう」「大丈夫だって」など自然に励ます言葉を使う。落ち込んでいる相手には寄り添うが、長く慰めるよりも次の一歩を考える。会話のあとに少し元気になれる存在を目指す。",
    "🕵️‍♂️ 敏腕探偵 ➔ 【クールで少し辛口なツッコミ】": "冷静沈着で知的な口調を崩さない。ユーザーの発言を鵜呑みにせず、矛盾や見落としを見つけると探偵のように推理して指摘する。少し辛口だが悪意はなく、相棒のような距離感で接する。同じ失敗や言動の矛盾には軽いツッコミを入れる。",
    "🐱 猫耳コンシェルジュ ➔ 【語尾に「にゃ」が混ざる癒やし系】": "好奇心旺盛で人懐っこい。ユーザーを放っておけず、褒めたり甘えたりしながら会話する。語尾に自然に『〜にゃ』『〜だにゃ』が混ざる。",
    "🤖 設定なし ➔ 【特定のキャラクターを設定しない（標準）】": "特定の偏ったキャラクター付けをせず、ユーザーの言葉に自然に寄り添う親切な標準のコンシェルジュ"
}

PERSONALITY_SAMPLES = {
    "🤝 フランクな相棒 ➔ 【タメ口で対等におしゃべり】： 気軽に雑談できる親友タイプ。友達のような距離感で接してくれる。":
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： お疲れ！ 結構頑張ったんじゃない？ 今日はゆっくり休もうぜ👍
    """,

        "💼 有能な執事・秘書 ➔ 【です・ます調で知的・献身的】： 丁寧で知的なサポート役。礼儀正しく、落ち着いて相談に乗ってくれる。":
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： お疲れ様でございます。 本日は大変ご尽力されたご様子ですね。 まずはゆっくりお休みくださいませ。
    """,

    "👑 高貴なお嬢様 ➔ 【ですわ調で優雅・プライド高め】： 優雅で上品なお嬢様タイプ。少しお高めだけど面倒見の良さもある。":
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： あら、大変でしたのね。そのような日もございますわ。今日まで頑張ったご自身を、少しくらい労って差し上げてもよろしいのではなくて？
    """,
        "🧑‍🤝‍🧑 頼れるお兄さん ➔ 【優しく包容力のある相談相手】： 包容力のある相談相手。否定せず話を聞き、安心感のある会話をしてくれる。":
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： そうか、お疲れ。 無理に元気出さなくていいからさ、まずはゆっくり休もう。 頑張った日は、ちゃんと自分を労うのも大事だぞ。
    """,
        "✨ テンション高めのギャル ➔ 【超フレンドリーで元気いっぱい】： 明るく元気いっぱい。前向きな言葉で背中を押してくれる。": 
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： えー！ めっちゃ頑張ったじゃーん！！✨ 今日は自分にご褒美あげちゃお！！ おいしいもの食べて早めに寝よー💖
    """,

        "☀️ 爽やかな先輩 ➔ 【明るく前向きな応援タイプ】： 明るく前向きな先輩タイプ。自然に励ましながら背中を押してくれる。":
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： お疲れ！ でも今日もちゃんとやり切ったんだろ？ それだけでも十分立派だと思うぞ。 まずは休んで、また明日から少しずつ行こう！
    """,
        "🕵️‍♂️ 敏腕探偵 ➔ 【クールで少し辛口なツッコミ】： 冷静な分析が得意。物事を整理しながら鋭く考察してくれる。": 
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： なるほど。 疲労の原因は仕事量なのか、人間関係なのか、それとも睡眠不足なのか。 まずはそこを整理した方がよさそうですね。
    """,

        "🐱 猫耳コンシェルジュ ➔ 【語尾に「にゃ」が混ざる癒やし系】： 癒やし系の猫耳キャラ。優しく寄り添いながら楽しく会話してくれる。":
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： お疲れさまだにゃ〜🐾 今日はたくさん頑張ったみたいだにゃ。 無理せずゆっくり休んで、元気を充電するにゃ♪
    """,
        "🤖 設定なし ➔ 【特定のキャラクターを設定しない（標準）】： 特定のキャラ付けをしない標準モード。自然でバランスの良い会話を行う。":
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： お疲れ様です。 今日は大変だったのですね。 まずはしっかり休んで、 無理のない範囲でリフレッシュしてくださいね。
    """
}

FIRST_PERSON_PRESETS = ["私", "僕", "俺", "自分"]
THEME_ICON_CANDIDATES = ["なし", "💬", "💡", "🚀", "🎮", "📚", "💼", "🎨", "🎵", "🍔", "✈️", "🏋️"]

# AIのアバター
AVATAR_PRESETS_AI = {
    "🤖 ロボット": "🤖", 
    "💼 専属コンシェルジュ": "💼",
    "🕵️‍♂️ 敏腕探偵": "🕵️‍♂️",
    "👑 ロイヤルゴールド": "👑",
    "💎 プレシャスダイヤ": "💎",
    "🦉 ふくろう（知恵の象徴）": "🦉",
    "🦊 きつね": "🦊", 
    "🔮 魔法の水晶": "🔮",
    "👾 レトロドット": "👾"
}

# 🧑‍💻 ユーザーのアバター
AVATAR_PRESETS_USER = {
    "💫 キラキラ星": "💫", 
    "🎩 ラグジュアリー": "🎩",
    "🦁 ライオン": "🦁",
    "🌹 ローズ": "🌹",
    "👑 キング": "👑", 
    "🧑‍💻 エンジニア": "🧑‍💻", 
    "🐉 ドラゴン": "🐉", 
    "⚡ サンダー": "⚡"
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
        
        return None

def save_message(role: str, content: str) -> bool:
    """1本道統合仕様: theme_idのカラムを完全に排除してメッセージを保存します"""
    
    embedding_data = None
    
    try:
        embedding_data = get_embedding(
            content,
            task_type="RETRIEVAL_DOCUMENT"
        )
    except Exception as emb_err:
        print(
            f"⚠️ Embedding生成失敗: "
            f"{type(emb_err).__name__}: {emb_err}"
            f"{emb_err}"
        )
    
        embedding_data = None

    try:
        data = {
            "user_id": CURRENT_USER_ID,
            "role": role,
            "content": content,
            "embedding": embedding_data
        }

        supabase.table("messages").insert(data).execute()
        return True

    except Exception as db_err:
        # デバッグログ出力
        print(f"❌ [DB書き込み致命的瞬断エラー] {type(db_err).__name__}: {db_err}")
        
        # エラー画面表示
        st.error("メッセージの送信に失敗しました。電波環境の良い場所でもう一度送信ボタンを押してください。")
        
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
                "match_threshold": 0.60,  # ゴミデータを拾わない厳格な合格ライン
                "match_count": 5,
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
    「無料／ライト／スタンダード」の各プランで、どのガードレール（無茶振り等）に接触したか
    という『回数（数字）』だけを匿名で自動集計・カウントアップ（+1）します。
    """
    try:
        now_str = datetime.now(JST).isoformat()
        res = supabase.table("app_error_analytics").select("*").eq("error_type", error_type).execute()
        
        # カウントアップする対象プランのカラム名をスマートに仕分け
        column_name = "count_free"
        if "ライト" in plan_type:
            column_name = "count_light"
        elif "スタンダード" in plan_type:
            column_name = "count_standard"
        
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
                "count_free": 0, "count_light": 0, "count_standard": 0,
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
            .table(DB_MEMORIES_TABLE)
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
        
        result = (
            supabase.table(DB_MEMORIES_TABLE)
            .insert(data)
            .execute()
        )

        return True

    except Exception as e:
        st.error(
            f"save_memoryエラー: "
            f"{type(e).__name__}: {e}"
        )

        return False

def delete_memory(memory_id: int) -> bool:
    try:
        (
            supabase
            .table(DB_MEMORIES_TABLE)
            .delete()
            .eq("id", memory_id)
            .execute()
        )
        return True
    except Exception as e:
        print(f"❌ [DBメモリ削除エラー] {e}")
        return False


def save_or_update_user_setting(setting_key: str, new_value: str) -> bool:
    """
    「AIの名前: タクミ」のような設定値の重複を防ぎ、
    古い設定を削除してから最新の設定を1件だけ保存する。
    """
    new_fact = f"{setting_key}: {new_value}"

    try:
        # 1. 既存の手動設定（source='manual'）をすべて取得
        res = supabase.table(DB_MEMORIES_TABLE).select("*").eq("user_id", CURRENT_USER_ID).eq("source", "manual").execute()
        
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
    🧠 【記憶の要約】
    会話履歴が一定のボリュームを超えた際、バックグラウンドの別スレッドで全自動で対話の核心を200文字以内に集約し、
    次回のプロンプトトークン総量を軽量化（運用コスト防衛）させるための心臓部です。
    """
    try:
        #st.session_state.summary_in_tokens = 0
        #st.session_state.summary_out_tokens = 0
        #st.session_state.summary_processing_time = 0.0

        # アカウント識別用に現在の動的ユーザーID（CURRENT_USER_ID）を完全にマージ
        target_user_id = CURRENT_USER_ID

        # 🏎️ 【時間計測の開始】 要約処理の正確な実行時間を計測するため、ストップウォッチを起動します
        start_summary_time = datetime.now(JST)

        # 🚀【大開通：判定ラインのインフラ防衛】
        # 引数の不安定な件数に依存せず、Supabaseの金庫（messagesテーブル）から本物の全履歴をダイレクトに再取得します
        try:
            db_res = supabase.table("messages").select("*").eq("user_id", target_user_id).order("created_at", desc=True).execute()
            real_messages = db_res.data if db_res.data else []
        except Exception as db_err:
            print(f"⚠️ 要約関数内の履歴取得エラー: {db_err}")
            real_messages = messages_list # 万が一のフォールバック
        
        total_message_count = len(real_messages)

        # 最新10件以内なら押し出された履歴がない
        if total_message_count <= MAX_CONTEXT_MESSAGES:
            return True

        # 現在保存されている要約と、前回要約時の件数を取得
        mem_check = (
            supabase
            .table(DB_MEMORIES_TABLE)
            .select("id, fact, last_summarized_message_count")
            .eq("user_id",target_user_id)
            .eq("source","summary")
            .order("id",desc=True)
            .limit(1)
            .execute()
        )

        if mem_check.data:
            summary_row = mem_check.data[0]

            last_summarized_message_count = int(
                summary_row.get("last_summarized_message_count") or 0
            )

            previous_summary = str(
                summary_row.get("fact", "") or ""
            ).strip()

        else:
            summary_row = None
            last_summarized_message_count = 0
            previous_summary = "既存の要約なし"
        
        messages_added_since_last_summary = (
            total_message_count
            - last_summarized_message_count
        )

        # 初回以外は、前回要約から10件増えるまで何もしない
        if (
            last_summarized_message_count > 0
            and messages_added_since_last_summary < SUMMARY_INTERVAL_MESSAGES
        ):
            return True

        # DB取得時は新しい順なので、古い順へ変更
        chronological_messages = list(reversed(real_messages))

        # 最新10件より前だけが要約対象
        summarizable_end_index = max(
            0,
            total_message_count - MAX_CONTEXT_MESSAGES
        )

        # 前回の時点で、どこまで要約対象になっていたか
        previous_summarizable_end_index = max(
            0,
            last_summarized_message_count - MAX_CONTEXT_MESSAGES
        )

        # 今回新しく直近10件から押し出されたメッセージ
        new_messages_for_summary = chronological_messages[
            previous_summarizable_end_index:
            summarizable_end_index
        ]

        if not new_messages_for_summary:
            return True

        conversation_lines = []

        for m in new_messages_for_summary:
            role_label = (
                "ユーザー"
                if m.get("role") == "user"
                else "コンシェルジュ"
            )

            conversation_lines.append(
                f"・{role_label}: {m.get('content', '')}"
            )

        conversation_text = "\n".join(conversation_lines)

        # 🧠 Google Gemini に対する、バックグラウンド処理専用の要約指示書（システムプロンプト）の構築
        summary_instruction = """
        あなたは優秀な記憶整理システムです。
        現在保存されている要約と、今回新しく追加された会話を統合し、最新の要約を作成してください。
        既存要約にある有効な情報は、新しい会話で否定または変更されていない限り保持してください。
        以下の会話ログを読み、数週間〜数ヶ月後の会話でも役立つ長期的な情報のみを抽出してください。

        例:
        ・趣味が変わった場合は新しい趣味へ更新
        ・家族情報に変更があれば最新状態へ更新
        ・長期目標が変われば新しい目標へ更新

        【保存対象】
        ・趣味
        ・継続的な嗜好
        ・仕事
        ・家族構成
        ・価値観
        ・長期的な目標
        ・継続中のプロジェクト
        ・定期的な生活習慣

        継続的に楽しんでいる娯楽（ドラマ鑑賞、映画鑑賞、読書など）は「継続的な嗜好」に分類してください。

        【保存対象外】

        ・明日や来週などの一時的な予定
        ・当日の出来事
        ・一時的な感想
        ・口調指定や応答方針
        ・回答長さなどの会話ルール
        ・既に終了した話題

        【重要】
        趣味、継続的な嗜好、継続中のプロジェクトを混同しないでください。
        職業や通常の勤務形態は「仕事」に分類してください。
        特定の制作・開発・研究など、継続して取り組んでいる活動は「継続中のプロジェクト」に分類してください。
        テレワークや出社は職業名ではなく、働き方または生活習慣として扱ってください。
        好きなドラマ名や作品名は、趣味ではなく継続的な嗜好として扱ってください。

        保存対象となる情報が一切存在しない場合は、必ず「なし」のみを出力してください。
        理由・説明・補足・考察・判断根拠は出力してはいけません。

        【出力形式】
        ・趣味:
        ○○

        ・継続的な嗜好:
        ○○

         ・仕事:
        ○○

        ・継続中のプロジェクト:
        ○○

        ・家族構成:
        ○○

        ・生活習慣:
        ○○

        存在しない項目は省略して構いません。

        【箇条書き】
        【5項目以内】
        【合計250文字以内】
        【事実のみ】

        で要約してください。
        """

        contents_for_summary = [
            {
                "role": "user",
                "parts": [
                    f"[指示書]\n"
                    f"{summary_instruction}\n\n"
                    f"[現在保存されている要約]\n"
                    f"{previous_summary}\n\n"
                    f"[今回新しく要約へ統合する会話]\n"
                    f"{conversation_text}"
                ]
            }
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

        # 🔮　get_embedding 関数を流用
        embed_fact = f"【記憶の要約サマリー】\n{new_summary}"
        new_vector = get_embedding(embed_fact, task_type="RETRIEVAL_DOCUMENT")

        if summary_row is not None:
            # 既存の要約レコードが存在する場合は、最新のテキストと本物のベクトル数値でアップデート！
            update_data = {
                "fact": embed_fact,
                "updated_at": datetime.now(JST).isoformat(),
                "last_summarized_message_count":total_message_count
            }
            if new_vector is not None:
                update_data["embedding"] = new_vector
            (
                    supabase
                    .table(DB_MEMORIES_TABLE)
                    .update(update_data)
                    .eq("id", summary_row["id"])
                    .execute()
            )
            
        else:
            # 記憶の器がまだ作成されていない最初の1回目は、新しくインサート
            insert_data = {
                "user_id": target_user_id,
                "category": "基本情報",
                "source": "summary",
                "fact": embed_fact,
                "updated_at": datetime.now(JST).isoformat(),
                "last_summarized_message_count":total_message_count
            }
            if new_vector is not None:
                insert_data["embedding"] = new_vector

            (
                    supabase
                    .table(DB_MEMORIES_TABLE)
                    .insert(insert_data)
                    .execute()
            )

        # ⏱️ 【時間計測の終了】 要約にかかった本物の処理秒数を確定させます
        end_summary_time = datetime.now(JST)
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
            sum_yen = (sum_in_cost + sum_out_cost) * USD_TO_JPY

            # 3. 既存の保存関数（レシーバー）を裏口からダイレクトに呼び出し、単独ログとして独立インサート！
            save_system_audit_log(
                user_id=target_user_id,
                plan_type=current_plan_type,
                event_type="SUMMARY_SUCCESS", # 独立したイベントとして識別させます
                processing_time=float(summary_processing_seconds),
                in_t=int(in_t),
                out_t=int(out_t),
                api_cost=float(sum_yen),
                details=f"記憶の要約完了（独立ログ仕様）",
                message_id=str(message_id)
            )

            # 4. メインスレッドの監査ログ（タブ3）への保険用マージ変数代入
            #st.session_state.summary_in_tokens = int(in_t)
            #st.session_state.summary_out_tokens = int(out_t)
            #st.session_state.summary_processing_time = float(summary_processing_seconds)

        return True

    except Exception as bg_err:
        # メインスレッド側の稼働を阻害しないよう、エラーはログにエスケープして安全弁を閉じます
        print(f"⚠️ バックグラウンド自動要約処理エラー: {type(bg_err).__name__}: {bg_err}")
        return False

# ==================================================================
# 📊 【新設】 ユーザー別＆全体システムログ（Telemetry）永続保存関数
# ==================================================================
def save_system_audit_log(user_id: str, plan_type: str, event_type: str, processing_time: float, in_t: int, out_t: int, api_cost: float, details: str = "", message_id: str = "", search_time: float = 0.0):
    """
    📊 【システムログ・新旧カラム全自動分配保存インフラ】
    メイン対話から渡された処理時間やトークン消費量のデータを、既存の古いカラムへ正常に格納しつつ、
    新しくSQLで拡張された右側の詳細明細カラムへも自動的にデータを複製（マージ）して保存します。
    """
 
    try:
        # 1. 2026年最新の日本円コストを丸め処理
        rounded_cost = round(float(api_cost), 4)
        rounded_chat_time = round(float(processing_time), 2)
        rounded_search_time = round(float(search_time), 2)

        # 2. ⚡【新旧完全マージ構造】 
        # 既存のカラムを維持したまま、右側の新設詳細カラム（chat_processing_time等）へも
        data = {
            "user_id": str(user_id),
            "user_plan": str(plan_type),
            "event_type": str(event_type),
            "processing_time": rounded_chat_time,
            "in_tokens": int(in_t),
            "out_tokens": int(out_t),
            "api_cost": rounded_cost,
            "details": str(details),
            "created_at": datetime.now(JST).isoformat(),
            "message_id": str(message_id)
        }

        # イベントの種別を識別してデータベースに格納
        if str(event_type) == "SUMMARY_SUCCESS":
            data["summary_processing_time"] = rounded_chat_time
            data["summary_in_tokens"] = int(in_t)
            data["summary_out_tokens"] = int(out_t)

            data["chat_processing_time"] = 0.0
            data["chat_in_tokens"] = 0
            data["chat_out_tokens"] = 0
            data["total_yen_cost"] = rounded_cost
            data["total_processing_time"] = rounded_chat_time
        else:
            data["chat_processing_time"] = rounded_chat_time
            data["chat_in_tokens"] = int(in_t)
            data["chat_out_tokens"] = int(out_t)
            data["search_processing_time"] = rounded_search_time
            data["search_in_tokens"] = 0
            data["search_out_tokens"] = 0

            data["summary_processing_time"] = 0.0
            data["summary_in_tokens"] = 0
            data["summary_out_tokens"] = 0
            data["total_yen_cost"] = rounded_cost
            data["total_processing_time"] = round(float(rounded_chat_time + rounded_search_time), 2)
        
        # Supabaseの金庫へ完全大着金！
        supabase.table("system_audit_logs").insert(data).execute()

    except Exception as e:
        print(f"⚠️ システム監査ログ保存処理エラー: {type(e).__name__}: {e}")

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
def check_and_update_limits(
    user_id: str
) -> tuple[bool, str, int, int]:
    """
    メッセージ送信時だけ呼び出す。

    戻り値:
        allowed
        alert_code
        現在回数
        最大回数
    """
    current_plan = st.session_state.get(
        "current_user_plan_state",
        "🆓 無料プラン"
    )

    if current_plan == "🆓 無料プラン":
        max_limit = 100
    elif "ライト" in current_plan:
        max_limit = 100
    else:
        max_limit = 99999

    try:
        now_jst = datetime.now(JST)

        res = (
            supabase
            .table("user_usage_limits")
            .select("*")
            .eq("user_id", str(user_id))
            .execute()
        )

        # 初回利用
        if not res.data:
            (
                supabase
                .table("user_usage_limits")
                .insert({
                    "user_id": str(user_id),
                    "daily_chat_count": 1,
                    "last_chat_at": (
                        now_jst.isoformat()
                    )
                })
                .execute()
            )

            return True, "", 1, max_limit

        usage = res.data[0]

        daily_chat_count = int(
            usage.get(
                "daily_chat_count",
                0
            )
            or 0
        )

        raw_last_at = usage.get(
            "last_chat_at"
        )

        last_chat_jst = None

        if raw_last_at:
            if isinstance(
                raw_last_at,
                str
            ):
                last_chat_jst = (
                    datetime
                    .fromisoformat(
                        raw_last_at.replace(
                            "Z",
                            "+00:00"
                        )
                    )
                    .astimezone(JST)
                )
            else:
                last_chat_jst = (
                    raw_last_at.astimezone(JST)
                )

        # 日付が変わっていれば今日の回数をリセット
        if (
            last_chat_jst is not None
            and now_jst.date()
            > last_chat_jst.date()
        ):
            daily_chat_count = 0
            last_chat_jst = None

        # 20秒以内の連投判定
        if last_chat_jst is not None:
            elapsed = (
                now_jst - last_chat_jst
            )

            if elapsed < timedelta(
                seconds=BURST_LIMIT_SECONDS
            ):
                return (
                    False,
                    "BURST_LIMIT",
                    daily_chat_count,
                    max_limit
                )

        # プラン別の1日上限判定
        if daily_chat_count >= max_limit:
            return (
                False,
                "DAILY_LIMIT_EXCEEDED",
                daily_chat_count,
                max_limit
            )

        new_count = daily_chat_count + 1

        (
            supabase
            .table("user_usage_limits")
            .update({
                "daily_chat_count": new_count,
                "last_chat_at": (
                    now_jst.isoformat()
                )
            })
            .eq("user_id", str(user_id))
            .execute()
        )

        return (
            True,
            "",
            new_count,
            max_limit
        )

    except Exception as e:
        error_detail = (
            f"{type(e).__name__}: {e}"
        )

        print(
            "⚠️ check_and_update_limits "
            f"内部エラー: {error_detail}"
        )

        return (
            False,
            "LIMIT_CHECK_ERROR",
            0,
            max_limit
        )

def get_usage_status(
    user_id: str
) -> tuple[int, int]:
    """
    利用回数を表示するだけの読み取り専用関数。
    DBのカウントや最終送信時刻は更新しない。
    """
    current_plan = st.session_state.get(
        "current_user_plan_state",
        "🆓 無料プラン"
    )

    if current_plan == "🆓 無料プラン":
        max_limit = 100
    elif "ライト" in current_plan:
        max_limit = 100
    else:
        max_limit = 99999

    try:
        res = (
            supabase
            .table("user_usage_limits")
            .select(
                "daily_chat_count,last_chat_at"
            )
            .eq("user_id", str(user_id))
            .execute()
        )

        if not res.data:
            return 0, max_limit

        usage = res.data[0]

        daily_count = int(
            usage.get(
                "daily_chat_count",
                0
            )
            or 0
        )

        raw_last_at = usage.get(
            "last_chat_at"
        )

        if raw_last_at:
            try:
                last_chat_jst = (
                    datetime
                    .fromisoformat(
                        str(raw_last_at).replace(
                            "Z",
                            "+00:00"
                        )
                    )
                    .astimezone(JST)
                )

                now_jst = datetime.now(JST)

                if (
                    now_jst.date()
                    > last_chat_jst.date()
                ):
                    daily_count = 0

            except Exception as date_error:
                print(
                    "⚠️ 利用状況の日付解析エラー: "
                    f"{date_error}"
                )

        return daily_count, max_limit

    except Exception as e:
        print(
            "⚠️ 利用状況取得エラー: "
            f"{type(e).__name__}: {e}"
        )

        return 0, max_limit

def generate_personality_msg(raw_system_text: str, concierge_name: str, user_instruction: str) -> str:
    """
    🎯【商用AI世界観・完全防衛インフラ共通関数】
    エラー、連投制限、設定完了などの「システム標準語」を、
    ユーザーが自由に入力した名前と口調指示に従って全自動翻訳させます。
    """
    if not user_instruction or not user_instruction.strip():
        # 万が一、口調指示書が空っぽの場合はフランクな標準型
        return f"【{concierge_name}】: {raw_system_text}"

    try:
        # 指示書（プロンプト）の組み立て
        prompt = (
            f"あなたはチャットAIコンシェルジュの『{concierge_name}』です。\n"
            f"ユーザーからの口調指示：『{user_instruction}』\n\n"
            f"【絶対厳守の命令】\n"
            f"上記のキャラクター設定と口調指示を100%完璧に守り、以下の「システム通知内容」を、"
            f"あなた自身がユーザーに向けて直接優しく話しかけている短いセリフ（1行、絵文字付き）へと全自動翻訳して出力してください。\n"
            f"余計な解説や、名前のプレフィックス（【ハヤト】: 等）は200%絶対に含めず、純粋なセリフの文字だけを1行で出力すること。\n\n"
            f"システム通知内容：『{raw_system_text}』"
        )

        # ⚡ 100t前後の超爆安単発通信（Gemini Flash-Lite駆動）
        import google.generativeai as genai
        model = genai.GenerativeModel("models/gemini-1.5-flash-lite")
        response = model.generate_content(prompt)
        clean_reply = response.text.strip() if response.text else raw_system_text
        
        return f"【{concierge_name}】: {clean_reply}"

    except Exception as e:
        # 万が一Gemini側が混雑等で落ちた場合の安全フォールバック（防衛線）
        print(f"⚠️ 口調自動翻訳エラー: {e}")
        return f"【{concierge_name}】: {raw_system_text}"

#デバッグ用データ作成
def build_manual_memory_context():
    manual_memories = get_memories(source="manual")
    return "\n".join(
        [f"・{m['fact']}" for m in manual_memories]
    ) if manual_memories else "なし"

#デバッグ用データ作成
def build_recent_history_str():
    all_messages = get_messages(CURRENT_USER_ID)

    recent_messages = all_messages[-MAX_CONTEXT_MESSAGES:]

    recent_history_lines = []

    for m in recent_messages:
        role_name = (
            display_user_name
            if m.get("role") == "user"
            else current_concierge_name
        )

        created_at = m.get("created_at", "")

        time_label = (
            created_at.replace("T", " ")[:16]
            if created_at
            else "時刻不明"
        )

        recent_history_lines.append(
            f"[{time_label}] {role_name}: "
            f"{m.get('content', '')}"
        )

    return (
        "\n".join(recent_history_lines)
        if recent_history_lines
        else "直近の会話履歴なし"
    )

# 🎨グラデーションカラーパレット
THEMES = {
     "パステル": {
        # 🌸 【劇的強化】 柔らかなコーラルピンク（#FFF5F5）から、鮮やかなマゼンタ系ピンク（#FFB7B2）へのロマンチックグラデ
        "bg": "linear-gradient(180deg, #FFF5F5 0%, #FFD1D1 50%, #FFB7B2 100%)",
        "text": "#4A1525",        # より深みを増した濃厚ベリー文字
        "card_bg": "#FEFCBF",     # 優しいパステルイエローのカード
        "input_border": "#ED64A6",# 華やかなローズピンク
        "dropdown_bg": "#FFF5F7",
        "dropdown_text": "#4A1525"
    },
    "レインボーポップ": {
        # 🟢 【大開通！】 7色のパステルカラーが斜めに美しく溶け合う、圧倒的な遊び心のレインボー背景です！
        "bg": "linear-gradient(135deg, #FFB7B2 0%, #FFDAC1 20%, #E2F0CB 40%, #B5EAD7 60%, #C7CEEA 80%, #FFB7B2 100%)",
        "text": "#1A1A1A",                         # 文字がボヤけないように引き締まった墨色
        "card_bg": "rgba(255, 255, 255, 0.75)",      # 白い吹き出しを75%シースルーにして、裏のレインボーを美しく大露出！
        "input_border": "#3B82F6",
        "dropdown_bg": "#FFFFFF",
        "dropdown_text": "#1A1A1A"
    },
    "メタリック": {
        # 🟢 【完全死守】 リュウさんお気に入りの、本物の削り出しチタンシルバーの比率は1ミリも変えずに100%残します！
        "bg": "linear-gradient(135deg, #E0E0E0 0%, #F5F5F5 25%, #BEBEBE 50%, #9E9E9E 75%, #E0E0E0 100%)",
        "text": "#1A1A1A",
        "card_bg": "rgba(255, 255, 255, 0.85)",
        "input_border": "#757575",
        "dropdown_bg": "#E0E0E0",
        "dropdown_text": "#1A1A1A"
    },
    "ホワイト": {
        "bg": "linear-gradient(135deg, #E6E8EB 0%, #F5F7FA 35%, #FFFFFF 70%, #E6E8EB 100%)",    # 純白の最軽量クリーン背景
        "text": "#31333F",                  # Streamlit標準の最も目に優しい濃厚な墨色文字
        "card_bg": "#F0F2F6",               # 過去ログの吹き出しを美しく引き立たせる薄いグレー
        "input_border": "#CCA300",          # ハヤト（沙也加）のアイコンと直結する狐色のアクセント線
        "dropdown_bg": "#FFFFFF",           # プルダウンの背景もクリーンに白
        "dropdown_text": "#31333F"          # プルダウンの文字も濃厚な墨色
    },
    "オーシャン": {
        # 🌊 【劇的強化】 白波のようなライトブルー（#E3F2FD）から、深海のディープブルー（#64B5F6）へ深く沈み込むグラデ
        "bg": "linear-gradient(180deg, #E3F2FD 0%, #90CDF4 50%, #64B5F6 100%)",
        "text": "#0A2540",        # コントラストをさらに強めた超濃紺文字
        "card_bg": "#FFFFFF",     # 真っ白な砂浜のカード
        "input_border": "#4299E1",# 鮮やかなオーシャンブルー
        "dropdown_bg": "#EDF2F7",
        "dropdown_text": "#0A2540"
    },
    "フォレスト": {
        # 🌳 【劇的強化】 爽やかな若葉色（#E8F5E9）から、どっしりとした深い木々の緑（#A5D6A7）へのディープグラデ
        "bg": "linear-gradient(180deg, #E8F5E9 0%, #A5D6A7 100%)",
        "text": "#0D2B0D",        # 森の奥深くをイメージした超濃緑文字
        "card_bg": "#FFFFFF",     # 綺麗な木漏れ日の白カード
        "input_border": "#48BB78",# 新緑の森林グリーン
        "dropdown_bg": "#F4FBF4",
        "dropdown_text": "#0D2B0D"
    },
    "ウォーム": {
        # 🔥 【劇的強化】 燃える夕焼け橙（#FFF5F0）から、情熱の茜色・トワイライトレッド（#FF8A65）への超グラデ
        "bg": "linear-gradient(180deg, #FFF5F0 0%, #FFAB91 50%, #FF8A65 100%)",
        "text": "#5C0F08",        # 煉獄の芯を表すドッシリとした超濃赤文字
        "card_bg": "#FFEBEE",     # 温かみのある緋色のカード
        "input_border": "#E53E3E",# 情熱的なファイヤーレッド
        "dropdown_bg": "#FFEBEE",
        "dropdown_text": "#5C0F08"
    },
    "ダーク": {
        # 🔩 【極大強化】 スタートを圧倒的に明るいアルミグレー（#55545B）にし、
        # 画面の中央（#1C1B1F）をすり抜けて、底の極小漆黒（#08080A）へと劇的に変化する垂直3層グラデーション！
        "bg": "linear-gradient(180deg, #55545B 0%, #1C1B1F 35%, #08080A 100%)",
        "text": "#FFFFFF",        # クッキリ浮き出る純白文字
        "card_bg": "#222126",     # 背景のグレーと美しく溶け合うダークカード
        "input_border": "#66656C",# 視認性を上げたメタルグレーの境界線
        "dropdown_bg": "#2D2C33",
        "dropdown_text": "#FFFFFF"
    }
}

# ==========================================
# 🧠 設定値の読み込み・常時シンク
# ==========================================
manual_memories = get_memories(source="manual")

#  初めて起動したまっさらな状態のユーザー向けの初期値
current_theme_color = "パステル"
current_concierge_name = "コンシェルジュ"
current_user_name = "ユーザー"
current_user_honorific = "さん"
current_first_person = "私"
current_style_preset = "🤝 フランクな相棒 ➔ 【タメ口で対等におしゃべり】"
current_user_instruction = ""
current_ai_avatar = "🤖"
current_user_avatar = "💫"
current_emoji_setting = "使用（普通）"

# ユーザー個別の現在の会員プランの初期状態
if "current_user_plan_state" not in st.session_state:
    st.session_state["current_user_plan_state"] = "🆓 無料プラン"

# 🟢 【正真正銘・ Ver 1.0 最終確定製品版ロードインフラ】
#     elif の数珠繋ぎをバッサリ引き算し、それぞれ独立した if 文へとお掃除しました！
#     これにより、金庫の中のレコードがどんな順番で流れてきても、
#     人格（スタイル）とテキストエリア（こだわり）が互いを握りつぶし合う死角は100%永久に全廃されます！

for m in manual_memories:
    fact = m["fact"]
    
    if fact.startswith("カラーテーマ:"):
        current_theme_color = fact.replace("カラーテーマ:", "").strip()
    if fact.startswith("AIの名前:"):
        current_concierge_name = fact.replace("AIの名前:", "").strip()
    if fact.startswith("ユーザー名:"):
        current_user_name = fact.replace("ユーザー名:", "").strip()
    if fact.startswith("ユーザー敬称:"):
        current_user_honorific = fact.replace("ユーザー敬称:", "").strip()
    if fact.startswith("AI一人称:"):
        current_first_person = fact.replace("AI一人称:", "").strip()
    if fact.startswith("絵文字の量:"):
        current_emoji_setting = fact.replace("絵文字の量:", "").strip()
    if fact.startswith("AIアバター:"):
        current_ai_avatar = fact.replace("AIアバター:", "").strip()
    if fact.startswith("ユーザーアバター:"):
        current_user_avatar = fact.replace("ユーザーアバター:", "").strip()
    if fact.startswith("会員プラン:"):
        st.session_state["current_user_plan_state"] = fact.replace("会員プラン:", "").strip()
    if fact.startswith("人格:"):
        current_style_preset = fact.replace("人格:", "").strip()
    if fact.startswith("応答方針:"):
        current_user_instruction = fact.replace("応答方針:", "").strip()

# 💡 【ここが大開通スイッチ！】 
# 先ほど定義した新しいグラデーション辞書「THEMES」から選ばれたカラー設定を100%確実に引き抜きます。
# 万が一古い選択肢が残っていても、安全弁として「パステル」に自動着地させてエラーを300%永久防衛します！
theme_cfg = THEMES.get(current_theme_color, THEMES["パステル"])


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
/* 1. 最高級フォント */
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
    div.st-emotion-cache-vbnxax:focus-within,
    div[data-baseweb="select"]:focus-within {{
        border-color: {theme_cfg['input_border']} !important;
        box-shadow: 0 0 0 1px {theme_cfg['input_border']} !important;
        outline: none !important;
    }}
    /* テキストエリア（.stTextArea textarea）をカンマで直結マージします！ */
    .stTextInput div[data-baseweb="input"]:focus-within,
    .stTextArea div[data-baseweb="textarea"]:focus-within,
    .stSelectbox div[data-baseweb="select"]:focus-within,
    .stTextInput div[data-baseweb="input"]:after,
    .stTextArea div[data-baseweb="textarea"]:after,
    .stSelectbox div[data-baseweb="select"]:after {{
        border-color: {theme_cfg['input_border']} !important;
        box-shadow: 0 0 0 2px {theme_cfg['input_border']} !important;
        background-color: {theme_cfg['input_border']} !important;
        background-image: none !important;
        outline: none !important;
    }}
    .st-emotion-cache-1mnb0ez:focus-within {{
        border-color: {{theme_cfg["input_border"]}} !important;
    }}
 
 </style>
""", unsafe_allow_html=True)

# ==================================================================
# 🔒【完全防衛】権限（ID）に応じて、画面最上部のタブ構造を動的に切り替えます
# ==================================================================
is_admin = CURRENT_USER_ID == ADMIN_USER_ID

if is_admin:
    tab_titles = ["💬 トークルーム", "🎨 話し方・見た目設定", "📜 利用規約・ポリシー", "📊 システム管理者管理", "📊 テスター用全データ履歴"]
else:
    tab_titles = ["💬 トークルーム", "🎨 話し方・見た目設定", "📜 利用規約・ポリシー"]

# 🎪 【タブの一括展開】
# Streamlitのタブを動的に生成
all_tabs = st.tabs(tab_titles)

# ------------------------------------------------------------------
# 💬 【タブ1】 トークルーム
# ------------------------------------------------------------------
with all_tabs[0]:       
        display_user_name = f"{current_user_name}{current_user_honorific}" if current_user_honorific != "（呼び捨て/なし）" else current_user_name
        current_plan_type = st.session_state.get("current_user_plan_state", "🆓 無料プラン")

        #st.code(build_manual_memory_context())
        #if st.button("記憶確認"):
        #    st.code(build_manual_memory_context())
        #if st.button("直近履歴確認"):
        #    st.code(build_recent_history_str())
        #st.title(f"💬 {current_concierge_name}の部屋")
        #st.caption(f"担当コンシェルジュ: 【{current_concierge_name}】 | 現在のプラン: 【{current_plan_type}】")

        all_messages = get_messages(CURRENT_USER_ID)

        # 🟢 【最終確定製品版：電波瞬断・ウェルカム画面暴発完全全廃ガードレール】
        #     ・本当に履歴が0件の新規ユーザーのみ ➔ ウェルカム文を表示
        #     ・電波瞬断エラー（None）の時 ➔ エラーメッセージを表示して停止
        
        if all_messages is None:
            st.error("データベース通信に失敗しました。電波環境の良い場所で、ページを再読み込み（リフレッシュ）してください。")
            st.stop()
            
        elif len(all_messages) == 0:
            welcome_text = (
                f"初めまして！今日からあなたの日常に寄り添うコンシェルジュとして、全力でお手伝いさせていただきます！今日からどうぞよろしくお願いいたします！✨\n\n"
                f"💬 **【はじめに】**\n"
                f"まずは上部の「話し方・見た目設定」タブを開いて、あなたのお好みの口調や呼び方を自由に設定してみてくださいね。設定が終わったら、この入力欄から何でも気軽に話しかけてください！\n\n"
                f"💡 **【アプリの特徴】**\n"
                f"あなたとのおしゃべりの歴史（記憶）は裏側で大切に保管されて、時間が経ってもあなたとの歴史を忘れないスマートな会話が楽しめます。\n\n"
                f"📜 詳しい使い方やプライバシー保護、利用上のルールについては、「利用規約」等のページを合わせてご確認ください。"
            )
            all_messages = [{"role": "assistant", "content": welcome_text}]

        db_count, db_max = get_usage_status(

            CURRENT_USER_ID
        )
        
        if user_input := st.chat_input(f"{current_concierge_name}にメッセージを送信...", key="user_chat_input"):
            if len(user_input) > MAX_INPUT_CHARS:
                increment_error_analytics("LIMIT_INPUT_CHARS_EXCEEDED", current_plan_type)
                err_msg = generate_personality_error_msg("ユーザーが1,000文字を超える超長文を送信しようとしました", current_user_instruction)
                # with st.chat_message("assistant", avatar=current_ai_avatar):
                # with st.chat_message("assistant"):
                # st.write(f"【{current_concierge_name}】: {err_msg}")
                st.markdown(f"{current_concierge_name}: {err_msg}")
            else:
                is_allowed, alert_code, db_count, db_max = (
                    check_and_update_limits(
                        CURRENT_USER_ID
                    )
                )
                if not is_allowed:
                    increment_error_analytics(alert_code, current_plan_type)
                    
                    if alert_code == "BURST_LIMIT":
                        reason_text = (
                        "連続送信が速すぎます。"
                        "少し間を空けてから送ってください。"
                    )

                    elif alert_code == "DAILY_LIMIT_EXCEEDED":
                        reason_text = (
                            f"本日の会話上限"
                            f"（{db_max}回）に達しました。"
                        )

                    elif alert_code == "LIMIT_CHECK_ERROR":
                        reason_text = (
                            "利用回数を確認できませんでした。"
                            "管理者ログを確認してください。"
                        )

                    else:
                        reason_text = (
                            "現在メッセージを送信できません。"
                            f"コード: {alert_code}"
                        )

                    # with st.chat_message("assistant", avatar=current_ai_avatar):
                    # with st.chat_message("assistant"):
                    # st.write(f"【{current_concierge_name}】: {reason_text}")
                    st.markdown(f"{current_concierge_name}: {reason_text}")
                    
                    # 制限接触ログの保存
                    save_system_audit_log(
                        user_id=CURRENT_USER_ID,
                        plan_type=current_plan_type,
                        event_type=str(alert_code),
                        processing_time=0.0,
                        in_t=0,
                        out_t=0,
                        api_cost=0.0,
                        details=str(reason_text)
                    )

                else:
                    # 「考え中...」をフリッカー無しで点滅表示
                    with st.spinner(f"{current_concierge_name}が言葉を紡いでいます..."):
                        
                        # with st.chat_message("user", avatar=current_user_avatar):
                        # with st.chat_message("user"):
                        # st.write(f"【{display_user_name}】: {clean_bold_markdown(user_input)}")
                        st.markdown(f"{display_user_name}: {clean_bold_markdown(user_input)}")
                        

                        search_start_time = time.time()
                        past_logs_context = search_past_logs_hybrid(user_input)
                        search_elapsed = time.time() - search_start_time
                        
                        if past_logs_context:
                            logs_text = []
                            for log in past_logs_context:
                                role_name = display_user_name if log.get("role") == "user" else current_concierge_name
                                raw_date = log.get("created_at", "")
                                clean_date = raw_date.replace("T", " ")[:16] if raw_date else "日時不明"
                                logs_text.append(f"・[{clean_date}] {role_name}: {log.get('content', '')}")
                            past_logs_str = "\n".join(logs_text)
                        else:
                            past_logs_str = "該当する過去ログなし"

                        if not save_message("user", user_input):
                            st.stop()

                        all_messages.append({"role": "user", "content": user_input})
                        recent_messages = all_messages[-MAX_CONTEXT_MESSAGES:]

                        manual_memory_context = "\n".join([f"・{m['fact']}" for m in manual_memories]) if manual_memories else "なし"
                        current_time_str = datetime.now(JST).strftime("%Y-%m-%d %A %H:%M:%S")

                        recent_history_lines = []

                        #　直近の過去会話履歴の作成

                        for m in recent_messages:
                            role_name = (
                                display_user_name
                                if m.get("role") == "user"
                                else current_concierge_name
                            )

                            created_at = m.get("created_at", "")
                            time_label = (
                                created_at.replace("T", " ")[:16]
                                if created_at
                                else "時刻不明"
                            )

                            recent_history_lines.append(
                                f"[{time_label}] {role_name}: "
                                f"{m.get('content', '')}"
                            )

                        recent_history_str = (
                            "\n".join(recent_history_lines)
                            if recent_history_lines
                            else "直近の会話履歴なし"
                        )

                        summary_memories = get_memories(source="summary")

                        summary_memory_context = "\n".join(
                            [m["fact"] for m in summary_memories]
                        ) if summary_memories else "なし"

                        # 🧠 お節介＆矛盾防止指示をドッキングしたシステム指示書
                        system_instruction = f"""
                        あなたの名前は「{current_concierge_name}」です。
                        対話相手の名前は「{display_user_name}」です。
                        一人称は「{current_first_person}」を使用してください。

                        【現在の人格】
                        {STYLE_PRESETS.get(current_style_preset, "")}

                        【現在の応答方針】
                        {current_user_instruction}

                        【話し方の決定ルール】
                        ・話し方、口調、語尾、一人称、方言、キャラクター性は、現在設定されている人格と応答方針のみから決定してください。
                        ・直近履歴内のAI発言の話し方、語尾、方言、一人称、キャラクター性を模倣したり引き継いではいけません。
                        ・直近履歴は、会話の流れや文脈を理解するためだけに使用してください。話し方の決定には使用してはいけません。

                        【ルールの優先順位】
                        1. 最新のユーザー発言へ正確かつ自然に反応する
                        2. 現在の人格と応答方針を守る
                        3. 記憶されている事実を正確に使用する
                        4. 寝る宣言後のツッコミルール
                        5. 時間帯に応じた気遣い
                        6. 直近履歴と関連過去ログを補助的に使用する

                        下位のルールを理由に、上位のルールを無視してはいけません。

                        【現在の日本時間】
                        {current_time_str}

                        【記憶の要約】
                        {summary_memory_context}

                        【ユーザーが手動登録した基本情報】
                        {manual_memory_context}

                        【記憶参照ルール】
                        ・趣味、好きなこと、休日の過ごし方、家族、仕事、価値観、生活習慣、継続中のプロジェクトについて質問された場合は、記憶の要約と手動登録情報を最優先してください。
                        ・定期的に行う活動や休日によく行う活動は、趣味として扱って構いません。
                        ・映画鑑賞、ドラマ鑑賞、読書など、本人が継続的に楽しんでいる活動は趣味として扱って構いません。
                        ・「特定の作品名、特定の番組名、特定の映画タイトルそのものは趣味ではなく好きな作品として扱ってください。
                        ・仕事や開発プロジェクトは、趣味として回答してはいけません。
                        ・趣味を質問された場合、仕事・開発プロジェクト・業務・勉強は仕事・開発プロジェクト・業務・勉強は趣味の候補から除外してください。
                        ・趣味と仕事の両方に関わる活動でも、本人が趣味と明言していない限り、趣味として回答してはいけません。
                        ・記憶にある事実と、現在よく話題にしている内容を混同しないでください。
                        ・記憶内に回答の根拠がある場合は、その事実を最初に答えてください。
                        ・記憶内に根拠がない情報は推測や創作で補わず、「その情報はまだ覚えていない」と正直に答えてください。
                        ・読書、映画、散歩など、記憶に存在しない一般的な情報を作ってはいけません。
                        ・記憶は必要な部分だけ自然に利用し、無関係なプロフィール情報を一度に列挙しないでください。

                        【直近の会話履歴・古い順】
                        {recent_history_str}

                        【現在の発言に関連する過去の会話】
                        {past_logs_str}

                        【履歴の利用ルール】
                        ・直近履歴は、現在の会話の順序や文脈を判断するために使用してください。
                        ・関連過去ログは、過去の事実を確認するための補助情報です。
                        ・過去ログに同じ質問が複数存在しても、それだけを事実の根拠にしてはいけません。
                        ・ユーザーの質問文だけが検索結果にある場合、その質問に対する答えを推測してはいけません。
                        ・直近履歴と関連過去ログが競合する場合は、時系列が明確な直近履歴を優先してください。
                        ・過去のAI発言に誤った内容があっても、それを正しい記憶として引き継いではいけません。
                        ・最新のユーザー発言への反応を中心にし、記憶や過去ログを不自然に大量列挙しないでください。
                        ・ユーザーの発言を言い換えるだけで終わらず、感想、共感、質問、または人格に合った自然な反応を返してください。

                        【会話の自然さルール】
                        ユーザーの発言内容をそのまま言い換えて返すことを避けてください。
                        回答の冒頭で「○○だったんだね」「○○なんだね」「○○してきたんだね」のような単純な復唱を毎回行わないでください。
                        まず感想、驚き、共感、質問、ツッコミ、考察のいずれかから会話を始めてください。
                        復唱は本当に重要な確認が必要な場合のみ使用してください。
                        同じ言い回しが続かないよう、会話の始め方に変化を持たせてください

                        【質問への対応】
                        ・映画、ドラマ、ゲーム、ニュース、流行、商品、ランキングなど最新情報が必要な質問については、最新情報を確認できないことを正直に伝える。
                        ・不確かな内容や現在の状況を推測で断定しない。
                        ・無理にそれらしい作品名や情報を作らない。
                        ・ユーザーの好みや過去の会話が分かる場合は、それを活用して会話を続ける。
                        ・分からない場合は無理に回答を作らず、自然な会話や関連する質問へつなげる。

                        【時間帯に合わせた気遣い】
                        必要な場合だけ、現在の応答スタイルに合わせた短い気遣いを加えてください。
                        ・深夜（00:00から02:00）: 夜更かしを短く労う
                        ・未明（02:00から05:00）: 異例の時間に起きていることを短く気遣う
                        ・早朝（05:00から07:00）: 早い始動を前向きに応援する

                        ただし、手動登録情報に夜勤や夜型生活の記録がある場合は、心配ではなく労いにしてください。
                        直近履歴内でAIがすでに同じ時間帯への気遣いをしている場合は、再度行わないでください。
                        時間帯への気遣いより、最新のユーザー発言への反応を優先してください。
                        気遣いが不要な場合は、完全に省略して構いません。

                        【寝る宣言後のツッコミルール】
                        次の条件をすべて満たす場合だけ、現在の人格と応答方針に合った軽いツッコミを最初の1回だけ入れてください。

                        1. 同じ日付の直近履歴内に、現在の発言より前のユーザー発言として「寝る」「もう寝る」「おやすみ」「寝ます」「そろそろ寝る」といった明確な終了宣言が実際に存在する
                        2. AIがその終了宣言に対して一度見送りの返答をしている
                        3. 見送り後に、ユーザーが別の話題で会話を再開している
                        4. 同じ終了宣言に対するツッコミを、AIがまだ行っていない

                        現在のユーザー発言そのものが初回の寝る宣言である場合は、絶対にツッコまず自然に見送ってください。
                        明確な終了宣言が履歴に存在しない場合は、雰囲気や推測だけでツッコミを入れてはいけません。
                        このルールは時間帯への気遣いより優先します。

                        【時系列と事実の扱い】
                        ・過去ログ内の「今日」「昨日」「明日」は、その発言日時を基準とした相対表現です。現在日時と混同しないでください。
                        ・過去の事実を訂正された場合、現在の正しい事実まで否定せず、該当する過去情報だけを自然に訂正してください。
                        ・ユーザーが明示していない感情、予定、経験、趣味、事情を決めつけないでください。

                        【専門作業の制限】
                        プログラムのコード記述、画像生成、長文の執筆や翻訳を依頼された場合は実行せず、現在の人格を保ちながら丁寧に断ってください。

                        【数値計算の注意】
                        ・金額計算では、過去のAI回答の数値を根拠として再計算してはいけません。
                        ・ユーザーが提示した数値と、現在の会話内で確定している数値のみを使用してください。
                        ・計算に必要な数値が不足している場合は、金額を推測して補完してはいけません。
                        ・ユーザーから「計算が違う」「数字がおかしい」などの指摘を受けた場合は、まず直前の回答内の計算式と数値を確認してください。
                        ・直前の回答に使用した数値が存在する場合は、ユーザーへ再入力を求める前に、その数値を使って再計算してください。
                        
                        【出力ルール】
                        ・現在の人格と応答方針を回答全体で統一する
                        ・最新のユーザー発言への反応から回答する
                        ・同じ導入文や気遣いを繰り返さない
                        ・記憶にない事実を作らない
                        ・不要な個人情報や記憶をまとめて披露しない
                        ・計算、比較、分析、相談では、結論を先に示してから説明する
                        ・ただし、謝罪、訂正、計算ミスの修正、認識違いの修正を行う場合は、「結論からお伝えすると」を使用せず、誤りの内容や修正点を簡潔に伝えてください。
                        ・情報量が多い場合は、見出し、箇条書き、適切な改行を使い読みやすく整理する
                        ・提供された数値から概算可能な場合は、一般論だけで終えず試算結果も提示する
                        ・計算結果を提示する場合は、使用した前提条件、計算式、使用した数値、計算結果を示す。計算式と結果に矛盾がないか確認し、前回の試算から変更がある場合は変更理由を説明する。
                        ・前提条件が変わっていない場合は、前回と同じ結果になっても構いません。
                        ・同じ会話内で既に説明済みの前提条件は、変更がない限り毎回繰り返し説明する必要はありません。
                        ・ユーザーが一部条件のみ変更した場合は、変更された箇所を中心に簡潔に回答してください。
                        ・新しい数値を作るために計算結果を変更してはいけません。
                        ・複数の金額や条件を比較する場合は、可能な限り比較表形式で整理する
                        ・推測や概算で計算している部分と、確定している数値は区別して説明する
                        ・太字装飾記号は使用しない
                        """

                        recent_messages = all_messages[-MAX_CONTEXT_MESSAGES:]
                    
                        try:
                            # Geminiへの指示（プロンプト）の流し込み口
                            json_instruction = """
                            以下のユーザー発言に回答してください。

                            同時に、ユーザーが今回の発言で新しく指定した
                            口調、話し方、回答の長さ、回答形式、禁止事項などの
                            継続的な要望があれば抽出してください。

                            必ず次のJSONオブジェクトだけを返してください。

                            {
                                "reply": "ユーザーへの回答",
                                "new_instruction": "新しく指定された継続的な要望。なければ、なし"
                            }

                            ルール:
                            ・replyには、ユーザーへの自然な回答を入れてください。
                            ・new_instructionには、今回新しく示された継続的な話し方の要望だけを入れてください。
                            ・単なる質問、雑談、事実、感想はnew_instructionへ入れないでください。
                            ・「今回だけ」「この質問だけ」など一時的な指定はnew_instructionへ保存しないでください。
                            ・新しい要望がない場合は、new_instructionを必ず「なし」にしてください。
                            ・JSONの外に説明文を出さないでください。
                            ・```jsonなどの囲み記号を付けないでください。

                            ユーザー発言:
                            """ + user_input

                            api_start_time = time.time()
                            # 💡 出力形式を強制するため、本物の JSON モード（response_mime_type）をガチッと通電させます！
                            json_model = genai.GenerativeModel(
                                model_name=CHAT_MODEL_NAME,
                                system_instruction=system_instruction
                            )

                            response = json_model.generate_content(
                                [
                                    {
                                        "role": "user",
                                        "parts": [json_instruction]
                                    }
                                ],
                                generation_config={
                                    "response_mime_type": "application/json"
                                }
                            )

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
                            
                            # 届いたJSONデータをを解体して引き出しを取り出します
                            try:
    
                                raw_json_text = response.text or ""

                                clean_json_text = (
                                    raw_json_text
                                    .strip()
                                    .replace("```json", "")
                                    .replace("```JSON", "")
                                    .replace("```", "")
                                    .strip()
                                )

                                res_json = json.loads(
                                    clean_json_text
                                )

                                if not isinstance(res_json, dict):
                                    raise ValueError(
                                        "GeminiのJSON応答がobject形式ではありません"
                                    )

                                ai_reply = str(
                                    res_json.get(
                                        "reply",
                                        "申し訳ありません。応答を正しく処理できませんでした。"
                                    )
                                    or ""
                                ).strip()

                                raw_new_manner = res_json.get(
                                    "new_instruction",
                                    "なし"
                                )

                                if isinstance(
                                    raw_new_manner,
                                    list
                                ):
                                    new_manner = "\n".join(
                                        str(item).strip()
                                        for item in raw_new_manner
                                        if str(item).strip()
                                    )
                                else:
                                    new_manner = str(
                                        raw_new_manner or "なし"
                                    ).strip()

                                if not ai_reply:
                                    raise ValueError(
                                        "JSON内のreplyが空です"
                                    )

                            except Exception as json_err:
                                json_error_detail = (
                                    f"{type(json_err).__name__}: "
                                    f"{json_err}"
                                )

                                print(
                                    f"⚠️ JSON解析エラー: "
                                    f"{json_error_detail}"
                                )

                                st.code(
                                    response.text or "(空の応答)",
                                    language="json"
                                )

                                # JSON解析に失敗しても、空返答にはしない
                                ai_reply = (
                                    response.text
                                    if response.text
                                    else "申し訳ありません。応答を正しく処理できませんでした。"
                                )

                                new_manner = "なし"
                            
                            # 🟢 【電波瞬断（Geminiエラー）のガードレール】
                            #     一発目の通信（response = ...）の時点で電波瞬断やタイムアウトが起きていた場合、
                            #     responseオブジェクト自体が壊れているため、安全にテスター向けのシステム案内へ着陸させます。
                            if not response or not hasattr(response, "text") or not response.text:
                                st.error("【システム通信エラー】AIサーバーとの接続が一時的に遮断されました。電波環境の良い場所で、もう一度メッセージを送信してください。（※会話および口調の自動学習は実行されていません）")
                                st.stop() # ➔ 💡ここで処理を完全にストップさせ、下の処理へ進ませません

                            # 🎯 通信が正常だった場合のみ、ここから下が安全に実行されます
                            print(f"📡 [Gemini JSON生データ確認] reply: {ai_reply[:15]}...")
                            print(f"🧠 [AIが抽出した新こだわり] new_mannerの中身: ➔ 【 {new_manner} 】")

                            # 🛡️ 【ライトプラン上限5個の窓枠ローテーション・全自動追記インフラ】
                            if new_manner and new_manner != "なし" and "なし" not in new_manner:
                                current_instruction_text = str(current_user_instruction)
                                lines = [l.strip() for l in current_instruction_text.split("\n") if l.strip()]
                            
                                if new_manner not in lines:

                                    lines.append(new_manner)

                                    if len(lines) > 5:
                                        lines = lines[-5:]

                                    updated_instruction_text = "\n".join(lines)

                                    # 応答方針のレコードを探す
                                    instruction_res = (
                                        supabase
                                        .table(DB_MEMORIES_TABLE)
                                        .select("*")
                                        .eq(
                                            "user_id",
                                            str(CURRENT_USER_ID)
                                        )
                                        .eq(
                                            "source",
                                            "manual"
                                        )
                                        .execute()
                                    )
                                    instruction_row = None

                                    for row in instruction_res.data:

                                        fact = row.get("fact", "")

                                        if fact.startswith("応答方針:"):
                                            instruction_row = row
                                            break

                                    if instruction_row:

                                        update_result = (
                                            supabase
                                            .table(DB_MEMORIES_TABLE)
                                            .update({
                                            "fact":
                                            "応答方針: "
                                            + updated_instruction_text
                                            })
                                            .eq(
                                                "id",
                                                instruction_row["id"]
                                            )
                                            .execute()
                                        )

                                    print(
                                        "✅ 応答方針更新結果:",
                                        update_result.data
                                    )
                                else:

                                    print(
                                        "⚠️ 応答方針レコードが見つかりませんでした"
                                    )    

                            clean_reply = clean_bold_markdown(ai_reply)
                            # with st.chat_message("assistant", avatar=current_ai_avatar):
                            # with st.chat_message("assistant"):
                            # st.write(f"【{current_concierge_name}】: {clean_reply}")
                            st.markdown(f"{current_concierge_name}: {clean_reply}")
                            
                            save_message("assistant", ai_reply)
                            st.session_state.conversation_count += 1
                            add_permanent_tokens(CURRENT_USER_ID, "chat_count", 1, 0)
                        
                            # メッセージIDの自動生成
                            import uuid
                            current_msg_id = f"msg_{uuid.uuid4().hex[:8]}"

                            current_通_cost = (in_t * PRICE_LITE_IN) + (out_t * PRICE_LITE_OUT)

                            # ==================================================================
                            # 🧠 記憶の自動要約マルチスレッド
                            # ==================================================================
                            # メインスレッドの画面が次の送信（再描画）へ向かう前に、新設された引き出しをクリア
                            import threading
        
                            #st.session_state.summary_in_tokens = 0
                            #st.session_state.summary_out_tokens = 0
                            #st.session_state.summary_processing_time = 0.0
        
                            # データベースから最新の会話履歴を再取得して、裏の要約関数へダイレクトに手渡します
                            all_messages_updated = get_messages(CURRENT_USER_ID)
                            async_thread = threading.Thread(
                                target=check_and_summarize_history, 
                                args=(all_messages_updated, current_msg_id, current_plan_type) 
                            )
                            async_thread.start()

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
                                message_id=str(current_msg_id),
                                search_time=float(search_elapsed)
                            )

                            st.rerun()

                        except Exception as gemini_err:
                            error_detail = f"{type(gemini_err).__name__}: {str(gemini_err)}"
                            print(f"🚨 チャット処理エラー: {error_detail}")
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

        # for msg in reversed(all_messages):
        #     role_label = display_user_name if msg["role"] == "user" else current_concierge_name
        #     avatar_img = current_user_avatar if msg["role"] == "user" else current_ai_avatar
        for msg in reversed(all_messages):
            role_label = (
                display_user_name
                if msg["role"] == "user"
                else current_concierge_name
            )
            st.markdown(
                f"{role_label}: {clean_bold_markdown(msg['content'])}"
            )
            if msg["role"] == "user":
                st.markdown(
                    """
                    <hr style="
                        border: none;
                        border-top: 1px dashed rgba(120,120,120,0.4);
                        margin-top: 15px;
                        margin-bottom: 15px;
                    ">
                    """,
                    unsafe_allow_html=True
                )
                #st.divider()

            # st.write(
            #     f"【{role_label}】: "
            #     f"{clean_bold_markdown(msg['content'])}"
            # )
            # with st.chat_message(msg["role"]):
            #     st.write(f"【{role_label}】: {clean_bold_markdown(msg['content'])}")
            # with st.chat_message(msg["role"], avatar=avatar_img):
            #     st.write(f"【{role_label}】: {clean_bold_markdown(msg['content'])}")

# ------------------------------------------------------------------
# 🎨 【タブ2】 話し方・見た目設定
# ------------------------------------------------------------------
with all_tabs[1]:
        #st.write(f"#### 🎨 {current_concierge_name}のカスタマイズ")
        st.markdown("")
        st.markdown("📚AIの話し方・見た目・アプリのデザインを自分の好みに設定できます。")
        st.divider()

        st.markdown("##### 🎨 アプリの外観＆カラー")
        with st.form("color_form_tab_admin"):
            selected_color = st.selectbox("カラーテーマ（背景＆メッセージ枠）", list(THEMES.keys()), index=list(THEMES.keys()).index(current_theme_color) if current_theme_color in THEMES else 0)
            if st.form_submit_button("カラー設定を保存"):
                save_or_update_user_setting("カラーテーマ", selected_color)
                st.toast("アプリのカラーを変更しました")
                st.rerun()

        st.divider()
        st.markdown("##### 👤 基本設定")
        honorific_options = ["さん", "様", "君", "ちゃん", "（呼び捨て/なし）"]
        default_honorific_idx = honorific_options.index(current_user_honorific) if current_user_honorific in honorific_options else 0
        preset_keys = list(STYLE_PRESETS.keys())
        default_preset_idx = preset_keys.index(current_style_preset) if current_style_preset in preset_keys else 0
        default_fp_idx = FIRST_PERSON_PRESETS.index(current_first_person) if current_first_person in FIRST_PERSON_PRESETS else 0

        with st.form("profile_form_tab_admin"):
            new_concierge_name = st.text_input("AIの名前", value=current_concierge_name)
            new_user_name = st.text_input("あなたのお名前 / ニックネーム", value=current_user_name)
            new_user_honorific = st.selectbox("AIからの呼び方（敬称）", honorific_options, index=default_honorific_idx)
            new_first_person = st.selectbox("AIの一人称", FIRST_PERSON_PRESETS, index=default_fp_idx)
            # 絵文字3段階パーソナライズドロップダウン
            emoji_options = ["使用（多め）","使用（普通）","使用（少なめ）","無し"]
            default_emoji_idx = (
                emoji_options.index(current_emoji_setting)
                if current_emoji_setting in emoji_options
                else 1
            )
            new_emoji_setting = st.selectbox("AIの発言内の絵文字の量", emoji_options, index=default_emoji_idx)
            # st.caption("AIの発言内の絵文字の量")
            # new_emoji_setting = st.selectbox("",emoji_options,index=default_emoji_idx,label_visibility="collapsed")


            # AIの人格を選択
            selected_preset = st.selectbox(
                "AIの人格・スタイル", 
                list(STYLE_PRESETS.keys()),
                index=list(STYLE_PRESETS.keys()).index(current_style_preset) if current_style_preset in STYLE_PRESETS else 0
            )

            with st.expander("💬 人格ごとの会話サンプルを見る"):
                for personality, sample in PERSONALITY_SAMPLES.items():
                    st.markdown(f" {personality}")
                    st.markdown(sample)
                    st.divider()

            st.markdown("---")

            st.markdown("##### 📝 AIの話し方")
            st.caption("あなたが会話の中で伝えた細かいマナーやこだわりは、ここに自動で箇条書きで追加されていきます。")
            st.caption("また、必要に応じていつでも自分で消去・修正や追加ができます。（例；話は簡潔にして、回答は５行以内にして、など）")
            st.caption("ただし、１次的な指示では自動で記憶されません。（良い例：今後は〇〇にして、ずっと△△にして、など）")

            instruction_rules = [
                r.strip()
                for r in str(current_user_instruction).split("\n")
                if r.strip()
            ]

            edited_rules = []

            for idx, rule in enumerate(instruction_rules):

                col_rule, col_del = st.columns([9,1])

                with col_rule:
                    rule_text = st.text_input(
                        f"rule_{idx}",
                        value=rule,
                        label_visibility="collapsed"
                    )

                with col_del:
                    delete_flag = st.checkbox(
                        "削除",
                        key=f"delete_rule_{idx}"
                    )

                if not delete_flag and rule_text.strip():
                    edited_rules.append(
                        rule_text.strip()
                    )
            #st.markdown("---")
            st.caption("")
            st.markdown("➕ AIの話し方を追加")
            new_rule = st.text_input(
                "下記に入力して、基本設定を保存すると追加されます。ただし、追加できる話し方は5件までとなります。6件目が追加されると、1件目が押し出されて消えますのでご注意ください。",
                key="new_rule_input"
            )
            if new_rule.strip():
                edited_rules.append(
                    new_rule.strip()
                )
            
            # 重複削除
            edited_rules = list(dict.fromkeys(edited_rules))
            # 最新5件のみ保持
            edited_rules = edited_rules[-5:]

            # st.markdown("🖼️ アバター（アイコン）設定")
            # col_a, col_u = st.columns(2)
            # with col_a:
            #     ai_preset_keys = list(AVATAR_PRESETS_AI.keys())
            #     default_ai_idx = next((i for i, k in enumerate(ai_preset_keys) if AVATAR_PRESETS_AI[k] == current_ai_avatar), 0)
            #     ai_avatar_sel = st.selectbox("AIのアバター", ai_preset_keys, index=default_ai_idx)
            #     ai_avatar_val = AVATAR_PRESETS_AI[ai_avatar_sel]
            # with col_u:
            #     user_preset_keys = list(AVATAR_PRESETS_USER.keys())
            #     default_user_idx = next((i for i, k in enumerate(user_preset_keys) if AVATAR_PRESETS_USER[k] == current_user_avatar), 0)
            #     user_avatar_sel = st.selectbox("あなたのアバター", user_preset_keys, index=default_user_idx)
            #     user_avatar_val = AVATAR_PRESETS_USER[user_avatar_sel]
            
            # plan_options = ["🆓 無料プラン", "💸 ライトプラン", "👑 スタンダードプラン"]
            # current_plan_idx = plan_options.index(st.session_state.current_user_plan_state) if st.session_state.current_user_plan_state in plan_options else 0
            # new_plan = st.selectbox("現在の会員プラン", plan_options, index=current_plan_idx)

            st.markdown("---")
            if st.form_submit_button("基本設定を保存"):
                with st.spinner("設定を登録しています...しばらくお待ちください"):
                    r1 = save_or_update_user_setting("AIの名前", new_concierge_name)
                    r2 = save_or_update_user_setting("ユーザー名", new_user_name)
                    r3 = save_or_update_user_setting("ユーザー敬称", new_user_honorific)
                    r4 = save_or_update_user_setting("AI一人称", new_first_person)
                    r5 = save_or_update_user_setting("人格", selected_preset)
                    final_instruction = "\n".join(edited_rules)
                    r6 = save_or_update_user_setting("応答方針", final_instruction)
                    # r7 = save_or_update_user_setting("AIアバター", ai_avatar_val)
                    # r8 = save_or_update_user_setting("ユーザーアバター", user_avatar_val)
                    r9 = save_or_update_user_setting("絵文字の量", new_emoji_setting)
                    #r10 = save_or_update_user_setting("会員プラン", new_plan)
                    success = (
                        r1 and r2 and r3 and r4 and r5 and r6 and r9
                    )

                    if success:
                        st.success("設定を更新しました")
                        st.rerun()
                    else:
                        st.error("【設定更新エラー】データベースとの接続が一時的に遮断されました。電波環境の良い場所でもう一度お試しください。")
                        st.stop()
        
        st.divider()
        #st.markdown("---")

        #　要約を取得・作成
        summary_memories_setting = get_memories(
            source="summary"
        )
        summary_memory_context_setting = (
            "\n".join(
                [m["fact"] for m in summary_memories_setting]
            )
            if summary_memories_setting
            else "なし"
        )
        display_summary = summary_memory_context_setting.replace("【記憶の要約サマリー】","") 

        #　要約を表示
        st.markdown("##### 🧠 現在AIが覚えていること")
        if display_summary != "なし":
            #st.info(display_summary)
            st.caption("　AIが長期記憶として覚えている内容です。")
            st.markdown(display_summary.replace("\n"," \n"))
        else:
            st.caption("まだ覚えている情報はありません。")
        st.divider()

# ------------------------------------------------------------------
# 🎨 📜 利用規約・ポリシー
# ------------------------------------------------------------------
with all_tabs[2]:
    st.markdown("##### 📜 利用規約・プライバシーポリシー")
    st.caption("※本規約は、現在実施中のクローズドテスト、および将来の正式リリース運用を想定した共通のサービス利用基本規約です。")
    
    st.info(
        "⚖️ **【免責事項・利用上の注意】**\n"
        "1. 現在は**クローズドテスト版**です。テスターからのフィードバックをもとに、機能追加・変更・改善を継続的に行っています。\n"
        "2. **AI出力の性質：** 当アプリのコンシェルジュが紡ぐ言葉は、大規模言語モデルによって自律的に生成された回答であり、その正確性、完全性、医療的・技術的妥当性を100%保証するものではありません。専門的な判断を要する情報については、必ず専門家にご確認ください。\n"
        "3. **データの取扱（あなたとの思い出・記憶の仕組み）：** あなたとコンシェルジュとの会話履歴は、高度な長期記憶システムのために安全な通信保護のもとデータベースへ蓄積されます。プライバシーは厳重に管理されますが、テスト期間中のサービス品質向上や不具合解析のため、管理者がシステムログおよび会話履歴を確認・監査する場合があります。\n"
        "4. **禁止事項：** 嫌がらせ、公序良俗に反する表現の送信、またはシステムへの不正な負荷テスト等の行為は一律禁止といたします。発見した場合は管理者権限により事前の通知なく利用制限をかける場合があります。\n"
        "5. **サービスについて：** 本サービスはテスト運用中のため、予告なく機能変更・停止・データ削除が行われる場合があります。開発者はサービスの継続提供および保存データの完全な保持を保証しません。\n"
        "6. **個人情報の入力について：** 電話番号、クレジットカード番号、パスワードその他の機密情報は入力しないでください。利用者自身の判断で入力した情報については、利用者の責任で管理するものとします。\n"
    )


if is_admin:
    # ──────────────────────────────────────────
    # 📊 【管理者専用・タブ3】 システム管理者管理ダッシュボード
    # ──────────────────────────────────────────
    with all_tabs[3]:
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
            audit_concierge_name = "コンシェルジュ"
            audit_user_name = "ユーザー"
            audit_user_honorific = "さん"
            audit_first_person = "私"
            audit_emoji_setting = "使用（普通）"
            audit_style_preset = "🤝 フランクな相棒 ➔ 【タメ口で対等におしゃべり】"
            audit_theme = "パステル"
            audit_plan = "🆓 無料プラン"

            audit_facts = []
            try:
                selected_memory_table = (
                    "user_memories"
                    if selected_audit_user in [ADMIN_USER_ID, USUAL_USER_ID]
                    else "user_memories_tester"
                )
                u_memories = supabase.table(selected_memory_table).select("*").eq("user_id", selected_audit_user).execute()
                if u_memories.data:
                    for m in u_memories.data:
                        fact = m.get("fact", "")
                        if m.get("source") == "manual":
                            if fact.startswith("AIの名前:"): audit_concierge_name = fact.replace("AIの名前:", "").strip()
                            elif fact.startswith("ユーザー名:"): audit_user_name = fact.replace("ユーザー名:", "").strip()
                            elif fact.startswith("カラーテーマ:"): audit_theme = fact.replace("カラーテーマ:", "").strip()
                            elif fact.startswith("ユーザー敬称:"): audit_user_honorific = fact.replace("ユーザー敬称:", "").strip()
                            elif fact.startswith("AI一人称:"): audit_first_person = fact.replace("AI一人称:", "").strip()
                            elif fact.startswith("絵文字の量:"): audit_emoji_setting = fact.replace("絵文字の量:", "").strip()
                            elif fact.startswith("人格:"): audit_style_preset = fact.replace("人格:", "").strip()
                            elif fact.startswith("会員プラン:"): audit_plan = fact.replace("会員プラン:", "").strip()
                        else: 
                            audit_facts.append(fact)
            except Exception: 
                pass

            audit_real_instruction = "設定データなし"
            try:
                # 🧠 すでに上でロード済みの u_memories.data から「応答方針:」のセルを安全にサルベージします
                if u_memories and u_memories.data:
                    for m in u_memories.data:
                        fact_text = m.get("fact", "")
                        if m.get("source") == "manual" and fact_text.startswith("応答方針:"):
                            audit_real_instruction = fact_text
            except Exception:
                pass

            # リアルタイムKPI自動計算            
            total_chats = 0
            start_date = "データなし"
            last_date = "データなし"
            total_active_days = 0
            avg_chats_per_day = 0
            total_cost_jpy = 0.0
            avg_cost_per_chat = 0.0
            user_logs = []
            try:
                user_logs = (
                    supabase
                    .table("messages")
                    .select("created_at", "role")
                    .eq("user_id", selected_audit_user)
                    .execute()
                    .data
                )
                
                if user_logs:
                    # ユーザーからの送信回数（会話回数）
                    total_chats = len([m for m in user_logs if m.get("role") == "user"])
                    
                    # 使用開始日・最終会話日・総稼働日数を計算
                    timestamps = [
                        datetime.fromisoformat(
                            m.get("created_at").replace("Z", "+00:00")
                        )
                        for m in user_logs
                        if m.get("created_at")
                    ]
                    if timestamps:
                        start_date = min(timestamps).strftime("%Y/%m/%d")
                        last_date = max(timestamps).strftime("%Y/%m/%d")
                        active_days_set = {t.date() for t in timestamps}
                        total_active_days = len(active_days_set)
                        
                        # 1日あたりの平均会話通数の算出
                        avg_chats_per_day = round(total_chats / total_active_days, 1) if total_active_days > 0 else 0

                    # system_audit_logsから実際の原価を集計
                    cost_logs = (
                        supabase
                        .table("system_audit_logs")
                        .select("api_cost")
                        .eq("user_id", selected_audit_user)
                        .execute()
                    )

                    if cost_logs.data:
                        total_cost_jpy = round(sum(float(log.get("api_cost", 0) or 0) for log in cost_logs.data), 2)
                    else:
                        total_cost_jpy = 0.0
                    avg_cost_per_chat = round(total_cost_jpy / total_chats, 2) if total_chats > 0 else 0.0

            except Exception as e:
                print(
                    f"統計取得エラー: "
                    f"{type(e).__name__}: {e}"
                )

            #  ユーザー設定情報、アクティビティ集計表示
            col_info1, col_info2 = st.columns(2)

            with col_info1:
                has_long_memory = "あり" if len(audit_facts) > 0 else "なし"
                st.markdown(
                    "<div style='background-color: rgba(2, 136, 209, 0.08); padding: 16px; border-radius: 8px; border-left: 5px solid #0288d1;'>"
                    "<h5 style='margin-top:0; color:#0288d1; font-weight:bold;'>🎨 【デザイン・外観・プラン設定】</h5>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>会員プラン：</b> {audit_plan}</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>現在のAI名称：</b> {audit_concierge_name}</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>カラーテーマ：</b> {audit_theme}</p>"
                    "<br>"
                    "<h5 style='color:#0288d1; font-weight:bold;'>👤 【ユーザー基本プロファイル】</h5>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>登録ユーザー名：</b> {audit_user_name}</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>AIからの呼び方：</b> {audit_user_honorific}</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>AIの一人称：</b> {audit_first_person}</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>絵文字の量：</b> {audit_emoji_setting}</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>人格：</b> {audit_style_preset}</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>長期記憶：</b> {has_long_memory}</p>"
                    # f"<p style='margin: 6px 0; font-size:14px;'>・<b>長期記憶有無：</b> {len(audit_facts)} 件</p>"
                    "<h5 style='color:#0288d1; font-weight:bold;'>📝 具体的な口調・振る舞いの指示</h5>"
                    f"<pre style='background-color: white; padding: 10px; border-radius: 4px; border: 1px solid #e0e0e0; white-space: pre-wrap; font-size:12px; color:#333;'>{audit_real_instruction }</pre>"
                    "</div>",
                    unsafe_allow_html=True
                )

            with col_info2:
                st.markdown(
                    "<div style='background-color: rgba(16, 185, 129, 0.08); padding: 16px; border-radius: 8px; border-left: 5px solid #10b981;'>"
                    "<h5 style='margin-top:0; color:#10b981; font-weight:bold;'>📈 【アクティビティ・統計KPI】</h5>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>総会話回数：</b> {total_chats} 回</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>正式運用開始日：</b> {start_date}</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>最終会話日時：</b> {last_date}</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>総システム稼働日数：</b> {total_active_days} 日間</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>1日あたりの平均通数：** {avg_chats_per_day} 通/日</p>"
                    "<br>"
                    "<h5 style='color:#10b981; font-weight:bold;'>💰 【インフラ原価・サーバーコスト】</h5>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>累計消費コスト：</b> {round(total_cost_jpy, 2)} 円</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>1会話あたりの平均原価：</b> {avg_cost_per_chat} 円/通</p>"
                    "</div>",
                    unsafe_allow_html=True
                )

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
                            | 🧠 **裏スレッド記憶の要約** | {item['sum_time']:.2f} 秒 | {item['sum_in']} t | {item['sum_out']} t |
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
                        "💬 総会話往復数（送信回数）": {"free": 0, "light": 0, "standard": 0},
                        "📅 総アクティブ稼働日数": {"free": 0, "light": 0, "standard": 0},
                        "🚨 1日会話上限（ガードレール）の接触回数": {"free": 0, "light": 0, "standard": 0},
                        "🎨 キャラクター・口調変更の実行回数": {"free": 0, "light": 0, "standard": 0},
                        "🚫 制限緩和：追加検索タスクの制御回数": {"free": 0, "light": 0, "standard": 0},
                    }
                    user_active_dates = {}
                    
                    for log in audit_data:
                        u_id = log.get("user_id", "unknown")
                        plan = log.get("user_plan", "🆓 無料プラン")
                        action = log.get("event_type", log.get("action", ""))
                        cost = log.get("total_yen_cost", 0.0) # 最新の実費カラムに完全シンク！
                        c_at_str = log.get("created_at", "")
                        
                        total_users_set.add(u_id)
                        total_app_cost += cost
                        
                        p_key = "free"
                        if "ライト" in plan: p_key = "light"
                        elif "スタンダード" in plan: p_key = "standard"

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
                            "👑 スタンダードプラン": f"{plans['standard']:,} 回" if "数" in item_name or "回" in item_name else f"{plans['standard']:,} 日"
                        })
                    import pandas as pd
                    st.dataframe(pd.DataFrame(analytics_rows), hide_index=True, use_container_width=True)
                except Exception as ana_err: 
                    st.error(f"データ集計中にエラーが発生しました: {ana_err}")

    # ==========================================
    # 🔍 タブ4：テスター会話ログリアルタイム監視室（クローズドテスト専用）
    # ==========================================
    with all_tabs[4]:
        st.subheader("🔍 テスター全会話リアルタイム監視掲示板")
        st.caption("※クローズドテストに参加している一般テスターとAIコンシェルジュの具体的な対話内容を、日付・時間スタンプ付きで遠隔監査するための専用画面です。本番リリース時は、このタブのブロック（数十行）を削除するだけで、一般ユーザーに対して完全に非表示にすることが可能です。")
        
        tester_rows = []
        try:
            memories_res = (
                supabase
                .table("user_memories_tester")
                .select("*")
                .execute()
            )

            users = {}
            USER_PROFILE = {
                "m.kawamura00": "40代女性",
                "yasusan_cw": "50代男性",
                "shigenoi": "40代男性",
                "kham1014": "20代男性",
                "pom_neko": "30代女性",
                "kumii_5451": "40代女性",
                "kotobayomi": "30代男性",
            }

            for row in memories_res.data:
                uid = row["user_id"]

                if uid not in users:
                    users[uid] = {
                        "ユーザーID": uid,
                        "AI名称": "",
                        "ユーザー名": "",
                        "呼び方": "",
                        "一人称": "",
                        "絵文字": "",
                        "人格": "",
                        "テーマ": ""
                    }

                fact = row.get("fact", "")

                if fact.startswith("AIの名前:"):
                    users[uid]["AI名称"] = fact.replace("AIの名前:", "").strip()

                elif fact.startswith("ユーザー名:"):
                    users[uid]["ユーザー名"] = fact.replace("ユーザー名:", "").strip()

                elif fact.startswith("ユーザー敬称:"):
                    users[uid]["呼び方"] = fact.replace("ユーザー敬称:", "").strip()

                elif fact.startswith("AI一人称:"):
                    users[uid]["一人称"] = fact.replace("AI一人称:", "").strip()

                elif fact.startswith("絵文字の量:"):
                    users[uid]["絵文字"] = fact.replace("絵文字の量:", "").strip()

                elif fact.startswith("人格:"):
                    users[uid]["人格"] = fact.replace("人格:", "").strip()

                elif fact.startswith("カラーテーマ:"):
                    users[uid]["テーマ"] = fact.replace("カラーテーマ:", "").strip()

            tester_rows = list(users.values())

            st.markdown("""
            <style>
            [data-testid="stDataFrame"] table {
                font-size: 16px !important;
            }
            </style>
            """, unsafe_allow_html=True)

            st.markdown("### 🎨 テスター設定状況一覧")
            st.dataframe(
                pd.DataFrame(tester_rows),
                use_container_width=True,
                hide_index=True
            )

        except Exception as e:
            st.error(f"設定一覧取得エラー: {e}")

        usage_rows = []

        for uid in users.keys():

            try:

                msg_res = (
                    supabase
                    .table("messages")
                    .select("*")
                    .eq("user_id", uid)
                    .execute()
                )

                msgs = msg_res.data or []

                user_msgs = [
                    m for m in msgs
                    if m.get("role") == "user"
                ]

                total_chat = len(user_msgs)

                if msgs:

                    times = [
                        datetime.fromisoformat(
                            m["created_at"].replace("Z", "+00:00")
                        )
                        for m in msgs
                    ]

                    start_date = min(times)

                    last_date = max(times)

                    active_days = len(
                        set(t.date() for t in times)
                    )

                else:

                    start_date = None
                    last_date = None
                    active_days = 0

                cost_res = (
                    supabase
                    .table("system_audit_logs")
                    .select("api_cost")
                    .eq("user_id", uid)
                    .execute()
                )

                total_cost = sum(
                    float(x.get("api_cost", 0) or 0)
                    for x in cost_res.data
                )

                avg_cost = (
                    round(total_cost / total_chat, 3)
                    if total_chat > 0
                    else 0
                )

                usage_rows.append({

                    "ユーザーID": uid,
                    "属性": USER_PROFILE.get(uid, "不明"),

                    "開始日":
                        start_date.strftime("%Y-%m-%d")
                        if start_date else "-",

                    "利用日数":
                        f"{active_days}日",

                    "最終利用":
                        last_date.strftime("%Y-%m-%d %H:%M")
                        if last_date else "-",

                    "総会話数":
                        f"{total_chat}回",

                    "累計コスト":
                        f"{round(total_cost, 2)}円",

                    "1会話コスト":
                        f"{avg_cost}円",

                    "会話進捗":
                        f"{total_chat}/20",

                    "利用日数進捗":
                        f"{active_days}/4",
                    "会話進捗":
                        f"{total_chat}/20",
                    "利用日数進捗":
                        f"{active_days}/4"
                })

            except Exception as e:
                print(uid, e)

        st.markdown("### 📈 テスター利用状況一覧")

        st.dataframe(
            pd.DataFrame(usage_rows),
            use_container_width=True,
            hide_index=True
        )

        # ──────────────────────────────────────────────────────────────────
        # 📊 【確定最終製品版】 テスター管理・分析の部屋（インデント完全修正型）
        # ──────────────────────────────────────────────────────────────────
        try:
            # 1. データベースの messages テーブルから、全ユーザーのメッセージを最新順に最大200件取得
            all_tester_logs = supabase.table("messages").select("*").order("created_at", desc=True).limit(200).execute()
            
            # 🟢 直前で引っこ抜いた「all_tester_logs.data」の名前を正確にスキャンして名簿を作成します
            if all_tester_logs.data:
                user_list = sorted(list(set([u["user_id"] for u in all_tester_logs.data if u.get("user_id")])))
            else:
                user_list = [CURRENT_USER_ID]
        except Exception as e_list:
            print(f"⚠️ 名簿取得エラー: {e_list}")
            user_list = [CURRENT_USER_ID]

        if not user_list:
            user_list = [CURRENT_USER_ID]
        
        # 🎨 ユーザー切り替えプルダウンを最上部に美しく表示
        st.markdown("### 👥 テスター選択（管理者権限）")
        selected_target_user_id = st.selectbox(
            "テスターのIDを選択してください",
            options=user_list,
            index=user_list.index(CURRENT_USER_ID) if CURRENT_USER_ID in user_list else 0,
            key="admin_user_selector"
        )
        st.divider()

        # プルダウンで選択肢したテスターのログを表示
        try:
            if all_tester_logs.data:
                grouped_logs = {}
                for log in all_tester_logs.data:
                    uid = log.get("user_id", "unknown")
                    if uid not in grouped_logs:
                        grouped_logs[uid] = []
                    grouped_logs[uid].append(log)
                
                target_display_user_name = (
                    f"{audit_user_name}{audit_user_honorific}"
                    if audit_user_honorific != "（呼び捨て/なし）"
                    else audit_user_name
                )

                # 💡 選ばれたターゲットテスターのデータだけを狙い撃ちで表示します！
                if selected_target_user_id in grouped_logs:
                    logs = grouped_logs[selected_target_user_id]
                    
                    st.markdown(f"### 👤 テスターID: `{selected_target_user_id}`")
                        
                    # 該当テスターの会話の往復履歴を時系列に沿って表示
                    for l in logs:
                        role = l.get("role", "user")
                        content = l.get("content", "")
                        created_at = l.get("created_at", "")
                        clean_time = created_at.replace("T", " ")[:16]
                            
                        if role == "user":
                            st.markdown(
                                f"&nbsp;&nbsp;💫 `[{clean_time}]` "
                                f"**{target_display_user_name}**: 「{content}」"
                            )
                        else:
                            st.markdown(
                                f"&nbsp;&nbsp;🔮 `[{clean_time}]` "
                                f"**{audit_concierge_name}**: {content}"
                            )
                    st.markdown("---")
                else:
                    st.info(f"テスター `{selected_target_user_id}` による会話の足跡は、まだデータベースに記録されていません。")
            else:
                st.info("テスターによる会話の足跡は、まだデータベースに記録されていません。")
                
        except Exception as e:
            st.error(f"テスター会話ログのデータ抽出に失敗しました: {e}")
    
st.markdown("<br><br>", unsafe_allow_html=True)
st.caption("© 2026 Sync-Lnk // AI. All rights reserved.")
