import re
import unicodedata
from decimal import Decimal

from backend.app.calculations.general import parse_date, to_decimal

REAL_ESTATE_SALE_ALLOWED_FIELDS = {
    "owner_type", "sale_price",
    "loan_balance", "loan_balance_confirmed",
    "land_acquisition_cost", "land_acquisition_cost_confirmed",
    "building_acquisition_cost","building_acquisition_cost_confirmed",
    "accumulated_depreciation", "building_tax_basis",
    "acquisition_related_costs", "acquisition_related_costs_confirmed",
    "total_acquisition_cost",
    "brokerage_fee", "transfer_expenses", "other_cash_expenses",
    "acquisition_date", "sale_date", "holding_period_type",
    "special_deduction", "corporate_effective_tax_rate",
    "use_deemed_acquisition_cost", "deemed_acquisition_cost_rate",
    "property_usage", "building_structure",
    "building_acquisition_type", "building_useful_life",
    "building_acquisition_date"
}

REAL_ESTATE_NUMERIC_FIELDS = {
    "sale_price", "loan_balance", "land_acquisition_cost",
    "building_acquisition_cost", "accumulated_depreciation",
    "building_tax_basis", "acquisition_related_costs",
    "total_acquisition_cost", "brokerage_fee",
    "transfer_expenses", "other_cash_expenses",
    "special_deduction", "corporate_effective_tax_rate",
    "deemed_acquisition_cost_rate", "building_useful_life"
}

REAL_ESTATE_DATE_FIELDS = {
    "acquisition_date", "sale_date", "building_acquisition_date"
}

CONFIRMABLE_FIELDS = {
    "land_acquisition_cost",
    "building_acquisition_cost",
    "acquisition_related_costs",
}

ACQUISITION_COMPONENT_FIELDS = {
    "land_acquisition_cost",
    "building_acquisition_cost",
    "acquisition_related_costs",
}

# 不動産売却の正規化処理関数
def normalize_real_estate_sale_arguments(
    arguments: dict,
    apply_defaults: bool = True
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
                normalized["owner_type"] = normalized_owner_type

            continue
            
        if key == "holding_period_type":

            holding_text = str(value).strip().lower()

            if holding_text in {
                "long_term",
                "長期",
                "長期譲渡",
                "5年超"
            }:
                normalized[key] = "long_term"

            elif holding_text in {
                "short_term",
                "短期",
                "短期譲渡",
                "5年以下"
            }:
                normalized[key] = "short_term"
            continue
        
        if key == "property_usage":
            property_usage_text = str(value).strip().lower()
            property_usage_mapping = {
                "owner_occupied": "owner_occupied",
                "非業務用": "owner_occupied",
                "自宅": "owner_occupied",
                "自宅用": "owner_occupied",
                "居住用": "owner_occupied",
                "マイホーム": "owner_occupied",
                "別荘": "owner_occupied",
                "セカンドハウス": "owner_occupied",
                "空き家": "owner_occupied",
                "自己使用": "owner_occupied",

                "investment": "investment",
                "業務用": "investment",
                "投資用": "investment",
                "賃貸用": "investment",
                "収益物件": "investment",
                "事業用": "investment",
                "店舗": "investment",
                "事務所": "investment"
            }
            normalized_property_usage = property_usage_mapping.get(
                property_usage_text
            )
            if normalized_property_usage is not None:
                normalized["property_usage"] = normalized_property_usage
            continue

        if key == "building_structure":
            structure_text = (
                unicodedata.normalize("NFKC",str(value))
                .strip()
                .lower()
            )

            structure_mapping = {
                "wood": "wood",
                "木造": "wood",

                "light_steel": "light_steel",
                "軽量鉄骨造": "light_steel",
                "軽量鉄骨": "light_steel",

                "steel": "steel",
                "重量鉄骨造": "steel",
                "重量鉄骨": "steel",
                "鉄骨造": "steel",
                "鉄骨": "steel",

                "rc": "rc",
                "rc造": "rc",
                "鉄筋コンクリート造": "rc",

                "src": "src",
                "src造": "src",
                "鉄骨鉄筋コンクリート造": "src"
            }

            normalized_structure = structure_mapping.get(structure_text)

            if normalized_structure is not None:
                normalized["building_structure"] = (normalized_structure)

            continue
            
        if key == "building_acquisition_type":
            acquisition_type_text = unicodedata.normalize("NFKC", str(value)).strip().lower()
            acquisition_type_mapping = {
                "new": "new",
                "新築": "new",
                "新築取得": "new",
                "新築購入": "new",
                "新築物件": "new",
                "used": "used",
                "中古": "used",
                "中古取得": "used",
                "中古購入": "used",
                "中古物件": "used"
            }
            normalized_acquisition_type = acquisition_type_mapping.get(acquisition_type_text)
            if normalized_acquisition_type is not None:
                normalized["building_acquisition_type"] = normalized_acquisition_type
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
    
        normalized[key] = value

    # 計算実行時だけ任意項目へ安全な初期値を設定
    if apply_defaults:
        normalized.setdefault(
            "loan_balance",
            Decimal("0")
        )

        normalized.setdefault(
            "total_acquisition_cost",
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
# ==========================================

# 不動産売却計算に必要な条件の不足判定関数
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
        acquisition_date = arguments.get("acquisition_date")
        sale_date = arguments.get("sale_date")
        holding_period_type = arguments.get("holding_period_type")
        dates_are_complete = bool(acquisition_date and sale_date)
        holding_type_is_valid = (holding_period_type in {"long_term", "short_term"})
        if (not dates_are_complete and not holding_type_is_valid):
            missing_fields.append("holding_period_type")

    loan_balance_confirmed = bool(
        arguments.get(
            "loan_balance_confirmed",
            False
        )
    )

    if not loan_balance_confirmed:
        missing_fields.append(
            "loan_balance"
        )

    use_deemed_acquisition_cost = bool(
        arguments.get(
            "use_deemed_acquisition_cost",
            False
        )
    )

    if not use_deemed_acquisition_cost:
        total_acquisition_cost = to_decimal(arguments.get("total_acquisition_cost",Decimal("0")))

        if total_acquisition_cost <= Decimal("0"):
            for field in CONFIRMABLE_FIELDS:
                field_is_provided = False
                if (
                    field in arguments
                    and arguments.get(field) is not None
                ):
                    try:
                        field_amount = to_decimal(
                            arguments.get(field)
                        )
                        if field == "loan_balance":
                            field_is_provided = bool(
                                arguments.get(
                                    "loan_balance_confirmed",
                                    False
                                )
                            )
                        else:
                            field_is_provided = (
                                field_amount > Decimal("0")
                                or bool(
                                    arguments.get(
                                        f"{field}_confirmed",
                                        False
                                    )
                                )
                            )
                    except (
                        ValueError,
                        TypeError,
                        ArithmeticError
                    ):
                        field_is_provided = False
                
                if not field_is_provided:
                    missing_fields.append(field)

    building_cost = to_decimal(arguments.get("building_acquisition_cost",Decimal("0")))
    building_tax_basis = arguments.get("building_tax_basis")
    property_usage = arguments.get("property_usage")
    building_acquisition_type = arguments.get("building_acquisition_type")
    building_useful_life = arguments.get("building_useful_life")

    if building_cost > Decimal("0"):
        if building_acquisition_type not in {"new", "used"}:
            missing_fields.append("building_acquisition_type")
        elif building_acquisition_type == "used":
            try:
                useful_life_is_valid = building_useful_life is not None and to_decimal(building_useful_life) > Decimal("0")
            except (ValueError, TypeError, ArithmeticError):
                useful_life_is_valid = False
            if not useful_life_is_valid:
                missing_fields.append("building_useful_life")

    if (
        building_cost > Decimal("0")
        and building_tax_basis is None
        and property_usage not in {
            "owner_occupied",
            "investment"
        }
    ):
        missing_fields.append("property_usage")

    if (
        building_cost > Decimal("0")
        and "accumulated_depreciation"
        not in arguments
    ):

        building_original_cost = to_decimal(arguments.get("building_acquisition_cost", Decimal("0")))
        building_structure = arguments.get("building_structure")
        building_acquisition_date = arguments.get("building_acquisition_date")

        can_auto_calculate = (
            building_original_cost > Decimal("0")
            and building_structure
            and building_acquisition_date
            and building_acquisition_type in {"new", "used"}
            and (building_acquisition_type == "new" or building_useful_life is not None)
        )

        if not can_auto_calculate:
            if (building_original_cost <= Decimal("0")):
                missing_fields.append("building_original_cost")
            if not building_structure: missing_fields.append("building_structure")
            if not building_acquisition_date: missing_fields.append("building_acquisition_date")

    # 重複を除き、追加順を維持
    return list(dict.fromkeys(missing_fields))
# ==========================================

# 日本語の金額表記を円単位の数値文字列へ変換する関数
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
#============================================

# 不動産売却の明示的な金額を原文から抽出する関数
def extract_explicit_real_estate_amounts(user_input: str) -> dict:
    normalized_text = unicodedata.normalize(
        "NFKC",
        str(user_input or "")
    )

    normalized_text = (
        normalized_text
        .replace("，", ",")
        .replace("：", ":")
    )

    number_part = (
        r"[0-9][0-9,]*"
        r"(?:\.[0-9]+)?"
    )

    amount_part = (
        rf"{number_part}"
        rf"(?:"
        rf"億(?:{number_part}万)?|"
        rf"万|"
        rf"円"
        rf")"
    )

    field_patterns = {
        "sale_price": [
            (
                rf"(?:売却予定額|売却額|売却価格|売値)"
                rf"\s*(?:は|が|を|で|:)?\s*"
                rf"(?P<amount>{amount_part})"
            ),
            (
                rf"(?P<amount>{amount_part})"
                rf"\s*(?:で|にて)?\s*"
                rf"(?:売却予定|売却する|売却した|売却)"
            )
        ],
        "loan_balance": [
            (
                rf"(?:"
                rf"ローン(?:の)?残債|"
                rf"ローン(?:の)?残高|"
                rf"借入(?:金)?残高"
                rf")"
                rf"\s*(?:は|が|を|:)?\s*"
                rf"(?P<amount>{amount_part})"
            ),
            (
                rf"(?P<amount>{amount_part})"
                rf"\s*(?:の)?\s*"
                rf"(?:ローン残債|ローン残高|借入残高)"
            )
        ],
        "land_acquisition_cost": [
            (
                rf"(?:"
                rf"土地(?:の)?取得(?:費|価額|価格)?|"
                rf"土地(?:の)?購入(?:費|価額|価格)?|"
                rf"土地代"
                rf")"
                rf"\s*(?:は|が|を|:)?\s*"
                rf"(?P<amount>{amount_part})"
            ),
            (
                rf"土地"
                rf"\s*(?:は|が|を)?\s*"
                rf"(?P<amount>{amount_part})"
                rf"\s*(?:で)?\s*"
                rf"(?:取得|購入)"
            ),
            (
                rf"土地"
                rf"\s*(?:は|が|を|:)?\s*"
                rf"(?P<amount>{amount_part})"
            )
        ],
        "building_acquisition_cost": [
            (
                rf"(?:"
                rf"建物(?:の)?取得(?:費|価額|価格)?|"
                rf"建物(?:の)?購入(?:費|価額|価格)?|"
                rf"建物代"
                rf")"
                rf"\s*(?:は|が|を|:)?\s*"
                rf"(?P<amount>{amount_part})"
            ),
            (
                rf"建物"
                rf"\s*(?:は|が|を|:)?\s*"
                rf"(?P<amount>{amount_part})"
                rf"\s*(?:で)?\s*"
                rf"(?:取得|購入)"
            ),
            (
                rf"建物"
                rf"\s*(?:は|が|を|:)?\s*"
                rf"(?P<amount>{amount_part})"
            )
        ],
        "building_tax_basis": [
            (
                rf"(?:"
                rf"建物(?:の)?未償却残高|"
                rf"建物(?:の)?簿価|"
                rf"減価償却後(?:の)?建物残高"
                rf")"
                rf"\s*(?:は|が|を|:)?\s*"
                rf"(?P<amount>{amount_part})"
            )
        ],
        "acquisition_related_costs": [
            (
                rf"(?:"
                rf"購入時(?:の)?諸費用|"
                rf"取得時(?:の)?諸費用|"
                rf"取得関連費用"
                rf")"
                rf"\s*(?:は|が|を|:)?\s*"
                rf"(?P<amount>{amount_part})"
            ),
            (
                rf"(?:"
                rf"購入(?:時)?(?:の)?仲介手数料|"
                rf"取得(?:時)?(?:の)?仲介手数料|"
                rf"購入(?:時)?(?:の)?登記費用(?:等)?|"
                rf"取得(?:時)?(?:の)?登記費用(?:等)?|"
                rf"不動産取得税"
                rf")"
                rf"\s*(?:は|が|を|:)?\s*"
                rf"(?P<amount>{amount_part})"
            )
        ],
        "total_acquisition_cost": [
            (
                rf"(?:"
                rf"総取得費|"
                rf"取得費総額|"
                rf"取得価額合計"
                rf")"
                rf"\s*(?:は|が|を|:)?\s*"
                rf"(?P<amount>{amount_part})"
            )
        ],
        "brokerage_fee": [
            (
                rf"(?:"
                rf"売却(?:時)?(?:の)?仲介手数料|"
                rf"今回(?:の)?売却(?:の)?仲介手数料"
                rf")"
                rf"\s*(?:は|が|を|:)?\s*"
                rf"(?P<amount>{amount_part})"
            ),
            (
                rf"(?<!購入)(?<!取得)"
                rf"仲介手数料"
                rf"\s*(?:は|が|を|:)?\s*"
                rf"(?P<amount>{amount_part})"
            )
        ],
        "transfer_expenses": [
            (
                rf"(?:"
                rf"譲渡費用|"
                rf"売却時(?:の)?諸費用"
                rf")"
                rf"\s*(?:は|が|を|:)?\s*"
                rf"(?P<amount>{amount_part})"
            )
        ],
        "other_cash_expenses": [
            (
                rf"(?:"
                rf"その他(?:の)?現金支出|"
                rf"その他(?:の)?支出"
                rf")"
                rf"\s*(?:は|が|を|:)?\s*"
                rf"(?P<amount>{amount_part})"
            )
        ]
    }

    extracted_amounts = {}

    for field_name, patterns in field_patterns.items():
        for pattern in patterns:
            match = re.search(
                pattern,
                normalized_text,
                flags=re.IGNORECASE
            )

            if not match:
                continue

            amount_text = match.group("amount")

            try:
                extracted_amounts[field_name] = to_decimal(
                    normalize_japanese_number_text(amount_text)
                )
            except (
                ValueError,
                TypeError,
                ArithmeticError
            ):
                pass

            break

    purchase_cost_pattern = (
        rf"(?:"
        rf"購入(?:時)?(?:の)?仲介手数料|"
        rf"取得(?:時)?(?:の)?仲介手数料|"
        rf"購入(?:時)?(?:の)?登記費用(?:等)?|"
        rf"取得(?:時)?(?:の)?登記費用(?:等)?|"
        rf"不動産取得税"
        rf")"
        rf"\s*(?:は|が|を|:)?\s*"
        rf"(?P<amount>{amount_part})"
    )

    purchase_cost_matches = list(
        re.finditer(
            purchase_cost_pattern,
            normalized_text,
            flags=re.IGNORECASE
        )
    )

    if purchase_cost_matches:
        purchase_cost_total = Decimal("0")

        for match in purchase_cost_matches:
            try:
                purchase_cost_total += to_decimal(
                    normalize_japanese_number_text(match.group("amount"))
                )
            except (
                ValueError,
                TypeError,
                ArithmeticError
            ):
                continue

        extracted_amounts["acquisition_related_costs"] = purchase_cost_total

        # 購入時の仲介手数料を
        # 売却時仲介手数料として扱わない
        extracted_amounts.pop("brokerage_fee", None)

    return extracted_amounts
#==============================================

# 単純な金額変更だけをPythonで確定できるか判定する関数
def extract_simple_real_estate_amount_update(user_input: str) -> dict:

    normalized_text = unicodedata.normalize(
        "NFKC",
        str(user_input or "")
    ).strip()

    if not normalized_text:
        return {}

    segments = [
        segment.strip()
        for segment in re.split(r"[、,\n]+", normalized_text)
        if segment.strip()
    ]

    if not segments:
        return {}

    number_part = (
        r"[0-9][0-9,]*"
        r"(?:\.[0-9]+)?"
    )
    amount_part = (
        rf"{number_part}"
        rf"(?:"
        rf"億(?:{number_part}万)?円?|"
        rf"万円?|"
        rf"円"
        rf")"
    )

    field_labels = (
        r"売却予定額|売却額|売却価格|売値|"
        r"ローン(?:の)?残債|ローン(?:の)?残高|"
        r"借入(?:金)?残高|"
        r"土地(?:の)?取得(?:費|価額|価格)?|"
        r"土地(?:の)?購入(?:費|価額|価格)?|土地代|"
        r"建物(?:の)?取得(?:費|価額|価格)?|"
        r"建物(?:の)?購入(?:費|価額|価格)?|建物代|"
        r"購入時(?:の)?諸費用|取得時(?:の)?諸費用|"
        r"取得関連費用|総取得費|取得費総額|"
        r"取得価額合計|仲介手数料|譲渡費用|"
        r"売却時(?:の)?諸費用|"
        r"その他(?:の)?現金支出|その他(?:の)?支出"
    )

    simple_update_pattern = (
        rf"^(?:{field_labels})"
        rf"\s*(?:は|が|を|で|:)?\s*"
        rf"{amount_part}"
        rf"\s*(?:"
        rf"にして|へ変更|に変更|でお願いします|"
        rf"です|にする|とする"
        rf")?\s*[。.]?$"
    )

    extracted_arguments = {}

    for segment in segments:
        if not re.fullmatch(
            simple_update_pattern,
            segment,
            flags=re.IGNORECASE
        ):
            return {}

        segment_amounts = (extract_explicit_real_estate_amounts(segment))

        if len(segment_amounts) != 1:
            return {}

        field_name, amount = next(
            iter(segment_amounts.items())
        )

        if field_name in extracted_arguments:
            return {}

        extracted_arguments[field_name] = amount

    if not extracted_arguments:
        return {}

    if "loan_balance" in extracted_arguments:
        extracted_arguments[
            "loan_balance_confirmed"
        ] = True

    for field_name in ACQUISITION_COMPONENT_FIELDS:
        if field_name in extracted_arguments:
            extracted_arguments[
                f"{field_name}_confirmed"
            ] = True

    return extracted_arguments
#==============================================
