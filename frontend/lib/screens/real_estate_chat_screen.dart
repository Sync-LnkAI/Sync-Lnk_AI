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

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _isLoading) return;

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
        _calculationPending = response.status == 'missing_fields';
      });
    } catch (error) {
      setState(() => _messages.add('エラー: $error'));
    } finally {
      setState(() => _isLoading = false);
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
                    onSubmitted: (_) => _send(),
                    decoration: const InputDecoration(
                      hintText: '不動産売却の条件を入力',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton(
                  onPressed: _isLoading ? null : _send,
                  icon: _isLoading
                      ? const CircularProgressIndicator()
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
