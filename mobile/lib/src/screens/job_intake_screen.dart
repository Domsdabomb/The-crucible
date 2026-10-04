import 'package:flutter/material.dart';

import '../api/api_exception.dart';
import '../state/session.dart';
import '../utils/format.dart';
import '../utils/status_meta.dart';
import 'job_detail_screen.dart';

/// Admin-only new-job intake. Mirrors the web intake form:
/// upserts the customer by phone, creates device + job, seeds history,
/// fires the intake SMS server-side.
class JobIntakeScreen extends StatefulWidget {
  const JobIntakeScreen({super.key, required this.session});

  final Session session;

  @override
  State<JobIntakeScreen> createState() => _JobIntakeScreenState();
}

class _JobIntakeScreenState extends State<JobIntakeScreen> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _phone = TextEditingController();
  final _email = TextEditingController();
  final _make = TextEditingController();
  final _model = TextEditingController();
  final _serial = TextEditingController();
  final _passcode = TextEditingController();
  final _condition = TextEditingController();
  final _description = TextEditingController();
  final _quoted = TextEditingController();

  String _priority = 'normal';
  DateTime? _promisedDate;
  bool _busy = false;

  @override
  void dispose() {
    for (final c in [
      _name,
      _phone,
      _email,
      _make,
      _model,
      _serial,
      _passcode,
      _condition,
      _description,
      _quoted,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  String? _phoneValidator(String? v) {
    final t = (v ?? '').trim();
    if (t.isEmpty) return 'Required';
    if (!RegExp(r'^\+1\d{10}$').hasMatch(t)) {
      return 'Use Canadian E.164 format: +1XXXXXXXXXX';
    }
    return null;
  }

  Future<void> _pickDate() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: now.add(const Duration(days: 3)),
      firstDate: now,
      lastDate: now.add(const Duration(days: 365)),
    );
    if (picked != null) setState(() => _promisedDate = picked);
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _busy = true);
    try {
      final body = <String, dynamic>{
        'customer_name': _name.text.trim(),
        'customer_phone': _phone.text.trim(),
        'device_make': _make.text.trim(),
        'device_model': _model.text.trim(),
        'priority': _priority,
      };
      void addIf(String key, TextEditingController c) {
        final t = c.text.trim();
        if (t.isNotEmpty) body[key] = t;
      }

      addIf('customer_email', _email);
      addIf('device_serial', _serial);
      addIf('device_passcode', _passcode);
      addIf('device_condition', _condition);
      addIf('description', _description);
      if (_promisedDate != null) {
        body['promised_date'] =
            '${_promisedDate!.year.toString().padLeft(4, '0')}-'
            '${_promisedDate!.month.toString().padLeft(2, '0')}-'
            '${_promisedDate!.day.toString().padLeft(2, '0')}';
      }
      final quoted = _quoted.text.trim();
      if (quoted.isNotEmpty) {
        final cents = parseDollarsToCents(quoted);
        if (cents == null) {
          throw ApiException(
              status: 0, code: 'local', message: 'Invalid quoted amount.');
        }
        body['quoted_cents'] = cents;
      }

      final json = await widget.session.api.post('/jobs', body: body);
      if (!mounted) return;
      final jobId = (json['job_id'] as num).toInt();
      final sms = json['sms'];
      String? smsNote;
      if (sms is Map<String, dynamic> && sms['success'] != true) {
        smsNote = (sms['error_message'] as String?) ??
            'Intake SMS was not sent.';
      }
      if (!mounted) return;
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(
          builder: (_) =>
              JobDetailScreen(session: widget.session, jobId: jobId),
        ),
      );
      if (smsNote != null && mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(smsNote)));
      }
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content: Text(e.message),
            backgroundColor: Colors.red.shade700),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('New job intake')),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _Header('Customer'),
            _Field(controller: _name, label: 'Full name', icon: Icons.person),
            _Field(
                controller: _phone,
                label: 'Phone (+1XXXXXXXXXX)',
                icon: Icons.phone,
                keyboard: TextInputType.phone,
                validator: _phoneValidator),
            _Field(
                controller: _email,
                label: 'Email (optional)',
                icon: Icons.email,
                keyboard: TextInputType.emailAddress),
            const SizedBox(height: 8),
            _Header('Device'),
            _Field(controller: _make, label: 'Make (e.g. Apple)', icon: Icons.smartphone),
            _Field(controller: _model, label: 'Model (e.g. iPhone 14)', icon: Icons.phone_android),
            _Field(controller: _serial, label: 'Serial / IMEI (optional)', icon: Icons.numbers),
            _Field(controller: _passcode, label: 'Passcode (optional)', icon: Icons.key),
            _Field(controller: _condition, label: 'Condition notes (optional)', icon: Icons.notes, maxLines: 2),
            const SizedBox(height: 8),
            _Header('Repair'),
            _Field(controller: _description, label: 'Issue description', icon: Icons.build, maxLines: 3),
            DropdownButtonFormField<String>(
              initialValue: _priority,
              decoration: const InputDecoration(
                  labelText: 'Priority', border: OutlineInputBorder()),
              items: [
                for (final p in StatusMeta.priorities)
                  DropdownMenuItem(value: p, child: Text(StatusMeta.label(p))),
              ],
              onChanged: (v) => setState(() => _priority = v ?? 'normal'),
            ),
            const SizedBox(height: 12),
            _Field(controller: _quoted, label: 'Quoted price \$ (optional)', icon: Icons.attach_money, keyboard: const TextInputType.numberWithOptions(decimal: true)),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              icon: const Icon(Icons.calendar_today),
              label: Text(_promisedDate == null
                  ? 'Promised date (optional)'
                  : 'Promised: ${formatDate('${_promisedDate!.year.toString().padLeft(4, '0')}-${_promisedDate!.month.toString().padLeft(2, '0')}-${_promisedDate!.day.toString().padLeft(2, '0')}')}'),
              onPressed: _pickDate,
            ),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: _busy ? null : _submit,
              child: _busy
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: Colors.white))
                  : const Text('Create job'),
            ),
          ],
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8, top: 4),
      child: Text(text,
          style: Theme.of(context)
              .textTheme
              .titleSmall
              ?.copyWith(fontWeight: FontWeight.bold, color: Colors.deepOrange)),
    );
  }
}

class _Field extends StatelessWidget {
  const _Field({
    required this.controller,
    required this.label,
    required this.icon,
    this.keyboard,
    this.validator,
    this.maxLines = 1,
  });

  final TextEditingController controller;
  final String label;
  final IconData icon;
  final TextInputType? keyboard;
  final String? Function(String?)? validator;
  final int maxLines;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextFormField(
        controller: controller,
        keyboardType: keyboard,
        maxLines: maxLines,
        decoration: InputDecoration(
          labelText: label,
          prefixIcon: Icon(icon),
          border: const OutlineInputBorder(),
        ),
        validator: validator ??
            (v) => (v == null || v.trim().isEmpty) &&
                    !label.contains('optional')
                ? 'Required'
                : null,
      ),
    );
  }
}
