/// Generic paginated list shape from the API contract.
class Paged<T> {
  const Paged({
    required this.data,
    required this.page,
    required this.perPage,
    required this.total,
  });

  final List<T> data;
  final int page;
  final int perPage;
  final int total;

  bool get hasMore => data.length < total;

  factory Paged.fromJson(
    Map<String, dynamic> json,
    T Function(Map<String, dynamic>) fromJson,
  ) {
    final raw = json['data'] as List<dynamic>? ?? const [];
    return Paged(
      data: raw
          .whereType<Map<String, dynamic>>()
          .map(fromJson)
          .toList(growable: false),
      page: (json['page'] as num?)?.toInt() ?? 1,
      perPage: (json['per_page'] as num?)?.toInt() ?? raw.length,
      total: (json['total'] as num?)?.toInt() ?? raw.length,
    );
  }
}
