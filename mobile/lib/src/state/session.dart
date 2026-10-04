import 'package:flutter/foundation.dart';

import '../api/api_client.dart';
import '../api/api_exception.dart';
import '../api/auth_store.dart';
import '../config.dart';
import '../models/auth_session.dart';

/// Holds the login session and the API client for the whole app.
///
/// On start, [init] restores the token from secure storage. Any API call
/// that returns 401/unauthorized triggers the client's [onUnauthorized]
/// hook, which drops the session and sends the user back to login.
class Session extends ChangeNotifier {
  Session({AuthStore? store, ApiClient? client})
      : _store = store ?? AuthStore(),
        _client = client ?? ApiClient(baseUrl: '$kApiBaseUrl$kApiPathPrefix');

  final AuthStore _store;
  final ApiClient _client;

  AuthSession? _session;
  bool _ready = false;
  bool _loggingOut = false;

  AuthSession? get session => _session;
  bool get isLoggedIn => _session != null;
  bool get ready => _ready;

  /// The client the UI should use for all API calls.
  ApiClient get api => _client;

  Future<void> init() async {
    _client.onUnauthorized = handleUnauthorized;
    _session = await _store.load();
    _client.setToken(_session?.token);
    _ready = true;
    notifyListeners();
  }

  Future<void> _applySession(AuthSession s) async {
    await _store.save(s);
    _session = s;
    _client.setToken(s.token);
    notifyListeners();
  }

  /// Staff login with username + password.
  Future<void> loginStaff(String username, String password) async {
    final json = await _client.post('/auth/login', body: {
      'username': username.trim(),
      'password': password,
      'device_name': 'Crucible Android app',
    });
    await _applySession(AuthSession.fromLoginJson(json));
  }

  /// Customer login with phone + password.
  Future<void> loginCustomer(String phone, String password) async {
    final json = await _client.post('/auth/login', body: {
      'phone': phone.trim(),
      'password': password,
      'device_name': 'Crucible Android app',
    });
    await _applySession(AuthSession.fromLoginJson(json));
  }

  /// Best-effort server logout, then always clears local state.
  /// Guarded against re-entrancy: the unauthorized hook fires [logout]
  /// too, and the logout call itself can 401 when the token is dead.
  Future<void> logout() async {
    if (_loggingOut) return;
    _loggingOut = true;
    try {
      try {
        await _client.post('/auth/logout');
      } on ApiException {
        // Token may already be dead — clearing local state is what matters.
      }
      await _store.clear();
      _session = null;
      _client.setToken(null);
      notifyListeners();
    } finally {
      _loggingOut = false;
    }
  }

  /// Called when any API call gets 401/unauthorized.
  Future<void> handleUnauthorized() => logout();

  @override
  void dispose() {
    _client.dispose();
    super.dispose();
  }
}
