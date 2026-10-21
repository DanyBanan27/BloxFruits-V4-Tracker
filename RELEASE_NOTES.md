# Blox Fruits V4 Tracker 2.3.0

## Highlights

- Time tracking for multiple races in each profile.
- Configurable global timer hotkey and upgrade-readiness notifications.
- Four themes and Russian/English UI.
- SQLite-backed profiles, session history, and database backups.
- Time-history clearing now recalculates and persists totals from remaining sessions.

## Windows release

The EXE is built by GitHub Actions on Windows with Python 3.12. Each workflow run uploads the EXE as an artifact. A pushed `v*` tag creates a **draft** GitHub Release containing the EXE and `SHA256SUMS.txt`; review the draft before publishing it.

The EXE is not automatically Authenticode-signed. See `SIGNING.md` if you have a trusted code-signing certificate.
