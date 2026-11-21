import 'package:material_ui/material_ui.dart';

import '../services/real_estate_api_service.dart';

class RealEstateChatScreen extends StatefulWidget {
  const RealEstateChatScreen({super.key});

  @override
  State<RealEstateChatScreen> createState() => _RealEstateChatScreenState();
}

class _RealEstateChatScreenState extends State<RealEstateChatScreen> {
  final _controller = TextEditingController();
  final _messages = <String>[];
  final _previousArguments = <String, dynamic>{};

  final _api = RealEstateApiService(baseUrl: 'http://127.0.0.1:8000');

  bool _calculationPending = false;
  bool _isLoading = false;

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

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _isLoading) return;

    if (_calculationPending && _isFinishCommand(text)) {
      _finishCalculation(addUserMessage: true);
      return;
    }

    setState(() {
      _messages.add('あなた: $text');
      _isLoading = true;
    });
    _controller.clear();

    try {
      final response = await _api.calculateFromText(
        userInput: text,
        calculationPending: _calculationPending,
        previousArguments: _previousArguments,
      );

      _previousArguments
        ..clear()
        ..addAll(response.arguments);

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
    } catch (error) {
      setState(() {
        _messages.add('エラー: $error');
      });
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
              padding: const EdgeInsets.all(16),
              itemCount: _messages.length,
              itemBuilder: (_, index) => Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(_messages[index]),
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
