import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../models/auth_session.dart';

/// Persists the login session in platform secure storage
/// (Android Keystore / iOS Keychain). The raw token is only ever
/// written here right after login and read back on app start.
class AuthStore {
  AuthStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  static const _kToken = 'crucible.token';
  static const _kAccountType = 'crucible.account_type';
  static const _kRole = 'crucible.role';
  static const _kUsername = 'crucible.username';
  static const _kCustomerId = 'crucible.customer_id';
  static const _kName = 'crucible.name';

  Future<void> save(AuthSession session) async {
    await _storage.write(key: _kToken, value: session.token);
    await _storage.write(key: _kAccountType, value: session.accountType);
    if (session.role != null) {
      await _storage.write(key: _kRole, value: session.role);
    } else {
      await _storage.delete(key: _kRole);
    }
    if (session.username != null) {
      await _storage.write(key: _kUsername, value: session.username);
    } else {
      await _storage.delete(key: _kUsername);
    }
    if (session.customerId != null) {
      await _storage.write(
          key: _kCustomerId, value: session.customerId.toString());
    } else {
      await _storage.delete(key: _kCustomerId);
    }
    if (session.displayName != null) {
      await _storage.write(key: _kName, value: session.displayName);
    } else {
      await _storage.delete(key: _kName);
    }
  }

  Future<AuthSession?> load() async {
    final token = await _storage.read(key: _kToken);
    final accountType = await _storage.read(key: _kAccountType);
    if (token == null || accountType == null) return null;
    final customerIdRaw = await _storage.read(key: _kCustomerId);
    return AuthSession(
      token: token,
      accountType: accountType,
      role: await _storage.read(key: _kRole),
      username: await _storage.read(key: _kUsername),
      customerId:
          customerIdRaw == null ? null : int.tryParse(customerIdRaw),
      displayName: await _storage.read(key: _kName),
    );
  }

  Future<void> clear() async {
    await _storage.deleteAll();
  }
}
