import 'package:flutter/material.dart';

import '../utils/status_meta.dart';

/// Small colored chip for a job status (or priority).
class StatusChip extends StatelessWidget {
  const StatusChip({super.key, required this.value, this.isPriority = false});

  final String value;
  final bool isPriority;

  @override
  Widget build(BuildContext context) {
    final color =
        isPriority ? StatusMeta.priorityColor(value) : StatusMeta.color(value);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Text(
        StatusMeta.label(value),
        style: TextStyle(
          color: color,
          fontWeight: FontWeight.w600,
          fontSize: 12,
        ),
      ),
    );
  }
}
