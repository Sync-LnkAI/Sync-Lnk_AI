import 'package:material_ui/material_ui.dart';

class AppColorTheme {
  const AppColorTheme({
    required this.backgroundColors,
    required this.textColor,
    required this.cardColor,
    required this.borderColor,
  });

  final List<Color> backgroundColors;
  final Color textColor;
  final Color cardColor;
  final Color borderColor;

  static AppColorTheme fromName(String name) {
    return themes[name] ?? themes['パステル']!;
  }

  static const themes = <String, AppColorTheme>{
    'パステル': AppColorTheme(
      backgroundColors: [
        Color(0xFFFFF5F5),
        Color(0xFFFFD1D1),
        Color(0xFFFFB7B2),
      ],
      textColor: Color(0xFF4A1525),
      cardColor: Color(0xFFFEFCBF),
      borderColor: Color(0xFFED64A6),
    ),
    'レインボーポップ': AppColorTheme(
      backgroundColors: [
        Color(0xFFFFB7B2),
        Color(0xFFFFDAC1),
        Color(0xFFE2F0CB),
        Color(0xFFB5EAD7),
        Color(0xFFC7CEEA),
        Color(0xFFFFB7B2),
      ],
      textColor: Color(0xFF1A1A1A),
      cardColor: Color(0xBFFFFFFF),
      borderColor: Color(0xFF3B82F6),
    ),
    'メタリック': AppColorTheme(
      backgroundColors: [
        Color(0xFFE0E0E0),
        Color(0xFFF5F5F5),
        Color(0xFFBEBEBE),
        Color(0xFF9E9E9E),
        Color(0xFFE0E0E0),
      ],
      textColor: Color(0xFF1A1A1A),
      cardColor: Color(0xD9FFFFFF),
      borderColor: Color(0xFF757575),
    ),
    'ホワイト': AppColorTheme(
      backgroundColors: [
        Color(0xFFE6E8EB),
        Color(0xFFF5F7FA),
        Color(0xFFFFFFFF),
        Color(0xFFE6E8EB),
      ],
      textColor: Color(0xFF31333F),
      cardColor: Color(0xFFF0F2F6),
      borderColor: Color(0xFFCCA300),
    ),
    'オーシャン': AppColorTheme(
      backgroundColors: [
        Color(0xFFE3F2FD),
        Color(0xFF90CDF4),
        Color(0xFF64B5F6),
      ],
      textColor: Color(0xFF0A2540),
      cardColor: Color(0xFFFFFFFF),
      borderColor: Color(0xFF4299E1),
    ),
    'フォレスト': AppColorTheme(
      backgroundColors: [Color(0xFFE8F5E9), Color(0xFFA5D6A7)],
      textColor: Color(0xFF0D2B0D),
      cardColor: Color(0xFFFFFFFF),
      borderColor: Color(0xFF48BB78),
    ),
    'ウォーム': AppColorTheme(
      backgroundColors: [
        Color(0xFFFFF5F0),
        Color(0xFFFFAB91),
        Color(0xFFFF8A65),
      ],
      textColor: Color(0xFF5C0F08),
      cardColor: Color(0xFFFFEBEE),
      borderColor: Color(0xFFE53E3E),
    ),
    'ダーク': AppColorTheme(
      backgroundColors: [
        Color(0xFF55545B),
        Color(0xFF1C1B1F),
        Color(0xFF08080A),
      ],
      textColor: Color(0xFFFFFFFF),
      cardColor: Color(0xFF222126),
      borderColor: Color(0xFF66656C),
    ),
  };
}
