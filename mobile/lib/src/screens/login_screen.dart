import 'package:flutter/material.dart';

import '../api/api_exception.dart';
import '../config.dart';
import '../state/session.dart';

/// Login with a Staff / Customer toggle.
/// Staff sign in with username, customers with phone number.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.session});

  final Session session;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _idController = TextEditingController();
  final _passwordController = TextEditingController();

  bool _isStaff = true;
  bool _busy = false;
  bool _obscure = true;
  String? _error;

  @override
  void dispose() {
    _idController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (_isStaff) {
        await widget.session
            .loginStaff(_idController.text, _passwordController.text);
      } else {
        await widget.session
            .loginCustomer(_idController.text, _passwordController.text);
      }
      // Success: the app root rebuilds on session change.
    } on ApiException catch (e) {
      setState(() {
        _error = switch (e.code) {
          'invalid_credentials' =>
            'Wrong ${_isStaff ? 'username' : 'phone number'} or password.',
          'account_locked' =>
            'Account locked after too many attempts — try again in 15 minutes.',
          'rate_limited' => 'Too many attempts — wait a moment and retry.',
          _ => e.message,
        };
      });
    } catch (_) {
      setState(() {
        _error = 'Could not reach the server. Check your connection.';
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Icon(Icons.build_circle,
                        size: 64, color: Colors.deepOrange),
                    const SizedBox(height: 12),
                    Text(kAppName,
                        textAlign: TextAlign.center,
                        style: Theme.of(context)
                            .textTheme
                            .headlineMedium
                            ?.copyWith(fontWeight: FontWeight.bold)),
                    const SizedBox(height: 4),
                    const Text("Dom's Tech Repair — shop app",
                        textAlign: TextAlign.center,
                        style: TextStyle(color: Colors.grey)),
                    const SizedBox(height: 24),
                    SegmentedButton<bool>(
                      segments: const [
                        ButtonSegment(
                            value: true,
                            label: Text('Staff'),
                            icon: Icon(Icons.badge)),
                        ButtonSegment(
                            value: false,
                            label: Text('Customer'),
                            icon: Icon(Icons.person)),
                      ],
                      selected: {_isStaff},
                      onSelectionChanged: (s) =>
                          setState(() => _isStaff = s.first),
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: _idController,
                      keyboardType: _isStaff
                          ? TextInputType.text
                          : TextInputType.phone,
                      autocorrect: false,
                      decoration: InputDecoration(
                        labelText:
                            _isStaff ? 'Username' : 'Phone (+1XXXXXXXXXX)',
                        prefixIcon: Icon(
                            _isStaff ? Icons.person : Icons.phone),
                        border: const OutlineInputBorder(),
                      ),
                      validator: (v) =>
                          (v == null || v.trim().isEmpty) ? 'Required' : null,
                    ),
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: _passwordController,
                      obscureText: _obscure,
                      decoration: InputDecoration(
                        labelText: 'Password',
                        prefixIcon: const Icon(Icons.lock),
                        border: const OutlineInputBorder(),
                        suffixIcon: IconButton(
                          icon: Icon(_obscure
                              ? Icons.visibility
                              : Icons.visibility_off),
                          onPressed: () =>
                              setState(() => _obscure = !_obscure),
                        ),
                      ),
                      validator: (v) =>
                          (v == null || v.isEmpty) ? 'Required' : null,
                      onFieldSubmitted: (_) => _submit(),
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.red.withValues(alpha: 0.08),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(
                              color: Colors.red.withValues(alpha: 0.3)),
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.error_outline,
                                color: Colors.red, size: 20),
                            const SizedBox(width: 8),
                            Expanded(
                                child: Text(_error!,
                                    style: const TextStyle(
                                        color: Colors.red))),
                          ],
                        ),
                      ),
                    ],
                    const SizedBox(height: 16),
                    FilledButton(
                      onPressed: _busy ? null : _submit,
                      child: _busy
                          ? const SizedBox(
                              height: 20,
                              width: 20,
                              child: CircularProgressIndicator(
                                  strokeWidth: 2, color: Colors.white),
                            )
                          : const Text('Sign in'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
