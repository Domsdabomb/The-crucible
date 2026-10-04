/// Job models — brief (list) and full (detail) shapes from API_CONTRACT.md.
library;

class CustomerRef {
  const CustomerRef({required this.id, required this.name, required this.phone});

  final int id;
  final String name;
  final String phone;

  factory CustomerRef.fromJson(Map<String, dynamic> json) => CustomerRef(
        id: (json['id'] as num).toInt(),
        name: (json['name'] as String?) ?? '',
        phone: (json['phone'] as String?) ?? '',
      );
}

class DeviceRef {
  const DeviceRef({required this.make, required this.model});

  final String make;
  final String model;

  String get label => '$make $model'.trim();

  factory DeviceRef.fromJson(Map<String, dynamic> json) => DeviceRef(
        make: (json['make'] as String?) ?? '',
        model: (json['model'] as String?) ?? '',
      );
}

class TechnicianRef {
  const TechnicianRef({required this.id, required this.name});

  final int id;
  final String name;

  factory TechnicianRef.fromJson(Map<String, dynamic> json) => TechnicianRef(
        id: (json['id'] as num).toInt(),
        name: (json['name'] as String?) ?? '',
      );
}

/// Compact job shape returned by `GET /jobs` and `GET /dashboard`.
class JobBrief {
  const JobBrief({
    required this.id,
    required this.status,
    required this.priority,
    required this.createdAt,
    this.promisedDate,
    required this.totalCents,
    required this.customer,
    required this.device,
    this.technician,
  });

  final int id;
  final String status;
  final String priority;
  final String createdAt;
  final String? promisedDate;
  final int totalCents;
  final CustomerRef customer;
  final DeviceRef device;
  final TechnicianRef? technician;

  factory JobBrief.fromJson(Map<String, dynamic> json) {
    final tech = json['technician'];
    return JobBrief(
      id: (json['id'] as num).toInt(),
      status: (json['status'] as String?) ?? '',
      priority: (json['priority'] as String?) ?? 'normal',
      createdAt: (json['created_at'] as String?) ?? '',
      promisedDate: json['promised_date'] as String?,
      totalCents: (json['total_cents'] as num?)?.toInt() ?? 0,
      customer: CustomerRef.fromJson(
          (json['customer'] as Map<String, dynamic>?) ?? const {}),
      device: DeviceRef.fromJson(
          (json['device'] as Map<String, dynamic>?) ?? const {}),
      technician: tech is Map<String, dynamic>
          ? TechnicianRef.fromJson(tech)
          : null,
    );
  }
}

/// One row of the repair timeline (`job_status_history`).
class JobHistoryEntry {
  const JobHistoryEntry({
    this.oldStatus,
    required this.newStatus,
    required this.changedBy,
    this.note,
    required this.changedAt,
  });

  final String? oldStatus;
  final String newStatus;
  final String changedBy;
  final String? note;
  final String changedAt;

  factory JobHistoryEntry.fromJson(Map<String, dynamic> json) =>
      JobHistoryEntry(
        oldStatus: json['old_status'] as String?,
        newStatus: (json['new_status'] as String?) ?? '',
        changedBy: (json['changed_by'] as String?) ?? '',
        note: json['note'] as String?,
        changedAt: (json['changed_at'] as String?) ?? '',
      );
}

/// Full job shape from `GET /jobs/{id}`.
class JobDetail {
  const JobDetail({
    required this.id,
    required this.status,
    required this.priority,
    this.description,
    this.diagnosisNotes,
    required this.quotedCents,
    required this.depositCents,
    required this.labourCents,
    required this.partsCents,
    required this.gstCents,
    required this.pstCents,
    required this.totalCents,
    this.promisedDate,
    required this.createdAt,
    required this.updatedAt,
    required this.customer,
    required this.device,
    this.technician,
    required this.history,
  });

  final int id;
  final String status;
  final String priority;
  final String? description;
  final String? diagnosisNotes;
  final int quotedCents;
  final int depositCents;
  final int labourCents;
  final int partsCents;
  final int gstCents;
  final int pstCents;
  final int totalCents;
  final String? promisedDate;
  final String createdAt;
  final String updatedAt;
  final CustomerRef customer;
  final DeviceFull device;
  final TechnicianRef? technician;
  final List<JobHistoryEntry> history;

  /// Balance still owed on the job (total minus deposit), in cents.
  int get balanceCents => totalCents - depositCents;

  factory JobDetail.fromJson(Map<String, dynamic> json) {
    final tech = json['technician'];
    final rawHistory = json['history'] as List<dynamic>? ?? const [];
    int cents(Object? v) => (v as num?)?.toInt() ?? 0;
    return JobDetail(
      id: (json['id'] as num).toInt(),
      status: (json['status'] as String?) ?? '',
      priority: (json['priority'] as String?) ?? 'normal',
      description: json['description'] as String?,
      diagnosisNotes: json['diagnosis_notes'] as String?,
      quotedCents: cents(json['quoted_cents']),
      depositCents: cents(json['deposit_cents']),
      labourCents: cents(json['labour_cents']),
      partsCents: cents(json['parts_cents']),
      gstCents: cents(json['gst_cents']),
      pstCents: cents(json['pst_cents']),
      totalCents: cents(json['total_cents']),
      promisedDate: json['promised_date'] as String?,
      createdAt: (json['created_at'] as String?) ?? '',
      updatedAt: (json['updated_at'] as String?) ?? '',
      customer: CustomerRef.fromJson(
          (json['customer'] as Map<String, dynamic>?) ?? const {}),
      device: DeviceFull.fromJson(
          (json['device'] as Map<String, dynamic>?) ?? const {}),
      technician: tech is Map<String, dynamic>
          ? TechnicianRef.fromJson(tech)
          : null,
      history: rawHistory
          .whereType<Map<String, dynamic>>()
          .map(JobHistoryEntry.fromJson)
          .toList(growable: false),
    );
  }
}

/// Device shape on the full job (passcode is never exposed by the API).
class DeviceFull {
  const DeviceFull({
    required this.id,
    required this.make,
    required this.model,
    this.serialImei,
    this.conditionNotes,
  });

  final int id;
  final String make;
  final String model;
  final String? serialImei;
  final String? conditionNotes;

  String get label => '$make $model'.trim();

  factory DeviceFull.fromJson(Map<String, dynamic> json) => DeviceFull(
        id: (json['id'] as num?)?.toInt() ?? 0,
        make: (json['make'] as String?) ?? '',
        model: (json['model'] as String?) ?? '',
        serialImei: json['serial_imei'] as String?,
        conditionNotes: json['condition_notes'] as String?,
      );
}
