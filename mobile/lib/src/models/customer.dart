/// Customer shape from API_CONTRACT.md.
class Customer {
  const Customer({
    required this.id,
    required this.name,
    required this.phone,
    this.email,
    required this.createdAt,
  });

  final int id;
  final String name;
  final String phone;
  final String? email;
  final String createdAt;

  factory Customer.fromJson(Map<String, dynamic> json) => Customer(
        id: (json['id'] as num).toInt(),
        name: (json['name'] as String?) ?? '',
        phone: (json['phone'] as String?) ?? '',
        email: json['email'] as String?,
        createdAt: (json['created_at'] as String?) ?? '',
      );
}
