import 'job.dart';

/// `GET /dashboard` response shape (staff admin only).
class DashboardData {
  const DashboardData({
    required this.collectedCents,
    required this.monthCents,
    required this.outstandingCents,
    required this.unpaidCount,
    required this.statusCounts,
    required this.recentJobs,
  });

  final int collectedCents;
  final int monthCents;
  final int outstandingCents;
  final int unpaidCount;
  final Map<String, int> statusCounts;
  final List<JobBrief> recentJobs;

  factory DashboardData.fromJson(Map<String, dynamic> json) {
    final revenue = (json['revenue'] as Map<String, dynamic>?) ?? const {};
    final counts = (json['status_counts'] as Map<String, dynamic>?) ?? const {};
    final recent = json['recent_jobs'] as List<dynamic>? ?? const [];
    int cents(Object? v) => (v as num?)?.toInt() ?? 0;
    return DashboardData(
      collectedCents: cents(revenue['collected_cents']),
      monthCents: cents(revenue['month_cents']),
      outstandingCents: cents(revenue['outstanding_cents']),
      unpaidCount: (revenue['unpaid_count'] as num?)?.toInt() ?? 0,
      statusCounts: {
        for (final e in counts.entries) e.key: (e.value as num?)?.toInt() ?? 0,
      },
      recentJobs: recent
          .whereType<Map<String, dynamic>>()
          .map(JobBrief.fromJson)
          .toList(growable: false),
    );
  }
}
