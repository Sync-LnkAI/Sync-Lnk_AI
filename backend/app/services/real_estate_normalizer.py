import unicodedata
from decimal import Decimal

from backend.app.calculations.general import parse_date, to_decimal

REAL_ESTATE_SALE_ALLOWED_FIELDS = {
    "owner_type", "sale_price", "loan_balance",
    "land_acquisition_cost", "building_acquisition_cost",
    "accumulated_depreciation", "building_tax_basis",
    "acquisition_related_costs", "total_acquisition_cost",
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
