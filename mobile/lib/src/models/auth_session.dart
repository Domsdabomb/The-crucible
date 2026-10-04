/// The persisted login session, per API_CONTRACT.md's login responses.
class AuthSession {
  const AuthSession({
    required this.token,
    required this.accountType,
    this.role,
    this.username,
    this.customerId,
    this.displayName,
  });

  /// Opaque bearer token, shown once at login.
  final String token;

  /// 'staff' or 'customer'.
  final String accountType;

  /// Staff only: 'admin' or 'technician'.
  final String? role;

  /// Staff only.
  final String? username;

  /// Customer only.
  final int? customerId;

  /// Staff: username. Customer: name.
  final String? displayName;

  bool get isStaff => accountType == 'staff';
  bool get isCustomer => accountType == 'customer';
  bool get isAdmin => isStaff && role == 'admin';
  bool get isTechnician => isStaff && role == 'technician';

  /// Builds a session from the `POST /auth/login` response body.
  factory AuthSession.fromLoginJson(Map<String, dynamic> json) {
    final accountType = json['account_type'] as String;
    return AuthSession(
      token: json['token'] as String,
      accountType: accountType,
      role: json['role'] as String?,
      username: json['username'] as String?,
      customerId: (json['customer_id'] as num?)?.toInt(),
      displayName: accountType == 'staff'
          ? json['username'] as String?
          : json['name'] as String?,
    );
  }
}
