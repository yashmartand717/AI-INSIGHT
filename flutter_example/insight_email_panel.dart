import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

/// Pass GyanBuddy's authenticated HTTP client. AI and SMTP secrets stay in Django.
class InsightsApi {
  final Uri baseUri; // e.g. https://api.your-school.example/api/insights/
  final http.Client client;
  InsightsApi(this.baseUri, this.client);

  Future<Map<String, dynamic>> _call(String path, {bool post = false}) async {
    final uri = baseUri.resolve(path);
    final response = await (post
        ? client.post(uri, headers: {'Content-Type': 'application/json'}, body: '{}')
        : client.get(uri)).timeout(const Duration(seconds: 30));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('Request failed (${response.statusCode}): ${response.body}');
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> status(String batchId) => _call('batches/$batchId/');
  Future<Map<String, dynamic>> emailPlan(String batchId) => _call('batches/$batchId/emails/');
  Future<Map<String, dynamic>> sendAll(String batchId) => _call('batches/$batchId/emails/', post: true);
}

/// Show after the existing marks upload returns `insight_batch_id`.
class InsightEmailPanel extends StatefulWidget {
  final String batchId;
  final InsightsApi api;
  const InsightEmailPanel({super.key, required this.batchId, required this.api});
  @override
  State<InsightEmailPanel> createState() => _InsightEmailPanelState();
}

class _InsightEmailPanelState extends State<InsightEmailPanel> {
  Map<String, dynamic>? status;
  String? error;
  bool busy = false;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    refresh();
    timer = Timer.periodic(const Duration(seconds: 5), (_) => refresh());
  }

  @override
  void didUpdateWidget(covariant InsightEmailPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.batchId != widget.batchId) {
      status = null;
      error = null;
      refresh();
    }
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> refresh() async {
    if (busy) return;
    final id = widget.batchId;
    busy = true;
    try {
      final data = await widget.api.status(id);
      if (mounted && widget.batchId == id) setState(() { status = data; error = null; });
    } catch (e) {
      if (mounted && widget.batchId == id) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> send() async {
    if (busy) return;
    final id = widget.batchId;
    setState(() { busy = true; error = null; });
    try {
      final data = await widget.api.sendAll(id);
      if (mounted && widget.batchId == id) setState(() => status = data);
    } catch (e) {
      if (mounted && widget.batchId == id) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final ready = status?['status'] == 'ready';
    final published = status?['status'] == 'published';
    final states = (status?['email_states'] as Map<String, dynamic>?) ?? {};
    return Card(child: Padding(padding: const EdgeInsets.all(20), child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Student insight emails', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 12),
        Text('${status?['ready_students'] ?? 0} of ${status?['total_students'] ?? 0} student reports ready'),
        const Text('Parents receive their children’s reports. Teachers and principals receive combined reports for their assigned students.'),
        if (status?['status'] == 'failed') const Text('Some reports need attention. Ask the administrator to check the generation log.'),
        if (published) Text('Email server accepted: ${states['sent'] ?? 0}. Queued: ${states['pending'] ?? 0}. Sending: ${states['sending'] ?? 0}. Needs attention: ${(states['blocked'] ?? 0) + (states['uncertain'] ?? 0)}.'),
        if (error != null) Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        const SizedBox(height: 12),
        FilledButton.icon(onPressed: ready && !busy ? send : null,
          icon: const Icon(Icons.email_outlined),
          label: Text(published ? 'Emails queued' : busy ? 'Please wait…' : 'Email all reports')),
        TextButton(onPressed: busy ? null : refresh, child: const Text('Refresh status')),
      ],
    )));
  }
}
