import 'package:flutter/material.dart';

import '../state/session.dart';
import 'customers_screen.dart';
import 'dashboard_screen.dart';
import 'invoices_screen.dart';
import 'jobs_screen.dart';

/// Bottom-navigation shell for staff logins.
/// Admins get Dashboard / Jobs / Invoices / Customers.
/// Technicians get Jobs only (the API enforces the rest anyway).
class StaffHome extends StatefulWidget {
  const StaffHome({super.key, required this.session});

  final Session session;

  @override
  State<StaffHome> createState() => _StaffHomeState();
}

class _StaffHomeState extends State<StaffHome> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final isAdmin = widget.session.session?.isAdmin ?? false;
    final tabs = <_Tab>[
      if (isAdmin)
        _Tab('Dashboard', Icons.dashboard,
            DashboardScreen(session: widget.session)),
      _Tab('Jobs', Icons.handyman, JobsScreen(session: widget.session)),
      if (isAdmin)
        _Tab('Invoices', Icons.receipt_long,
            InvoicesScreen(session: widget.session)),
      if (isAdmin)
        _Tab('Customers', Icons.people,
            CustomersScreen(session: widget.session)),
    ];
    final index = _index.clamp(0, tabs.length - 1);
    return Scaffold(
      appBar: AppBar(
        title: Text(tabs[index].label),
        actions: [
          IconButton(
            tooltip: 'Sign out',
            icon: const Icon(Icons.logout),
            onPressed: () => _confirmLogout(context),
          ),
        ],
      ),
      body: IndexedStack(
        index: index,
        children: [for (final t in tabs) t.screen],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: [
          for (final t in tabs)
            NavigationDestination(icon: Icon(t.icon), label: t.label),
        ],
      ),
    );
  }

  Future<void> _confirmLogout(BuildContext context) async {
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
}

class _Tab {
  const _Tab(this.label, this.icon, this.screen);
  final String label;
  final IconData icon;
  final Widget screen;
}
