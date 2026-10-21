# Changelog

## 2.4.1

- Corrected the progression to all 10 purchasable upgrades across stages 2–5. Stage 5 adds five upgrades rather than replacing earlier stages.
- Restored the earlier compact training-table layout and added the activation alternative and duration after each upgrade.
- Corrected each upgrade's fragment cost, time, activation count, trial requirement and transformation duration according to the supplied wiki reference.
- Training readiness now accepts the required V4 time OR the required number of full activations.
- Existing profile/session history is preserved by the database migration.

## 2.4.0

- Superseded by v2.4.1: the earlier release incorrectly represented stage 5 as the entire progression.

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
