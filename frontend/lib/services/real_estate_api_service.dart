import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/real_estate_response.dart';

import 'package:supabase_flutter/supabase_flutter.dart';

class RealEstateApiService {
  RealEstateApiService({required this.baseUrl});

  final String baseUrl;

  Future<RealEstateResponse> calculateFromText({
    required String userInput,
    String recentHistory = '',
    bool calculationPending = false,
    Map<String, dynamic> previousArguments = const {},
  }) async {
    final accessToken =
        Supabase.instance.client.auth.currentSession?.accessToken;

    if (accessToken == null || accessToken.isEmpty) {
      throw Exception('ログイン情報を確認できませんでした');
    }

    final response = await http.post(
      Uri.parse('$baseUrl/api/v1/real-estate/calculate-from-text'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $accessToken',
      },
      body: jsonEncode({
        'user_input': userInput,
        'recent_history': recentHistory,
        'calculation_pending': calculationPending,
        'previous_arguments': previousArguments,
      }),
    );

    final body = jsonDecode(utf8.decode(response.bodyBytes));

    if (response.statusCode != 200) {
      final detail = body is Map ? body['detail'] : null;
      throw Exception(detail ?? '不動産計算APIの呼び出しに失敗しました');
    }

    return RealEstateResponse.fromJson(Map<String, dynamic>.from(body as Map));
  }
}
