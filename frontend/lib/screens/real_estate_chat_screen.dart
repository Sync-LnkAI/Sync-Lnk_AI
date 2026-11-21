import 'package:material_ui/material_ui.dart';

import '../config/app_config.dart';
import '../services/calculation_case_api_service.dart';
import '../services/real_estate_api_service.dart';

class RealEstateChatScreen extends StatefulWidget {
  const RealEstateChatScreen({super.key});

  @override
  State<RealEstateChatScreen> createState() => _RealEstateChatScreenState();
}

class _RealEstateChatScreenState extends State<RealEstateChatScreen> {
  final _controller = TextEditingController();
  final _scrollController = ScrollController();
  final _messages = <String>[];
  final _previousArguments = <String, dynamic>{};

  final _api = RealEstateApiService(baseUrl: AppConfig.apiBaseUrl);

  final _caseApi = CalculationCaseApiService(baseUrl: AppConfig.apiBaseUrl);

  bool _calculationPending = false;
  bool _isLoading = false;
  String? _lastFailedInput;

  List<Map<String, dynamic>> _caseCandidates = [];
  String? _pendingCaseInput;
  bool _selectingCase = false;
  String? _activeCaseId;
  bool _creatingNewCase = false;

  Future<void> _scrollToBottom() async {
    await Future<void>.delayed(const Duration(milliseconds: 100));

    if (!mounted || !_scrollController.hasClients) return;

    await _scrollController.animateTo(
      0,
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeOut,
    );
  }

  bool _isFinishCommand(String text) {
    final normalized = text.replaceAll(RegExp(r'\s+'), '');

    return normalized == '計算終了' || normalized == '計算を終了' || normalized == '終了';
  }

  void _clearCaseSelection() {
    _caseCandidates = [];
    _pendingCaseInput = null;
    _selectingCase = false;
  }

  void _finishCalculation({bool addUserMessage = false}) {
    setState(() {
      if (addUserMessage) {
        _messages.add('あなた: 計算終了');
      }

      _previousArguments.clear();
      _clearCaseSelection();
      _activeCaseId = null;
      _creatingNewCase = false;
      _lastFailedInput = null;
      _calculationPending = false;
      _messages.add('ハヤト: 計算を終了しました。');
    });

    _controller.clear();
    _scrollToBottom();
  }

  void _retryLastRequest() {
    if (_lastFailedInput == null || _isLoading) return;
    _send();
  }

  Future<bool> _loadCaseCandidates(String userInput) async {
    final candidates = await _caseApi.getCandidates(
      caseType: 'real_estate_sale',
      userInput: userInput,
      limit: 5,
    );

    if (!mounted) return false;

    if (candidates.isEmpty) {
      _clearCaseSelection();
      return false;
    }

    final lines = <String>['以前の計算案件が見つかりました。', ''];

    for (var index = 0; index < candidates.length; index++) {
      final caseName = candidates[index]['case_name'] ?? '名称未設定';

      lines.add('${index + 1}. $caseName');
    }

    lines
      ..add('${candidates.length + 1}. 新しく追加')
      ..add('')
      ..add('利用する番号を入力してください。');

    setState(() {
      _caseCandidates = candidates;
      _pendingCaseInput = userInput;
      _selectingCase = true;
      _messages.add('ハヤト: ${lines.join('\n')}');
    });

    _scrollToBottom();
    return true;
  }

  Future<void> _handleCaseSelection(String inputText) async {
    final normalizedInput = inputText.replaceAllMapped(
      RegExp(r'[０-９]'),
      (match) => String.fromCharCode(match.group(0)!.codeUnitAt(0) - 0xFEE0),
    );
    final selectedNumber = int.tryParse(normalizedInput.trim());
    final newCaseNumber = _caseCandidates.length + 1;

    if (selectedNumber == null ||
        selectedNumber < 1 ||
        selectedNumber > newCaseNumber) {
      setState(() {
        _messages.add('あなた: $inputText');
        _messages.add('ハヤト: 1から$newCaseNumberまでの番号を入力してください。');
      });

      _controller.clear();
      _scrollToBottom();
      return;
    }

    final originalInput = _pendingCaseInput;

    if (originalInput == null || originalInput.isEmpty) {
      setState(() {
        _clearCaseSelection();
        _messages.add(
          'ハヤト: 計算条件を確認できませんでした。'
          'もう一度条件を入力してください。',
        );
      });

      _controller.clear();
      _scrollToBottom();
      return;
    }

    setState(() {
      _messages.add('あなた: $inputText');
      _isLoading = true;
    });

    _controller.clear();
    _scrollToBottom();

    try {
      if (selectedNumber == newCaseNumber) {
        _previousArguments.clear();

        setState(() {
          _activeCaseId = null;
          _creatingNewCase = true;
          _clearCaseSelection();
        });

        await _executeCalculation(originalInput, addUserMessage: false);

        return;
      }
      final selectedCase = _caseCandidates[selectedNumber - 1];

      final caseId = strValue(selectedCase['case_id']);

      if (caseId.isEmpty) {
        throw Exception('選択した計算案件のIDを確認できませんでした');
      }

      final caseDetail = await _caseApi.getCase(caseId);
      final caseData = Map<String, dynamic>.from(
        caseDetail['case_data'] as Map? ?? {},
      );

      _previousArguments
        ..clear()
        ..addAll(caseData);

      _activeCaseId = caseId;
      _creatingNewCase = false;

      final caseName = strValue(caseDetail['case_name'], fallback: '名称未設定');

      setState(() {
        _clearCaseSelection();
        _calculationPending = true;
        _messages.add('ハヤト: 「$caseName」の条件を読み込みました。');
      });

      _scrollToBottom();

      await _executeCalculation(originalInput, addUserMessage: false);
    } catch (error) {
      debugPrint('計算案件選択エラー: $error');

      if (!mounted) return;

      setState(() {
        _messages.add(
          'ハヤト: 計算案件を読み込めませんでした。'
          '接続を確認して、もう一度お試しください。',
        );
      });

      _scrollToBottom();
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  Future<void> _executeCalculation(
    String inputText, {
    bool addUserMessage = true,
  }) async {
    if (addUserMessage) {
      setState(() {
        _messages.add('あなた: $inputText');
      });

      _scrollToBottom();
    }

    try {
      final response = await _api.calculateFromText(
        userInput: inputText,
        calculationPending: _calculationPending,
        previousArguments: _previousArguments,
      );

      _previousArguments
        ..clear()
        ..addAll(response.arguments);

      _lastFailedInput = null;

      if (response.status == 'success' && _creatingNewCase) {
        final propertyUsage =
            _previousArguments['property_usage']?.toString() ?? 'other';
        final created = await _caseApi.createCase(
          caseType: 'real_estate_sale',
          propertyUsage: propertyUsage,
          caseData: _previousArguments,
        );

        _activeCaseId = created['case_id']?.toString();
        _creatingNewCase = false;
      } else if (response.status == 'success' && _activeCaseId != null) {
        await _caseApi.updateCase(
          caseId: _activeCaseId!,
          caseData: _previousArguments,
          propertyUsage: _previousArguments['property_usage']?.toString(),
        );
      }

      final reply = response.status == 'missing_fields'
          ? response.followUpMessage
          : response.status == 'success'
          ? response.resultMessage
          : '不動産売却計算の対象ではありません。';

      if (!mounted) return;

      setState(() {
        _messages.add('ハヤト: ${reply ?? '回答を取得できませんでした。'}');

        if (response.status == 'missing_fields' ||
            response.status == 'success') {
          _calculationPending = true;
        } else {
          _calculationPending = false;
          _previousArguments.clear();
        }
      });

      _scrollToBottom();
    } catch (error) {
      debugPrint('不動産計算APIエラー: $error');

      if (!mounted) return;

      setState(() {
        _lastFailedInput = inputText;
        _messages.add(
          'ハヤト: 通信できませんでした。'
          '接続を確認して、再試行してください。',
        );
      });

      _scrollToBottom();
    }
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    final retryText = text.isEmpty ? _lastFailedInput : null;
    final inputText = retryText ?? text;

    if (inputText.isEmpty || _isLoading) return;

    if (_selectingCase) {
      await _handleCaseSelection(inputText);
      return;
    }

    if (_calculationPending && _isFinishCommand(inputText)) {
      _finishCalculation(addUserMessage: true);
      return;
    }

    setState(() {
      _isLoading = true;

      if (retryText == null) {
        _messages.add('あなた: $inputText');
      }
    });

    _controller.clear();
    _scrollToBottom();

    try {
      if (!_calculationPending &&
          _previousArguments.isEmpty &&
          retryText == null) {
        final selectionRequired = await _loadCaseCandidates(inputText);

        if (selectionRequired) {
          return;
        }
      }

      await _executeCalculation(inputText, addUserMessage: false);
    } catch (error) {
      debugPrint('不動産計算開始エラー: $error');

      if (!mounted) return;

      setState(() {
        _lastFailedInput = inputText;
        _messages.add(
          'ハヤト: 通信できませんでした。'
          '接続を確認して、再試行してください。',
        );
      });

      _scrollToBottom();
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  static String strValue(Object? value, {String fallback = ''}) {
    final text = value?.toString().trim() ?? '';
    return text.isEmpty ? fallback : text;
  }

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('不動産売却計算')),
      body: Column(
        children: [
          if (_calculationPending)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              color: Theme.of(context).colorScheme.primaryContainer,
              child: Row(
                children: [
                  const Expanded(
                    child: Text(
                      '計算を継続中です。'
                      '条件の追加・変更ができます。',
                    ),
                  ),
                  const SizedBox(width: 8),
                  TextButton(
                    onPressed: _isLoading ? null : () => _finishCalculation(),
                    child: const Text('計算終了'),
                  ),
                ],
              ),
            ),
          Expanded(
            child: ListView.builder(
              controller: _scrollController,
              reverse: true,
              padding: const EdgeInsets.all(16),
              itemCount: _messages.length,
              itemBuilder: (_, index) {
                final messageIndex = _messages.length - 1 - index;

                return Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Text(_messages[messageIndex]),
                );
              },
            ),
          ),
          if (_lastFailedInput != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: Align(
                alignment: Alignment.centerLeft,
                child: OutlinedButton.icon(
                  onPressed: _isLoading ? null : _retryLastRequest,
                  icon: const Icon(Icons.refresh),
                  label: const Text('再試行'),
                ),
              ),
            ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _controller,
                    minLines: 1,
                    maxLines: 4,
                    enabled: !_isLoading,
                    onSubmitted: (_) => _send(),
                    decoration: InputDecoration(
                      hintText: _selectingCase
                          ? '利用する案件の番号を入力'
                          : _calculationPending
                          ? '条件の追加・変更、'
                                'または「計算終了」と入力'
                          : '不動産売却の条件を入力',
                      border: const OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton(
                  onPressed: _isLoading ? null : _send,
                  icon: _isLoading
                      ? const SizedBox(
                          width: 24,
                          height: 24,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.send),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
