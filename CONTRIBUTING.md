# Contributing

Thanks for helping improve Blox Fruits V4 Tracker!

## Before opening a pull request

1. Keep changes focused and explain the user-facing problem they solve.
2. Do not add personal profile data, real databases, passwords, certificates, or signing keys.
3. Run the syntax and database regression checks:

   ```bat
   python -m compileall -q main.py tests
   python -m unittest discover -s tests -v
   ```

4. Update `RELEASE_NOTES.md` when the change affects users.
5. If you change the app version, update `APP_VERSION` in `main.py` and the EXE metadata in `version_info.txt` together.

## Bug reports

Include the app version, Windows version, steps to reproduce, expected behavior, and actual behavior. Remove account names or other personal information from screenshots. Never attach your SQLite database to a public issue.
