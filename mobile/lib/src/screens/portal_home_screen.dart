import 'package:flutter/material.dart';

import '../api/api_exception.dart';
import '../models/portal_job.dart';
import '../state/session.dart';
import '../utils/format.dart';
import '../widgets/empty_state.dart';
import '../widgets/status_chip.dart';
import '../widgets/timeline.dart';

/// Customer portal: the logged-in customer's own repair jobs,
/// each expandable to a read-only repair timeline.
class PortalHomeScreen extends StatefulWidget {
  const PortalHomeScreen({super.key, required this.session});

  final Session session;

  @override
  State<PortalHomeScreen> createState() => _PortalHomeScreenState();
}

class _PortalHomeScreenState extends State<PortalHomeScreen> {
  List<PortalJob> _jobs = [];
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
      final json = await widget.session.api.get('/portal/timeline');
      if (!mounted) return;
      final raw = json['jobs'] as List<dynamic>? ?? const [];
      setState(() {
        _jobs = raw
            .whereType<Map<String, dynamic>>()
            .map(PortalJob.fromJson)
            .toList(growable: false);
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

  Future<void> _confirmLogout() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Sign out?'),
        content: const Text('You will need to sign in again.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Sign out')),
        ],
      ),
    );
    if (ok == true) await widget.session.logout();
  }

  @override
  Widget build(BuildContext context) {
    final name = widget.session.session?.displayName;
    return Scaffold(
      appBar: AppBar(
        title: Text(name?.isNotEmpty ?? false ? 'Hi, $name' : 'My repairs'),
        actions: [
          IconButton(
            tooltip: 'Sign out',
            icon: const Icon(Icons.logout),
            onPressed: _confirmLogout,
          ),
        ],
      ),
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
    if (_jobs.isEmpty) {
      return const EmptyState(
        icon: Icons.handyman,
        title: 'No repairs yet',
        subtitle: 'Your repair tickets will show up here.',
      );
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.builder(
        padding: const EdgeInsets.all(12),
        itemCount: _jobs.length,
        itemBuilder: (context, i) => _PortalJobCard(job: _jobs[i]),
      ),
    );
  }
}

class _PortalJobCard extends StatelessWidget {
  const _PortalJobCard({required this.job});

  final PortalJob job;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: ExpansionTile(
        leading: const Icon(Icons.smartphone),
        title: Text(job.device.label.isEmpty
            ? 'Ticket #${job.id}'
            : job.device.label),
        subtitle: Text('Ticket #${job.id} · ${formatCents(job.totalCents)}'),
        trailing: StatusChip(value: job.status),
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (job.promisedDate != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Row(
                      children: [
                        const Icon(Icons.event,
                            size: 16, color: Colors.grey),
                        const SizedBox(width: 6),
                        Text(
                            'Promised: ${formatDate(job.promisedDate!)}',
                            style:
                                const TextStyle(color: Colors.grey)),
                      ],
                    ),
                  ),
                RepairTimeline(history: job.history),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
