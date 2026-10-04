import 'package:flutter/material.dart';

import '../models/job.dart';
import '../utils/format.dart';
import '../utils/status_meta.dart';

/// Vertical timeline of a job's status history (oldest first).
/// The latest entry is highlighted as the current step.
class RepairTimeline extends StatelessWidget {
  const RepairTimeline({super.key, required this.history});

  final List<JobHistoryEntry> history;

  @override
  Widget build(BuildContext context) {
    if (history.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 12),
        child: Text('No history yet.',
            style: TextStyle(color: Colors.grey)),
      );
    }
    return Column(
      children: [
        for (var i = 0; i < history.length; i++)
          _TimelineRow(
            entry: history[i],
            isFirst: i == 0,
            isLast: i == history.length - 1,
            isCurrent: i == history.length - 1,
          ),
      ],
    );
  }
}

class _TimelineRow extends StatelessWidget {
  const _TimelineRow({
    required this.entry,
    required this.isFirst,
    required this.isLast,
    required this.isCurrent,
  });

  final JobHistoryEntry entry;
  final bool isFirst;
  final bool isLast;
  final bool isCurrent;

  @override
  Widget build(BuildContext context) {
    final color = StatusMeta.color(entry.newStatus);
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: 28,
            child: Column(
              children: [
                Expanded(
                  child: Container(
                    width: 2,
                    color: isFirst
                        ? Colors.transparent
                        : Colors.grey.withValues(alpha: 0.35),
                  ),
                ),
                Container(
                  width: isCurrent ? 16 : 12,
                  height: isCurrent ? 16 : 12,
                  decoration: BoxDecoration(
                    color: isCurrent ? color : Colors.white,
                    border: Border.all(color: color, width: 2.5),
                    shape: BoxShape.circle,
                  ),
                ),
                Expanded(
                  child: Container(
                    width: 2,
                    color: isLast
                        ? Colors.transparent
                        : Colors.grey.withValues(alpha: 0.35),
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(left: 8, bottom: 18, top: 2),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          StatusMeta.label(entry.newStatus),
                          style: TextStyle(
                            fontWeight:
                                isCurrent ? FontWeight.bold : FontWeight.w600,
                            fontSize: isCurrent ? 16 : 14,
                          ),
                        ),
                      ),
                      if (isCurrent)
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 8, vertical: 2),
                          decoration: BoxDecoration(
                            color: color.withValues(alpha: 0.14),
                            borderRadius: BorderRadius.circular(999),
                          ),
                          child: Text('current',
                              style: TextStyle(
                                  color: color,
                                  fontSize: 11,
                                  fontWeight: FontWeight.w600)),
                        ),
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text(
                    formatDateTime(entry.changedAt),
                    style: const TextStyle(color: Colors.grey, fontSize: 12),
                  ),
                  if (entry.changedBy.isNotEmpty)
                    Text(
                      'by ${entry.changedBy}',
                      style:
                          const TextStyle(color: Colors.grey, fontSize: 12),
                    ),
                  if (entry.note != null && entry.note!.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(entry.note!),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
