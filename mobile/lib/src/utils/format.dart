import 'package:intl/intl.dart';

/// Money: the API speaks integer cents — the UI speaks dollars.
String formatCents(int cents) {
  final dollars = cents / 100.0;
  return NumberFormat.currency(locale: 'en_CA', symbol: '\$', decimalDigits: 2)
      .format(dollars);
}

/// Parses a dollars-and-cents text field into integer cents.
/// Returns null when the input isn't a valid non-negative amount.
int? parseDollarsToCents(String input) {
  final trimmed = input.trim().replaceAll(',', '').replaceAll('\$', '');
  if (trimmed.isEmpty) return null;
  final value = double.tryParse(trimmed);
  if (value == null || value < 0) return null;
  return (value * 100).round();
}

/// '2026-10-04T07:30:00.000Z' -> 'Oct 4, 2:30 AM' (device-local time).
String formatDateTime(String iso) {
  if (iso.isEmpty) return '—';
  try {
    final dt = DateTime.parse(iso).toLocal();
    return DateFormat('MMM d, h:mm a').format(dt);
  } catch (_) {
    return iso;
  }
}

/// '2026-10-08' (promised_date) -> 'Oct 8, 2026'.
String formatDate(String yyyyMmDd) {
  if (yyyyMmDd.isEmpty) return '—';
  try {
    final dt = DateTime.parse(yyyyMmDd);
    return DateFormat('MMM d, y').format(dt);
  } catch (_) {
    return yyyyMmDd;
  }
}
