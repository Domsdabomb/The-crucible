/// Single place for app-wide configuration.
library;

/// Base URL of the Crucible backend API (no trailing slash).
/// Everything else in the app builds request URLs from this.
const String kApiBaseUrl = 'https://Domsdabomb.pythonanywhere.com';

/// API version prefix, per API_CONTRACT.md.
const String kApiPathPrefix = '/api/v1';

/// App name shown in the UI.
const String kAppName = 'The Crucible';
