/// Invoice shape from API_CONTRACT.md. All money is integer cents.
class Invoice {
  const Invoice({
    required this.id,
    required this.jobId,
    required this.customerId,
    required this.customerName,
    required this.labourCents,
    required this.partsCents,
    required this.gstCents,
    required this.pstCents,
    required this.subtotalCents,
    required this.coinsApplied,
    required this.discountCents,
    required this.amountDueCents,
    required this.status,
    this.paidAt,
    this.notes,
    required this.createdAt,
  });

  final int id;
  final int jobId;
  final int customerId;
  final String customerName;
  final int labourCents;
  final int partsCents;
  final int gstCents;
  final int pstCents;
  final int subtotalCents;
  final int coinsApplied;
  final int discountCents;
  final int amountDueCents;
  final String status;
  final String? paidAt;
  final String? notes;
  final String createdAt;

  bool get isPaid => status == 'paid';

  factory Invoice.fromJson(Map<String, dynamic> json) {
    int cents(Object? v) => (v as num?)?.toInt() ?? 0;
    return Invoice(
      id: (json['id'] as num).toInt(),
      jobId: (json['job_id'] as num?)?.toInt() ?? 0,
      customerId: (json['customer_id'] as num?)?.toInt() ?? 0,
      customerName: (json['customer_name'] as String?) ?? '',
      labourCents: cents(json['labour_cents']),
      partsCents: cents(json['parts_cents']),
      gstCents: cents(json['gst_cents']),
      pstCents: cents(json['pst_cents']),
      subtotalCents: cents(json['subtotal_cents']),
      coinsApplied: (json['coins_applied'] as num?)?.toInt() ?? 0,
      discountCents: cents(json['discount_cents']),
      amountDueCents: cents(json['amount_due_cents']),
      status: (json['status'] as String?) ?? 'unpaid',
      paidAt: json['paid_at'] as String?,
      notes: json['notes'] as String?,
      createdAt: (json['created_at'] as String?) ?? '',
    );
  }
}
