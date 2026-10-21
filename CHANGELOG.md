# Changelog

## 2.4.0

- Replaced the old ten-tier placeholder list with five Race V4 upgrade stages.
- Updated fragment costs, approximate V4 training time, estimated activation counts, and typical activation durations from the supplied reference.
- Added a database migration that updates existing training rows and caps legacy tier progress at the new maximum while preserving profile and session history.
- Expanded the training reference table and updated the Windows version metadata.

## 2.3.1

- Fixed the Settings page on smaller windows by placing its panels in a scroll area.
- Prevented settings buttons, community links, and footer notes from overlapping or being clipped.
- Updated the developer contact to the Discord server and removed Telegram references from the app.

## 2.3.0

- Added Emerald, Purple, White, and Black themes.
- Added Russian and English interface text.
- Added a Windows app icon and standalone EXE build support.
- Added configurable global hotkey and optional upgrade-readiness notifications.
- Added multiple races per profile, with independent per-race progress and time tracking.
- Fixed time-history clearing to remove session rows and recalculate the counters from remaining records.
- Added optional backup before clearing time records and retention of the five latest automatic backups.
- Added history correction, Windows startup, system-tray options, manual database backup, and developer contact.
