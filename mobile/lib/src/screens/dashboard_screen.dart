import 'package:flutter/material.dart';

import '../api/api_exception.dart';
import '../models/dashboard.dart';
import '../models/job.dart';
import '../state/session.dart';
import '../utils/format.dart';
import '../utils/status_meta.dart';
import '../widgets/empty_state.dart';
import '../widgets/status_chip.dart';
import 'job_detail_screen.dart';

/// Admin dashboard: revenue cards, status counts, recent jobs.
class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key, required this.session});

  final Session session;

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  DashboardData? _data;
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
      final json = await widget.session.api.get('/dashboard');
      if (!mounted) return;
      setState(() {
        _data = DashboardData.fromJson(json);
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
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
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
                  onPressed: _load, child: const Text('Retry')),
            ],
          ),
        ),
      );
    }
    final data = _data!;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _RevenueGrid(data: data),
          const SizedBox(height: 16),
          _StatusCounts(counts: data.statusCounts),
          const SizedBox(height: 16),
          Text('Recent jobs',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          if (data.recentJobs.isEmpty)
            const EmptyState(
                icon: Icons.handyman,
                title: 'No jobs yet',
                subtitle: 'New intake jobs will show up here.'),
          for (final job in data.recentJobs)
            _RecentJobTile(
              session: widget.session,
              job: job,
            ),
        ],
      ),
    );
  }
}

class _RevenueGrid extends StatelessWidget {
  const _RevenueGrid({required this.data});

  final DashboardData data;

  @override
  Widget build(BuildContext context) {
    final cards = [
      _MoneyCard(
          label: 'Collected',
          cents: data.collectedCents,
          icon: Icons.attach_money,
          color: Colors.green),
      _MoneyCard(
          label: 'This month',
          cents: data.monthCents,
          icon: Icons.calendar_month,
          color: Colors.blue),
      _MoneyCard(
          label: 'Outstanding',
          cents: data.outstandingCents,
          icon: Icons.pending_actions,
          color: Colors.orange),
      _MoneyCard(
          label: 'Unpaid invoices',
          cents: null,
          count: data.unpaidCount,
          icon: Icons.receipt_long,
          color: Colors.red),
    ];
    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      mainAxisSpacing: 12,
      crossAxisSpacing: 12,
      childAspectRatio: 1.35,
      children: cards,
    );
  }
}

class _MoneyCard extends StatelessWidget {
  const _MoneyCard({
    required this.label,
    this.cents,
    this.count,
    required this.icon,
    required this.color,
  });

  final String label;
  final int? cents;
  final int? count;
  final IconData icon;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, color: color, size: 22),
            const SizedBox(height: 8),
            Text(
              cents != null ? formatCents(cents!) : '${count ?? 0}',
              style: Theme.of(context)
                  .textTheme
                  .headlineSmall
                  ?.copyWith(fontWeight: FontWeight.bold),
            ),
            Text(label, style: const TextStyle(color: Colors.grey)),
          ],
        ),
      ),
    );
  }
}

class _StatusCounts extends StatelessWidget {
  const _StatusCounts({required this.counts});

  final Map<String, int> counts;

  @override
  Widget build(BuildContext context) {
    if (counts.isEmpty) return const SizedBox.shrink();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Jobs by status',
                style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final e in counts.entries)
                  Chip(
                    label: Text('${StatusMeta.label(e.key)} · ${e.value}'),
                    avatar: CircleAvatar(
                      backgroundColor: StatusMeta.color(e.key),
                      radius: 8,
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _RecentJobTile extends StatelessWidget {
  const _RecentJobTile({required this.session, required this.job});

  final Session session;
  final JobBrief job;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: const Icon(Icons.smartphone),
        title: Text(job.device.label.isEmpty ? 'Device' : job.device.label),
        subtitle: Text(
            '${job.customer.name} · ${StatusMeta.label(job.priority)} priority'),
        trailing: StatusChip(value: job.status),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) =>
                JobDetailScreen(session: session, jobId: job.id),
          ),
        ),
      ),
    );
  }
}
