import 'package:flutter/material.dart';

import '../api/api_exception.dart';
import '../models/customer.dart';
import '../models/paged.dart';
import '../state/session.dart';
import '../widgets/empty_state.dart';
import 'customer_detail_screen.dart';

/// Admin customer list with search and pagination.
class CustomersScreen extends StatefulWidget {
  const CustomersScreen({super.key, required this.session});

  final Session session;

  @override
  State<CustomersScreen> createState() => _CustomersScreenState();
}

class _CustomersScreenState extends State<CustomersScreen> {
  final _searchController = TextEditingController();
  final _scrollController = ScrollController();

  List<Customer> _customers = [];
  bool _loading = true;
  bool _loadingMore = false;
  String? _error;
  String _search = '';
  int _page = 1;
  int _total = 0;
  static const _perPage = 20;

  @override
  void initState() {
    super.initState();
    _scrollController.addListener(_onScroll);
    _load(reset: true);
  }

  @override
  void dispose() {
    _searchController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (_scrollController.position.pixels >=
            _scrollController.position.maxScrollExtent - 200 &&
        !_loadingMore &&
        !_loading &&
        _customers.length < _total) {
      _loadMore();
    }
  }

  Future<void> _load({required bool reset}) async {
    setState(() {
      _loading = true;
      _error = null;
      if (reset) {
        _page = 1;
        _customers = [];
      }
    });
    try {
      final query = <String, String>{
        'page': '$_page',
        'per_page': '$_perPage',
      };
      if (_search.isNotEmpty) query['search'] = _search;
      final json = await widget.session.api.get('/customers', query: query);
      if (!mounted) return;
      final paged = Paged<Customer>.fromJson(json, Customer.fromJson);
      setState(() {
        _customers = paged.data;
        _total = paged.total;
        _loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = 'Could not reach the server.';
        _loading = false;
      });
    }
  }

  Future<void> _loadMore() async {
    setState(() => _loadingMore = true);
    try {
      final query = <String, String>{
        'page': '${_page + 1}',
        'per_page': '$_perPage',
      };
      if (_search.isNotEmpty) query['search'] = _search;
      final json = await widget.session.api.get('/customers', query: query);
      if (!mounted) return;
      final paged = Paged<Customer>.fromJson(json, Customer.fromJson);
      setState(() {
        _page += 1;
        _customers = [..._customers, ...paged.data];
        _total = paged.total;
        _loadingMore = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _loadingMore = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
            child: TextField(
              controller: _searchController,
              decoration: InputDecoration(
                hintText: 'Search name, phone, email…',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _search.isNotEmpty
                    ? IconButton(
                        icon: const Icon(Icons.clear),
                        onPressed: () {
                          _searchController.clear();
                          setState(() => _search = '');
                          _load(reset: true);
                        },
                      )
                    : null,
                border: const OutlineInputBorder(),
                isDense: true,
              ),
              textInputAction: TextInputAction.search,
              onSubmitted: (v) {
                setState(() => _search = v.trim());
                _load(reset: true);
              },
            ),
          ),
          Expanded(child: _buildList()),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.person_add),
        label: const Text('New customer'),
        onPressed: () => _showAddDialog(),
      ),
    );
  }

  Widget _buildList() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_error!, textAlign: TextAlign.center),
              const SizedBox(height: 12),
              FilledButton(
                  onPressed: () => _load(reset: true),
                  child: const Text('Retry')),
            ],
          ),
        ),
      );
    }
    if (_customers.isEmpty) {
      return const EmptyState(
        icon: Icons.people,
        title: 'No customers found',
        subtitle: 'Try a different search.',
      );
    }
    return RefreshIndicator(
      onRefresh: () => _load(reset: true),
      child: ListView.builder(
        controller: _scrollController,
        padding: const EdgeInsets.all(12),
        itemCount: _customers.length + (_loadingMore ? 1 : 0),
        itemBuilder: (context, i) {
          if (i >= _customers.length) {
            return const Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: CircularProgressIndicator()),
            );
          }
          final c = _customers[i];
          return Card(
            child: ListTile(
              leading: CircleAvatar(
                  child: Text(c.name.isEmpty ? '?' : c.name[0].toUpperCase())),
              title: Text(c.name),
              subtitle: Text(c.phone),
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => CustomerDetailScreen(
                      session: widget.session, customerId: c.id),
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  void _showAddDialog() {
    final name = TextEditingController();
    final phone = TextEditingController();
    final email = TextEditingController();
    bool busy = false;
    showDialog<void>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setState) => AlertDialog(
          title: const Text('New customer'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: name,
                decoration: const InputDecoration(
                    labelText: 'Full name', border: OutlineInputBorder()),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: phone,
                keyboardType: TextInputType.phone,
                decoration: const InputDecoration(
                  labelText: 'Phone (+1XXXXXXXXXX)',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: email,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(
                  labelText: 'Email (optional)',
                  border: OutlineInputBorder(),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Cancel')),
            FilledButton(
              onPressed: busy
                  ? null
                  : () async {
                      final n = name.text.trim();
                      final p = phone.text.trim();
                      if (n.isEmpty ||
                          !RegExp(r'^\+1\d{10}$').hasMatch(p)) {
                        ScaffoldMessenger.of(ctx).showSnackBar(
                          const SnackBar(
                              content: Text(
                                  'Name required; phone must be +1XXXXXXXXXX.')),
                        );
                        return;
                      }
                      setState(() => busy = true);
                      try {
                        final body = <String, dynamic>{
                          'name': n,
                          'phone': p,
                        };
                        if (email.text.trim().isNotEmpty) {
                          body['email'] = email.text.trim();
                        }
                        await widget.session.api
                            .post('/customers', body: body);
                        if (ctx.mounted) Navigator.pop(ctx);
                        _load(reset: true);
                      } on ApiException catch (e) {
                        if (ctx.mounted) {
                          ScaffoldMessenger.of(ctx).showSnackBar(SnackBar(
                              content: Text(e.message),
                              backgroundColor: Colors.red.shade700));
                        }
                        setState(() => busy = false);
                      }
                    },
              child: const Text('Add'),
            ),
          ],
        ),
      ),
    );
  }
}
