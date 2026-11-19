import json
import re
import unicodedata
from datetime import date, datetime
from typing import Callable
from zoneinfo import ZoneInfo

from backend.app.calculations.general import add_years_safely
from backend.app.services.real_estate_normalizer import (
    extract_explicit_real_estate_amounts,
)

JST = ZoneInfo("Asia/Tokyo")

# 不動産売却計算 呼び出し判定関数
def extract_real_estate_sale_parameters(
    user_input: str,
    recent_history: str = "",
    calculation_pending: bool = False,
    *,
    generate_response: Callable,
    calculate_cost: Callable,
    provider: str,
    model_name: str
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
    ・argumentsには、最新のユーザー発言で明示された条件だけを設定してください。
    ・直近の会話は発言の意味を理解するためだけに使用し、過去の金額、日付、構造、条件をargumentsへ再出力してはいけません。
    ・過去に確認済みの条件はPython側で保持するため、抽出処理では引き継いではいけません。
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

    【仲介手数料】
    ・売却仲介手数料、売却時仲介手数料、今回の売却にかかる仲介手数料は、brokerage_feeへ円単位の整数で設定してください。
    ・購入仲介手数料、購入時仲介手数料、取得時仲介手数料は、売却時のbrokerage_feeではありません。
    ・購入仲介手数料は購入時諸費用に含まれるため、acquisition_related_costsとして扱ってください。
    ・購入仲介手数料と、購入登記費用、取得時登記費用、不動産取得税などが同時に明示された場合は、それらを合計してacquisition_related_costsへ設定してください。
    ・「購入仲介手数料」と明示された金額を、 brokerage_feeへ設定してはいけません。
    ・不動産売却計算の継続中に、確認項目として売却時仲介手数料を求めている場合の「仲介手数料」は、brokerage_feeとして扱ってください。
    ・それ以外で、単に「仲介手数料」とだけ書かれ、購入時か売却時か判断できない場合は、brokerage_feeとacquisition_related_costsの両方をnullにしてください。
    ・売却時の仲介手数料が明示されていない場合は、brokerage_feeをnullにしてください。
    ・売却時仲介手数料を自動計算する場合でも、AI側で計算してはいけません。brokerage_feeをnullのまま出力し、Python側の計算に任せてください。
    ・売却時仲介手数料が不要または0円と明示された場合だけ、brokerage_feeを0にしてください。
    ・ユーザーが「仲介手数料は自動計算」「売却仲介手数料を自動で」「売却仲介手数料は計算して」などと明示した場合は、brokerage_feeをnullにしてください。

    【取得費】
    ・次の表現は total_acquisition_cost として扱ってください。
        - 取得費
        - 総取得費
        - 合算簿価
        - 購入経費込の取得費

    例
    取得費: ○○円、総取得費: ○○円、合算簿価: ○○円
    ↓
    total_acquisition_costに設定してください。

    【建物取得価額】
    ・建物購入価格、建物取得額、建物価格は、building_acquisition_cost に設定してください。
    ・建物購入価格を、building_original_cost や total_acquisition_cost に設定してはいけません。
    ・total_acquisition_cost は、土地と建物などを合算した取得費総額が明示された場合だけ設定してください。

    【建物未償却残高・建物簿価】
    ・次の表現は building_tax_basis に設定してください。
    - 建物未償却残高
    - 建物の未償却残高
    - 建物簿価
    - 建物の簿価
    - 減価償却後の建物残高
    ・building_tax_basis は、すでに減価償却後の建物金額です。
    ・building_tax_basis を building_acquisition_cost に設定してはいけません。
    ・building_tax_basis を total_acquisition_cost に設定してはいけません。
    ・建物取得価額と建物未償却残高を混同してはいけません。

    【不動産用途】
    次の表現は property_usage として扱ってください。
    ・非業務用
    ・自宅
    ・自宅用
    ・居住用
    ・マイホーム
    ・別荘
    ・セカンドハウス
    ・貸していない空き家
    ・自己使用
    → owner_occupied

    ・業務用
    ・投資用
    ・投資用マンション
    ・収益物件
    ・賃貸用
    ・一棟マンション
    ・一棟アパート
    ・アパート経営
    ・マンション経営
    ・事業用
    ・店舗
    ・事務所
    → investment

    ・以前は自宅で現在は賃貸
    ・以前は賃貸で現在は自宅
    ・自宅兼店舗
    ・一部を賃貸
    ・用途が途中で変わった
    など、利用区分の変更や併用がある場合は、
    property_usage を推測せず null にしてください。

    用途が不明な場合は null にしてください。

    【重要】
    ・取得費が明示されている場合は、acquisition_related_costs を 0 や null にしてはいけません。
    ・土地取得費や建物取得費が不明であっても、総取得費や合算簿価が提示されている場合はacquisition_related_costs に設定してください。

    【税率の扱い】
    ・パーセントは0から1の小数へ変換してください。
    ・30%は0.30です。
    ・税率が明示されていない場合はnullにしてください。

    【日付の扱い】
    ・日付はYYYY-MM-DD形式にしてください。
    ・取得日、売却日については、年月まで分かる場合は月初日を補完してください。
    例
    2015年8月
    ↓
    2015-08-01

    2020年3月
    ↓
    2020-03-01

    ・取得年、売却年しか分からない場合はその年の1月1日を補完してください。
    例
    2015年
    ↓
    2015-01-01

    2027年
    ↓
    2027-01-01

    ・取得日または売却日が完全に不明な場合のみ null にしてください。
    ・「売却日は未定」「これから売る予定」のような表現で年月も分からない場合は null にしてください。
    ・ローン残債の基準日、返済日、借入残高の時点日、残高確認日などの日時は売却日として扱ってはいけません。
    ・sale_date に設定してよいのは、売却日であることが明示されている場合だけです。単に日付が出てきただけではsale_date に設定してはいけません。

    【保有期間区分】
    ・ユーザーが長期譲渡または5年超と明示した場合は、holding_period_typeをlong_termにしてください。
    ・ユーザーが短期譲渡または5年以下と明示した場合は、holding_period_typeをshort_termにしてください。
    ・取得日と売却日の両方が確認できる場合は、譲渡した年の1月1日時点の所有期間に基づいて判定してください。
    ・取得日または売却日が不明で、長期譲渡か短期譲渡かも明示されていない場合は、holding_period_typeをnullにしてください。
    ・日付が不明な場合に、長期または短期を推測してはいけません。

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

    【建物の取得区分】
    ・建物を新築で取得した、新築で購入した、新築物件だった場合は、building_acquisition_typeをnewにしてください。
    ・建物を中古で取得した、中古で購入した、中古物件だった場合は、building_acquisition_typeをusedにしてください。
    ・新築か中古か明示されていない場合は、building_acquisition_typeをnullにしてください。
    ・建物の築年数だけを理由に、新築または中古を推測してはいけません。

    【建物の耐用年数】
    ・申告、固定資産台帳、減価償却明細などで使用している耐用年数が明示された場合は、building_useful_lifeに年数を整数で設定してください。
    ・「耐用年数は21年」「申告では21年」は、building_useful_lifeを21にしてください。
    ・中古建物でも耐用年数が明示されていない場合は、AIで計算せずnullにしてください。
    ・新築建物で耐用年数が明示されていない場合もnullにし、構造別の法定耐用年数はPython側で設定してください。

    【建物構造】
    次の表現は building_structure として扱ってください。

    ・木造 → wood
    ・軽量鉄骨造、軽量鉄骨 → light_steel
    ・重量鉄骨造、重量鉄骨 → steel
    ・鉄骨造、鉄骨 → steel
    ・RC造、RC、鉄筋コンクリート造 → rc
    ・SRC造、SRC、鉄骨鉄筋コンクリート造 → src

    構造が不明な場合は null にしてください。

    【不動産売却計算に該当しない場合】
    ・最新の発言が、計算、試算、比較、シミュレーション、再計算の依頼ではなく、出来事、状況、経過、結果、感想、考え、希望などを伝える通常会話である場合は、should_calculateをfalseにしてください。
    ・不動産売却計算継続中であっても、最新の発言が、現在確認中の不足項目への回答、既存条件の変更、または計算依頼であることを明確に確認できない場合は、should_calculateをfalseにしてください。
    ・不動産、売却、金額、ローンなど計算に関連する語や数値が含まれていることだけを理由に、計算対象としてはいけません。
    ・判断に迷う場合は通常会話を優先し、should_calculateをfalseにしてください。
    ・should_calculateをfalseにしてください。
    ・argumentsの各値はnullにしてください。

    【現在の計算状態】
    不動産売却計算継続中: {calculation_pending}

    【計算継続中のルール】
    不動産売却計算継続中がTrueの場合、最新のユーザー発言は、不足項目への回答として優先的に解釈してください。
    以下のような発言は、不動産売却計算対象として扱い、should_calculate を true にしてください。

    ・金額のみの回答
    ・土地取得費
    ・建物取得費
    ・購入時諸費用
    ・建物構造
    ・新築または中古
    ・建物の耐用年数
    ・取得年月
    ・取得日
    ・売却日
    ・長期譲渡
    ・短期譲渡

    計算継続中の場合は、単独では不動産売却に見えない短文でも、不足項目への回答として解釈してください。

    例
    木造 → building_structure = "wood"
    RC造 → building_structure = "rc"
    中古で購入 → building_acquisition_type = "used"
    新築で購入 → building_acquisition_type = "new"
    耐用年数は21年 → building_useful_life = 21
    2018年購入 → building_acquisition_date
    8年前に購入 → building_acquisition_date
    長期譲渡 → holding_period_type = "long_term"
    短期譲渡 → holding_period_type = "short_term"

    【会話の継続ルール】
    直近の会話で不動産売却計算を行っており、「長期譲渡で計算して」「短期譲渡で計算して」のような回答があった場合は、should_calculate を true にしてください。
    その場合、holding_period_type を設定し、他の条件は直近の会話から引き継ぐ前提でarguments に null を入れて構いません。

    【直近の会話】
    {recent_history}

    【最新ユーザー発言】
    {user_input}

    【出力形式】
    {{
        "should_calculate": true,
        "arguments": {{
            "owner_type": null,
            "sale_price": null,
            "property_usage": null,
            "loan_balance": null,
            "land_acquisition_cost": null,
            "building_acquisition_cost": null,
            "building_tax_basis": null,
            "building_structure": null,
            "building_acquisition_type": null,
            "building_useful_life": null,
            "building_acquisition_date": null,
            "accumulated_depreciation": null,
            "acquisition_related_costs": null,
            "total_acquisition_cost": null,
            "brokerage_fee": null,
            "transfer_expenses": null,
            "other_cash_expenses": null,
            "acquisition_date": null,
            "sale_date": null,
            "holding_period_type": null,
            "special_deduction": null,
            "corporate_effective_tax_rate": null,
            "use_deemed_acquisition_cost": false,
            "deemed_acquisition_cost_rate": null
        }}
    }}
    """

    try:
        extraction_result = generate_response(
            provider=provider,
            system_instruction="",
            user_prompt=extraction_prompt,
            response_format_json=True,
            model_name=model_name
        )

        raw_text = str(extraction_result.get("text", "") or "").strip()

        if not raw_text:
            raise ValueError("不動産売却条件の抽出結果が空です")

        clean_text = (
            raw_text
            .replace("```json", "")
            .replace("```JSON", "")
            .replace("```", "")
            .strip()
        )

        extracted_data = json.loads(clean_text)

        if not isinstance(extracted_data, dict):
            raise ValueError(
                "不動産売却条件の抽出結果がobject形式ではありません"
            )

        should_calculate = bool(extracted_data.get("should_calculate", False))

        raw_arguments = (extracted_data.get("arguments", {}))

        if not isinstance(raw_arguments, dict):
            raw_arguments = {}
        
        normalized_user_input = unicodedata.normalize(
            "NFKC",
            str(user_input or "")
        )

        # 建物構造が最新発言に明示されている場合は、
        # AI抽出結果より優先して確定する
        explicit_building_structure = None

        if any(
            keyword in normalized_user_input
            for keyword in {
                "SRC造",
                "鉄骨鉄筋コンクリート造"
            }
        ):
            explicit_building_structure = "src"

        elif any(
            keyword in normalized_user_input
            for keyword in {
                "RC造",
                "鉄筋コンクリート造"
            }
        ):
            explicit_building_structure = "rc"

        elif any(
            keyword in normalized_user_input
            for keyword in {
                "重量鉄骨造",
                "重量鉄骨"
            }
        ):
            explicit_building_structure = "steel"

        elif any(
            keyword in normalized_user_input
            for keyword in {
                "軽量鉄骨造",
                "軽量鉄骨"
            }
        ):
            explicit_building_structure = "light_steel"

        elif any(
            keyword in normalized_user_input
            for keyword in {
                "鉄骨造",
                "鉄骨"
            }
        ):
            explicit_building_structure = "steel"

        elif "木造" in normalized_user_input:
            explicit_building_structure = "wood"

        if explicit_building_structure is not None:
            raw_arguments["building_structure"] = (
                explicit_building_structure
            )

        mentions_building_age = any(
            keyword in normalized_user_input
            for keyword in {"建築", "築年", "築後", "築"}
        )

        mentions_acquisition_date = bool(
            re.search(
                r"(?:"
                r"[0-9]+年前に(?:購入|取得)|"
                r"[0-9]{4}年(?:[0-9]{1,2}月)?に(?:購入|取得)|"
                r"(?:購入|取得)(?:した|したのは|した時期|年月|日)"
                r")",
                normalized_user_input
            )
        )

        relative_acquisition_date_match = re.search(
            r"(?:取得日は?|購入日は?|取得年月は?|購入年月は?)"
            r"([0-9]+)年前の([0-9]{1,2})月"
            r"(?:([0-9]{1,2})日)?",
            normalized_user_input
        )

        relative_purchase_match = re.search(
            r"(?:(建物|土地|物件|不動産|土地建物)(?:は|を)?)?"
            r"([0-9]+)年前に(?:購入|取得)",
            normalized_user_input
        )

        if relative_acquisition_date_match:
            years_ago = int(relative_acquisition_date_match.group(1))
            acquisition_month = int(
                relative_acquisition_date_match.group(2)
            )
            acquisition_day = int(
                relative_acquisition_date_match.group(3) or 1
            )
            acquisition_year = datetime.now(JST).year - years_ago

            try:
                acquisition_date = date(
                    acquisition_year,
                    acquisition_month,
                    acquisition_day
                ).isoformat()
            except ValueError:
                acquisition_date = ""

            if acquisition_date:
                raw_arguments["acquisition_date"] = acquisition_date
                raw_arguments["building_acquisition_date"] = (
                    acquisition_date
                )
            else:
                raw_arguments["acquisition_date"] = None
                raw_arguments["building_acquisition_date"] = None

        elif relative_purchase_match:
            purchase_target = relative_purchase_match.group(1) or ""
            years_ago = int(relative_purchase_match.group(2))
            acquisition_date = add_years_safely(
                datetime.now(JST).date(), -years_ago
            ).isoformat()

            raw_arguments["acquisition_date"] = acquisition_date

            if purchase_target != "土地":
                raw_arguments["building_acquisition_date"] = (
                    acquisition_date
                )

        elif mentions_building_age and not mentions_acquisition_date:
            raw_arguments["building_acquisition_date"] = None

        explicit_amounts = extract_explicit_real_estate_amounts(user_input)
        for field_name, amount in explicit_amounts.items():
            raw_arguments[field_name] = amount

        in_tokens = int(extraction_result.get("in_tokens", 0) or 0)
        out_tokens = int(extraction_result.get("out_tokens", 0) or 0)
        # extraction_cost = (in_tokens * PRICE_BACKGROUND_IN + out_tokens * PRICE_BACKGROUND_OUT)
        extraction_cost = calculate_cost(
            provider=provider,
            in_tokens=in_tokens,
            out_tokens=out_tokens
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
            "cost": 0.0,
            "error": f"{type(extraction_error).__name__}: {extraction_error}"
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
            "cost": 0.0,
            "error": f"{type(unexpected_error).__name__}: {unexpected_error}"
        }
#==============================================