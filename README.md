# AdMeNot

**English** | [Polski](README.pl.md)

A Windows program that, once an Android phone is connected (USB debugging), heuristically detects intrusive apps (ads, notification spam, overlays, fake launchers, device administrators), lets you mute, disable or remove them, and undo every change.

## Requirements

- Windows 10/11 x64, Python 3.13, Node.js 24 (only for building the UI)
- `adb.exe` ships together with scrcpy (`scripts\fetch_tools.py`); a different adb can be set in the settings
- Microsoft Edge WebView2 Runtime (built into Windows 11)

## Installation (development environment)

    py -3.13 -m venv .venv
    .venv\Scripts\pip install -e ".[dev,gui,release]"
    python scripts\build_phone_db.py            # phone database and photos
    python scripts\fetch_tools.py               # scrcpy 4.1 with adb (screen preview)
    powershell -ExecutionPolicy Bypass -File scripts\build_ui.ps1
    python scripts\build_icons.py               # only after changing assets\icon\*.svg (PNG, ICO, copy for the UI)

## Running the GUI

    .venv\Scripts\admenot gui

or `.venv\Scripts\admenot-gui`. The window needs the built UI (`src\admenot\app\web\`, not in git) — without it the program prints the build command.

Theme (System / Light / Dark), language and default mode are changed in Settings; "System" follows the Windows theme.

Working on the UI alone, without a phone or Python (a fake bridge replays recorded scenarios):

    cd ui
    npm run dev          # http://localhost:5173/?scenario=adware|clean|disconnect|unauthorized|many|empty

## CLI

    admenot devices | device | scan [--apk] | capture | fix | undo | resume | history | cache | service | report | screenshot | selfcheck | gui

- `service` — saves the repair shop's details (name, address, phone, logo) for the service report, e.g. `admenot service --name "…"`.
- `report` — creates the service report (PDF and HTML) for an order from the journal, e.g. `admenot report --order ZS/…`.
- `screenshot` — phone screenshot: `--order ZS/…` stores it in the order (it goes into the report), `--out file.png` saves just the file.
- `selfcheck` — checks that the program has all its files (data, tools, UI); `--device --reference file` compares a phone scan with the output of `scan --apk --all`.

## Release

    .venv\Scripts\python scripts\build_release.py [--device]

Produces `dist\release\AdMeNot-<version>-setup.exe` (per-user install, no administrator rights). The version number lives only in `src\admenot\__init__.py`. Full procedure and checklist (in Polish): `docs/release.md`.

## Tests

    .venv\Scripts\python -m pytest
    .venv\Scripts\python -m ruff check src tests
    cd ui; npm test; npm run check; npm run e2e

After changing the bridge (`src/admenot/app/`), refresh the scenario recordings for the UI:

    .venv\Scripts\python scripts\record_bridge_fixtures.py

## User data

`%LOCALAPPDATA%\AdMeNot\`: `settings.json`, `journal.db`, `backups\`, `logs\` (ADB session log and `app-*.log` with window errors), `phone_overrides.json`.

## Known limitations

- An abandoned background APK analysis (e.g. by clicking "Fix" while it runs) may still finish up to two already started, read-only `adb pull` commands — they never touch the journal, but may show up as extra lines in the ADB console after the new order has started.
- While open, the GUI window serves the built UI from its own local static server on `127.0.0.1` (ephemeral port; `js_api` calls do not go over HTTP).

## License

AdMeNot is free and licensed under [PolyForm Shield 1.0.0](LICENSE). You may use it, including commercially — for example in a repair shop working on customers' phones. You may not sell it or use this code to offer a product that competes with it. The code is source-available, not open source in the OSI sense. Third-party licenses are listed in `THIRD_PARTY_NOTICES.txt` in the installed program's folder.
