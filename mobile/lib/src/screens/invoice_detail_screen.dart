import 'package:flutter/material.dart';

import '../api/api_exception.dart';
import '../models/invoice.dart';
import '../state/session.dart';
import '../utils/format.dart';

/// Invoice detail: line items, totals, paid status.
/// Also hosts the "create invoice from job" dialog (used from job detail).
class InvoiceDetailScreen extends StatefulWidget {
  const InvoiceDetailScreen(
      {super.key, required this.session, required this.invoiceId});

  final Session session;
  final int invoiceId;

  @override
  State<InvoiceDetailScreen> createState() => _InvoiceDetailScreenState();
}

class _InvoiceDetailScreenState extends State<InvoiceDetailScreen> {
  Invoice? _invoice;
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final json =
          await widget.session.api.get('/invoices/${widget.invoiceId}');
      if (!mounted) return;
      setState(() {
        _invoice = Invoice.fromJson(json);
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Invoice #${widget.invoiceId}')),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
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
              FilledButton(onPressed: _load, child: const Text('Retry')),
            ],
          ),
        ),
      );
    }
    final inv = _invoice!;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text('Invoice #${inv.id}',
                          style: Theme.of(context)
                              .textTheme
                              .titleLarge
                              ?.copyWith(fontWeight: FontWeight.bold)),
                    ),
                    _PaidBadge(paid: inv.isPaid),
                  ],
                ),
                const SizedBox(height: 4),
                Text(inv.customerName,
                    style: Theme.of(context).textTheme.titleMedium),
                Text('Job #${inv.jobId}',
                    style: const TextStyle(color: Colors.grey)),
                Text(formatDateTime(inv.createdAt),
                    style: const TextStyle(color: Colors.grey, fontSize: 12)),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              children: [
                _Line('Labour', formatCents(inv.labourCents)),
                _Line('Parts', formatCents(inv.partsCents)),
                _Line('GST (5%)', formatCents(inv.gstCents)),
                _Line('PST (7%)', formatCents(inv.pstCents)),
                const Divider(),
                _Line('Subtotal', formatCents(inv.subtotalCents)),
                if (inv.coinsApplied > 0)
                  _Line('Crucible Coins (${inv.coinsApplied})',
                      '−${formatCents(inv.discountCents)}'),
                const Divider(),
                _Line('Amount due', formatCents(inv.amountDueCents),
                    bold: true),
                if (inv.paidAt != null)
                  _Line('Paid at', formatDateTime(inv.paidAt!)),
              ],
            ),
          ),
        ),
        if (inv.notes?.isNotEmpty ?? false) ...[
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Notes',
                      style: Theme.of(context).textTheme.titleSmall),
                  const SizedBox(height: 4),
                  Text(inv.notes!),
                ],
              ),
            ),
          ),
        ],
      ],
    );
  }
}

class _PaidBadge extends StatelessWidget {
  const _PaidBadge({required this.paid});
  final bool paid;

  @override
  Widget build(BuildContext context) {
    final color = paid ? Colors.green : Colors.orange;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Text(paid ? 'PAID' : 'UNPAID',
          style: TextStyle(color: color, fontWeight: FontWeight.bold)),
    );
  }
}

class _Line extends StatelessWidget {
  const _Line(this.label, this.value, {this.bold = false});
  final String label;
  final String value;
  final bool bold;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(child: Text(label)),
          Text(value,
              style: TextStyle(
                  fontWeight: bold ? FontWeight.bold : FontWeight.normal,
                  fontSize: bold ? 16 : 14)),
        ],
      ),
    );
  }
}

/// Shows the "create invoice" dialog for a job; returns the new invoice id.
Future<int?> showCreateInvoiceDialog(
    BuildContext context, Session session, int jobId) {
  final coins = TextEditingController();
  final notes = TextEditingController();
  bool busy = false;
  return showDialog<int>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setState) => AlertDialog(
        title: Text('Invoice for job #$jobId'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: coins,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: 'Crucible Coins to apply (optional)',
                border: OutlineInputBorder(),
                helperText: 'Capped at 25% of subtotal server-side.',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: notes,
              decoration: const InputDecoration(
                labelText: 'Notes (optional)',
                border: OutlineInputBorder(),
              ),
              maxLines: 2,
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
                    setState(() => busy = true);
                    try {
                      final body = <String, dynamic>{'job_id': jobId};
                      final coinsInt =
                          int.tryParse(coins.text.trim());
                      if (coinsInt != null && coinsInt > 0) {
                        body['coins_applied'] = coinsInt;
                      }
                      if (notes.text.trim().isNotEmpty) {
                        body['notes'] = notes.text.trim();
                      }
                      final json =
                          await session.api.post('/invoices', body: body);
                      if (ctx.mounted) {
                        Navigator.pop(
                            ctx, (json['id'] as num).toInt());
                      }
                    } on ApiException catch (e) {
                      if (ctx.mounted) {
                        ScaffoldMessenger.of(ctx).showSnackBar(SnackBar(
                            content: Text(e.message),
                            backgroundColor: Colors.red.shade700));
                      }
                      setState(() => busy = false);
                    }
                  },
            child: busy
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(
                        strokeWidth: 2, color: Colors.white))
                : const Text('Create'),
          ),
        ],
      ),
    ),
  );
}
