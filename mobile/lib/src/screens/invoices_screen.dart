import 'package:flutter/material.dart';

import '../api/api_exception.dart';
import '../models/invoice.dart';
import '../models/paged.dart';
import '../state/session.dart';
import '../utils/format.dart';
import '../widgets/empty_state.dart';
import 'invoice_detail_screen.dart';

/// Admin invoice list with pagination.
class InvoicesScreen extends StatefulWidget {
  const InvoicesScreen({super.key, required this.session});

  final Session session;

  @override
  State<InvoicesScreen> createState() => _InvoicesScreenState();
}

class _InvoicesScreenState extends State<InvoicesScreen> {
  final _scrollController = ScrollController();

  List<Invoice> _invoices = [];
  bool _loading = true;
  bool _loadingMore = false;
  String? _error;
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
    _scrollController.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (_scrollController.position.pixels >=
            _scrollController.position.maxScrollExtent - 200 &&
        !_loadingMore &&
        !_loading &&
        _invoices.length < _total) {
      _loadMore();
    }
  }

  Future<void> _load({required bool reset}) async {
    setState(() {
      _loading = true;
      _error = null;
      if (reset) {
        _page = 1;
        _invoices = [];
      }
    });
    try {
      final json = await widget.session.api.get('/invoices', query: {
        'page': '$_page',
        'per_page': '$_perPage',
      });
      if (!mounted) return;
      final paged = Paged<Invoice>.fromJson(json, Invoice.fromJson);
      setState(() {
        _invoices = paged.data;
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
      final json = await widget.session.api.get('/invoices', query: {
        'page': '${_page + 1}',
        'per_page': '$_perPage',
      });
      if (!mounted) return;
      final paged = Paged<Invoice>.fromJson(json, Invoice.fromJson);
      setState(() {
        _page += 1;
        _invoices = [..._invoices, ...paged.data];
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
    if (_invoices.isEmpty) {
      return const EmptyState(
        icon: Icons.receipt_long,
        title: 'No invoices yet',
        subtitle: 'Create one from a job detail screen.',
      );
    }
    return RefreshIndicator(
      onRefresh: () => _load(reset: true),
      child: ListView.builder(
        controller: _scrollController,
        padding: const EdgeInsets.all(12),
        itemCount: _invoices.length + (_loadingMore ? 1 : 0),
        itemBuilder: (context, i) {
          if (i >= _invoices.length) {
            return const Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: CircularProgressIndicator()),
            );
          }
          final inv = _invoices[i];
          final paid = inv.isPaid;
          return Card(
            child: ListTile(
              leading: Icon(
                paid ? Icons.check_circle : Icons.pending,
                color: paid ? Colors.green : Colors.orange,
              ),
              title: Text('Invoice #${inv.id} · ${inv.customerName}'),
              subtitle: Text(
                  'Job #${inv.jobId} · ${formatDateTime(inv.createdAt)}'),
              trailing: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(formatCents(inv.amountDueCents),
                      style:
                          const TextStyle(fontWeight: FontWeight.bold)),
                  Text(paid ? 'Paid' : 'Unpaid',
                      style: TextStyle(
                          color: paid ? Colors.green : Colors.orange,
                          fontSize: 12)),
                ],
              ),
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => InvoiceDetailScreen(
                      session: widget.session, invoiceId: inv.id),
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}
