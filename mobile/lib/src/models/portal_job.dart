import 'job.dart';

/// One job in the customer portal timeline (`GET /portal/timeline`).
class PortalJob {
  const PortalJob({
    required this.id,
    required this.status,
    required this.priority,
    required this.createdAt,
    this.promisedDate,
    required this.totalCents,
    required this.device,
    required this.history,
  });

  final int id;
  final String status;
  final String priority;
  final String createdAt;
  final String? promisedDate;
  final int totalCents;
  final DeviceRef device;
  final List<JobHistoryEntry> history;

  factory PortalJob.fromJson(Map<String, dynamic> json) {
    final rawHistory = json['history'] as List<dynamic>? ?? const [];
    return PortalJob(
      id: (json['id'] as num).toInt(),
      status: (json['status'] as String?) ?? '',
      priority: (json['priority'] as String?) ?? 'normal',
      createdAt: (json['created_at'] as String?) ?? '',
      promisedDate: json['promised_date'] as String?,
      totalCents: (json['total_cents'] as num?)?.toInt() ?? 0,
      device: DeviceRef.fromJson(
          (json['device'] as Map<String, dynamic>?) ?? const {}),
      history: rawHistory
          .whereType<Map<String, dynamic>>()
          .map(JobHistoryEntry.fromJson)
          .toList(growable: false),
    );
  }
}
