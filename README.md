# Blox Fruits V4 Tracker

A lightweight Windows desktop companion for tracking Blox Fruits Race V4 time, training progress, fragments, multiple races per profile, and session history.

![Blox Fruits V4 Tracker app icon](app_icon.png)

**Current version:** `2.3.0`  
**Interface languages:** Russian and English  
**Community and support:** [Join the Discord server](https://discord.gg/SvYqcks5Pz)

> This is an unofficial fan-made tracker. It is not affiliated with, endorsed by, or sponsored by Roblox or the Blox Fruits developers. The app does not connect to Roblox, inspect game memory, or automate gameplay. V4 time is recorded manually or with the configured global hotkey.

## Features

- Track V4 time overall and for the current upgrade stage.
- Keep several races under one account profile, with separate progress for each race.
- Track player level, fragments, V4 tier, trials, training history, and activation sessions.
- Use a configurable global hotkey (default: `F8`) while the game is focused.
- Receive optional desktop notifications when the selected race is ready for an upgrade.
- Choose Emerald, Purple, White, or Black themes and Russian or English interface text.
- Use the system tray, optional Windows startup, database backups, and history correction tools.
- Save local data in SQLite; the database is stored outside the program directory.

## Download the Windows app

Open the repository's **Releases** page and download `Blox Fruits V4 Tracker.exe` from the latest published release. No separate Python installation is needed to run the EXE.

Windows may show an unknown-publisher or SmartScreen warning because release builds are not automatically signed with a trusted publisher certificate. Do not treat a file as trusted solely because it appears in a release; verify the SHA-256 checksum attached to each release.

## Build the EXE yourself

### Automatic build on GitHub

The workflow in `.github/workflows/windows-release.yml` builds the app on a Windows runner using Python 3.12, runs the database regression tests, creates the standalone EXE, and generates a SHA-256 checksum.

1. Push this project to a GitHub repository with a `main` branch.
2. Open **Actions** and run **Windows build and release** to create a downloadable build artifact.
3. To prepare a release, create and push a version tag, for example:

   ```bash
   git tag v2.3.0
   git push origin v2.3.0
   ```

4. Wait for the workflow to finish, then open **Releases** and review the generated **draft release**. Publish it after checking the notes, EXE, and checksum.

The release is deliberately created as a draft so you can review it before publishing.

### Build locally on Windows

Use 64-bit Python 3.12. From the project directory, run:

```bat
build_exe.bat
```

The executable and checksum are written to `dist\`. The script does not modify the user's existing database in `%APPDATA%`.

### Run from source

Install Python 3.12 and run:

```bat
python -m pip install -r requirements.txt
python main.py
```

For a visible error message when diagnosing startup problems, use `start.bat`. The standalone EXE is the easiest option for everyday use.

## Data location and backups

The SQLite database is stored at:

```text
%APPDATA%\BloxFruitsV4Tracker\blox_fruits_v4.db
```

The database is separate from the EXE, so replacing the app does not normally remove profiles or progress. Use the backup option in Settings before manually editing the database or clearing history. Keep backup copies private because they can contain your local profile names and game-progress records.

## Verify an EXE

Each release includes `SHA256SUMS.txt`. In PowerShell, run this from the directory containing the downloaded EXE and checksum file:

```powershell
(Get-FileHash -Algorithm SHA256 '.\Blox Fruits V4 Tracker.exe').Hash.ToLower()
Get-Content '.\SHA256SUMS.txt'
```

Compare the calculated hash with the hash in `SHA256SUMS.txt`. They should match exactly.

## Digital signatures

The repository includes `sign_release.ps1` and `SIGNING.md` for maintainers who have a trusted code-signing certificate and Windows SDK SignTool. No certificate or signing password is included. A self-signed certificate does not establish a publicly trusted publisher and is not used by the automated release workflow.

## Development and tests

Install app dependencies with `python -m pip install -r requirements.txt`. Run syntax checks and database regression tests with:

```bat
python -m compileall -q main.py tests
python -m unittest discover -s tests -v
```

Pull requests and pushes to `main` are built and tested automatically by GitHub Actions.

## Developer contact and support

- Discord: [discord.gg/SvYqcks5Pz](https://discord.gg/SvYqcks5Pz)
- For bugs and feature requests, use the GitHub **Issues** tab. Please do not attach your database or other private profile data to public issues.

## License

This project is licensed under the MIT License. See [`LICENSE`](LICENSE).
"# BloxFruits-V4-Tracker" 
