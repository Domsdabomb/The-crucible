import 'package:flutter/material.dart';

import '../api/api_exception.dart';
import '../models/job.dart';
import '../state/session.dart';
import '../utils/format.dart';
import '../utils/status_meta.dart';
import '../widgets/status_chip.dart';
import '../widgets/timeline.dart';
import 'invoice_detail_screen.dart';

/// Full job view: device/customer info, pricing, repair timeline,
/// status changes (422-safe), and pricing/priority edits.
class JobDetailScreen extends StatefulWidget {
  const JobDetailScreen(
      {super.key, required this.session, required this.jobId});

  final Session session;
  final int jobId;

  @override
  State<JobDetailScreen> createState() => _JobDetailScreenState();
}

class _JobDetailScreenState extends State<JobDetailScreen> {
  JobDetail? _job;
  String? _error;
  bool _loading = true;
  bool _saving = false;

  bool get _isAdmin => widget.session.session?.isAdmin ?? false;

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
          await widget.session.api.get('/jobs/${widget.jobId}');
      if (!mounted) return;
      setState(() {
        _job = JobDetail.fromJson(json);
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

  Future<void> _patch(Map<String, dynamic> body, {String? successNote}) async {
    setState(() => _saving = true);
    try {
      final json =
          await widget.session.api.patch('/jobs/${widget.jobId}', body: body);
      if (!mounted) return;
      setState(() {
        _job = JobDetail.fromJson(json);
        _saving = false;
      });
      if (successNote != null && mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(successNote)));
      }
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _saving = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(e.code == 'invalid_transition'
              ? e.message // server lists the allowed next states here
              : e.message),
          backgroundColor: Colors.red.shade700,
          duration: const Duration(seconds: 5),
        ),
      );
    } catch (_) {
      if (!mounted) return;
      setState(() => _saving = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not reach the server.')),
      );
    }
  }

  void _showStatusSheet() {
    final job = _job;
    if (job == null) return;
    final noteController = TextEditingController();
    String selected = job.status;
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheet) => Padding(
          padding: EdgeInsets.only(
            left: 20,
            right: 20,
            top: 20,
            bottom: MediaQuery.of(ctx).viewInsets.bottom + 20,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('Change status',
                  style: Theme.of(ctx).textTheme.titleMedium),
              const SizedBox(height: 4),
              const Text(
                'Illegal moves are rejected by the server — it will tell you which moves are allowed.',
                style: TextStyle(color: Colors.grey, fontSize: 12),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: selected,
                decoration: const InputDecoration(
                    labelText: 'New status',
                    border: OutlineInputBorder()),
                items: [
                  for (final s in StatusMeta.jobStatuses)
                    DropdownMenuItem(
                      value: s,
                      child: Text(
                          '${StatusMeta.label(s)}${s == job.status ? ' (current)' : ''}'),
                    ),
                ],
                onChanged: (v) =>
                    setSheet(() => selected = v ?? job.status),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: noteController,
                decoration: const InputDecoration(
                  labelText: 'Note (optional)',
                  border: OutlineInputBorder(),
                ),
                maxLines: 2,
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: selected == job.status &&
                        noteController.text.trim().isEmpty
                    ? null
                    : () {
                        Navigator.pop(ctx);
                        final body = <String, dynamic>{};
                        if (selected != job.status) {
                          body['status'] = selected;
                        }
                        final note = noteController.text.trim();
                        if (note.isNotEmpty) body['note'] = note;
                        _patch(body,
                            successNote:
                                'Job #${job.id} updated.');
                      },
                child: const Text('Save'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _showPricingSheet() {
    final job = _job;
    if (job == null) return;
    final labour = TextEditingController(
        text: (job.labourCents / 100).toStringAsFixed(2));
    final parts = TextEditingController(
        text: (job.partsCents / 100).toStringAsFixed(2));
    final deposit = TextEditingController(
        text: (job.depositCents / 100).toStringAsFixed(2));
    final priority = ValueNotifier<String>(job.priority);
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => Padding(
        padding: EdgeInsets.only(
          left: 20,
          right: 20,
          top: 20,
          bottom: MediaQuery.of(ctx).viewInsets.bottom + 20,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Edit pricing & priority',
                style: Theme.of(ctx).textTheme.titleMedium),
            const SizedBox(height: 4),
            const Text(
              'Tax (GST 5% + PST 7%) is recalculated server-side.',
              style: TextStyle(color: Colors.grey, fontSize: 12),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: labour,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                  labelText: 'Labour (\$)', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: parts,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                  labelText: 'Parts (\$)', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: deposit,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                  labelText: 'Deposit (\$)', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            ValueListenableBuilder<String>(
              valueListenable: priority,
              builder: (ctx, value, _) => DropdownButtonFormField<String>(
                initialValue: value,
                decoration: const InputDecoration(
                    labelText: 'Priority', border: OutlineInputBorder()),
                items: [
                  for (final p in StatusMeta.priorities)
                    DropdownMenuItem(
                        value: p, child: Text(StatusMeta.label(p))),
                ],
                onChanged: (v) {
                  if (v != null) priority.value = v;
                },
              ),
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: () {
                final labourCents = parseDollarsToCents(labour.text);
                final partsCents = parseDollarsToCents(parts.text);
                final depositCents = parseDollarsToCents(deposit.text);
                if (labourCents == null ||
                    partsCents == null ||
                    depositCents == null) {
                  ScaffoldMessenger.of(ctx).showSnackBar(
                    const SnackBar(
                        content: Text('Enter valid dollar amounts.')),
                  );
                  return;
                }
                Navigator.pop(ctx);
                _patch({
                  'labour_cents': labourCents,
                  'parts_cents': partsCents,
                  'deposit_cents': depositCents,
                  'priority': priority.value,
                }, successNote: 'Pricing updated.');
              },
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Ticket #${widget.jobId}'),
        actions: [
          if (_job != null && !_loading)
            IconButton(
              tooltip: 'Refresh',
              icon: const Icon(Icons.refresh),
              onPressed: _load,
            ),
        ],
      ),
      body: _buildBody(),
      floatingActionButton: _job == null
          ? null
          : Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                FloatingActionButton.extended(
                  heroTag: 'status',
                  icon: const Icon(Icons.swap_horiz),
                  label: const Text('Status'),
                  onPressed: _saving ? null : _showStatusSheet,
                ),
                const SizedBox(height: 12),
                FloatingActionButton.extended(
                  heroTag: 'pricing',
                  icon: const Icon(Icons.edit),
                  label: const Text('Pricing'),
                  onPressed: _saving ? null : _showPricingSheet,
                ),
                if (_isAdmin) ...[
                  const SizedBox(height: 12),
                  FloatingActionButton.extended(
                    heroTag: 'invoice',
                    icon: const Icon(Icons.receipt_long),
                    label: const Text('Invoice'),
                    onPressed: _saving
                        ? null
                        : () async {
                            final id =
                                await showCreateInvoiceDialog(
                                    context, widget.session, _job!.id);
                            if (id != null && context.mounted) {
                              Navigator.push(
                                context,
                                MaterialPageRoute(
                                  builder: (_) => InvoiceDetailScreen(
                                      session: widget.session,
                                      invoiceId: id),
                                ),
                              );
                            }
                          },
                  ),
                ],
              ],
            ),
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
    final job = _job!;
    return Stack(
      children: [
        ListView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 160),
          children: [
            Row(
              children: [
                StatusChip(value: job.status),
                const SizedBox(width: 8),
                StatusChip(value: job.priority, isPriority: true),
                const Spacer(),
                Text(formatCents(job.totalCents),
                    style: Theme.of(context)
                        .textTheme
                        .headlineSmall
                        ?.copyWith(fontWeight: FontWeight.bold)),
              ],
            ),
            const SizedBox(height: 16),
            _Section(
              title: 'Device',
              icon: Icons.smartphone,
              children: [
                _Row('Device', job.device.label),
                if (job.device.serialImei?.isNotEmpty ?? false)
                  _Row('Serial / IMEI', job.device.serialImei!),
                if (job.device.conditionNotes?.isNotEmpty ?? false)
                  _Row('Condition', job.device.conditionNotes!),
                if ((job.description?.isNotEmpty ?? false))
                  _Row('Issue', job.description!),
                if ((job.diagnosisNotes?.isNotEmpty ?? false))
                  _Row('Diagnosis', job.diagnosisNotes!),
              ],
            ),
            _Section(
              title: 'Customer',
              icon: Icons.person,
              children: [
                _Row('Name', job.customer.name),
                _Row('Phone', job.customer.phone),
              ],
            ),
            _Section(
              title: 'Pricing',
              icon: Icons.receipt,
              children: [
                _Row('Quoted', formatCents(job.quotedCents)),
                _Row('Labour', formatCents(job.labourCents)),
                _Row('Parts', formatCents(job.partsCents)),
                _Row('GST (5%)', formatCents(job.gstCents)),
                _Row('PST (7%)', formatCents(job.pstCents)),
                _Row('Deposit paid', formatCents(job.depositCents)),
                const Divider(),
                _Row('Total', formatCents(job.totalCents), bold: true),
                _Row('Balance due', formatCents(job.balanceCents),
                    bold: true),
              ],
            ),
            _Section(
              title: 'Details',
              icon: Icons.info_outline,
              children: [
                if (job.technician != null)
                  _Row('Technician', job.technician!.name),
                if (job.promisedDate != null)
                  _Row('Promised', formatDate(job.promisedDate!)),
                _Row('Created', formatDateTime(job.createdAt)),
                _Row('Updated', formatDateTime(job.updatedAt)),
              ],
            ),
            _Section(
              title: 'Repair timeline',
              icon: Icons.timeline,
              children: [RepairTimeline(history: job.history)],
            ),
          ],
        ),
        if (_saving)
          Container(
            color: Colors.black.withValues(alpha: 0.2),
            child: const Center(child: CircularProgressIndicator()),
          ),
      ],
    );
  }
}

class _Section extends StatelessWidget {
  const _Section(
      {required this.title, required this.icon, required this.children});

  final String title;
  final IconData icon;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, size: 18, color: Colors.grey.shade600),
                const SizedBox(width: 8),
                Text(title,
                    style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.bold)),
              ],
            ),
            const SizedBox(height: 8),
            ...children,
          ],
        ),
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row(this.label, this.value, {this.bold = false});

  final String label;
  final String value;
  final bool bold;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
              width: 110,
              child: Text(label,
                  style: const TextStyle(color: Colors.grey))),
          Expanded(
            child: Text(value,
                style: TextStyle(
                    fontWeight: bold ? FontWeight.bold : FontWeight.normal)),
          ),
        ],
      ),
    );
  }
}
