import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config.dart';
import 'api_exception.dart';

/// Thin HTTP client for the Crucible JSON API (v1).
///
/// - Attaches `Authorization: Bearer <token>` when a token is set.
/// - Parses the contract's `{"error": {"code", "message"}}` shape into
///   [ApiException].
/// - Calls [onUnauthorized] (fire-and-forget safe) on 401/unauthorized so
///   the app can drop the session and show the login screen.
class ApiClient {
  ApiClient({String? baseUrl, this.onUnauthorized})
      : baseUrl = baseUrl ?? '$kApiBaseUrl$kApiPathPrefix';

  final String baseUrl;

  /// Called (awaited) when a request gets 401/unauthorized.
  /// Settable so the app root can wire navigation-safe handling.
  Future<void> Function()? onUnauthorized;

  String? _token;
  final http.Client _http = http.Client();

  void setToken(String? token) => _token = token;

  Map<String, String> _headers({bool json = false}) {
    final headers = <String, String>{'Accept': 'application/json'};
    if (json) headers['Content-Type'] = 'application/json';
    if (_token != null && _token!.isNotEmpty) {
      headers['Authorization'] = 'Bearer $_token';
    }
    return headers;
  }

  Uri _uri(String path, [Map<String, String>? query]) {
    final base = Uri.parse(baseUrl);
    return base.replace(
      path: '${base.path}$path',
      queryParameters: query?.isEmpty ?? true ? null : query,
    );
  }

  Future<Map<String, dynamic>> get(String path,
      {Map<String, String>? query}) async {
    final res = await _http.get(_uri(path, query), headers: _headers());
    return _decode(res);
  }

  Future<Map<String, dynamic>> post(String path,
      {Map<String, dynamic>? body}) async {
    final res = await _http.post(
      _uri(path),
      headers: _headers(json: true),
      body: body == null ? null : jsonEncode(body),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> patch(String path,
      {Map<String, dynamic>? body}) async {
    final res = await _http.patch(
      _uri(path),
      headers: _headers(json: true),
      body: body == null ? null : jsonEncode(body),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> _decode(http.Response res) async {
    Map<String, dynamic> json = const {};
    if (res.body.isNotEmpty) {
      final decoded = jsonDecode(res.body);
      if (decoded is Map<String, dynamic>) json = decoded;
    }
    if (res.statusCode >= 200 && res.statusCode < 300) return json;

    String code = 'http_${res.statusCode}';
    String message = 'Request failed (${res.statusCode}).';
    final err = json['error'];
    if (err is Map<String, dynamic>) {
      code = (err['code'] as String?) ?? code;
      message = (err['message'] as String?) ?? message;
    }
    final ex =
        ApiException(status: res.statusCode, code: code, message: message);
    if (ex.isUnauthorized) {
      final cb = onUnauthorized;
      if (cb != null) await cb();
    }
    throw ex;
  }

  void dispose() => _http.close();
}
