import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';

class CalculationCaseApiService {
  CalculationCaseApiService({required this.baseUrl});

  final String baseUrl;

  Future<List<Map<String, dynamic>>> getCandidates({
    required String caseType,
    String userInput = '',
    int limit = 5,
  }) async {
    final accessToken =
        Supabase.instance.client.auth.currentSession?.accessToken;

    if (accessToken == null || accessToken.isEmpty) {
      throw Exception('ログイン情報を確認できませんでした');
    }

    final uri = Uri.parse('$baseUrl/api/v1/calculation-cases/candidates')
        .replace(
          queryParameters: {
            'case_type': caseType,
            'user_input': userInput,
            'limit': limit.toString(),
          },
        );

    final response = await http.get(
      uri,
      headers: {'Authorization': 'Bearer $accessToken'},
    );

    final body = jsonDecode(utf8.decode(response.bodyBytes));

    if (response.statusCode != 200) {
      final detail = body is Map ? body['detail'] : null;
      throw Exception(detail ?? '計算案件を取得できませんでした');
    }

    final data = Map<String, dynamic>.from(body as Map);

    return (data['candidates'] as List<dynamic>? ?? [])
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
  }

  Future<Map<String, dynamic>> getCase(String caseId) async {
    final accessToken =
        Supabase.instance.client.auth.currentSession?.accessToken;

    if (accessToken == null || accessToken.isEmpty) {
      throw Exception('ログイン情報を確認できませんでした');
    }

    final response = await http.get(
      Uri.parse(
        '$baseUrl/api/v1/calculation-cases/'
        '${Uri.encodeComponent(caseId)}',
      ),
      headers: {'Authorization': 'Bearer $accessToken'},
    );

    final body = jsonDecode(utf8.decode(response.bodyBytes));

    if (response.statusCode != 200) {
      final detail = body is Map ? body['detail'] : null;
      throw Exception(detail ?? '計算案件を取得できませんでした');
    }

    final data = Map<String, dynamic>.from(body as Map);
    return Map<String, dynamic>.from(data['case'] as Map);
  }

  Future<Map<String, dynamic>> createCase({
    required String caseType,
    required String propertyUsage,
    required Map<String, dynamic> caseData,
  }) async {
    final accessToken =
        Supabase.instance.client.auth.currentSession?.accessToken;

    if (accessToken == null || accessToken.isEmpty) {
      throw Exception('ログイン情報を確認できませんでした');
    }

    final response = await http.post(
      Uri.parse('$baseUrl/api/v1/calculation-cases'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $accessToken',
      },
      body: jsonEncode({
        'case_type': caseType,
        'property_usage': propertyUsage,
        'case_data': caseData,
      }),
    );

    final body = jsonDecode(utf8.decode(response.bodyBytes));

    if (response.statusCode != 200) {
      final detail = body is Map ? body['detail'] : null;
      throw Exception(detail ?? '計算案件を作成できませんでした');
    }

    final data = Map<String, dynamic>.from(body as Map);

    return {
      'case_id': data['case_id'],
      'case': Map<String, dynamic>.from(data['case'] as Map),
    };
  }

  Future<void> updateCase({
    required String caseId,
    required Map<String, dynamic> caseData,
    String? caseName,
    String? caseStatus,
    String? propertyUsage,
  }) async {
    final accessToken =
        Supabase.instance.client.auth.currentSession?.accessToken;
    if (accessToken == null || accessToken.isEmpty) {
      throw Exception('ログイン情報を確認できませんでした');
    }

    final response = await http.patch(
      Uri.parse(
        '$baseUrl/api/v1/calculation-cases/${Uri.encodeComponent(caseId)}',
      ),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $accessToken',
      },
      body: jsonEncode({
        'case_data': caseData,
        'case_name': ?caseName,
        'case_status': ?caseStatus,
        'property_usage': ?propertyUsage,
      }),
    );

    final body = jsonDecode(utf8.decode(response.bodyBytes));
    if (response.statusCode != 200) {
      final detail = body is Map ? body['detail'] : null;
      throw Exception(detail ?? '計算案件を更新できませんでした');
    }
  }
}
