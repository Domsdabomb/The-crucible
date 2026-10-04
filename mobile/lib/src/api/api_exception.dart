/// Typed error thrown by [ApiClient] for non-2xx API responses.
/// Mirrors the contract's `{"error": {"code", "message"}}` shape.
class ApiException implements Exception {
  ApiException({required this.status, required this.code, required this.message});

  final int status;
  final String code;
  final String message;

  /// True when the token is missing/invalid/revoked — the UI should log out.
  bool get isUnauthorized => status == 401 && code == 'unauthorized';

  /// True when the account is temporarily locked after failed logins.
  bool get isAccountLocked => status == 423;

  @override
  String toString() => 'ApiException($status, $code): $message';
}
