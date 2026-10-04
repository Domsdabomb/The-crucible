import 'package:flutter/material.dart';

import '../api/api_exception.dart';
import '../models/job.dart';
import '../models/paged.dart';
import '../state/session.dart';
import '../utils/format.dart';
import '../utils/status_meta.dart';
import '../widgets/empty_state.dart';
import '../widgets/status_chip.dart';
import 'job_detail_screen.dart';
import 'job_intake_screen.dart';

/// Staff job list: search, status filter chips, pagination.
/// Technicians automatically see only their own jobs (API-enforced).
class JobsScreen extends StatefulWidget {
  const JobsScreen({super.key, required this.session});

  final Session session;

  @override
  State<JobsScreen> createState() => _JobsScreenState();
}

class _JobsScreenState extends State<JobsScreen> {
  final _searchController = TextEditingController();
  final _scrollController = ScrollController();

  List<JobBrief> _jobs = [];
  bool _loading = true;
  bool _loadingMore = false;
  String? _error;
  String? _statusFilter;
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
        _jobs.length < _total) {
      _loadMore();
    }
  }

  Map<String, String> _query({required int page}) {
    final q = <String, String>{
      'page': '$page',
      'per_page': '$_perPage',
    };
    if (_statusFilter != null) q['status'] = _statusFilter!;
    if (_search.isNotEmpty) q['search'] = _search;
    return q;
  }

  Future<void> _load({required bool reset}) async {
    setState(() {
      _loading = true;
      _error = null;
      if (reset) {
        _page = 1;
        _jobs = [];
      }
    });
    try {
      final json = await widget.session.api.get('/jobs', query: _query(page: _page));
      if (!mounted) return;
      final paged = Paged<JobBrief>.fromJson(json, JobBrief.fromJson);
      setState(() {
        _jobs = paged.data;
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
      final json =
          await widget.session.api.get('/jobs', query: _query(page: _page + 1));
      if (!mounted) return;
      final paged = Paged<JobBrief>.fromJson(json, JobBrief.fromJson);
      setState(() {
        _page += 1;
        _jobs = [..._jobs, ...paged.data];
        _total = paged.total;
        _loadingMore = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _loadingMore = false);
    }
  }

  void _onSearch(String value) {
    _search = value.trim();
    _load(reset: true);
  }

  void _onStatusTap(String? status) {
    setState(() => _statusFilter = status);
    _load(reset: true);
  }

  @override
  Widget build(BuildContext context) {
    final isAdmin = widget.session.session?.isAdmin ?? false;
    return Scaffold(
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
            child: TextField(
              controller: _searchController,
              decoration: InputDecoration(
                hintText: 'Search customer, device…',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _search.isNotEmpty
                    ? IconButton(
                        icon: const Icon(Icons.clear),
                        onPressed: () {
                          _searchController.clear();
                          _onSearch('');
                        },
                      )
                    : null,
                border: const OutlineInputBorder(),
                isDense: true,
              ),
              textInputAction: TextInputAction.search,
              onSubmitted: _onSearch,
            ),
          ),
          SizedBox(
            height: 48,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              children: [
                _FilterChip(
                  label: 'All',
                  selected: _statusFilter == null,
                  onTap: () => _onStatusTap(null),
                ),
                for (final s in StatusMeta.jobStatuses)
                  _FilterChip(
                    label: StatusMeta.label(s),
                    selected: _statusFilter == s,
                    onTap: () => _onStatusTap(s),
                  ),
              ],
            ),
          ),
          Expanded(child: _buildList()),
        ],
      ),
      floatingActionButton: isAdmin
          ? FloatingActionButton.extended(
              icon: const Icon(Icons.add),
              label: const Text('New job'),
              onPressed: () async {
                final created = await Navigator.push<bool>(
                  context,
                  MaterialPageRoute(
                    builder: (_) =>
                        JobIntakeScreen(session: widget.session),
                  ),
                );
                if (created == true) _load(reset: true);
              },
            )
          : null,
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
    if (_jobs.isEmpty) {
      return const EmptyState(
        icon: Icons.handyman,
        title: 'No jobs found',
        subtitle: 'Try a different search or filter.',
      );
    }
    return RefreshIndicator(
      onRefresh: () => _load(reset: true),
      child: ListView.builder(
        controller: _scrollController,
        padding: const EdgeInsets.all(12),
        itemCount: _jobs.length + (_loadingMore ? 1 : 0),
        itemBuilder: (context, i) {
          if (i >= _jobs.length) {
            return const Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: CircularProgressIndicator()),
            );
          }
          final job = _jobs[i];
          return Card(
            child: ListTile(
              leading: const Icon(Icons.smartphone),
              title: Text(job.device.label.isEmpty
                  ? 'Ticket #${job.id}'
                  : job.device.label),
              subtitle: Text(
                  '${job.customer.name} · ${formatDateTime(job.createdAt)}'),
              trailing: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  StatusChip(value: job.status),
                  const SizedBox(height: 4),
                  Text(formatCents(job.totalCents),
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                ],
              ),
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) =>
                      JobDetailScreen(session: widget.session, jobId: job.id),
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

class _FilterChip extends StatelessWidget {
  const _FilterChip(
      {required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4),
      child: FilterChip(
        label: Text(label),
        selected: selected,
        onSelected: (_) => onTap(),
      ),
    );
  }
}
