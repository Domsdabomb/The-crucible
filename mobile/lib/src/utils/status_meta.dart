import 'package:flutter/material.dart';

/// Display metadata for the API's job statuses and priorities.
/// Statuses are lowercase snake_case per API_CONTRACT.md.
class StatusMeta {
  /// All valid statuses, in rough workflow order.
  static const List<String> jobStatuses = [
    'received',
    'diagnosed',
    'awaiting_parts',
    'in_repair',
    'quality_check',
    'ready',
    'picked_up',
    'cancelled',
    'warranty_return',
    'closed',
  ];

  static const List<String> priorities = ['low', 'normal', 'high', 'urgent'];

  /// 'in_repair' -> 'In Repair'.
  static String label(String snake) {
    if (snake.isEmpty) return '—';
    return snake
        .split('_')
        .map((w) => w.isEmpty ? w : '${w[0].toUpperCase()}${w.substring(1)}')
        .join(' ');
  }

  /// A stable color per status for chips and timeline dots.
  static Color color(String status) {
    switch (status) {
      case 'received':
        return Colors.blueGrey;
      case 'diagnosed':
        return Colors.indigo;
      case 'awaiting_parts':
        return Colors.orange;
      case 'in_repair':
        return Colors.blue;
      case 'quality_check':
        return Colors.teal;
      case 'ready':
        return Colors.green;
      case 'picked_up':
      case 'closed':
        return Colors.grey;
      case 'cancelled':
        return Colors.red;
      case 'warranty_return':
        return Colors.purple;
      default:
        return Colors.blueGrey;
    }
  }

  static Color priorityColor(String priority) {
    switch (priority) {
      case 'urgent':
        return Colors.red;
      case 'high':
        return Colors.orange;
      case 'low':
        return Colors.blueGrey;
      default:
        return Colors.green;
    }
  }
}
