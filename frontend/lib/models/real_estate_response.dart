class RealEstateResponse {
  final String status;
  final Map<String, dynamic> arguments;
  final List<String> missingFields;
  final List<String> missingFieldLabels;
  final String? followUpMessage;
  final String? resultMessage;
  final Map<String, dynamic>? result;
  final int inTokens;
  final int outTokens;
  final double cost;

  const RealEstateResponse({
    required this.status,
    required this.arguments,
    required this.missingFields,
    required this.missingFieldLabels,
    this.followUpMessage,
    this.resultMessage,
    this.result,
    required this.inTokens,
    required this.outTokens,
    required this.cost,
  });

  factory RealEstateResponse.fromJson(Map<String, dynamic> json) {
    return RealEstateResponse(
      status: json['status'] as String,
      arguments: Map<String, dynamic>.from(json['arguments'] ?? {}),
      missingFields: List<String>.from(json['missing_fields'] ?? []),
      missingFieldLabels: List<String>.from(json['missing_field_labels'] ?? []),
      followUpMessage: json['follow_up_message'] as String?,
      resultMessage: json['result_message'] as String?,
      result: json['result'] == null
          ? null
          : Map<String, dynamic>.from(json['result']),
      inTokens: (json['in_tokens'] as num?)?.toInt() ?? 0,
      outTokens: (json['out_tokens'] as num?)?.toInt() ?? 0,
      cost: (json['cost'] as num?)?.toDouble() ?? 0,
    );
  }
}
