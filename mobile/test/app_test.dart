// Unit tests for the pure-Dart helpers (no widgets, no network).
import 'package:crucible/src/models/auth_session.dart';
import 'package:crucible/src/models/job.dart';
import 'package:crucible/src/utils/format.dart';
import 'package:crucible/src/utils/status_meta.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('formatCents', () {
    test('formats cents as dollars', () {
      expect(formatCents(11200), '\$112.00');
      expect(formatCents(0), '\$0.00');
      expect(formatCents(99), '\$0.99');
    });
  });

  group('parseDollarsToCents', () {
    test('parses valid amounts', () {
      expect(parseDollarsToCents('112'), 11200);
      expect(parseDollarsToCents('112.50'), 11250);
      expect(parseDollarsToCents('\$1,234.56'), 123456);
    });
    test('rejects garbage', () {
      expect(parseDollarsToCents(''), isNull);
      expect(parseDollarsToCents('abc'), isNull);
      expect(parseDollarsToCents('-5'), isNull);
    });
  });

  group('StatusMeta.label', () {
    test('humanizes snake_case', () {
      expect(StatusMeta.label('in_repair'), 'In Repair');
      expect(StatusMeta.label('awaiting_parts'), 'Awaiting Parts');
      expect(StatusMeta.label(''), '—');
    });
  });

  group('AuthSession.fromLoginJson', () {
    test('parses staff login', () {
      final s = AuthSession.fromLoginJson({
        'token': 'tok',
        'account_type': 'staff',
        'role': 'admin',
        'username': 'domsadmin',
      });
      expect(s.isStaff, isTrue);
      expect(s.isAdmin, isTrue);
      expect(s.displayName, 'domsadmin');
    });
    test('parses customer login', () {
      final s = AuthSession.fromLoginJson({
        'token': 'tok',
        'account_type': 'customer',
        'customer_id': 7,
        'name': 'Jane Doe',
      });
      expect(s.isCustomer, isTrue);
      expect(s.customerId, 7);
      expect(s.displayName, 'Jane Doe');
    });
  });

  group('JobBrief.fromJson', () {
    test('handles null technician', () {
      final j = JobBrief.fromJson({
        'id': 12,
        'status': 'received',
        'priority': 'high',
        'created_at': '2026-10-03T18:22:10.000Z',
        'total_cents': 13440,
        'customer': {'id': 7, 'name': 'Jane', 'phone': '+16045550101'},
        'device': {'make': 'Apple', 'model': 'iPhone 14'},
        'technician': null,
      });
      expect(j.technician, isNull);
      expect(j.device.label, 'Apple iPhone 14');
    });
  });
}
