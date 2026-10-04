import 'package:flutter/material.dart';

import 'src/config.dart';
import 'src/screens/login_screen.dart';
import 'src/screens/portal_home_screen.dart';
import 'src/screens/staff_home.dart';
import 'src/state/session.dart';

void main() {
  runApp(const CrucibleApp());
}

class CrucibleApp extends StatefulWidget {
  const CrucibleApp({super.key});

  @override
  State<CrucibleApp> createState() => _CrucibleAppState();
}

class _CrucibleAppState extends State<CrucibleApp> {
  late final Session _session;

  @override
  void initState() {
    super.initState();
    _session = Session();
    _session.init();
  }

  @override
  void dispose() {
    _session.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: kAppName,
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.deepOrange,
          brightness: Brightness.light,
        ),
        useMaterial3: true,
        inputDecorationTheme: const InputDecorationTheme(
          border: OutlineInputBorder(),
        ),
      ),
      darkTheme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.deepOrange,
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
        inputDecorationTheme: const InputDecorationTheme(
          border: OutlineInputBorder(),
        ),
      ),
      themeMode: ThemeMode.system,
      home: ListenableBuilder(
        listenable: _session,
        builder: (context, _) {
          if (!_session.ready) {
            return const Scaffold(
              body: Center(child: CircularProgressIndicator()),
            );
          }
          final session = _session.session;
          if (session == null) {
            return LoginScreen(session: _session);
          }
          if (session.isCustomer) {
            return PortalHomeScreen(session: _session);
          }
          return StaffHome(session: _session);
        },
      ),
    );
  }
}
