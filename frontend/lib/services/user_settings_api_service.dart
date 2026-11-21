import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';

class UserSettingsApiService {
  UserSettingsApiService({required this.baseUrl});

  final String baseUrl;

  Future<Map<String, dynamic>> getSettings() async {
    final accessToken =
        Supabase.instance.client.auth.currentSession?.accessToken;

    if (accessToken == null || accessToken.isEmpty) {
      throw Exception('ログイン情報を確認できませんでした');
    }

    final response = await http.get(
      Uri.parse('$baseUrl/api/v1/user-settings'),
      headers: {'Authorization': 'Bearer $accessToken'},
    );

    final body = jsonDecode(utf8.decode(response.bodyBytes));

    if (response.statusCode != 200) {
      final detail = body is Map ? body['detail'] : null;
      throw Exception(detail ?? 'ユーザー設定を取得できませんでした');
    }

    return Map<String, dynamic>.from(body as Map);
  }
}
