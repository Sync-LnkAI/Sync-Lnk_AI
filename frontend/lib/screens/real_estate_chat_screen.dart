import 'package:material_ui/material_ui.dart';

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

  final _api = RealEstateApiService(baseUrl: 'http://127.0.0.1:8000');

  bool _calculationPending = false;
  bool _isLoading = false;
  String? _lastFailedInput;

  Future<void> _scrollToBottom() async {
    await Future<void>.delayed(const Duration(milliseconds: 100));

    if (!mounted || !_scrollController.hasClients) return;

    await _scrollController.animateTo(
      _scrollController.position.maxScrollExtent,
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeOut,
    );
  }

  bool _isFinishCommand(String text) {
    final normalized = text.replaceAll(RegExp(r'\s+'), '');

    return normalized == '計算終了' || normalized == '計算を終了' || normalized == '終了';
  }

  void _finishCalculation({bool addUserMessage = false}) {
    setState(() {
      if (addUserMessage) {
        _messages.add('あなた: 計算終了');
      }

      _previousArguments.clear();
      _calculationPending = false;
      _messages.add('ハヤト: 計算を終了しました。');
    });

    _controller.clear();
  }

  void _retryLastRequest() {
    if (_lastFailedInput == null || _isLoading) return;
    _send();
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    final retryText = text.isEmpty ? _lastFailedInput : null;
    final inputText = retryText ?? text;
    if (inputText.isEmpty || _isLoading) return;

    if (_calculationPending && _isFinishCommand(inputText)) {
      _finishCalculation(addUserMessage: true);
      return;
    }

    setState(() {
      if (retryText == null) {
        _messages.add('あなた: $inputText');
      }
      _isLoading = true;
    });
    _scrollToBottom();
    _controller.clear();

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

      final reply = response.status == 'missing_fields'
          ? response.followUpMessage
          : response.status == 'success'
          ? response.resultMessage
          : '不動産売却計算の対象ではありません。';

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

      setState(() {
        _lastFailedInput = inputText;
        _messages.add('ハヤト: 通信できませんでした。接続を確認して、再試行してください。');
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
                  const Expanded(child: Text('計算を継続中です。条件の追加・変更ができます。')),
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
                      hintText: _calculationPending
                          ? '条件の追加・変更、または「計算終了」と入力'
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
