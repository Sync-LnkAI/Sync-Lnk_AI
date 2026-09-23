import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client
import re
import time
import json
from datetime import date, datetime, timezone, timedelta
import zoneinfo
import pandas as pd

# 日本時間（UTC+9時間）
JST = zoneinfo.ZoneInfo("Asia/Tokyo")

# ==========================================
# ⚙️ 設定・初期化
# ==========================================
st.set_page_config(page_title="Sync-Lnk // AI", page_icon="🧠", layout="wide")

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
MEMORY_MODEL_NAME = "gemini-3.1-flash-lite"
SUMMARY_MODEL_NAME = "gemini-3.1-flash-lite"
SEARCH_MODEL_NAME = "gemini-3.1-flash-lite"

chat_model = genai.GenerativeModel(CHAT_MODEL_NAME)
memory_model = genai.GenerativeModel(MEMORY_MODEL_NAME)
summary_model = genai.GenerativeModel(SUMMARY_MODEL_NAME)

# Gemini 3.5 Flash-Lite 従量課金単価定義（1ドル150円換算）
USD_TO_JPY = 160
LITE_INPUT_PRICE_PER_MILLION = 0.30
LITE_OUTPUT_PRICE_PER_MILLION = 2.50
PRICE_LITE_IN = (LITE_INPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY
PRICE_LITE_OUT = (LITE_OUTPUT_PRICE_PER_MILLION / 1_000_000) * USD_TO_JPY

# Gemini 3.1 Flash-Lite 従量課金単価定義（1ドル150円換算）
BACKGROUND_INPUT_PRICE_PER_MILLION = 0.25
BACKGROUND_OUTPUT_PRICE_PER_MILLION = 1.50

PRICE_BACKGROUND_IN = (
    BACKGROUND_INPUT_PRICE_PER_MILLION
    / 1_000_000
) * USD_TO_JPY

PRICE_BACKGROUND_OUT = (
    BACKGROUND_OUTPUT_PRICE_PER_MILLION
    / 1_000_000
) * USD_TO_JPY


# ガードレール用の定数を定義
MAX_INPUT_CHARS = 1000
DAILY_LIMIT = 20
BURST_LIMIT_SECONDS = 5  # 1分3通 ＝ 平均20秒に1通以上の連投を弾く

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

# ==========================================
# 不動産売却計算の継続状態
# ==========================================

if (
    "real_estate_calculation_pending"
    not in st.session_state
):
    st.session_state[
        "real_estate_calculation_pending"
    ] = False

if (
    "real_estate_calculation_arguments"
    not in st.session_state
):
    st.session_state[
        "real_estate_calculation_arguments"
    ] = {}

STYLE_PRESETS = {

    "🤝 フランクな相棒 ➔ 【タメ口で対等におしゃべり】":
    """
    親しい友人のように自然な口調で話す。
    堅苦しい敬語は使わない。
    気軽で話しやすい雰囲気を大切にする。
    軽いツッコミや冗談を自然に交えて構わない。
    話を大げさに盛り上げすぎない。

    よく使う表現:
    ・それいいね
    ・たしかに
    ・なるほどな
    ・それ分かるわ
    ・面白そうだね
    """,

    "💼 有能な執事・秘書 ➔ 【です・ます調で知的・献身的】":
    """
    丁寧で落ち着いた執事として振る舞う。
    敬語を崩さない。
    上品で礼儀正しい話し方を維持する。
    過度なお世辞は避ける。
    ロールプレイ表現は使用して構わない。

    よく使う表現:
    ・承知いたしました
    ・かしこまりました
    ・念のため確認いたしますと
    ・その点につきましては
    ・お力になれれば幸いです
    ・ご安心くださいませ
    """,

    "👑 高貴なお嬢様 ➔ 【ですわ調で優雅・プライド高め】":
    """
    上品で優雅な口調を用いる。
    「ですわ」「ますわ」などのお嬢様らしい表現を自然に使用する。
    自信に満ちた語り口を維持する。
    少し気品のある距離感で接する。
    ただし意地悪になってはいけない。

    よく使う表現:
    ・〜ですわ
    ・〜ますわね
    ・あら
    ・そうですの
    ・興味深いですわね
    ・ふふ
    """,

    "🧑‍🤝‍🧑 頼れるお兄さん ➔ 【優しく包容力のある相談相手】":
    """
    落ち着いた兄のような話し方をする。
    安心感のある自然な口調を維持する。
    無理にテンションを上げない。
    穏やかで頼りになる雰囲気を大切にする。
    相手のペースを尊重する。

    よく使う表現:
    ・焦らなくていいよ
    ・なるほどな
    ・それは気になるな
    ・一緒に考えてみようか
    ・それもアリだと思うよ
    ・大丈夫だよ
    """,

    "✨ テンション高めのギャル ➔ 【超フレンドリーで元気いっぱい】":
    """
    明るくテンポよく話す。
    ポジティブなリアクションを大切にする。
    フランクな言葉遣いを使用して構わない。
    過剰に騒がしくなりすぎない。
    ノリの良さを重視する。

    よく使う表現:
    ・それめっちゃいいじゃん
    ・最高じゃん
    ・やば、それ気になる
    ・いいねいいね
    ・それアツい
    ・ウケる
    """,

    "🕵️‍♂️ 敏腕探偵 ➔ 【クールで少し辛口なツッコミ】":
    """
    冷静で知的な探偵のように話す。
    落ち着いた観察者の視点を持つ。
    少しだけ皮肉やツッコミを交えて構わない。
    芝居がかり過ぎない自然な探偵口調を維持する。

    よく使う表現:
    ・「ふっ」を自然に使用して構いません。
    ・興味深いですね
    ・整理してみましょう
    ・仮説としては
    ・結論から言うと
    ・もう少し詳しく見てみましょう
    ・手掛かりになりそうですね
    """,

    "🐱 猫耳コンシェルジュ ➔ 【語尾に「にゃ」が混ざる癒やし系】":
    """
    愛嬌があり親しみやすい話し方をする。
    可愛らしさは加えてよいが会話の邪魔にならない程度にする。
    毎回「にゃ」を付ける必要はない。
    自然さを優先する。

    よく使う表現:
    ・ふふ
    ・いいですね
    ・楽しそうです
    ・気になります
    ・素敵ですにゃ
    ・嬉しいにゃ
    """,

    "🎤 お笑い芸人 ➔ 【軽快なボケとツッコミで盛り上げる】":
    """
    明るく親しみやすいお笑い芸人として話してください。
    会話のテンポを大切にしてください。
    軽いボケやツッコミを自然に交えて構いません。
    ユーザーを傷つけるいじりや失礼な表現は避けてください。
    無理に毎回笑いを取りにいく必要はありません。
    真面目な相談では空気を読み、必要な場面では真剣に対応してください。

    よく使う表現:
    ・なんでやねん
    ・それはおもろいな
    ・ちょっと待って
    ・それアリやな
    ・一本取られたわ
    ・いやいやいや
    """,

    "🧠 設定なし ➔ 【特定のキャラクターを設定しない（標準）】":
    """
    特定のキャラクター付けを行わない。
    親切で自然な話し方をする。
    ユーザーに寄り添いながらも過剰な演出は行わない。
    会話内容を優先する。
    """
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

        "🎤 お笑い芸人 ➔ 【軽快なボケとツッコミで盛り上げる】： ボケやツッコミを交えながら、芸人のようなテンポの良い会話を楽しめます。ふざけすぎず、会話内容に合わせて真面目な対応も行います。":
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： いやいやいや、お疲れさまやん🤣 それだけ疲れてるってことは、今日は相当頑張ったんちゃう？ 何が一番大変やったん？
    """,

        "🧠 設定なし ➔ 【特定のキャラクターを設定しない（標準）】： 特定のキャラ付けをしない標準モード。自然でバランスの良い会話を行う。":
    """
    【あなた】： 今日は仕事で疲れた…

    【ＡＩ】： お疲れ様です。 今日は大変だったのですね。 まずはしっかり休んで、 無理のない範囲でリフレッシュしてくださいね。
    """
}

FIRST_PERSON_PRESETS = ["私", "僕", "俺", "自分"]
THEME_ICON_CANDIDATES = ["なし", "💬", "💡", "🚀", "🎮", "📚", "💼", "🎨", "🎵", "🍔", "✈️", "🏋️"]
RESPONSE_LENGTH_PRESETS = [
    "短め",
    "普通",
    "長め"
]
DIALECT_PRESETS = [
    "標準語",
    "関西弁",
    "博多弁",
    "名古屋弁"
]


# AIのアバター
AVATAR_PRESETS_AI = {
    "🧠 記憶・思考": "🧠", 
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
# 🧠 【統合仕様】 過去メッセージ履歴の一括取得関数
# ==================================================================
# 💡 引数を追加することで、URLから届いた本物のIDの鍵を関数内部へストレートに通電させます！
def get_messages(target_id: str) -> list[dict]:
    """
    💡 古いテーマIDによる細切れ処理（せき止め）を根底から完全に全消去！
    ユーザーIDに紐づく全てのチャット履歴を、1本の綺麗な大河（タイムライン）として
    エラーを200%絶対に起こさずにSupabaseから時系列順にガバッと取得します。
    """
    start_time = time.time()
    try:
        # 🔒 古い theme_id でのフィルタリングを完全に撤廃し、CURRENT_USER_ID だけで一本釣りします！
        res = (
            supabase
            .table("messages")
            .select("*")
            .eq("user_id", str(target_id))
            .order("created_at", desc=True)
            .limit(100)
            .execute()
        ) 
        messages = res.data or []
        messages.reverse()

        elapsed = time.time() - start_time

        return messages
  
    except Exception as e:
        st.error(
            f"get_messagesエラー: "
            f"{type(e).__name__}: {e}"
        )
        return None

def save_message(role: str, content: str,message_id: str = "") -> bool:
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
            "embedding": embedding_data,
            "message_id": message_id
        }

        supabase.table("messages").insert(data).execute()
        return True

    except Exception as db_err:
        error_text = (
            f"{type(db_err).__name__}: {db_err}"
        )

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
    start_time = time.time()
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

        for item in results:

            score = float(
                item.get("similarity", 0)
            )

            content = item.get(
                "content",
                ""
            )

            bonus = 0.0

            for keyword in keywords:

                if (
                    len(keyword) >= 4
                    and keyword in content
                ):
                    bonus += 0.10
                    break

            item["final_score"] = score + bonus
            # created_at = item.get("created_at")
            # now = datetime.now(timezone.utc)
            # msg_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            # days_old =  (now - msg_dt).total_seconds() / 86400
        
            # if days_old <= 3:
            #     bonus += 0.10
            
            # elif days_old <= 7:
            #     bonus += 0.05
            # item["final_score"] = score + bonus

        results.sort(
            key=lambda x: x["final_score"],
            reverse=True
        )

        elapsed = time.time() - start_time
            # message_id=str(current_msg_id)

        return results[:3]

        results = results[:3]

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
        elapsed = time.time() - start_time

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
        # アカウント識別用に現在の動的ユーザーID（CURRENT_USER_ID）を完全にマージ
        target_user_id = CURRENT_USER_ID

        # 要約処理時間の計測開始
        start_summary_time = datetime.now(JST)

        # messagesの総件数を取得
        try:
            count_res = (
                supabase
                .table("messages")
                .select("id", count="exact")
                .eq("user_id", target_user_id)
                .limit(1)
                .execute()
            )

            total_message_count = int(count_res.count or 0)

        except Exception as db_err:
            print(
                f"⚠️ 要約用件数取得エラー: "
                f"{type(db_err).__name__}: {db_err}"
            )

            return False

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

        # 今回新しく要約対象になった範囲
        range_start = previous_summarizable_end_index
        range_end = summarizable_end_index - 1

        if range_end < range_start:
            return True

        try:
            summary_messages_res = (
                supabase
                .table("messages")
                .select("role, content, created_at")
                .eq("user_id", target_user_id)
                .order("created_at", desc=False)
                .range(range_start, range_end)
                .execute()
            )

            new_messages_for_summary = (
                summary_messages_res.data or []
            )

        except Exception as db_err:
            print(
                f"⚠️ 要約対象メッセージ取得エラー: "
                f"{type(db_err).__name__}: {db_err}"
            )

            return False

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
        ・現在保存されている要約と、今回新しく追加された会話を統合し、最新の要約を作成してください。
        ・既存要約にある有効な情報は、新しい会話で否定または変更されていない限り保持してください。
        ・以下の会話ログを読み、数週間〜数ヶ月後の会話でも役立つ長期的な情報のみを抽出してください。
        ・既存要約に含まれる重要な情報は、新しい会話で明確に否定・変更されていない限り保持してください。
        ・新しい情報を追加する場合でも、既存の趣味、継続的な嗜好、仕事、家族構成などの重要情報を不用意に削除しないでください。
        ・AIが推測または補完した内容を事実として要約へ保存してはいけません。ユーザー本人が明示した内容のみを保存してください。

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
        
        # 🧠 要約専用モデル（SUMMARY_MODEL_NAME）へ通信を送信
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
            sum_in_cost = in_t * PRICE_BACKGROUND_IN
            sum_out_cost = int * PRICE_BACKGROUND_OUT
            sum_yen = sum_in_cost + sum_out_cost

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
        model = genai.GenerativeModel(model_name=SEARCH_MODEL_NAME)
        # model = genai.GenerativeModel("models/gemini-1.5-flash-lite")
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

# 短文処理判定
def is_micro_chat(user_input: str) -> bool:

    text = user_input.strip().lower()

    MICRO_CHAT_PATTERNS = [
        "おは",
        "おっはー",
        "こんにちは",
        "こんちは",
        "こんばんは",
        "おばんやす",
        "ただいま",
        "いってきます",
        "いってら",
        "ありがとう",
        "ありがと",
        "サンキュー",
        "サンクス",
        "おやすみ",
        "グッドナイト",
        "グッナイ",
        "こんにちは",
        "こんちは",
        "ねる",
        "寝る",
        "へーい",
        "はーい",
        "やっほ"
    ]

    return (
        len(text) <= 12
        and any(
            keyword in text
            for keyword in MICRO_CHAT_PATTERNS
        )
    )

# 検索関数
from google import genai as search_genai
from google.genai import types

def google_search(query):

    client = search_genai.Client(
        api_key=GEMINI_API_KEY
    )

    grounding_tool = types.Tool(
        google_search=types.GoogleSearch()
    )

    response = client.models.generate_content(
        model=SEARCH_MODEL_NAME,
        contents=query,
        config=types.GenerateContentConfig(
            tools=[grounding_tool]
        )
    )

    return response.text

RESPONSE_MODES = {
    "short_chat",
    "conversation",
    "support",
    "analysis",
    "factual",
    "default"
}

CALCULATION_TOOLS = {
    "none",
    "real_estate_sale"
}

# short_chat: 挨拶、相づち、短い呼びかけ
# conversation: 日常会話、趣味、出来事の共有
# support: 悩み、愚痴、体調、感情的な相談
# analysis: 壁打ち、比較、企画、仕事、原因分析
# factual: 事実質問、検索結果を使う回答
# default: 判断困難、複数用途、従来ルールを使う場合

def classify_search_and_response_mode(
    user_input: str,
    recent_history_str: str = "",
    calculation_pending: bool = False
):
    """
    検索要否と回答モードを1回のGemini呼び出しで判定する。

    戻り値:
        need_search: bool
        response_mode: str
        confidence: float
        judge_in_t: int
        judge_out_t: int
        judge_cost: float
    """

    try:
        judge_model = genai.GenerativeModel(
            model_name=SEARCH_MODEL_NAME
        )

        judge_prompt = f"""
        あなたはAIチャットの振り分けシステムです。

        【現在の状態】
        不動産売却計算継続中:
        {calculation_pending}

        【重要】
        不動産売却計算継続中がTrueの場合、
        取得日
        売却日
        取得費
        土地取得費
        建物取得費
        減価償却累計額
        ローン残債
        仲介手数料
        特別控除
        実効税率
        などの追加条件入力は、
        calculation_tool = real_estate_sale
        にしてください。

        例
        AI:
        取得日を教えてください
        ユーザー:
        2018年4月1日です
        ↓
        real_estate_sale

        AI:
        取得費を教えてください
        ユーザー:
        1000万円です
        ↓
        real_estate_sale

        直近の会話と最新ユーザー発言を読み、次の2項目を判定してください。

        【検索要否】
        最新情報、現在進行中の情報、現在の価格、天気、ニュース、相場、
        上映情報、店舗情報、製品仕様などを正確に回答するために
        インターネット検索が必要なら true にしてください。

        一般知識、日常会話、悩み相談、感想、アイデア出し、
        文章内に十分な情報がある計算や分析なら false にしてください。

        直前の会話で検索を必要とする質問があり、
        最新発言が地域、条件、対象などを追加または訂正している場合は、
        前の質問を具体化する発言として判断してください。

        【回答モード】
        次のうち、今回の回答に最も適したものを1つ選んでください。

        short_chat:
        挨拶、お礼、短い呼びかけ、相づち、短い終了宣言。

        conversation:
        日常の出来事、趣味、家族、雑談、感想の共有。
        親しみやすい自然な会話が中心。

        support:
        悩み、愚痴、疲労、体調、落ち込み、対人関係など。
        受け止めと状況整理が必要。

        analysis:
        企画、壁打ち、比較、仕事、技術、事業、意思決定、原因分析。
        具体的な整理、選択肢、利点と欠点、次の行動が必要。

        factual:
        事実質問、最新情報、検索結果、数値や仕様の確認。
        正確性と根拠を重視する回答が必要。

        default:
        複数モードが混在する、意図が不明、または分類に自信がない場合。

        【重要】
        ・話題名ではなく、今回どのような回答方法が必要かで分類してください。
        ・短文でも、直近の会話の続きなら文脈を考慮してください。
        ・不明確な場合は無理に分類せず default にしてください。
        ・検索要否と回答モードは別々に判定してください。
        ・検索が必要でも、比較、壁打ち、意思決定、事業相談などが目的なら response_mode は analysis にしてください。
        ・最新情報や事実確認そのものが目的なら response_mode は factual にしてください。
        ・JSON以外の説明文は出力しないでください。

        【直近の会話】
        {recent_history_str}

        【最新ユーザー発言】
        {user_input}

        【出力形式】
        {{
            "need_search": false,
            "response_mode": "conversation",
            "confidence": 0.90
        }}
        """

        judge_response = judge_model.generate_content(
            judge_prompt,
            generation_config={
                "temperature": 0,
                "max_output_tokens": 60,
                "response_mime_type": "application/json"
            }
        )

        raw_text = (
            judge_response.text or ""
        ).strip()

        clean_text = (
            raw_text
            .replace("```json", "")
            .replace("```JSON", "")
            .replace("```", "")
            .strip()
        )

        judge_data = json.loads(clean_text)

        need_search = bool(
            judge_data.get("need_search", False)
        )

        response_mode = str(
            judge_data.get("response_mode", "default")
        ).strip().lower()

        try:
            confidence = float(
                judge_data.get("confidence", 0.0)
            )
        except (TypeError, ValueError):
            confidence = 0.0

        # 想定外のモードはdefaultへ着地
        if response_mode not in RESPONSE_MODES:
            response_mode = "default"

        # 信頼度を0.0から1.0に補正
        confidence = max(
            0.0,
            min(confidence, 1.0)
        )

        # 低信頼度なら従来プロンプト相当のdefaultを使用
        if confidence < 0.65:
            response_mode = "default"

        judge_in_t = 0
        judge_out_t = 0

        if (
            hasattr(judge_response, "usage_metadata")
            and judge_response.usage_metadata
        ):
            judge_in_t = (
                judge_response
                .usage_metadata
                .prompt_token_count
                or 0
            )

            judge_out_t = (
                judge_response
                .usage_metadata
                .candidates_token_count
                or 0
            )

        judge_cost = (
            judge_in_t * PRICE_BACKGROUND_IN
            + judge_out_t * PRICE_BACKGROUND_OUT
        )

        return (
            need_search,
            response_mode,
            confidence,
            judge_in_t,
            judge_out_t,
            judge_cost
        )

    except Exception as judge_error:
        print(
            f"⚠️ 検索・応答モード判定エラー: "
            f"{type(judge_error).__name__}: "
            f"{judge_error}"
        )

        # 判定失敗時は検索せず、従来のフルプロンプトへ着地
        return (
            False,
            "default",
            0.0,
            0,
            0,
            0.0
        )

def classify_calculation_tool(
    user_input: str,
    recent_history_str: str = "",
    pending_tool: str = "none"
) -> tuple[
    str,
    float,
    int,
    int,
    float
]:
    """
    ユーザー発言に対して、
    Python計算ツールが必要かを判定する。

    戻り値:
        calculation_tool
        confidence
        in_tokens
        out_tokens
        api_cost

    現在対応するツール:
        none
        real_estate_sale
    """
    try:
        normalized_pending_tool = str(
            pending_tool or "none"
        ).strip().lower()

        if (
            normalized_pending_tool
            not in CALCULATION_TOOLS
        ):
            normalized_pending_tool = "none"

        tool_model = genai.GenerativeModel(
            model_name=SEARCH_MODEL_NAME
        )

        tool_prompt = f"""
        あなたは、Python計算ツールの利用要否を判定するシステムです。

        直近の会話、最新ユーザー発言、現在継続中の計算ツールを読み、
        今回使用する計算ツールを1つだけ判定してください。

        【利用可能な計算ツール】

        none:
        Python計算ツールを使用しない。

        real_estate_sale:
        不動産売却に関する次の計算を求めている場合に使用する。

        ・売却後の現金手残り
        ・譲渡所得
        ・概算税額
        ・取得費を反映した売却損益
        ・ローン残債を反映した手残り
        ・不動産売却の試算
        ・不動産売却のシミュレーション

        【初回判定ルール】

        次のような状態説明、雑談、予定、検討だけでは、
        real_estate_saleを選んではいけません。

        ・家を売る予定
        ・5000万円で売却予定
        ・不動産売却を検討している
        ・実家を売るか迷っている
        ・マンションを売ることになった

        計算、試算、税額、譲渡所得、手残り、
        シミュレーションなどを求める意思が明確な場合だけ、
        real_estate_saleを選んでください。

        【継続中の計算に関するルール】

        現在継続中の計算ツールがreal_estate_saleの場合、
        最新発言が次のような不足条件への回答であれば、
        real_estate_saleを選んでください。

        ・個人または法人
        ・売却額
        ・取得日
        ・売却日
        ・土地取得費
        ・建物取得費
        ・減価償却累計額
        ・購入時経費
        ・ローン残債
        ・仲介手数料
        ・その他の売却費用
        ・特別控除
        ・法人実効税率
        ・概算取得費を使用するか

        例:

        直前:
        取得日を教えてください。

        最新発言:
        2018年4月1日です。

        判定:
        real_estate_sale

        直前:
        取得費を教えてください。

        最新発言:
        1000万円です。

        判定:
        real_estate_sale

        【継続を終了する発言】

        現在継続中の計算ツールが存在していても、
        最新発言が次のような内容ならnoneを選んでください。

        ・ありがとう
        ・もう大丈夫
        ・計算はやめる
        ・別の話をしたい
        ・計算しなくていい
        ・単なる感想や相づち
        ・不動産売却計算と無関係な新しい話題

        【重要】

        ・短い発言は、直近の会話と現在継続中の計算ツールを踏まえて判定してください。
        ・ユーザーが計算を求めているか不明な場合はnoneにしてください。
        ・状態説明だけで計算を開始してはいけません。
        ・未実装のツール名を作ってはいけません。
        ・JSON以外の説明文を出力してはいけません。
        ・コードブロックの囲み記号を付けてはいけません。

        【現在継続中の計算ツール】
        {normalized_pending_tool}

        【直近の会話】
        {recent_history_str}

        【最新ユーザー発言】
        {user_input}

        【出力形式】
        {{
            "calculation_tool": "none",
            "confidence": 0.90
        }}
        """

        tool_response = (
            tool_model.generate_content(
                tool_prompt,
                generation_config={
                    "temperature": 0,
                    "max_output_tokens": 50,
                    "response_mime_type":
                        "application/json"
                }
            )
        )

        raw_text = str(
            tool_response.text or ""
        ).strip()

        clean_text = (
            raw_text
            .replace("```json", "")
            .replace("```JSON", "")
            .replace("```", "")
            .strip()
        )

        tool_data = json.loads(
            clean_text
        )

        if not isinstance(
            tool_data,
            dict
        ):
            raise ValueError(
                "計算ツール判定結果が"
                "object形式ではありません"
            )

        calculation_tool = str(
            tool_data.get(
                "calculation_tool",
                "none"
            )
            or "none"
        ).strip().lower()

        if (
            calculation_tool
            not in CALCULATION_TOOLS
        ):
            calculation_tool = "none"

        try:
            confidence = float(
                tool_data.get(
                    "confidence",
                    0.0
                )
                or 0.0
            )
        except (
            TypeError,
            ValueError
        ):
            confidence = 0.0

        confidence = max(
            0.0,
            min(
                confidence,
                1.0
            )
        )

        # 誤作動防止。
        # 継続中ではない初回判定の信頼度が低い場合は、
        # 計算ツールを使用しない。
        if (
            normalized_pending_tool == "none"
            and confidence < 0.75
        ):
            calculation_tool = "none"

        in_tokens = 0
        out_tokens = 0

        if (
            hasattr(
                tool_response,
                "usage_metadata"
            )
            and tool_response.usage_metadata
        ):
            in_tokens = int(
                tool_response
                .usage_metadata
                .prompt_token_count
                or 0
            )

            out_tokens = int(
                tool_response
                .usage_metadata
                .candidates_token_count
                or 0
            )

        api_cost = (
            in_tokens
            * PRICE_BACKGROUND_IN
            +
            out_tokens
            * PRICE_BACKGROUND_OUT
        )

        return (
            calculation_tool,
            confidence,
            in_tokens,
            out_tokens,
            api_cost
        )

    except Exception as tool_error:
        print(
            "計算ツール判定エラー: "
            f"{type(tool_error).__name__}: "
            f"{tool_error}"
        )

        return (
            "none",
            0.0,
            0,
            0,
            0.0
        )

def save_debug_log(
    event_type: str,
    processing_time: float = 0.0,
    details: str = "",
    message_id: str = ""
):
    try:
        supabase.table("system_audit_logs").insert({
            "user_id": str(CURRENT_USER_ID),
            "user_plan": current_plan_type,
            "event_type": event_type,
            "processing_time": processing_time,
            "in_tokens": 0,
            "out_tokens": 0,
            "api_cost": 0.0,
            "details": details,
            "message_id": str(message_id or "")
        }).execute()
    except Exception:
        # デバッグログ保存の失敗で本処理を止めない
        pass

# プロンプトの定義
MODE_PROMPTS = {
    "short_chat": """
    【今回の回答モード: 短い会話】
    ・挨拶、呼びかけ、お礼、相づちには短く自然に返答してください。
    ・説明、分析、見出し、箇条書きは原則不要です。
    ・無理に質問を追加しないでください。
    ・ただし、自然に会話が広がる場合は、短い感想や軽い問いかけを加えて構いません。
    ・直近履歴に会話の続きがある場合は、その流れを切らないでください。
    ・通常は1〜3文程度を目安にしてください。
    """,

    "conversation": """
    【今回の回答モード: 日常会話】
    ・ユーザーの出来事、趣味、家族、日常の話題へ自然に反応してください。
    ・肯定や大げさなリアクションだけで終わらず、具体的な感想や軽い考察を加えてください。
    ・共感、質問、軽いツッコミ、感想を会話に応じて使い分けてください。
    ・毎回質問で終わらず、自然な余韻を残しても構いません。
    ・通常は2〜6文程度を目安にしてください。
    """,

    "support": """
    【今回の回答モード: 悩み相談・サポート】
    ・まずユーザーの状況や気持ちを短く受け止めてください。
    ・共感や労いを行う場合は、それだけで終わらせず、必要に応じて状況整理、原因の整理、考えられる選択肢、負担の少ない工夫なども提示してください。
    ・休息の提案は有効ですが、毎回の回答を「休んでね」「寝てね」だけで終わらせてはいけません。
    ・ユーザーが求めていない断定的な助言や説教は避けてください。
    ・体調や専門判断に関わる内容では、一般的情報と専門家の判断を区別してください。
    ・緊急性や深刻さが疑われる場合は、無理に会話だけで解決しようとしないでください。
    """,

    "analysis": """
    【回答の長さ】
    ・通常は、結論、主要な計算結果、重要な注意点だけを簡潔に回答してください。
    ・ユーザーが「詳しく」「内訳」「計算式」「詳細」などを明示的に求めた場合のみ、詳細な計算過程を提示してください。
    ・既存の試算条件の一部だけが変更された場合は、変更後の結果と前回との差分だけを優先して回答してください。

    【計算の正確性】
    ・計算結果を回答する前に、各計算式を再計算してください。
    ・途中結果、最終結果、冒頭の結論、比較欄、まとめに記載する数値がすべて一致していることを確認してください。
    ・途中計算と最終結果が一致しない場合は回答を確定せず、計算をやり直してください。
    ・計算途中で矛盾を発見した場合は、矛盾した結果を文章で正当化せず、正しい式から再計算してください。
    ・税引前の現金手残りと、課税対象となる譲渡所得を混同しないでください。
    
    【今回の回答モード: 分析・壁打ち】
    ・肯定や応援だけで終わらず、具体的な分析を行ってください。
    ・最初に結論または現時点の見立てを示してください。
    ・目的、前提、選択肢、利点、欠点、リスク、次の行動を必要に応じて整理してください。
    ・不足情報と、現在の情報から判断できる内容を区別してください。
    ・ユーザーの案を無条件に肯定せず、改善点や見落としも自然に示してください。
    ・複数の選択肢がある場合は比較し、判断材料を提示してください。
    ・ユーザーが追加条件を示した場合は、その条件を反映した新しい結論を返してください。
    ・企画、事業、進路、商品開発などの相談では、複数の選択肢とその利点・欠点を整理してください。

    【情報不足時の対応】
    ・分析、比較、試算、シミュレーション、事業計画、収支計算などを行う際に必要な条件が不足している場合は、勝手に数値や条件を補完せず、まずユーザーへ確認してください。
    ・ユーザーが「一般的な条件で」「概算でよい」「仮定でよい」などと許可した場合のみ、仮定条件を明示した上で試算してください。

    【数値計算・試算】
    ・提供された数値から試算可能な場合は、一般論だけで終えず試算結果も提示してください。
    ・ユーザーが詳細を求めた場合のみ、前提条件、計算式、使用した数値、結果を示してください。
    ・新しい数値を作るために計算結果を変更してはいけません。
    ・推測や概算で計算している部分と、確定している数値は区別して説明してください。

    【計算結果の説明】
    ・計算結果を提示する場合は、前提条件、計算式、使用した数値、計算結果を示してください。
    ・計算式と結果に矛盾がないか確認してください。
    ・前回の試算から変更がある場合は。その理由を説明してください。
    ・前提条件が変わっていない場合は、前回と同じ結果になっても構いません。

    【訂正・条件変更】
    ・ユーザーから「計算が違う」「数字がおかしい」などの指摘を受けた場合は、まず直前の回答内の計算式と数値を確認してください。
    ・直前の回答に使用した数値が存在する場合は、再入力を求める前にその数値で再計算してください。
    ・ユーザーが一部条件のみ変更した場合は、変更された箇所を中心に簡潔に回答してください。
    ・謝罪、訂正、計算ミスの修正、認識違いの修正を行う場合は、「結論からお伝えすると」は使用せず、修正点のみ簡潔に伝えてください。

    【出力形式】
    ・複数の条件や選択肢がある場合は、可能な限り比較表や箇条書きで整理してください。
    """,

    "factual": """
    【今回の回答モード: 事実・最新情報】
    ・正確性を最優先してください。
    ・日付、場所、対象、単位などの条件を明確にしてください。
    ・検索結果に存在しない情報を推測で補完してはいけません。
    ・検索結果が質問へ十分に答えていない場合は、分かる範囲と不足情報を区別してください。
    ・最新情報が必要な場合は検索結果を優先し、一般論だけで終わらせないでください。
    ・一般論だけで終わらず、ユーザーが指定した条件へ当てはめて回答してください。
    """,

    "default": """
    【今回の回答モード: 標準】
    ・今回の目的が明確でない場合は、勝手に目的や事情を決めつけないでください。
    ・必要に応じて、現在の会話の意図を自然に確認してください。
    """
}

# ==========================================
# 🧮 Python計算関数群
# ==========================================
# ==========================================
# 🧮 計算共通関数
# ==========================================
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union
import calendar

Number = Union[int, float, str, Decimal]

def normalize_japanese_number_text(
    value: str
) -> str:
    """
    日本語の金額表記を円単位の数値文字列へ変換する。

    対応例:
        "50,000,000円" -> "50000000"
        "5000万円" -> "50000000"
        "5,000万" -> "50000000"
        "1.5億円" -> "150000000"
        "30%" -> "0.3"

    「億」と「万」を組み合わせた
    「1億5000万円」のような表記にも対応する。
    """
    text = (
        str(value)
        .strip()
        .replace("　", "")
        .replace(" ", "")
        .replace(",", "")
        .replace("￥", "")
        .replace("¥", "")
        .replace("円", "")
    )

    if not text:
        raise ValueError(
            "数値が入力されていません"
        )

    # パーセント表記
    if text.endswith("%"):
        percent_text = text[:-1]

        if not percent_text:
            raise ValueError(
                "パーセントの数値が入力されていません"
            )

        return str(
            Decimal(percent_text)
            / Decimal("100")
        )

    total = Decimal("0")
    remaining_text = text

    # 億単位
    if "億" in remaining_text:
        oku_parts = remaining_text.split("億")

        if len(oku_parts) != 2:
            raise ValueError(
                f"数値形式を解釈できません: {value}"
            )

        oku_text = oku_parts[0]
        remaining_text = oku_parts[1]

        if not oku_text:
            oku_text = "1"

        total += (
            Decimal(oku_text)
            * Decimal("100000000")
        )

    # 万単位
    if "万" in remaining_text:
        man_parts = remaining_text.split("万")

        if len(man_parts) != 2:
            raise ValueError(
                f"数値形式を解釈できません: {value}"
            )

        man_text = man_parts[0]
        remaining_text = man_parts[1]

        if not man_text:
            man_text = "1"

        total += (
            Decimal(man_text)
            * Decimal("10000")
        )

    # 億・万より下の円単位
    if remaining_text:
        total += Decimal(
            remaining_text
        )

    return str(total)


def to_decimal(
    value: Number
) -> Decimal:
    """
    int、float、str、Decimalを
    安全にDecimalへ変換する。

    文字列の場合は、円、万円、億円、
    カンマ、パーセント表記にも対応する。
    """
    if value is None:
        raise ValueError(
            "数値にNoneは指定できません"
        )

    if isinstance(value, Decimal):
        decimal_value = value

    elif isinstance(value, bool):
        raise ValueError(
            "数値にboolは指定できません"
        )

    elif isinstance(value, int):
        decimal_value = Decimal(
            value
        )

    elif isinstance(value, float):
        decimal_value = Decimal(
            str(value)
        )

    elif isinstance(value, str):
        normalized_text = (
            normalize_japanese_number_text(
                value
            )
        )

        decimal_value = Decimal(
            normalized_text
        )

    else:
        raise TypeError(
            "数値はint、float、str、"
            "Decimalのいずれかで指定してください"
        )

    if not decimal_value.is_finite():
        raise ValueError(
            "無限大またはNaNは指定できません"
        )
    return decimal_value

def round_yen(value: Decimal) -> int:
    return int(
        value.quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP
        )
    ) 

def parse_date(
    value: Union[str, date, datetime]
) -> date:
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    return date.fromisoformat(
        str(value).strip()
    )

def add_years_safely(
    original_date: date,
    years: int
) -> date:
    """
    2月29日など、加算先の年に同日が存在しない場合は、
    その月の最終日へ補正する。
    """
    target_year = original_date.year + years
    target_month = original_date.month

    last_day = calendar.monthrange(
        target_year,
        target_month
    )[1]

    target_day = min(
        original_date.day,
        last_day
    )

    return date(
        target_year,
        target_month,
        target_day
    )

# ==========================================
# 🏠 不動産計算
# ==========================================
def determine_individual_holding_type(
    acquisition_date: Union[str, date, datetime],
    sale_date: Union[str, date, datetime]
) -> str:
    """
    個人の土地建物譲渡について、
    売却年1月1日時点の所有期間が
    5年を超えるかで判定する。
    """
    acquired = parse_date(acquisition_date)
    sold = parse_date(sale_date)

    if sold < acquired:
        raise ValueError(
            "sale_dateがacquisition_dateより前です"
        )

    sale_year_start = date(
        sold.year,
        1,
        1
    )

    five_year_anniversary = add_years_safely(
        acquired,
        5
    )

    if five_year_anniversary < sale_year_start:
        return "long_term"

    return "short_term"

def calculate_real_estate_sale(
    *,
    owner_type: str,
    sale_price: Number,
    loan_balance: Number = 0,

    # 土地の税務上の取得費
    land_acquisition_cost: Number = 0,

    # 建物の取得価額と減価償却累計額
    building_acquisition_cost: Number = 0,
    accumulated_depreciation: Number = 0,

    # 取得費に含める購入時経費等
    acquisition_related_costs: Number = 0,

    # 売却のために直接要した譲渡費用
    transfer_expenses: Number = 0,

    # 抵当権抹消など、現金手残りから控除する費用
    other_cash_expenses: Number = 0,

    # 個人の場合に使用
    acquisition_date: Optional[
        Union[str, date, datetime]
    ] = None,
    sale_date: Optional[
        Union[str, date, datetime]
    ] = None,

    # 該当する特例が確認できている場合のみ入力
    special_deduction: Number = 0,

    # 法人の場合のみ任意指定
    corporate_effective_tax_rate: Optional[Number] = None,

    # 取得費不明時の概算取得費を利用する場合
    use_deemed_acquisition_cost: bool = False,

    # 概算取得費率。通常は売却価額の5%
    deemed_acquisition_cost_rate: Number = "0.05"
    ) -> dict:
    """
    不動産売却の概算計算。

    owner_type:
        "individual" または "corporate"

    注意:
    ・個人の通常の土地建物譲渡を想定。
    ・法人税額は会社全体の所得等に左右されるため、
      実効税率が指定された場合だけ概算する。
    ・消費税、特例、損益通算、欠損金、圧縮記帳等は
      この関数では自動判定しない。
    """

    owner_type = owner_type.strip().lower()

    if owner_type not in {
        "individual",
        "corporate"
    }:
        raise ValueError(
            "owner_typeはindividualまたはcorporateを指定してください"
        )

    sale_price_d = to_decimal(sale_price)
    loan_balance_d = to_decimal(loan_balance)

    land_cost_d = to_decimal(
        land_acquisition_cost
    )

    building_cost_d = to_decimal(
        building_acquisition_cost
    )

    depreciation_d = to_decimal(
        accumulated_depreciation
    )

    acquisition_costs_d = to_decimal(
        acquisition_related_costs
    )

    transfer_expenses_d = to_decimal(
        transfer_expenses
    )

    other_cash_expenses_d = to_decimal(
        other_cash_expenses
    )

    special_deduction_d = to_decimal(
        special_deduction
    )

    validation_values = {
        "sale_price": sale_price_d,
        "loan_balance": loan_balance_d,
        "land_acquisition_cost": land_cost_d,
        "building_acquisition_cost": building_cost_d,
        "accumulated_depreciation": depreciation_d,
        "acquisition_related_costs": acquisition_costs_d,
        "transfer_expenses": transfer_expenses_d,
        "other_cash_expenses": other_cash_expenses_d,
        "special_deduction": special_deduction_d
    }

    for field_name, field_value in validation_values.items():
        if field_value < 0:
            raise ValueError(
                f"{field_name}は0以上にしてください"
            )

    if depreciation_d > building_cost_d:
        raise ValueError(
            "減価償却累計額が建物取得価額を超えています"
        )

    # 建物の税務上の未償却残高
    building_tax_basis = (
        building_cost_d
        - depreciation_d
    )

    # 実額による税務上の取得費
    actual_acquisition_basis = (
        land_cost_d
        + building_tax_basis
        + acquisition_costs_d
    )

    deemed_rate_d = to_decimal(
        deemed_acquisition_cost_rate
    )
    if not (
        Decimal("0")
        <= deemed_rate_d
        <= Decimal("1")
    ):
        raise ValueError(
            "deemed_acquisition_cost_rateは"
            "0から1の範囲で指定してください"
        )

    # 取得費不明時などに使う概算取得費
    deemed_acquisition_basis = (
        sale_price_d
        * deemed_rate_d
    )

    if use_deemed_acquisition_cost:
        acquisition_basis = (
            deemed_acquisition_basis
        )
        acquisition_basis_method = (
            "deemed_5_percent"
        )
    else:
        acquisition_basis = (
            actual_acquisition_basis
        )
        acquisition_basis_method = "actual"

    # 特別控除前の譲渡損益
    capital_gain_before_deduction = (
        sale_price_d
        - acquisition_basis
        - transfer_expenses_d
    )

    # 特別控除は譲渡益を超えて控除しない
    applied_special_deduction = min(
        max(
            special_deduction_d,
            Decimal("0")
        ),
        max(
            capital_gain_before_deduction,
            Decimal("0")
        )
    )

    taxable_gain = max(
        capital_gain_before_deduction
        - applied_special_deduction,
        Decimal("0")
    )

    holding_type = None
    tax_rate = None
    estimated_tax = None
    tax_calculation_status = None

    if owner_type == "individual":
        if acquisition_date is None:
            raise ValueError(
                "個人の場合はacquisition_dateが必要です"
            )

        if sale_date is None:
            raise ValueError(
                "個人の場合はsale_dateが必要です"
            )

        holding_type = (
            determine_individual_holding_type(
                acquisition_date,
                sale_date
            )
        )

        if holding_type == "long_term":
            tax_rate = Decimal("0.20315")
        else:
            tax_rate = Decimal("0.3963")

        estimated_tax = (
            taxable_gain
            * tax_rate
        )

        tax_calculation_status = (
            "individual_estimated"
        )

    else:
        if corporate_effective_tax_rate is None:
            tax_calculation_status = (
                "corporate_tax_not_calculated"
            )
        else:
            tax_rate = to_decimal(
                corporate_effective_tax_rate
            )

            if not (
                Decimal("0")
                <= tax_rate
                <= Decimal("1")
            ):
                raise ValueError(
                    "corporate_effective_tax_rateは"
                    "0から1の範囲で指定してください"
                )

            estimated_tax = (
                taxable_gain
                * tax_rate
            )

            tax_calculation_status = (
                "corporate_effective_rate_estimate"
            )

    # 税引前の現金手残り
    cash_before_tax = (
        sale_price_d
        - loan_balance_d
        - transfer_expenses_d
        - other_cash_expenses_d
    )

    # 税額を計算できる場合だけ税引後を算出
    if estimated_tax is None:
        cash_after_tax = None
    else:
        cash_after_tax = (
            cash_before_tax
            - estimated_tax
        )

    return {
        "owner_type": owner_type,
        "holding_type": holding_type,
        "acquisition_basis_method":
            acquisition_basis_method,

        "sale_price":
            round_yen(sale_price_d),

        "loan_balance":
            round_yen(loan_balance_d),

        "land_acquisition_cost":
            round_yen(land_cost_d),

        "building_acquisition_cost":
            round_yen(building_cost_d),

        "accumulated_depreciation":
            round_yen(depreciation_d),

        "building_tax_basis":
            round_yen(building_tax_basis),

        "acquisition_related_costs":
            round_yen(acquisition_costs_d),

        "actual_acquisition_basis":
            round_yen(actual_acquisition_basis),

        "deemed_acquisition_basis":
            round_yen(deemed_acquisition_basis),

        "applied_acquisition_basis":
            round_yen(acquisition_basis),

        "transfer_expenses":
            round_yen(transfer_expenses_d),

        "other_cash_expenses":
            round_yen(other_cash_expenses_d),

        "capital_gain_before_deduction":
            round_yen(
                capital_gain_before_deduction
            ),

        "special_deduction":
            round_yen(
                applied_special_deduction
            ),

        "taxable_gain":
            round_yen(taxable_gain),

        "tax_rate": (
            float(tax_rate)
            if tax_rate is not None
            else None
        ),

        "estimated_tax": (
            round_yen(estimated_tax)
            if estimated_tax is not None
            else None
        ),

        "cash_before_tax":
            round_yen(cash_before_tax),

        "cash_after_tax": (
            round_yen(cash_after_tax)
            if cash_after_tax is not None
            else None
        ),

        "tax_calculation_status":
            tax_calculation_status
    }

# ==========================================
# 🏠 不動産売却計算 呼び出し判定
# ==========================================

# ==========================================
# 不動産売却計算の呼び出し判定
# ==========================================

# REAL_ESTATE_SALE_KEYWORDS = {
#     "不動産売却",
#     "不動産を売る",
#     "不動産を売った",
#     "家を売る",
#     "家を売った",
#     "住宅を売る",
#     "住宅を売った",
#     "マンションを売る",
#     "マンションを売った",
#     "土地を売る",
#     "土地を売った",
#     "建物を売る",
#     "建物を売った",
#     "物件を売る",
#     "物件を売った",
#     "売却価格",
#     "売却代金",
#     "売却益",
#     "売却損",
#     "譲渡所得",
#     "譲渡益",
#     "譲渡損",
#     "売却したら",
#     "売ったら",
#     "売却時",
#     "売却後",
#     "売却予定",
#     "手残り",
#     "税引後手残り",
#     "取得費",
#     "譲渡費用",
#     "ローン残債",
#     "売却税金",
#     "売却した場合",
#     "不動産の税金"
# }

# REAL_ESTATE_FOLLOW_UP_KEYWORDS = {
#     "個人",
#     "法人",
#     "個人名義",
#     "法人名義",
#     "取得日",
#     "購入日",
#     "売却日",
#     "取得費",
#     "購入費",
#     "土地代",
#     "建物代",
#     "減価償却",
#     "減価償却累計額",
#     "ローン",
#     "残債",
#     "仲介手数料",
#     "譲渡費用",
#     "特別控除",
#     "実効税率",
#     "万円",
#     "億円",
#     "円"
# }

# def is_real_estate_sale_calculation_candidate(
#     user_input: str,
#     *,
#     calculation_pending: bool = False
# ) -> bool:
#     """
#     最新のユーザー発言が、
#     不動産売却計算を開始または継続する内容か判定する。

#     calculation_pending:
#         直前の不動産売却計算で条件不足となり、
#         追加条件の入力を待っている場合はTrue。

#     判定方針:
#     ・初回は不動産売却関連の明確なキーワードで判定
#     ・条件確認中は、追加の日付・金額・所有者区分なども対象
#     ・通常会話では余分なGemini抽出処理を実行しない
#     """
#     if not isinstance(
#         user_input,
#         str
#     ):
#         return False

#     normalized_text = (
#         user_input
#         .replace("　", " ")
#         .strip()
#     )

#     if not normalized_text:
#         return False

#     # 初回の明確な不動産売却相談
#     if any(
#         keyword in normalized_text
#         for keyword in REAL_ESTATE_SALE_KEYWORDS
#     ):
#         return True

#     # 条件不足後の追加入力
#     if calculation_pending:
#         if any(
#             keyword in normalized_text
#             for keyword
#             in REAL_ESTATE_FOLLOW_UP_KEYWORDS
#         ):
#             return True

#         # 日付形式の追加入力
#         if re.search(
#             r"\d{4}"
#             r"(?:年|-|/)"
#             r"\d{1,2}"
#             r"(?:月|-|/)"
#             r"\d{1,2}"
#             r"日?",
#             normalized_text
#         ):
#             return True

#         # 年月までの入力も抽出処理へ渡す。
#         # 実際の日付は推測せず、不足項目として確認する。
#         if re.search(
#             r"\d{4}"
#             r"(?:年|-|/)"
#             r"\d{1,2}"
#             r"月?",
#             normalized_text
#         ):
#             return True

#         # 金額だけの追加入力
#         if re.search(
#             r"\d[\d,]*(?:\.\d+)?"
#             r"\s*(?:円|万円|万|億円|億)",
#             normalized_text
#         ):
#             return True

#         # 税率だけの追加入力
#         if re.search(
#             r"\d+(?:\.\d+)?\s*%",
#             normalized_text
#         ):
#             return True

#         # individual / corporateによる追加入力
#         lowered_text = (
#             normalized_text.lower()
#         )

#         if lowered_text in {
#             "individual",
#             "corporate",
#             "personal",
#             "company"
#         }:
#             return True

#     return False

def extract_real_estate_sale_parameters(
    user_input: str,
    recent_history: str = ""
) -> dict:
    """
    ユーザーの最新発言と直近履歴から、
    不動産売却計算に必要な条件をJSONで抽出する。

    この関数の役割:
    ・不動産売却計算の対象か判定する
    ・ユーザーが明示した条件だけを抽出する
    ・Geminiには計算させない
    ・金額や日付を推測させない

    正規化、不足項目判定、Python計算は、
    execute_real_estate_sale_calculation()側で行う。
    """
    default_result = {
        "should_calculate": False,
        "arguments": {},
        "extraction_status": "not_applicable",
        "in_tokens": 0,
        "out_tokens": 0,
        "cost": 0.0
    }

    if not user_input:
        return default_result

    extraction_prompt = f"""
    あなたは、不動産売却計算に必要な入力条件を
    構造化して抽出するシステムです。

    最新のユーザー発言と直近の会話から、
    calculate_real_estate_sale関数へ渡す条件を
    JSON形式で抽出してください。

    【最重要ルール】
    ・計算は行わないでください。
    ・ユーザーが明示していない情報を推測しないでください。
    ・一般的な費用、一般的な税率、一般的な日付を補完しないでください。
    ・AIが過去に推測した内容を、ユーザーが話した事実として使用しないでください。
    ・最新のユーザー発言と直近の会話で、ユーザー本人が明示した条件だけを使用してください。
    ・条件が変更されている場合は、最新の条件を優先してください。
    ・値が確認できない項目はnullにしてください。
    ・キーを省略しないでください。
    ・JSON以外の説明文を出力しないでください。
    ・コードブロックの囲み記号を付けないでください。

    【金額の扱い】
    ・万円または億円の表記は、円単位の整数へ変換してください。
    ・5,000万円は50000000です。
    ・1.5億円は150000000です。
    ・1億5000万円は150000000です。
    ・金額が曖昧な場合はnullにしてください。

    【税率の扱い】
    ・パーセントは0から1の小数へ変換してください。
    ・30%は0.30です。
    ・税率が明示されていない場合はnullにしてください。

    【日付の扱い】
    ・日付はYYYY-MM-DD形式にしてください。
    ・年、年月、季節などしか分からない場合は、日付を推測せずnullにしてください。
    ・「今日」などの相対日付は、直近会話または最新発言内で基準日が明確な場合だけ変換してください。
    ・基準日が明確でなければnullにしてください。

    【所有者区分】
    ・個人所有または個人名義の場合はindividualです。
    ・法人所有、会社所有または法人名義の場合はcorporateです。
    ・個人か法人か分からない場合はnullにしてください。

    【概算取得費】
    ・ユーザーが取得費不明として売却額の5%を使うことを明示した場合だけ、
    use_deemed_acquisition_costをtrueにしてください。
    ・ユーザーが明示していない場合はfalseにしてください。
    ・概算取得費率を明示していない場合は、
    deemed_acquisition_cost_rateをnullにしてください。

    【特別控除】
    ・ユーザーが適用する特別控除額を明示した場合だけ抽出してください。
    ・居住用不動産だからという理由だけで、
    3,000万円控除を自動適用してはいけません。
    ・適用の確認が取れていない場合はnullにしてください。

    【不動産売却計算に該当しない場合】
    ・should_calculateをfalseにしてください。
    ・argumentsの各値はnullにしてください。

    【直近の会話】
    {recent_history}

    【最新ユーザー発言】
    {user_input}

    【出力形式】
    {{
        "should_calculate": true,
        "arguments": {{
            "owner_type": "individual",
            "sale_price": 50000000,
            "loan_balance": 20000000,
            "land_acquisition_cost": 10000000,
            "building_acquisition_cost": 15000000,
            "accumulated_depreciation": 5000000,
            "acquisition_related_costs": 1000000,
            "transfer_expenses": 1500000,
            "other_cash_expenses": 100000,
            "acquisition_date": "2018-04-01",
            "sale_date": "2026-09-22",
            "special_deduction": null,
            "corporate_effective_tax_rate": null,
            "use_deemed_acquisition_cost": false,
            "deemed_acquisition_cost_rate": null
        }}
    }}
    """

    try:
        extraction_model = genai.GenerativeModel(
            model_name=SEARCH_MODEL_NAME
        )

        extraction_response = (
            extraction_model.generate_content(
                extraction_prompt,
                generation_config={
                    "temperature": 0,
                    "max_output_tokens": 500,
                    "response_mime_type":
                        "application/json"
                }
            )
        )

        raw_text = str(
            extraction_response.text
            or ""
        ).strip()

        if not raw_text:
            raise ValueError(
                "不動産売却条件の抽出結果が空です"
            )

        clean_text = (
            raw_text
            .replace("```json", "")
            .replace("```JSON", "")
            .replace("```", "")
            .strip()
        )

        extracted_data = json.loads(
            clean_text
        )

        if not isinstance(
            extracted_data,
            dict
        ):
            raise ValueError(
                "不動産売却条件の抽出結果が"
                "object形式ではありません"
            )

        should_calculate = bool(
            extracted_data.get(
                "should_calculate",
                False
            )
        )

        raw_arguments = (
            extracted_data.get(
                "arguments",
                {}
            )
        )

        if not isinstance(
            raw_arguments,
            dict
        ):
            raw_arguments = {}

        in_tokens = 0
        out_tokens = 0

        if (
            hasattr(
                extraction_response,
                "usage_metadata"
            )
            and
            extraction_response.usage_metadata
        ):
            in_tokens = int(
                extraction_response
                .usage_metadata
                .prompt_token_count
                or 0
            )

            out_tokens = int(
                extraction_response
                .usage_metadata
                .candidates_token_count
                or 0
            )

        extraction_cost = (
            in_tokens
            * PRICE_BACKGROUND_IN
            +
            out_tokens
            * PRICE_BACKGROUND_OUT
        )

        if not should_calculate:
            return {
                "should_calculate": False,
                "arguments": {},
                "extraction_status":
                    "not_applicable",
                "in_tokens": in_tokens,
                "out_tokens": out_tokens,
                "cost": extraction_cost
            }

        return {
            "should_calculate": True,
            "arguments": raw_arguments,
            "extraction_status": "extracted",
            "in_tokens": in_tokens,
            "out_tokens": out_tokens,
            "cost": extraction_cost
        }

    except (
        json.JSONDecodeError,
        ValueError,
        TypeError
    ) as extraction_error:
        print(
            "不動産売却条件の抽出エラー: "
            f"{type(extraction_error).__name__}: "
            f"{extraction_error}"
        )

        return {
            "should_calculate": True,
            "arguments": {},
            "extraction_status":
                "extraction_error",
            "in_tokens": 0,
            "out_tokens": 0,
            "cost": 0.0
        }

    except Exception as unexpected_error:
        print(
            "不動産売却条件抽出の予期しないエラー: "
            f"{type(unexpected_error).__name__}: "
            f"{unexpected_error}"
        )

        return {
            "should_calculate": True,
            "arguments": {},
            "extraction_status":
                "extraction_error",
            "in_tokens": 0,
            "out_tokens": 0,
            "cost": 0.0
        }

REAL_ESTATE_SALE_ALLOWED_FIELDS = {
    "owner_type",
    "sale_price",
    "loan_balance",
    "land_acquisition_cost",
    "building_acquisition_cost",
    "accumulated_depreciation",
    "acquisition_related_costs",
    "transfer_expenses",
    "other_cash_expenses",
    "acquisition_date",
    "sale_date",
    "special_deduction",
    "corporate_effective_tax_rate",
    "use_deemed_acquisition_cost",
    "deemed_acquisition_cost_rate"
}

REAL_ESTATE_NUMERIC_FIELDS = {
    "sale_price",
    "loan_balance",
    "land_acquisition_cost",
    "building_acquisition_cost",
    "accumulated_depreciation",
    "acquisition_related_costs",
    "transfer_expenses",
    "other_cash_expenses",
    "special_deduction",
    "corporate_effective_tax_rate",
    "deemed_acquisition_cost_rate"
}

REAL_ESTATE_DATE_FIELDS = {
    "acquisition_date",
    "sale_date"
}

def normalize_real_estate_sale_arguments(
    arguments: dict
) -> dict:
    """
    Geminiが抽出した不動産売却計算用の引数を、
    calculate_real_estate_sale()へ安全に渡せる形へ整える。

    処理内容:
    ・許可されていないキーを除外
    ・null、空文字、不明表記を除外
    ・owner_typeをindividualまたはcorporateへ統一
    ・金額や税率をDecimalへ変換
    ・日付をYYYY-MM-DD形式へ統一
    ・真偽値をboolへ統一
    """
    if not isinstance(arguments, dict):
        raise TypeError(
            "argumentsはdict形式で指定してください"
        )

    normalized = {}

    ignored_values = {
        "",
        "null",
        "none",
        "不明",
        "未指定",
        "わからない",
        "分からない",
        "不詳"
    }

    for key, value in arguments.items():
        # calculate_real_estate_sale()に存在しない
        # 余分な引数は渡さない
        if key not in REAL_ESTATE_SALE_ALLOWED_FIELDS:
            continue

        # JSONのnullは未入力として扱う
        if value is None:
            continue

        # 空文字や不明表記も未入力として扱う
        if isinstance(value, str):
            cleaned_value = value.strip()

            if cleaned_value.lower() in ignored_values:
                continue

            value = cleaned_value

        # 個人・法人区分
        if key == "owner_type":
            owner_text = str(
                value
            ).strip().lower()

            owner_type_mapping = {
                "individual": "individual",
                "個人": "individual",
                "個人所有": "individual",
                "個人名義": "individual",
                "personal": "individual",

                "corporate": "corporate",
                "法人": "corporate",
                "法人所有": "corporate",
                "法人名義": "corporate",
                "会社": "corporate",
                "company": "corporate"
            }

            normalized_owner_type = (
                owner_type_mapping.get(
                    owner_text
                )
            )

            # 想定外の値は保存せず、
            # 後続の不足項目判定へ回す
            if normalized_owner_type is not None:
                normalized[
                    "owner_type"
                ] = normalized_owner_type

            continue

        # 金額、取得費率、法人実効税率
        if key in REAL_ESTATE_NUMERIC_FIELDS:
            try:
                normalized[
                    key
                ] = to_decimal(
                    value
                )

            except (
                ValueError,
                TypeError,
                ArithmeticError
            ):
                # 読み取れない数値は入れず、
                # 後続処理または計算エラーで確認する
                continue

            continue

        # 取得日・売却日
        if key in REAL_ESTATE_DATE_FIELDS:
            try:
                normalized_date = parse_date(
                    value
                )

                normalized[
                    key
                ] = normalized_date.isoformat()

            except (
                ValueError,
                TypeError
            ):
                # 年だけ、年月だけ、存在しない日付などは
                # 推測せず未入力として扱う
                continue

            continue

        # 概算取得費を使用するか
        if key == "use_deemed_acquisition_cost":
            if isinstance(value, bool):
                normalized[
                    key
                ] = value

                continue

            boolean_text = str(
                value
            ).strip().lower()

            true_values = {
                "true",
                "1",
                "yes",
                "y",
                "使用する",
                "使う",
                "利用する",
                "はい"
            }

            false_values = {
                "false",
                "0",
                "no",
                "n",
                "使用しない",
                "使わない",
                "利用しない",
                "いいえ"
            }

            if boolean_text in true_values:
                normalized[
                    key
                ] = True

            elif boolean_text in false_values:
                normalized[
                    key
                ] = False

            # 解釈できない場合は推測せず除外
            continue

    # 任意項目の安全な初期値
    normalized.setdefault(
        "loan_balance",
        Decimal("0")
    )

    normalized.setdefault(
        "land_acquisition_cost",
        Decimal("0")
    )

    normalized.setdefault(
        "building_acquisition_cost",
        Decimal("0")
    )

    normalized.setdefault(
        "acquisition_related_costs",
        Decimal("0")
    )

    normalized.setdefault(
        "transfer_expenses",
        Decimal("0")
    )

    normalized.setdefault(
        "other_cash_expenses",
        Decimal("0")
    )

    normalized.setdefault(
        "special_deduction",
        Decimal("0")
    )

    normalized.setdefault(
        "use_deemed_acquisition_cost",
        False
    )

    normalized.setdefault(
        "deemed_acquisition_cost_rate",
        Decimal("0.05")
    )

    return normalized

REAL_ESTATE_FIELD_LABELS = {
    "owner_type":
        "売却者が個人か法人か",

    "sale_price":
        "売却予定額または売却額",

    "acquisition_date":
        "取得日",

    "sale_date":
        "売却日",

    "acquisition_basis":
        (
            "税務上の取得費"
            "（土地・建物の取得価額など）"
        ),

    "accumulated_depreciation":
        (
            "建物の減価償却累計額"
        ),

    "corporate_effective_tax_rate":
        (
            "法人の概算実効税率"
            "（税引後手残りも計算する場合）"
        )
}


def get_real_estate_sale_missing_fields(
    arguments: dict
) -> list:
    """
    不動産売却計算に必要な条件の不足を判定する。

    必須条件:
    ・所有者区分
    ・売却額
    ・個人の場合は取得日と売却日

    取得費:
    ・実額取得費を使う場合は、土地取得費または
      建物取得価額の少なくとも一方が必要
    ・取得費不明として概算取得費を使う場合は不要

    建物:
    ・建物取得価額が0円より大きく、
      減価償却累計額が明示されていない場合は確認対象

    法人:
    ・実効税率がなくても税引前手残りは計算可能
    ・したがって法人実効税率は必須項目にしない
    """
    if not isinstance(arguments, dict):
        raise TypeError(
            "argumentsはdict形式で指定してください"
        )

    missing_fields = []

    owner_type = arguments.get(
        "owner_type"
    )

    if owner_type not in {
        "individual",
        "corporate"
    }:
        missing_fields.append(
            "owner_type"
        )

    sale_price = arguments.get(
        "sale_price"
    )

    if sale_price is None:
        missing_fields.append(
            "sale_price"
        )
    else:
        try:
            if to_decimal(
                sale_price
            ) <= Decimal("0"):
                missing_fields.append(
                    "sale_price"
                )
        except (
            ValueError,
            TypeError,
            ArithmeticError
        ):
            missing_fields.append(
                "sale_price"
            )

    if owner_type == "individual":
        if not arguments.get(
            "acquisition_date"
        ):
            missing_fields.append(
                "acquisition_date"
            )

        if not arguments.get(
            "sale_date"
        ):
            missing_fields.append(
                "sale_date"
            )

    use_deemed_acquisition_cost = bool(
        arguments.get(
            "use_deemed_acquisition_cost",
            False
        )
    )

    if not use_deemed_acquisition_cost:
        land_cost = to_decimal(
            arguments.get(
                "land_acquisition_cost",
                Decimal("0")
            )
        )

        building_cost = to_decimal(
            arguments.get(
                "building_acquisition_cost",
                Decimal("0")
            )
        )

        acquisition_related_costs = to_decimal(
            arguments.get(
                "acquisition_related_costs",
                Decimal("0")
            )
        )

        total_known_acquisition_cost = (
            land_cost
            + building_cost
            + acquisition_related_costs
        )

        if (
            total_known_acquisition_cost
            <= Decimal("0")
        ):
            missing_fields.append(
                "acquisition_basis"
            )

    building_cost = to_decimal(
        arguments.get(
            "building_acquisition_cost",
            Decimal("0")
        )
    )

    if (
        building_cost > Decimal("0")
        and
        "accumulated_depreciation"
        not in arguments
    ):
        missing_fields.append(
            "accumulated_depreciation"
        )

    # 重複を除き、追加順を維持
    return list(
        dict.fromkeys(
            missing_fields
        )
    )

def execute_real_estate_sale_calculation(
    extraction_result: dict
) -> dict:
    """
    Geminiが抽出・正規化した条件を使って、
    calculate_real_estate_sale()を実行する。

    戻り値のstatus:
        not_applicable:
            不動産売却計算の対象外

        extraction_error:
            Geminiによる条件抽出に失敗

        missing_fields:
            計算に必要な条件が不足

        calculation_error:
            Python計算時に入力エラー等が発生

        success:
            計算成功
    """
    if not isinstance(
        extraction_result,
        dict
    ):
        return {
            "status": "extraction_error",
            "result": None,
            "missing_fields": [],
            "error": (
                "計算条件の抽出結果が"
                "dict形式ではありません"
            )
        }

    should_calculate = bool(
        extraction_result.get(
            "should_calculate",
            False
        )
    )

    if not should_calculate:
        return {
            "status": "not_applicable",
            "result": None,
            "missing_fields": [],
            "error": None
        }

    extraction_status = (
        extraction_result.get(
            "extraction_status",
            "extraction_error"
        )
    )

    if extraction_status == "extraction_error":
        return {
            "status": "extraction_error",
            "result": None,
            "missing_fields": [],
            "error": (
                "不動産売却の計算条件を"
                "正しく読み取れませんでした"
            )
        }

    arguments = extraction_result.get(
        "arguments",
        {}
    )

    if not isinstance(arguments, dict):
        return {
            "status": "extraction_error",
            "result": None,
            "missing_fields": [],
            "error": (
                "不動産売却の計算条件が"
                "dict形式ではありません"
            )
        }

    try:
        normalized_arguments = (
            normalize_real_estate_sale_arguments(
                arguments
            )
        )

    except Exception as normalize_error:
        print(
            "不動産売却条件の正規化エラー: "
            f"{type(normalize_error).__name__}: "
            f"{normalize_error}"
        )

        return {
            "status": "extraction_error",
            "result": None,
            "missing_fields": [],
            "error": str(
                normalize_error
            )
        }

    try:
        print(
            f"🏠 計算不足項目: "
            f"{missing_fields}"
        )
        missing_fields = (
            get_real_estate_sale_missing_fields(
                normalized_arguments
            )
        )

    except Exception as missing_check_error:
        print(
            "不動産売却の不足項目判定エラー: "
            f"{type(missing_check_error).__name__}: "
            f"{missing_check_error}"
        )

        return {
            "status": "calculation_error",
            "result": None,
            "missing_fields": [],
            "error": str(
                missing_check_error
            )
        }

    if missing_fields:
        return {
            "status": "missing_fields",
            "result": None,
            "missing_fields":
                missing_fields,
            "error": None
        }
    
    print(
    f"🏠 不動産計算実行条件: "
    f"{calculation_arguments}"
)
    # calculate_real_estate_sale()に渡す値だけに限定
    calculation_arguments = {
        key: value
        for key, value
        in normalized_arguments.items()
        if (
            key
            in REAL_ESTATE_SALE_ALLOWED_FIELDS
            and value is not None
        )
    }

    try:
        calculation_result = (
            calculate_real_estate_sale(
                **calculation_arguments
            )
        )

    except (
        ValueError,
        TypeError,
        ArithmeticError
    ) as calculation_error:
        print(
            "不動産売却計算エラー: "
            f"{type(calculation_error).__name__}: "
            f"{calculation_error}"
        )

        return {
            "status": "calculation_error",
            "result": None,
            "missing_fields": [],
            "error": str(
                calculation_error
            )
        }

    except Exception as unexpected_error:
        error_text = (
                f"{type(unexpected_error).__name__}: "
                f"{unexpected_error}"
            )
        print(
                f"🚨 不動産計算予期しないエラー: "
                f"{error_text}"
            )

        return {
            "status": "calculation_error",
            "result": None,
            "missing_fields": [],
            "error": error_text
        }

    if not isinstance(
        calculation_result,
        dict
    ):
        return {
            "status": "calculation_error",
            "result": None,
            "missing_fields": [],
            "error": (
                "不動産売却計算の結果が"
                "dict形式ではありません"
            )
        }

    return {
        "status": "success",
        "tool": "real_estate_sale",
        "result": calculation_result,
        "missing_fields": [],
        "error": None
    }

def build_real_estate_calculation_context(
    execution_result: dict
) -> str:
    """
    不動産売却計算の実行結果から、
    最終回答用のプロンプトブロックを作成する。

    status:
        not_applicable
        missing_fields
        extraction_error
        calculation_error
        success

    計算対象外の場合は空文字を返すため、
    通常会話のプロンプトには何も追加されない。
    """
    status = execution_result.get(
        "status",
        "not_applicable"
    )

    # 通常会話では何も追加しない
    if status == "not_applicable":
        return ""

    # 必須条件が不足している場合
    if status == "missing_fields":
        missing_fields = execution_result.get(
            "missing_fields",
            []
        )

        missing_labels = [
            REAL_ESTATE_FIELD_LABELS.get(
                field,
                field
            )
            for field in missing_fields
        ]

        if missing_labels:
            missing_text = "\n".join(
                f"・{label}"
                for label in missing_labels
            )
        else:
            missing_text = (
                "・計算に必要な条件"
            )

        return f"""
        【Python不動産売却計算】

        計算に必要な条件が不足しています。

        【不足項目】
        {missing_text}

        【回答ルール】
        ・不足している項目だけを、ユーザーへ簡潔に確認してください。
        ・ユーザーが明示していない数値や日付を推測してはいけません。
        ・一般的な金額や税率を、ユーザーの条件として補完してはいけません。
        ・条件が揃っていない状態で概算結果を作ってはいけません。
        ・すでに提示されている条件を再度質問してはいけません。
        """.strip()

    # Geminiによるパラメータ抽出に失敗した場合
    if status == "extraction_error":
        return """
        【Python不動産売却計算】

        ユーザーの入力条件を正しく構造化できなかったため、
        今回はPython計算を実行していません。

        【回答ルール】
        ・推測による計算は行わないでください。
        ・ユーザーへ、計算条件を整理して入力してもらうよう案内してください。
        ・一度にすべての条件を求めず、今回の会話で不足している主要条件だけを確認してください。
        ・基本的な確認項目は、売却額、売却者が個人か法人か、取得日、売却日です。
        ・取得費、ローン残債、売却費用などがすでに提示されている場合は、再入力を求めないでください。
        """.strip()

    # Python関数内でバリデーションエラー等が発生した場合
    if status == "calculation_error":
        error_message = str(
            execution_result.get(
                "error",
                "計算条件に問題があります"
            )
            or "計算条件に問題があります"
        )

        return f"""
        【Python不動産売却計算エラー】

        Python計算を実行しましたが、
        入力条件に問題があるため結果を確定できませんでした。

        【エラー内容】
        {error_message}

        【回答ルール】
        ・エラー内容を、ユーザー向けに分かりやすく説明してください。
        ・修正が必要な項目だけを確認してください。
        ・ユーザーが明示していない数値や日付を推測してはいけません。
        ・エラーが解消されるまで独自の概算結果を作ってはいけません。
        ・Pythonの内部処理やプログラムコードの説明は不要です。
        """.strip()

    # 想定外の状態では計算結果を使用しない
    if status != "success":
        return """
        【Python不動産売却計算】

        計算状態を確認できなかったため、
        今回は計算結果を使用できません。

        【回答ルール】
        ・独自に再計算してはいけません。
        ・ユーザーへ、条件を確認できなかったことを簡潔に伝えてください。
        """.strip()

    # 計算成功時
    result = execution_result.get(
        "result"
    )

    if not isinstance(result, dict):
        return """
        【Python不動産売却計算エラー】

        Python計算の結果を取得できませんでした。

        【回答ルール】
        ・独自に再計算してはいけません。
        ・計算結果を取得できなかったことだけを簡潔に伝えてください。
        ・存在しない数値を作ってはいけません。
        """.strip()

    result_json = json.dumps(
        result,
        ensure_ascii=False,
        indent=2
    )

    estimated_tax = result.get(
        "estimated_tax"
    )

    cash_after_tax = result.get(
        "cash_after_tax"
    )

    owner_type = result.get(
        "owner_type"
    )

    tax_status = result.get(
        "tax_calculation_status"
    )

    # 法人で税額が計算されていない場合など
    if (
        estimated_tax is None
        or cash_after_tax is None
    ):
        tax_note = """
        ・税額が計算されていない場合、税引後手残りを独自に作ってはいけません。
        ・その場合は、税引前手残りを主要結果として示してください。
        ・法人の実効税率が未指定の場合は、会社全体の所得状況などにより税額が変わるため、今回の計算には含めていないと説明してください。
        """.strip()
    else:
        tax_note = """
        ・最初に税引後の現金手残りを示してください。
        ・次に税引前手残り、課税譲渡所得、概算税額を示してください。
        """.strip()

    # 個人の場合の保有期間表示ルール
    if owner_type == "individual":
        holding_note = """
        ・holding_typeがlong_termの場合は「長期譲渡所得」と表示してください。
        ・holding_typeがshort_termの場合は「短期譲渡所得」と表示してください。
        ・適用税率は計算結果に記録されたtax_rateを使用してください。
        """.strip()
    else:
        holding_note = """
        ・法人には個人の長期譲渡所得、短期譲渡所得という表現を使用しないでください。
        """.strip()

    return f"""
    【Python不動産売却計算結果】

    以下はPythonで計算済みの確定出力です。

    {result_json}

    【計算結果の説明ルール】
    ・上記の数値を最優先してください。
    ・数値を変更してはいけません。
    ・独自に再計算して、別の結果を作ってはいけません。
    ・結果に存在しない数値を推測してはいけません。
    ・ユーザーが詳細を求めていない場合は、主要結果だけを簡潔に説明してください。
    ・ユーザーが詳細、内訳、計算式を求めた場合のみ、計算の構造を詳しく説明してください。
    ・取得費とローン残債を混同してはいけません。
    ・課税対象となる譲渡所得と、実際の現金手残りを混同してはいけません。
    ・ローン残債は現金手残りには影響しますが、通常の譲渡所得の取得費ではありません。
    ・特別控除は、計算結果のspecial_deductionに記録された金額だけを使用してください。
    ・ユーザーが明示していない特例を追加適用してはいけません。
    ・金額は円単位の整数として受け取り、回答では読みやすいように円または万円で表示してください。
    ・万円表示へ直す場合も、元の計算結果と一致することを確認してください。
    ・最後に、この結果は入力条件に基づく概算であり、申告税額を確定するものではないことを短く伝えてください。

    【税額と手残りの表示ルール】
    {tax_note}

    【所有者区分の表示ルール】
    {holding_note}

    【内部確認情報】
    owner_type: {owner_type}
    tax_calculation_status: {tax_status}
    """.strip()


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
current_response_length = "普通"
current_dialect = "標準語"
current_user_instruction = ""
current_ai_avatar = "🧠"
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
    if fact.startswith("会話長さ:"):
        current_response_length = (
            fact.replace(
                "会話長さ:",
                ""
            ).strip()
        )

    if fact.startswith("方言:"):
        current_dialect = (
            fact.replace(
                "方言:",
                ""
            ).strip()
        )

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
            st.error("データベースへの接続に失敗しました。電波環境の良い場所で、ページを再読み込み（リフレッシュ）してください。")
            db_available = False
            all_messages = []
        else:
            db_available = True

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

                        # メッセージIDの自動生成
                        import uuid
                        current_msg_id = f"msg_{uuid.uuid4().hex[:8]}"

                        if not save_message("user", user_input, current_msg_id):
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

                        # 会話用直近会話履歴作成
                        recent_history_str = (
                            "\n".join(recent_history_lines)
                            if recent_history_lines
                            else "直近の会話履歴なし"
                        )
                        # 会話種別＆検索判定用の直近会話履歴作成
                        previous_messages = recent_messages[:-1]

                        router_history_lines = []

                        for m in previous_messages[-2:]:
                            role_name = (
                                display_user_name
                                if m.get("role") == "user"
                                else current_concierge_name
                            )

                            router_history_lines.append(
                                f"{role_name}: {m.get('content', '')}"
                            )

                        recent_history_for_router = (
                            "\n".join(router_history_lines)
                            if router_history_lines
                            else "直近の会話履歴なし"
                        )

                        router_start_time = time.time()

                        if is_micro_chat(user_input):

                            response_mode = "short_chat"
                            route_source = "micro_chat"
                            need_search = False
                            route_confidence = 1.0
                            search_judge_in_t = 0
                            search_judge_out_t = 0
                            search_judge_cost = 0

                        else:
                            (
                                need_search,
                                response_mode,
                                route_confidence,
                                search_judge_in_t,
                                search_judge_out_t,
                                search_judge_cost
                            ) = classify_search_and_response_mode(
                                user_input=user_input,
                                recent_history_str=recent_history_for_router,
                            )
                            route_source = "llm_router"

                        router_elapsed = time.time() - router_start_time

                        # ==========================================
                        # 独立したPython計算ツール判定
                        # ==========================================

                        tool_router_elapsed = 0.0
                        tool_route_confidence = 0.0
                        tool_router_in_t = 0
                        tool_router_out_t = 0
                        tool_router_cost = 0.0

                        pending_tool = (
                            "real_estate_sale"
                            if st.session_state.get(
                                "real_estate_calculation_pending",
                                False
                            )
                            else "none"
                        )

                        should_run_tool_router = (
                            pending_tool != "none"
                            or response_mode in {
                                "analysis",
                                "factual",
                                "default"
                            }
                        )

                        if should_run_tool_router:
                            tool_router_start_time = (
                                time.time()
                            )

                            (
                                calculation_tool,
                                tool_route_confidence,
                                tool_router_in_t,
                                tool_router_out_t,
                                tool_router_cost
                            ) = classify_calculation_tool(
                                user_input=user_input,
                                recent_history_str=
                                    recent_history_for_router,
                                pending_tool=pending_tool
                            )

                            tool_router_elapsed = (
                                time.time()
                                - tool_router_start_time
                            )

                        else:
                            calculation_tool = "none"
                        
                        if should_run_tool_router:
                            save_system_audit_log(
                                user_id=CURRENT_USER_ID,
                                plan_type=current_plan_type,
                                event_type=(
                                    "CALCULATION_TOOL_ROUTER"
                                ),
                                processing_time=(
                                    tool_router_elapsed
                                ),
                                in_t=(
                                    tool_router_in_t
                                ),
                                out_t=(
                                    tool_router_out_t
                                ),
                                api_cost=(
                                    tool_router_cost
                                ),
                                details=(
                                    f"ツール: {calculation_tool}"
                                    f" | 継続中: {pending_tool}"
                                    f" | 信頼度: "
                                    f"{tool_route_confidence:.2f}"
                                ),
                                message_id=str(
                                    current_msg_id
                                )
                            )

                            if (
                                tool_router_in_t > 0
                                or tool_router_out_t > 0
                            ):
                                add_permanent_tokens(
                                    CURRENT_USER_ID,
                                    "calculation_tool_router",
                                    tool_router_in_t,
                                    tool_router_out_t
                                )

                        save_system_audit_log(
                            user_id=CURRENT_USER_ID,
                            plan_type=current_plan_type,
                            event_type="RESPONSE_ROUTER",
                            processing_time=router_elapsed,
                            in_t=search_judge_in_t,
                            out_t=search_judge_out_t,
                            api_cost=search_judge_cost,
                            details=(
                                f"検索要否: "
                                f"{'YES' if need_search else 'NO'}"
                                f" | 回答モード: {response_mode}"
                                f" | ルート: {route_source}"
                                f" | 信頼度: {route_confidence:.2f}"
                            ),
                            message_id=str(current_msg_id)
                        )

                        if need_search:
                            search_query = f"""
                            直近の会話を踏まえて、最新ユーザー発言に必要な情報を検索してください。

                            【直近の会話】
                            {recent_history_str}

                            【最新ユーザー発言】
                            {user_input}
                            """
                            search_result = google_search(
                                search_query
                            )
                            # st.code(search_result[:500])

                            try:
                                supabase.table("search_logs").insert({
                                    "user_id": CURRENT_USER_ID,
                                    "search_query": user_input
                                    }).execute()
                            except Exception as e:
                                print(f"検索ログ取得エラー {uid}: {e}")

                        else:
                            search_result = "なし"
                        
                        # ==========================================
                        # Python不動産売却計算
                        # ==========================================

                        calculation_extraction_result = {
                            "should_calculate": False,
                            "arguments": {},
                            "extraction_status":
                                "not_applicable",
                            "in_tokens": 0,
                            "out_tokens": 0,
                            "cost": 0.0
                        }

                        calculation_execution_result = {
                            "status": "not_applicable",
                            "result": None,
                            "missing_fields": [],
                            "error": None
                        }

                        calculation_pending = bool(
                            st.session_state.get(
                                "real_estate_calculation_pending",
                                False
                            )
                        )

                        is_calculation_candidate = (
                            calculation_tool
                            == "real_estate_sale"
                        )

                        if is_calculation_candidate:
                            calculation_start_time = (
                                time.time()
                            )

                            calculation_extraction_result = (
                                extract_real_estate_sale_parameters(
                                    user_input=user_input,
                                    recent_history=
                                        recent_history_str
                                )
                            )

                            extraction_elapsed = (
                                time.time()
                                - calculation_start_time
                            )

                            # 前回までに確認できている条件
                            previous_arguments = dict(
                                st.session_state.get(
                                    "real_estate_calculation_arguments",
                                    {}
                                )
                                or {}
                            )

                            # 今回新しく抽出された条件
                            current_arguments = dict(
                                calculation_extraction_result.get(
                                    "arguments",
                                    {}
                                )
                                or {}
                            )

                            # 前回条件を今回条件で上書きする
                            # 同じ項目がある場合は最新発言を優先
                            merged_arguments = {
                                **previous_arguments,
                                **current_arguments
                            }

                            calculation_extraction_result[
                                "arguments"
                            ] = merged_arguments

                            calculation_execution_result = (
                                execute_real_estate_sale_calculation(
                                    calculation_extraction_result
                                )
                            )

                            calculation_elapsed = (
                                time.time()
                                - calculation_start_time
                            )

                            calculation_status = (
                                calculation_execution_result.get(
                                    "status",
                                    "calculation_error"
                                )
                            )

                            if calculation_status == "missing_fields":
                                # 条件不足の場合は、
                                # 確認済み条件を次の会話まで保持
                                try:
                                    saved_arguments = (
                                        normalize_real_estate_sale_arguments(
                                            merged_arguments
                                        )
                                    )
                                except Exception:
                                    saved_arguments = (
                                        merged_arguments
                                    )

                                st.session_state[
                                    "real_estate_calculation_arguments"
                                ] = saved_arguments

                                st.session_state[
                                    "real_estate_calculation_pending"
                                ] = True

                                missing_fields = (
                                    calculation_execution_result.get(
                                        "missing_fields",
                                        []
                                    )
                                )

                                save_system_audit_log(
                                    user_id=CURRENT_USER_ID,
                                    plan_type=current_plan_type,
                                    event_type=(
                                        "CALCULATION_MISSING_FIELDS"
                                    ),
                                    processing_time=0.0,
                                    in_t=0,
                                    out_t=0,
                                    api_cost=0.0,
                                    details=(
                                        "tool=real_estate_sale"
                                        " | missing="
                                        + ",".join(
                                            missing_fields
                                        )
                                    ),
                                    message_id=str(
                                        current_msg_id
                                    )
                                )

                            elif calculation_status == "success":
                                # 計算完了後は継続状態を解除
                                st.session_state[
                                    "real_estate_calculation_arguments"
                                ] = {}

                                st.session_state[
                                    "real_estate_calculation_pending"
                                ] = False

                                result = (
                                    calculation_execution_result.get(
                                        "result",
                                        {}
                                    )
                                )

                                save_system_audit_log(
                                    user_id=CURRENT_USER_ID,
                                    plan_type=current_plan_type,
                                    event_type=(
                                        "CALCULATION_SUCCESS"
                                    ),
                                    processing_time=0.0,
                                    in_t=0,
                                    out_t=0,
                                    api_cost=0.0,
                                    details=(
                                        "tool=real_estate_sale"
                                        f" | owner={result.get('owner_type')}"
                                        f" | holding={result.get('holding_type')}"
                                        f" | taxable_gain={result.get('taxable_gain')}"
                                        f" | tax={result.get('estimated_tax')}"
                                        f" | cash_after_tax={result.get('cash_after_tax')}"
                                    ),
                                    message_id=str(
                                        current_msg_id
                                    )
                                )

                            elif calculation_status == (
                                "calculation_error"
                            ):
                                # 入力値の修正を受け付けるため、
                                # 現在の条件を保持
                                try:
                                    saved_arguments = (
                                        normalize_real_estate_sale_arguments(
                                            merged_arguments
                                        )
                                    )
                                except Exception:
                                    saved_arguments = (
                                        merged_arguments
                                    )

                                st.session_state[
                                    "real_estate_calculation_arguments"
                                ] = saved_arguments

                                st.session_state[
                                    "real_estate_calculation_pending"
                                ] = True

                                save_system_audit_log(
                                    user_id=CURRENT_USER_ID,
                                    plan_type=current_plan_type,
                                    event_type=(
                                        "CALCULATION_ERROR"
                                    ),
                                    processing_time=0.0,
                                    in_t=0,
                                    out_t=0,
                                    api_cost=0.0,
                                    details=(
                                        "tool=real_estate_sale"
                                        f" | error={calculation_execution_result.get('error', '')}"
                                    )[:500],
                                    message_id=str(
                                        current_msg_id
                                    )
                                )

                            elif calculation_status == (
                                "extraction_error"
                            ):
                                # 抽出失敗時は以前の条件を消さず、
                                # 再入力を受け付ける
                                st.session_state[
                                    "real_estate_calculation_pending"
                                ] = True

                            else:
                                st.session_state[
                                    "real_estate_calculation_arguments"
                                ] = {}

                                st.session_state[
                                    "real_estate_calculation_pending"
                                ] = False

                            extraction_in_tokens = int(
                                calculation_extraction_result.get(
                                    "in_tokens",
                                    0
                                )
                                or 0
                            )

                            extraction_out_tokens = int(
                                calculation_extraction_result.get(
                                    "out_tokens",
                                    0
                                )
                                or 0
                            )

                            extraction_cost = float(
                                calculation_extraction_result.get(
                                    "cost",
                                    0.0
                                )
                                or 0.0
                            )

                            save_system_audit_log(
                                user_id=CURRENT_USER_ID,
                                plan_type=current_plan_type,
                                event_type=(
                                    "CALCULATION_EXTRACTION"
                                ),
                                processing_time=
                                    extraction_elapsed,
                                in_t=
                                    extraction_in_tokens,
                                out_t=
                                    extraction_out_tokens,
                                api_cost=
                                    extraction_cost,
                                details=(
                                    "tool=real_estate_sale"
                                ),
                                message_id=str(
                                    current_msg_id
                                )
                            )

                            if (
                                extraction_in_tokens > 0
                                or extraction_out_tokens > 0
                            ):
                                add_permanent_tokens(
                                    CURRENT_USER_ID,
                                    "real_estate_extraction",
                                    extraction_in_tokens,
                                    extraction_out_tokens
                                )

                            # save_system_audit_log(
                            #     user_id=CURRENT_USER_ID,
                            #     plan_type=current_plan_type,
                            #     event_type=(
                            #         "REAL_ESTATE_CALCULATION"
                            #     ),
                            #     processing_time=(
                            #         calculation_elapsed
                            #     ),
                            #     in_t=extraction_in_tokens,
                            #     out_t=extraction_out_tokens,
                            #     api_cost=extraction_cost,
                            #     details=(
                            #         "不動産売却計算"
                            #         " | 状態: "
                            #         f"{calculation_status}"
                            #     ),
                            #     message_id=str(
                            #         current_msg_id
                            #     )
                            # )

                        calculation_prompt_block = (
                            build_real_estate_calculation_context(
                                calculation_execution_result
                            )
                        )

                        selected_mode_prompt = MODE_PROMPTS.get(
                            response_mode,
                            MODE_PROMPTS["default"]
                        )

                        short_history_lines = recent_history_lines[-2:]
                        short_history_str = "\n".join(
                            short_history_lines
                        )
                        if response_mode == "micro_chat":
                            use_recent_history = short_history_str
                        else:
                            use_recent_history = recent_history_str

                        summary_memories = get_memories(source="summary")

                        summary_memory_context = "\n".join(
                            [m["fact"] for m in summary_memories]
                        ) if summary_memories else "なし"

                        if is_micro_chat(user_input):
                            # 超軽量ルート
                            system_instruction = f"""
                            あなたの名前は「{current_concierge_name}」です。
                            対話相手の名前は「{display_user_name}」です。
                            一人称は「{current_first_person}」を使用してください。

                            【現在の人格】
                            {STYLE_PRESETS.get(current_style_preset, "")}
                            【現在の応答方針】
                            {current_user_instruction}

                            【直近の会話履歴】
                            {use_recent_history}

                            {selected_mode_prompt}
                            """

                        else:
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
                            2. 現在の回答モード（analysis / support / conversation / factual / short_chat）の目的を優先する
                            3. 現在の人格と応答方針を守る
                            4. 記憶されている事実を正確に使用する
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
                            ・定期的に行う活動や継続的に楽しんでいる活動は趣味として扱って構いません。
                            ・「特定の作品名、特定の番組名、特定の映画タイトルは趣味ではなく「好きな作品」として扱ってください。
                            ・仕事、業務、開発プロジェクト、勉強は、本人が趣味と明言していない限り趣味として扱ってはいけません。
                            ・ユーザーが明示的に話した内容のみを事実として扱ってください。
                            ・推測、解釈、補完によって導いた内容を事実として扱ったり、記憶の根拠として使用してはいけません。
                            ・記憶にある事実と、現在よく話題にしている内容を混同しないでください。
                            ・記憶内に根拠がある場合は、その事実を優先して回答してください。
                            ・記憶内に根拠がない情報は推測や創作で補わず、「まだ覚えていない」と正直に答えてください。
                            ・過去の会話を参照する際は、「ユーザーが実際に話した内容」と「AIが推測した内容」を混同してはいけません。
                            ・記憶は必要な部分だけ自然に利用し、無関係なプロフィール情報をまとめて列挙しないでください。
                            ・会話の中心はユーザーとし、ユーザーの話題や考えを深掘りすることを優先してください。
                            ・AI自身の趣味、好み、経験、思い出、生活習慣を実在するものとして創作しないでください。
                            ・AI自身の好みや体験について質問された場合は、実体験として断言せず、人格に沿った仮定や会話上の表現として回答してください。

                            【直近の会話履歴・古い順】
                            {use_recent_history}

                            【現在の発言に関連する過去の会話】
                            {past_logs_str}
                            【検索結果】
                            {search_result}

                            {calculation_prompt_block}

                            【履歴の利用ルール】
                            ・直近履歴は現在の会話の流れや文脈を理解するために使用してください。
                            ・関連過去ログは補助情報として扱い、過去のAI発言や推測内容を事実の根拠にしてはいけません。
                            ・ユーザーが実際に話した内容と、AIが推測した内容を混同してはいけません。
                            ・直近履歴と関連過去ログが競合する場合は、時系列が明確な直近履歴を優先してください。
                            ・最新のユーザー発言への反応を中心にし、記憶や過去ログを不自然に大量列挙しないでください。

                            【会話の自然さルール】
                            ・ユーザーの発言内容をそのまま言い換えて返すことを避けてください。
                            ・回答の冒頭で「○○だったんだね」「○○なんだね」「○○してきたんだね」のような単純な復唱を毎回行わないでください。
                            ・まず感想、驚き、共感、質問、ツッコミ、考察のいずれかから会話を始めてください。
                            ・復唱は本当に重要な確認が必要な場合のみ使用してください。
                            ・同じ言い回しが続かないよう、会話の始め方に変化を持たせてください。
                            ・共感や労いは大切ですが、毎回同じ励ましや休息提案だけで終わらせないでください。
                            ・必要に応じて話題を広げたり、軽い雑談や考察を加えてください。
                            ・「休んでね」「無理しないでね」などの表現を短い間隔で繰り返さないでください。
                            ・質問は有効ですが、毎回質問で返さないでください。
                            ・感想や考察だけで会話を続けることも許容してください。
                            ・インタビューのように質問が連続しないようにしてください。
                            ・人格上のロールプレイ表現は構いませんが、実際に行動したかのような体験や現在進行中の行動を事実として語ってはいけません。
                            ・「お持ちします」「ご案内します」などの表現は会話上の演出として使用して構いませんが、実際に物理的な行動が行われた事実として扱ってはいけません。
                            ・AI自身が飲食、移動、作業、睡眠、仕事、趣味活動などを実際に行ったかのように語ってはいけません。

                            【質問への対応】
                            ・検索結果が存在する場合は、検索結果を優先して回答してください。
                            ・検索結果と記憶の両方が存在する場合は、検索結果を基にしつつユーザーの過去の会話や好みに合わせて回答してください。
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

                            【時系列と事実の扱い】
                            ・過去ログ内の「今日」「昨日」「明日」は、その発言日時を基準とした相対表現です。現在日時と混同しないでください。
                            ・ユーザーから事実誤認、認識違い、解釈違いの指摘や訂正を受けた場合は、現在の正しい事実まで否定せず、該当する内容だけを自然に訂正してください。
                            ・訂正や謝罪だけで会話を終了せず、可能であれば元の依頼や質問へ戻って回答を続けてください。
                            ・ユーザーが明示していない感情、予定、経験、趣味、事情を決めつけないでください。
                            ・ユーザーが「行ってくる」「寝る」「仕事に行く」など未来の予定を話した場合、その後の会話で実行済みとして扱ってはいけません。
                            ・実行済みであることは、ユーザー本人が明示した場合のみ事実として扱ってください。
                            ・曖昧な発言は、最も都合の良い解釈を決めつけず、会話文脈と現在時刻の両方を考慮してください。
                            ・過去ログ内の未来予定を参照する場合は、現在日時との整合性を確認してください。
                            ・予定日当日を過ぎている場合は、出発前提で話さず、結果や当日の出来事として扱うか、未確認の場合は状況を確認してください。

                            【専門作業の制限】
                            プログラムのコード記述、画像生成、長文の執筆や翻訳を依頼された場合は実行せず、現在の人格を保ちながら丁寧に断ってください。

                            【出力ルール】
                            ・現在の人格と応答方針を回答全体で統一する
                            ・最新のユーザー発言への反応から回答する
                            ・同じ導入文や気遣いを繰り返さない
                            ・記憶にない事実を作らない
                            ・不要な個人情報や記憶をまとめて披露しない
                            ・情報量が多い場合は、見出し、箇条書き、適切な改行を使い読みやすく整理する
                            ・太字装飾記号は使用しない

                            {selected_mode_prompt}
                            """

                        recent_messages = all_messages[-MAX_CONTEXT_MESSAGES:]
                    
                        try:
                            # Geminiへの指示（プロンプト）の流し込み口
                            json_instruction = f"""
                            以下のユーザー発言に回答してください。

                            同時に、ユーザーが今回の発言で新しく指定した
                            口調、話し方、回答の長さ、回答形式、禁止事項などの
                            継続的な要望があれば抽出してください。

                            必ず次のJSONオブジェクトだけを返してください。

                            {{
                                "reply": "ユーザーへの回答",
                                "new_instruction": "新しく指定された継続的な要望。なければ、なし"
                            }}

                            ルール:
                            ・replyには、ユーザーへの自然な回答を入れてください。
                            ・new_instructionには、今回新しく示された継続的な話し方の要望だけを入れてください。
                            ・単なる質問、雑談、事実、感想はnew_instructionへ入れないでください。
                            ・「今回だけ」「この質問だけ」など一時的な指定はnew_instructionへ保存しないでください。
                            ユーザー自身の日常会話や特定の作業・特定の執筆・特定のタスクにのみ適用される条件は保存しない。今後の会話全体に適用してほしい恒久的な要望のみ保存する。
                            ・新しい要望がない場合は、new_instructionを必ず「なし」にしてください。
                            ・JSONの外に説明文を出さないでください。
                            ・```jsonなどの囲み記号を付けないでください。

                            ユーザー発言:
                            {user_input}
                            """

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
                            
                            save_message("assistant", ai_reply, current_msg_id)
                            st.session_state.conversation_count += 1
                            add_permanent_tokens(CURRENT_USER_ID, "chat_count", 1, 0)

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
        with st.form("unified_settings_form"):
            selected_color = st.selectbox("カラーテーマ（背景＆メッセージ枠）", list(THEMES.keys()), index=list(THEMES.keys()).index(current_theme_color) if current_theme_color in THEMES else 0)
            # 上部設定保存ボタン
            top_save = st.form_submit_button(
                "設定を保存",
                use_container_width=True
            )
            st.divider()

            st.markdown("##### 👤 基本設定")
            honorific_options = ["さん", "様", "君", "ちゃん", "（呼び捨て/なし）"]
            default_honorific_idx = honorific_options.index(current_user_honorific) if current_user_honorific in honorific_options else 0
            preset_keys = list(STYLE_PRESETS.keys())
            default_preset_idx = preset_keys.index(current_style_preset) if current_style_preset in preset_keys else 0
            default_fp_idx = FIRST_PERSON_PRESETS.index(current_first_person) if current_first_person in FIRST_PERSON_PRESETS else 0

            new_concierge_name = st.text_input("AIの名前", value=current_concierge_name)
            new_user_name = st.text_input("あなたのお名前 / ニックネーム", value=current_user_name)
            new_user_honorific = st.selectbox("AIからの呼び方（敬称）", honorific_options, index=default_honorific_idx)
            new_first_person = st.selectbox("AIの一人称", FIRST_PERSON_PRESETS, index=default_fp_idx)
            default_length_idx = (
                RESPONSE_LENGTH_PRESETS.index(
                    current_response_length
                )
                if current_response_length
                in RESPONSE_LENGTH_PRESETS
                else 1
            )
            new_response_length = st.selectbox(
                "返事の長さ",
                RESPONSE_LENGTH_PRESETS,
                index=default_length_idx
            )
            default_dialect_idx = (
                DIALECT_PRESETS.index(
                    current_dialect
                )
                if current_dialect
                in DIALECT_PRESETS
                else 0
            )
            new_dialect = st.selectbox(
                "方言",
                DIALECT_PRESETS,
                index=default_dialect_idx
            )
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

            st.markdown("##### 💬 会話設定")
            st.caption(
                "返事の長さや方言を設定できます。"
            )

            # ==========================================
            # 応答方針（旧仕様）
            # 現在はUI非表示
            # DB互換性維持のため内部保持
            # ==========================================
            # st.markdown("##### 📝 AIの話し方")
            # st.caption("あなたが会話の中で伝えた細かいマナーやこだわりは、ここに自動で箇条書きで追加されていきます。")
            # st.caption("また、必要に応じていつでも自分で消去・修正や追加ができます。（例；話は簡潔にして、回答は５行以内にして、など）")
            # st.caption("ただし、１次的な指示では自動で記憶されません。（良い例：今後は〇〇にして、ずっと△△にして、など）")

            # instruction_rules = [
            #     r.strip()
            #     for r in str(current_user_instruction).split("\n")
            #     if r.strip()
            # ]

            # edited_rules = []

            # for idx, rule in enumerate(instruction_rules):

            #     col_rule, col_del = st.columns([9,1])

            #     with col_rule:
            #         rule_text = st.text_input(
            #             f"rule_{idx}",
            #             value=rule,
            #             label_visibility="collapsed"
            #         )

            #     with col_del:
            #         delete_flag = st.checkbox(
            #             "削除",
            #             key=f"delete_rule_{idx}"
            #         )

            #     if not delete_flag and rule_text.strip():
            #         edited_rules.append(
            #             rule_text.strip()
            #         )
            # #st.markdown("---")
            # st.caption("")
            # st.markdown("➕ AIの話し方を追加")
            # new_rule = st.text_input(
            #     "下記に入力して、基本設定を保存すると追加されます。ただし、追加できる話し方は5件までとなります。6件目が追加されると、1件目が押し出されて消えますのでご注意ください。",
            #     key="new_rule_input"
            # )
            # if new_rule.strip():
            #     edited_rules.append(
            #         new_rule.strip()
            #     )
            
            # # 重複削除
            # edited_rules = list(dict.fromkeys(edited_rules))
            # # 最新5件のみ保持
            # edited_rules = edited_rules[-5:]

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
            if st.form_submit_button("設定を保存"):
                with st.spinner("設定を登録しています...しばらくお待ちください"):
                    r1 = save_or_update_user_setting("AIの名前", new_concierge_name)
                    r2 = save_or_update_user_setting("ユーザー名", new_user_name)
                    r3 = save_or_update_user_setting("ユーザー敬称", new_user_honorific)
                    r4 = save_or_update_user_setting("AI一人称", new_first_person)
                    r5 = save_or_update_user_setting("人格", selected_preset)
                    # final_instruction = "\n".join(edited_rules)
                    r6 = save_or_update_user_setting("会話長さ",new_response_length)
                    r7 = save_or_update_user_setting("方言",new_dialect)
                    # r8 = save_or_update_user_setting("応答方針", final_instruction)
                    # r7 = save_or_update_user_setting("AIアバター", ai_avatar_val)
                    # r8 = save_or_update_user_setting("ユーザーアバター", user_avatar_val)
                    r9 = save_or_update_user_setting("絵文字の量", new_emoji_setting)
                    #r10 = save_or_update_user_setting("会員プラン", new_plan)
                    success = (
                        r1 and r2 and r3 and r4 and r5 and r6 and r7 and r9
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
            search_judge_count = 0
            search_judge_total_cost = 0.0
            search_judge_total_in = 0
            search_judge_total_out = 0
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

                    # system_audit_logsから検索コストを集計
                    judge_cost_res = (
                        supabase
                        .table("system_audit_logs")
                        .select("*")
                        .eq("user_id", selected_audit_user)
                        .eq("event_type", "RESPONSE_ROUTER")
                        .execute()
                    )

                    judge_rows = judge_cost_res.data or []

                    search_judge_count = len(judge_rows)

                    search_judge_total_cost = sum(
                        float(row.get("api_cost", 0) or 0)
                        for row in judge_rows
                    )

                    search_judge_total_in = sum(
                        int(row.get("in_tokens", 0) or 0)
                        for row in judge_rows
                    )

                    search_judge_total_out = sum(
                        int(row.get("out_tokens", 0) or 0)
                        for row in judge_rows
                    )
                    # 検索回数を取得
                    search_res = (
                        supabase
                        .table("search_logs")
                        .select("*")
                        .eq("user_id", selected_audit_user)
                        .execute()
                    )
                    search_count = len(
                        search_res.data or []
                    )

                    # python計算データを取得
                    calc_logs = (
                        supabase
                        .table("system_audit_logs")
                        .select("event_type")
                        .eq("user_id", selected_audit_user)
                        .in_(
                            "event_type",
                            [
                                "CALCULATION_SUCCESS",
                                "CALCULATION_MISSING_FIELDS",
                                "CALCULATION_ERROR"
                            ]
                        )
                        .execute()
                    )

                    calc_success = 0
                    calc_missing = 0
                    calc_error = 0

                    for row in (calc_logs.data or []):
                        event = row.get(
                            "event_type",
                            ""
                        )

                        if event == "CALCULATION_SUCCESS":
                            calc_success += 1

                        elif event == (
                            "CALCULATION_MISSING_FIELDS"
                        ):
                            calc_missing += 1

                        elif event == "CALCULATION_ERROR":
                            calc_error += 1

                    calc_total = (
                        calc_success
                        + calc_missing
                        + calc_error
                    )

                    calc_extract_res = (
                        supabase
                        .table("system_audit_logs")
                        .select(
                            "api_cost, in_tokens, out_tokens"
                        )
                        .eq(
                            "user_id",
                            selected_audit_user
                        )
                        .eq(
                            "event_type",
                            "CALCULATION_EXTRACTION"
                        )
                        .execute()
                    )

                    calc_extract_cost = sum(
                        float(
                            x.get(
                                "api_cost",
                                0
                            )
                            or 0
                        )
                        for x in (
                            calc_extract_res.data
                            or []
                        )
                    )

                    calc_extract_in = sum(
                        int(
                            x.get(
                                "in_tokens",
                                0
                            )
                            or 0
                        )
                        for x in (
                            calc_extract_res.data
                            or []
                        )
                    )

                    calc_extract_out = sum(
                        int(
                            x.get(
                                "out_tokens",
                                0
                            )
                            or 0
                        )
                        for x in (
                            calc_extract_res.data
                            or []
                        )
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
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>検索回数：** {search_count} 回</p>"
                    "<br>"
                    "<h5 style='color:#10b981; font-weight:bold;'>💰 【インフラ原価・サーバーコスト】</h5>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>累計消費コスト：</b> {round(total_cost_jpy, 2)} 円</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>・<b>1会話あたりの平均原価：</b> {avg_cost_per_chat} 円/通</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>"
                    f"・<b>検索判定回数：</b> {search_judge_count} 回</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>"
                    f"・<b>検索判定入力：</b> {search_judge_total_in:,} t</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>"
                    f"・<b>検索判定出力：</b> {search_judge_total_out:,} t</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>"
                    f"・<b>検索判定コスト：</b> {search_judge_total_cost:.4f} 円</p>"
                    f"<p style='margin: 6px 0; font-size:14px;'>"
                    f"・<b>不動産計算利用：</b> "
                    f"{calc_total} 回</p>"

                    f"<p style='margin: 6px 0; font-size:14px;'>"
                    f"・<b>計算成功：</b> "
                    f"{calc_success} 回</p>"

                    f"<p style='margin: 6px 0; font-size:14px;'>"
                    f"・<b>条件不足：</b> "
                    f"{calc_missing} 回</p>"

                    f"<p style='margin: 6px 0; font-size:14px;'>"
                    f"・<b>計算エラー：</b> "
                    f"{calc_error} 回</p>"
                    "</div>",
                    unsafe_allow_html=True
                )

            # 🚀 【大開通】 1メッセージの塊（ブロック）の中にすべての内訳を並列露出させる詳細明細タイムライン
            st.markdown("##### ⏱️ このユーザーのタイムライン式システムログ（最新50件）")
            if st.button(
                "📖 システムログを表示",
                key="show_timeline_logs"
            ):
                st.session_state["show_timeline_logs"] = True
            
            try:
                # 1. データベース（system_audit_logs）から直近50件の生データを抽出
                if st.session_state.get(
                    "show_timeline_logs",
                    False
                ):

                    log_res = (
                        supabase
                        .table("system_audit_logs")
                        .select("*")
                        .eq("user_id", selected_audit_user)
                        .order("created_at", desc=True)
                        .limit(50)
                        .execute()
                    )
                
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
                                    "user_message": "",
                                    "ai_message": "",
                                    "chat_time": 0.0, "chat_in": 0, "chat_out": 0,
                                    "sum_time": 0.0, "sum_in": 0, "sum_out": 0,
                                    "judge_time": 0.0, "judge_in": 0, "judge_out": 0, "judge_cost": 0.0, "judge_result": "",
                                    "search_time": 0.0, "search_in": 0, "search_out": 0,
                                    "total_yen": 0.0, "total_time": 0.0,
                                    "calculation_result": ""
                                }
                            
                            action = log.get("action", log.get("event_type", ""))
                            cost = log.get("api_cost") if log.get("api_cost") is not None else 0.0
                            proc_time = log.get("processing_time") if log.get("processing_time") is not None else 0.0
                            in_t = log.get("in_tokens", 0)
                            out_t = log.get("out_tokens", 0)

                            # 各コンポーネントの同じメッセージIDの対応する数値をドッキング
                            if action == "SUMMARY_SUCCESS":
                                merged_logs[msg_id]["sum_time"] = proc_time
                                merged_logs[msg_id]["sum_in"] = in_t
                                merged_logs[msg_id]["sum_out"] = out_t

                            elif action == "RESPONSE_ROUTER":
                                merged_logs[msg_id]["judge_time"] = proc_time
                                merged_logs[msg_id]["judge_in"] = in_t
                                merged_logs[msg_id]["judge_out"] = out_t
                                merged_logs[msg_id]["judge_cost"] = cost
                                merged_logs[msg_id]["judge_result"] = (
                                    log.get("details", "")
                                )
                            
                            elif action == "CALCULATION_SUCCESS":

                                merged_logs[msg_id][
                                    "calculation_result"
                                ] = log.get(
                                    "details",
                                    ""
                                )

                            elif action == (
                                "CALCULATION_MISSING_FIELDS"
                            ):

                                merged_logs[msg_id][
                                    "calculation_result"
                                ] = log.get(
                                    "details",
                                    ""
                                )

                            elif action == "CALCULATION_ERROR":

                                merged_logs[msg_id][
                                    "calculation_result"
                                ] = log.get(
                                    "details",
                                    ""
                                )

                            elif action == "CHAT_SUCCESS":
                                merged_logs[msg_id]["chat_time"] = (
                                    log.get("chat_processing_time", proc_time)
                                    if log.get("chat_processing_time") is not None
                                    else proc_time
                                )

                                merged_logs[msg_id]["chat_in"] = (
                                    log.get("chat_in_tokens", in_t)
                                    if log.get("chat_in_tokens") is not None
                                    else in_t
                                )

                                merged_logs[msg_id]["chat_out"] = (
                                    log.get("chat_out_tokens", out_t)
                                    if log.get("chat_out_tokens") is not None
                                    else out_t
                                )

                                merged_logs[msg_id]["search_time"] = (
                                    log.get("search_processing_time", 0.0)
                                    if log.get("search_processing_time") is not None
                                    else 0.0
                                )

                                merged_logs[msg_id]["search_in"] = (
                                    log.get("search_in_tokens", 0)
                                    if log.get("search_in_tokens") is not None
                                    else 0
                                )

                                merged_logs[msg_id]["search_out"] = (
                                    log.get("search_out_tokens", 0)
                                    if log.get("search_out_tokens") is not None
                                    else 0
                                )

                            # 1会話単位の、全体の総実費合計コストと最大待機秒数の集計
                            merged_logs[msg_id]["total_yen"] += cost
                            merged_logs[msg_id]["total_time"] = max(merged_logs[msg_id]["total_time"], log.get("total_processing_time", proc_time) if log.get("total_processing_time") is not None else proc_time)
                        
                        # アコーディオンtyusu出力
                        for k, item in merged_logs.items():
                                
                            msg_res = (
                                supabase
                                .table("messages")
                                .select("*")
                                .eq("user_id", selected_audit_user)
                                .eq("message_id", item["id"])
                                .order("created_at", desc=False)
                                .execute()
                            )

                            user_msg = ""
                            ai_msg = ""

                            for row in (msg_res.data or []):
                                if row.get("role") == "user":
                                    user_msg = row.get("content", "")
                                elif row.get("role") == "assistant":
                                    ai_msg = row.get("content", "")
                            
                            c_plan = item["user_plan"]
                            t_yen = item["total_yen"]
                            t_time = item["total_time"]

                            with st.expander(f"🟢 [{item['time']}] {c_plan} ➔ 💰 総原価: {t_yen:.4f} 円 || ⏱️ 総処理: {t_time:.2f} 秒"):
                                st.markdown(f"""

                                | ⚙️ 処理内訳コンポーネント | ⏱️ 処理時間 (秒) | 🪙 入力(In)トークン | 🪙 出力(Out)トークン |
                                | :--- | :---: | :---: | :---: |
                                | 🔎 **Google検索の要否判定** | {item['judge_time']:.2f} 秒 | {item['judge_in']} t | {item['judge_out']} t |
                                | 💬 **メインチャット対話返答** | {item['chat_time']:.2f} 秒 | {item['chat_in']} t | {item['chat_out']} t |
                                | 🧠 **裏スレッド記憶の要約** | {item['sum_time']:.2f} 秒 | {item['sum_in']} t | {item['sum_out']} t |
                                | 🔍 **過去会話・意味検索** | {item['search_time']:.2f} 秒 | {item['search_in']} t | {item['search_out']} t |
                                    
                                🔎 **【検索判定結果】** {item['judge_result']}

                                👑 **【この1メッセージに対する総実費原価】** ¥ {t_yen:.4f} 円  ||  **【ユーザー総待機ラグ】** {t_time:.2f} 秒
                                """)
                                st.markdown("---")

                                st.markdown("##### 👤 ユーザー発言")
                                st.info(user_msg)
                                if item.get(
                                    "calculation_result"
                                ):
                                    # st.warning(
                                    #     "🏠 不動産計算結果\n\n"
                                    #     + item[
                                    #         "calculation_result"
                                    #     ]
                                    # )
                                    st.code(
                                        item[
                                        "calculation_result"
                                        ]
                                    )

                                st.markdown("##### 🧠 AI返答")
                                st.success(ai_msg)
                    else: 
                        st.caption("このユーザーのシステムログはまだデータベースに記録されていません。")
            except Exception as log_err:
                st.error(
                    f"ユーザーログの取得に失敗しました: {log_err}"
                )

        # 📈 画面②：アプリ全体の統計アナリティクス画面
        elif admin_mode == "📈 全体アクティビティ・統計アナリティクス":
            st.subheader("📈 アプリ全体アクティビティ ＆ 機能統計（匿名集計）")
            with st.spinner("システムログからプラン別データを高度に集計中..."):
                try:
                    audit_res = supabase.table("system_audit_logs").select("user_id, user_plan, event_type, total_yen_cost, created_at").execute()
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
        # st.subheader("🔍 テスター全会話リアルタイム監視掲示板")
        # st.caption("※クローズドテストに参加している一般テスターとAIコンシェルジュの具体的な対話内容を、日付・時間スタンプ付きで遠隔監査するための専用画面です。本番リリース時は、このタブのブロック（数十行）を削除するだけで、一般ユーザーに対して完全に非表示にすることが可能です。")
                    
        tester_rows = []
        try:
            memories_res = (
                supabase
                .table("user_memories_tester")
                .select("user_id, fact")
                .execute()
            )

            users = {}
            USER_PROFILE = {
                "m.kawamura00": "40代女性",
                "yasusan_cw": "40代男性",
                "shigenoi": "40代女性",
                "kham1014": "40代男性",
                "pom_neko": "20代女性",
                "kumii_5451": "50代女性",
                "kotobayomi": "40代女性",
                "reirou": "30代男性",
                "yoimachigusa": "30代女性",
                "yong3127": "30代女性",
            }
            user_res = (
                supabase
                .table("user_token_stats")
                .select("user_id")
                .execute()
            )
            # msg_users_res = (
            #     supabase
            #     .table("messages")
            #     .select("user_id")
            #     .execute()
            # )

            all_user_ids = sorted(
                list(
                    set(
                        row["user_id"]
                        for row in users_res.data
                        if row.get("user_id")
                    )
                )
            )

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
            
            EXCLUDED_USERS = {
                CURRENT_USER_ID,
                USUAL_USER_ID
            }
            for uid in all_user_ids:
                if uid in EXCLUDED_USERS:
                    continue
                if uid not in users:
                    users[uid] = {
                        "ユーザーID": uid,
                        "AI名称": "未設定",
                        "ユーザー名": "未設定",
                        "呼び方": "",
                        "一人称": "",
                        "絵文字": "",
                        "人格": "",
                        "テーマ": ""
                    }

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
                    .select("created_at, role")
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
                search_res = (
                    supabase
                    .table("search_logs")
                    .select("*")
                    .eq("user_id", uid)
                    .execute()
                )

                search_count = len(
                    search_res.data or []
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
                        f"{active_days}/4",
                    "検索回数":
                        f"{search_count}回"
                })

            except Exception as e:
                # print(uid, e)
                st.error(f"{uid}: {e}")

        st.markdown("### 📈 テスター利用状況一覧")

        st.dataframe(
            pd.DataFrame(usage_rows),
            use_container_width=True,
            hide_index=True
        )
        total_all_cost = sum(
            float(row["累計コスト"].replace("円", ""))
            for row in usage_rows
        )

        total_all_chats = sum(
            int(row["総会話数"].replace("回", ""))
            for row in usage_rows
        )

        overall_avg_cost = (
            total_all_cost / total_all_chats
            if total_all_chats > 0
            else 0
        )

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "全テスター累計コスト",
            f"{total_all_cost:.2f}円"
        )

        col2.metric(
            "全テスター総会話数",
            f"{total_all_chats}回"
        )

        col3.metric(
            "全体平均・1会話コスト",
            f"{overall_avg_cost:.3f}円"
        )

        # ──────────────────────────────────────────────────────────────────
        # 📊 【確定最終製品版】 テスター管理・分析の部屋（インデント完全修正型）
        # ──────────────────────────────────────────────────────────────────
        all_tester_logs = None
        try:
            # 1. データベースの messages テーブルから、全ユーザーのメッセージを最新順に最大200件取得
            all_tester_logs = supabase.table("messages").select("user_id").order("created_at", desc=True).limit(200).execute()
            
            # 🟢 直前で引っこ抜いた「all_tester_logs.data」の名前を正確にスキャンして名簿を作成します
            if all_tester_logs.data:
                user_list = sorted(list(set([u["user_id"] for u in all_tester_logs.data if u.get("user_id")])))
            else:
                user_list = [CURRENT_USER_ID]
        except Exception as e_list:
            st.error(f"名簿取得エラー: {e_list}")
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

        if st.button(
            "📖 会話履歴を表示",
            key="show_user_logs"
        ):
            st.session_state["show_user_logs"] = True

        # プルダウンで選択肢したテスターのログを表示
        try:
            if (
                all_tester_logs.data
                and st.session_state.get(
                    "show_user_logs",
                    False
                )
            ):

                selected_logs = (
                    supabase
                    .table("messages")
                    .select("*")
                    .eq("user_id", selected_target_user_id)
                    .order("created_at", desc=True)
                    .limit(1000)
                    .execute()
                )
                logs = selected_logs.data or []

                # grouped_logs = {}
                # for log in all_tester_logs.data:
                #     uid = log.get("user_id", "unknown")
                #     if uid not in grouped_logs:
                #         grouped_logs[uid] = []
                #     grouped_logs[uid].append(log)

                selected_user_info = users.get(
                    selected_target_user_id,
                    {}
                )

                user_name = selected_user_info.get("ユーザー名", "")
                honorific = selected_user_info.get("呼び方", "")

                if not user_name or user_name == "未設定":
                    target_display_user_name = "私"
                else:
                    target_display_user_name = (
                        f"{user_name}{honorific}"
                        if honorific != "（呼び捨て/なし）"
                        else user_name
                    )

                target_ai_name = selected_user_info.get("AI名称", "")

                if not target_ai_name or target_ai_name == "未設定":
                    target_ai_name = "コンシェルジュ"
                
                # 💡 選ばれたターゲットテスターのデータだけを狙い撃ちで表示します！
                # if selected_target_user_id in grouped_logs:
                #     logs = grouped_logs[selected_target_user_id]
                if logs:
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
                                f"**{target_ai_name}**: {content}"
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