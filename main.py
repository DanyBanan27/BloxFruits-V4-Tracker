from __future__ import annotations

import csv
import ctypes
import os
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QFont, QCloseEvent, QKeySequence, QShortcut, QIcon, QAction, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget, QComboBox,
    QProgressBar, QDialog, QFormLayout, QLineEdit, QSpinBox, QCheckBox,
    QAbstractItemView, QLayout,
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
    QKeySequenceEdit, QScrollArea, QFileDialog, QSystemTrayIcon, QMenu
)

APP_NAME = "Blox Fruits V4 Tracker"
APP_VERSION = "2.4.0 ADMIN"
RACES = ["Human", "Rabbit", "Shark", "Angel", "Ghoul", "Cyborg", "Draco"]
DEFAULT_HOTKEY = "F8"
HOTKEY_ID = 0xB40
IS_FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
ICON_PATH = BUNDLE_DIR / "app_icon.ico"
DISCORD_URL = "https://discord.gg/SvYqcks5Pz"

TRAININGS = [
    {"tier": 1, "cost": 3000, "activations": 7, "minutes": 8, "activation_duration": 80, "trial": 1, "label": "Улучшение Race V4 — уровень 1"},
    {"tier": 2, "cost": 3250, "activations": 8, "minutes": 10, "activation_duration": 85, "trial": 2, "label": "Улучшение Race V4 — уровень 2"},
    {"tier": 3, "cost": 3500, "activations": 10, "minutes": 13, "activation_duration": 85, "trial": 3, "label": "Улучшение Race V4 — уровень 3"},
    {"tier": 4, "cost": 3750, "activations": 11, "minutes": 15, "activation_duration": 90, "trial": 3, "label": "Улучшение Race V4 — уровень 4"},
    {"tier": 5, "cost": 4000, "activations": 12, "minutes": 18, "activation_duration": 110, "trial": 3, "label": "Улучшение Race V4 — уровень 5 (MAX)"},
}


def app_data_dir() -> Path:
    base = os.getenv("APPDATA")
    path = (Path(base) / "BloxFruitsV4Tracker") if base else (Path.home() / ".blox_fruits_v4_tracker")
    path.mkdir(parents=True, exist_ok=True)
    return path


DB_PATH = app_data_dir() / "blox_fruits_v4.db"


def fmt_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def fmt_num(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


class Database:
    """SQLite storage with migrations from the first single-race version."""

    def __init__(self, path: Path = DB_PATH):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Save a one-time copy of an existing single-race database before a schema migration.
        if path.exists():
            try:
                # sqlite3.Connection's context manager commits/rolls back but does NOT
                # close the connection. Always close this short-lived probe explicitly,
                # otherwise Windows can keep the database file locked during cleanup.
                probe = sqlite3.connect(path)
                try:
                    has_multi_race_table = probe.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='race_progress'"
                    ).fetchone() is not None
                finally:
                    probe.close()
                backup_path = path.with_name(path.stem + "_before_multirace_backup" + path.suffix)
                if not has_multi_race_table and not backup_path.exists():
                    shutil.copy2(path, backup_path)
            except (sqlite3.Error, OSError):
                # The migration still gets a chance to report the actual DB error to the app.
                pass
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.setup()

    def setup(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            race TEXT NOT NULL DEFAULT 'Human',
            player_level INTEGER NOT NULL DEFAULT 3000,
            fragments INTEGER NOT NULL DEFAULT 0,
            v4_unlocked INTEGER NOT NULL DEFAULT 0,
            v4_tier INTEGER NOT NULL DEFAULT 0,
            trials_completed INTEGER NOT NULL DEFAULT 0,
            training_activations INTEGER NOT NULL DEFAULT 0,
            training_seconds REAL NOT NULL DEFAULT 0,
            total_v4_seconds REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS race_progress (
            profile_id INTEGER NOT NULL,
            race TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            v4_unlocked INTEGER NOT NULL DEFAULT 0,
            v4_tier INTEGER NOT NULL DEFAULT 0,
            trials_completed INTEGER NOT NULL DEFAULT 0,
            training_activations INTEGER NOT NULL DEFAULT 0,
            training_seconds REAL NOT NULL DEFAULT 0,
            total_v4_seconds REAL NOT NULL DEFAULT 0,
            PRIMARY KEY(profile_id, race),
            FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS training_steps (
            tier INTEGER PRIMARY KEY,
            cost INTEGER NOT NULL,
            activations_required INTEGER NOT NULL,
            activation_duration_seconds INTEGER NOT NULL DEFAULT 0,
            minutes_required INTEGER NOT NULL DEFAULT 0,
            trial_required INTEGER NOT NULL,
            title TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            race TEXT NOT NULL DEFAULT '',
            stage_tier INTEGER NOT NULL DEFAULT -1,
            duration_seconds REAL NOT NULL,
            ended_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS training_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            race TEXT NOT NULL DEFAULT '',
            tier INTEGER NOT NULL,
            cost INTEGER NOT NULL,
            previous_tier INTEGER NOT NULL DEFAULT 0,
            previous_training_seconds REAL NOT NULL DEFAULT 0,
            previous_activations INTEGER NOT NULL DEFAULT 0,
            completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS app_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL
        );
        """)

        # Migrate databases created by the previous single-race version.
        self._add_column_if_missing("sessions", "race", "TEXT NOT NULL DEFAULT ''")
        self._add_column_if_missing("sessions", "stage_tier", "INTEGER NOT NULL DEFAULT -1")
        self._add_column_if_missing("training_history", "race", "TEXT NOT NULL DEFAULT ''")
        self._add_column_if_missing("training_history", "previous_tier", "INTEGER NOT NULL DEFAULT 0")
        self._add_column_if_missing("training_history", "previous_training_seconds", "REAL NOT NULL DEFAULT 0")
        self._add_column_if_missing("training_history", "previous_activations", "INTEGER NOT NULL DEFAULT 0")
        self._add_column_if_missing("training_steps", "activation_duration_seconds", "INTEGER NOT NULL DEFAULT 0")

        # Copy old profile-level race fields into the new per-race table once.
        self.conn.execute("""
            INSERT OR IGNORE INTO race_progress
                (profile_id, race, active, v4_unlocked, v4_tier, trials_completed,
                 training_activations, training_seconds, total_v4_seconds)
            SELECT id, race, 1, v4_unlocked, v4_tier, trials_completed,
                   training_activations, training_seconds, total_v4_seconds
            FROM profiles
        """)
        # Older log entries had no race field; attribute them to that profile's original race.
        self.conn.execute("""
            UPDATE sessions SET race=COALESCE(
                (SELECT race FROM profiles WHERE profiles.id=sessions.profile_id), 'Human'
            ) WHERE race='' OR race IS NULL
        """)
        self.conn.execute("""
            UPDATE training_history SET race=COALESCE(
                (SELECT race FROM profiles WHERE profiles.id=training_history.profile_id), 'Human'
            ) WHERE race='' OR race IS NULL
        """)

        for item in TRAININGS:
            self.conn.execute(
                "INSERT OR IGNORE INTO training_steps(tier,cost,activations_required,activation_duration_seconds,minutes_required,trial_required,title) VALUES(?,?,?,?,?,?,?)",
                (item["tier"], item["cost"], item["activations"], item["activation_duration"], item["minutes"], item["trial"], item["label"]),
            )
            # Keep existing installations aligned with the current game reference data.
            self.conn.execute(
                "UPDATE training_steps SET cost=?, activations_required=?, activation_duration_seconds=?, minutes_required=?, trial_required=?, title=? WHERE tier=?",
                (item["cost"], item["activations"], item["activation_duration"], item["minutes"], item["trial"], item["label"], item["tier"]),
            )
        self.conn.execute("DELETE FROM training_steps WHERE tier > ?", (len(TRAININGS),))
        # Older releases used ten placeholder tiers; cap saved progress to the new five-tier model.
        self.conn.execute("UPDATE race_progress SET v4_tier=MIN(v4_tier, ?)", (len(TRAININGS),))
        self.conn.execute("UPDATE profiles SET v4_tier=MIN(v4_tier, ?)", (len(TRAININGS),))
        default_settings = {
            "global_hotkey": DEFAULT_HOTKEY,
            "language": "ru",
            "theme": "red",
            "admin_red_theme_applied": "0",
            "notify_ready": "1",
            "notify_sound": "0",
            "minimize_to_tray": "0",
            "launch_at_startup": "0",
            "backup_before_clear": "1",
        }
        for key, value in default_settings.items():
            self.conn.execute("INSERT OR IGNORE INTO app_settings(setting_key,setting_value) VALUES(?,?)", (key, value))
        # Repair counters left behind if earlier versions' history rows were deleted manually.
        self._repair_stale_totals()
        self.conn.commit()

    def _repair_stale_totals(self):
        for state in self.conn.execute("SELECT * FROM race_progress").fetchall():
            pid, race, tier = int(state["profile_id"]), str(state["race"]), int(state["v4_tier"])
            rows = self.conn.execute("SELECT duration_seconds, stage_tier FROM sessions WHERE profile_id=? AND race=?", (pid, race)).fetchall()
            total = sum(max(0.0, float(row["duration_seconds"])) for row in rows)
            if not rows:
                stage_total, activations = 0.0, 0
            else:
                current_rows = [row for row in rows if int(row["stage_tier"]) == tier]
                legacy_rows = [row for row in rows if int(row["stage_tier"]) < 0]
                if legacy_rows and not current_rows:
                    # Preserve stage progress from older sessions that don't record a Tier.
                    stage_total = float(state["training_seconds"])
                    activations = int(state["training_activations"])
                else:
                    stage_total = sum(max(0.0, float(row["duration_seconds"])) for row in current_rows)
                    activations = len(current_rows)
            self.conn.execute("UPDATE race_progress SET total_v4_seconds=?,training_seconds=?,training_activations=? WHERE profile_id=? AND race=?",
                              (total, stage_total, activations, pid, race))
            base = self.conn.execute("SELECT race FROM profiles WHERE id=?", (pid,)).fetchone()
            if base and base["race"] == race:
                self.conn.execute("UPDATE profiles SET total_v4_seconds=?,training_seconds=?,training_activations=? WHERE id=?",
                                  (total, stage_total, activations, pid))

    def _add_column_if_missing(self, table: str, column: str, definition: str):
        columns = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def profiles(self):
        return self.conn.execute("SELECT * FROM profiles ORDER BY id").fetchall()

    def profile_base(self, profile_id: int):
        row = self.conn.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
        return dict(row) if row else None

    def profile(self, profile_id: int, race: Optional[str] = None):
        base = self.profile_base(profile_id)
        if not base:
            return None
        race = race or base["race"]
        state = self.conn.execute(
            "SELECT * FROM race_progress WHERE profile_id=? AND race=?", (profile_id, race)
        ).fetchone()
        if state:
            base.update(dict(state))
        base["race"] = race
        return base

    def race_progresses(self, profile_id: int):
        rows = self.conn.execute("SELECT * FROM race_progress WHERE profile_id=?", (profile_id,)).fetchall()
        result = {r["race"]: dict(r) for r in rows}
        # Keep all races available in the editor, including races not added yet.
        for race in RACES:
            result.setdefault(race, {
                "profile_id": profile_id, "race": race, "active": 0, "v4_unlocked": 0,
                "v4_tier": 0, "trials_completed": 0, "training_activations": 0,
                "training_seconds": 0.0, "total_v4_seconds": 0.0,
            })
        return result

    def active_races(self, profile_id: int):
        rows = self.conn.execute(
            "SELECT race FROM race_progress WHERE profile_id=? AND active=1", (profile_id,)
        ).fetchall()
        names = {r["race"] for r in rows}
        return [race for race in RACES if race in names]

    def save_profile(self, profile_id: Optional[int], data: dict) -> int:
        race_data = data["race_progresses"]
        active = [race for race in RACES if race_data.get(race, {}).get("active")]
        if not active:
            raise ValueError("Добавь хотя бы одну расу в профиль.")
        primary_race = active[0]
        main_state = race_data[primary_race]
        if profile_id is None:
            cur = self.conn.execute("""INSERT INTO profiles
                (name,race,player_level,fragments,v4_unlocked,v4_tier,trials_completed,
                 training_activations,training_seconds,total_v4_seconds)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (
                    data["name"], primary_race, data["player_level"], data["fragments"],
                    main_state["v4_unlocked"], main_state["v4_tier"], main_state["trials_completed"],
                    main_state.get("training_activations", 0), main_state.get("training_seconds", 0),
                    main_state.get("total_v4_seconds", 0),
                ))
            pid = int(cur.lastrowid)
        else:
            self.conn.execute("""UPDATE profiles SET name=?,race=?,player_level=?,fragments=?,
                v4_unlocked=?,v4_tier=?,trials_completed=?,training_activations=?,training_seconds=?,total_v4_seconds=?
                WHERE id=?""", (
                    data["name"], primary_race, data["player_level"], data["fragments"],
                    main_state["v4_unlocked"], main_state["v4_tier"], main_state["trials_completed"],
                    main_state.get("training_activations", 0), main_state.get("training_seconds", 0),
                    main_state.get("total_v4_seconds", 0), profile_id,
                ))
            pid = profile_id

        for race in RACES:
            state = race_data.get(race, {})
            self.conn.execute("""INSERT INTO race_progress
                (profile_id,race,active,v4_unlocked,v4_tier,trials_completed,
                 training_activations,training_seconds,total_v4_seconds)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(profile_id,race) DO UPDATE SET
                    active=excluded.active,
                    v4_unlocked=excluded.v4_unlocked,
                    v4_tier=excluded.v4_tier,
                    trials_completed=excluded.trials_completed""", (
                pid, race, int(bool(state.get("active", False))), int(bool(state.get("v4_unlocked", 0))),
                int(state.get("v4_tier", 0)), int(state.get("trials_completed", 0)),
                int(state.get("training_activations", 0)), float(state.get("training_seconds", 0)),
                float(state.get("total_v4_seconds", 0)),
            ))
        self.conn.commit()
        return int(pid)

    def delete_profile(self, profile_id: int):
        self.conn.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
        self.conn.commit()

    def add_session(self, profile_id: int, race: str, duration: float, stage_tier: int):
        stamp = datetime.now().isoformat(sep=" ", timespec="microseconds")
        self.conn.execute(
            "INSERT INTO sessions(profile_id,race,stage_tier,duration_seconds,ended_at) VALUES(?,?,?,?,?)",
            (profile_id, race, stage_tier, duration, stamp),
        )
        self.conn.execute("""UPDATE race_progress SET total_v4_seconds=total_v4_seconds+?,
            training_seconds=training_seconds+?, training_activations=training_activations+1
            WHERE profile_id=? AND race=?""", (duration, duration, profile_id, race))
        self.conn.commit()

    def log_training(self, profile_id: int, race: str, tier: int, cost: int,
                     previous_tier: int, previous_seconds: float, previous_activations: int):
        stamp = datetime.now().isoformat(sep=" ", timespec="microseconds")
        self.conn.execute("""INSERT INTO training_history
            (profile_id,race,tier,cost,previous_tier,previous_training_seconds,previous_activations,completed_at)
            VALUES(?,?,?,?,?,?,?,?)""", (
            profile_id, race, tier, cost, previous_tier, previous_seconds, previous_activations, stamp
        ))
        self.conn.execute("UPDATE profiles SET fragments=fragments-? WHERE id=?", (cost, profile_id))
        self.conn.execute("""UPDATE race_progress SET v4_tier=?, training_activations=0,
            training_seconds=0 WHERE profile_id=? AND race=?""", (tier, profile_id, race))
        self.conn.commit()

    def current_training(self, current_tier: int):
        return self.conn.execute("SELECT * FROM training_steps WHERE tier=?", (current_tier + 1,)).fetchone()

    def training_steps(self):
        return self.conn.execute("SELECT * FROM training_steps ORDER BY tier").fetchall()

    def history(self, profile_id: int, race: str, limit: int = 1000):
        sessions = self.conn.execute("""SELECT id AS event_id, 'session' AS event_type,
            'V4-сессия' AS kind, duration_seconds AS amount, ended_at AS when_at,
            NULL AS tier FROM sessions WHERE profile_id=? AND race=? ORDER BY id DESC LIMIT ?""",
            (profile_id, race, limit)).fetchall()
        trainings = self.conn.execute("""SELECT id AS event_id, 'training' AS event_type,
            'Тренировка' AS kind, cost AS amount, completed_at AS when_at,
            tier FROM training_history WHERE profile_id=? AND race=? ORDER BY id DESC LIMIT ?""",
            (profile_id, race, limit)).fetchall()
        return sorted([dict(r) for r in list(sessions) + list(trainings)],
                      key=lambda r: (r["when_at"], r["event_id"]), reverse=True)[:limit]

    def delete_history_entry(self, profile_id: int, race: str, event_type: str, event_id: int):
        if event_type == "session":
            row = self.conn.execute("""SELECT duration_seconds,stage_tier FROM sessions
                WHERE id=? AND profile_id=? AND race=?""", (event_id, profile_id, race)).fetchone()
            if not row:
                raise ValueError("Эта запись уже удалена.")
            self.conn.execute("DELETE FROM sessions WHERE id=?", (event_id,))
            self.recalculate_race_totals(profile_id, race)
        elif event_type == "training":
            row = self.conn.execute("""SELECT * FROM training_history
                WHERE id=? AND profile_id=? AND race=?""", (event_id, profile_id, race)).fetchone()
            if not row:
                raise ValueError("Эта запись уже удалена.")
            progress = self.conn.execute("SELECT v4_tier FROM race_progress WHERE profile_id=? AND race=?",
                                        (profile_id, race)).fetchone()
            current_tier = int(progress["v4_tier"]) if progress else 0
            if current_tier != int(row["tier"]):
                raise ValueError("Можно отменить только последнюю тренировку текущей расы. Сначала убери более новые изменения или исправь уровень расы в профиле.")
            # Refuse to rewind a training if later events depend on it. Delete those entries first.
            later_session = self.conn.execute("""SELECT 1 FROM sessions WHERE profile_id=? AND race=?
                AND ended_at>=? LIMIT 1""", (profile_id, race, row["completed_at"])).fetchone()
            later_training = self.conn.execute("""SELECT 1 FROM training_history WHERE profile_id=? AND race=?
                AND id<>? AND completed_at>=? LIMIT 1""", (profile_id, race, event_id, row["completed_at"])).fetchone()
            if later_session or later_training:
                raise ValueError("После этой тренировки есть более новые записи. Удали их сначала, затем повтори отмену тренировки.")
            self.conn.execute("UPDATE profiles SET fragments=fragments+? WHERE id=?", (int(row["cost"]), profile_id))
            self.conn.execute("""UPDATE race_progress SET v4_tier=?,training_seconds=?,training_activations=?
                WHERE profile_id=? AND race=?""", (
                int(row["previous_tier"]), float(row["previous_training_seconds"]),
                int(row["previous_activations"]), profile_id, race
            ))
            self.conn.execute("DELETE FROM training_history WHERE id=?", (event_id,))
            self.recalculate_race_totals(profile_id, race)
        else:
            raise ValueError("Неизвестный тип записи.")
        self.conn.commit()

    def recalculate_race_totals(self, profile_id: int, race: str):
        """Rebuild accumulated time from the surviving session log instead of trusting stale counters."""
        state = self.conn.execute(
            "SELECT v4_tier, training_seconds, training_activations FROM race_progress WHERE profile_id=? AND race=?",
            (profile_id, race),
        ).fetchone()
        if not state:
            return
        rows = self.conn.execute(
            "SELECT duration_seconds, stage_tier FROM sessions WHERE profile_id=? AND race=?",
            (profile_id, race),
        ).fetchall()
        total = sum(max(0.0, float(row["duration_seconds"])) for row in rows)
        current_tier = int(state["v4_tier"])
        current_rows = [r for r in rows if int(r["stage_tier"]) == current_tier]
        # Untagged legacy sessions still count toward lifetime time, but cannot safely be
        # assigned to the current upgrade stage. Use surviving tagged entries as the source
        # of truth so deleting a session can never leave its duration behind in the counter.
        stage_total = sum(max(0.0, float(r["duration_seconds"])) for r in current_rows)
        activations = len(current_rows)
        self.conn.execute("UPDATE race_progress SET total_v4_seconds=?, training_seconds=?, training_activations=? WHERE profile_id=? AND race=?",
                          (total, stage_total, activations, profile_id, race))
        # Keep the legacy mirrored columns in profiles in sync with the first/primary race.
        base = self.conn.execute("SELECT race FROM profiles WHERE id=?", (profile_id,)).fetchone()
        if base and base["race"] == race:
            self.conn.execute("UPDATE profiles SET total_v4_seconds=?, training_seconds=?, training_activations=? WHERE id=?",
                              (total, stage_total, activations, profile_id))

    def clear_session_history(self, profile_id: int, race: str) -> int:
        """Delete every time session for one race and rebuild all time counters from the remaining rows.

        Recalculation (instead of only changing the visible cache) prevents old totals from
        reappearing on the dashboard after switching pages or restarting the application.
        """
        with self.conn:
            # Defensive repair for a partially migrated profile with no row for this race.
            self.conn.execute("""INSERT OR IGNORE INTO race_progress
                (profile_id,race,active,v4_unlocked,v4_tier,trials_completed,
                 training_activations,training_seconds,total_v4_seconds)
                SELECT id,?,0,0,0,0,0,0,0 FROM profiles WHERE id=?""", (race, profile_id))
            cursor = self.conn.execute("DELETE FROM sessions WHERE profile_id=? AND race=?", (profile_id, race))
            deleted_count = max(0, int(cursor.rowcount))
            # This computes SUM(duration_seconds) from the database after deletion. With no
            # remaining sessions both lifetime and current-stage time become exactly zero.
            self.recalculate_race_totals(profile_id, race)
        return deleted_count

    def setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT setting_value FROM app_settings WHERE setting_key=?", (key,)).fetchone()
        return str(row[0]) if row else default

    def set_setting(self, key: str, value: str):
        self.conn.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES(?,?) "
                          "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",
                          (key, value))
        self.conn.commit()

    def close(self):
        self.conn.close()


STYLE = """
* { font-family: 'Segoe UI'; }
QMainWindow, QWidget#root { background: #0a1020; color: #ecf4ff; }
QWidget { color: #ecf4ff; font-size: 10pt; }
QFrame#sidebar { background: #0d1528; border-right: 1px solid #202c45; }
QFrame#panel, QFrame#statCard { background: #121d32; border: 1px solid #243451; border-radius: 15px; }
QFrame#statCard { min-height: 112px; }
QLabel#brand { font-size: 17pt; font-weight: 800; color: #62e4ff; }
QLabel#adminBadge { color: #ff687d; background: #351019; border: 1px solid #e42d4f; padding: 5px 8px; border-radius: 7px; font-size: 8pt; font-weight: 800; }
QLabel#muted { color: #8ea3c4; }
QLabel#pageTitle { font-size: 23pt; font-weight: 750; }
QLabel#statNumber { font-size: 21pt; font-weight: 750; color: #f5f9ff; }
QLabel#accent { color: #65e7ff; font-weight: 700; }
QLabel#success { color: #69f0ae; font-weight: 700; }
QLabel#warning { color: #ffca70; font-weight: 700; }
QPushButton { background: #202f4b; border: 1px solid #344866; padding: 10px 14px; border-radius: 9px; font-weight: 650; }
QPushButton:hover { background: #2a3e61; border-color: #5a7ca8; }
QPushButton#primary { background: #16a9d0; border: 1px solid #16a9d0; color: #04121d; font-weight: 800; }
QPushButton#primary:hover { background: #48d6f5; }
QPushButton#danger { background: #472538; border-color: #75405a; color: #ffd9e6; }
QPushButton#nav { text-align: left; padding: 12px 15px; background: transparent; border: 0; color: #9dafce; }
QPushButton#nav:checked, QPushButton#nav:hover { background: #1b2d4b; color: #ffffff; border-radius: 9px; }
QComboBox, QLineEdit, QSpinBox, QKeySequenceEdit { background: #0c1628; border: 1px solid #2b3c59; border-radius: 8px; padding: 8px 10px; min-height: 20px; selection-background-color: #139dca; }
QComboBox::drop-down { border: 0; width: 25px; }
QComboBox QAbstractItemView { background: #121d32; selection-background-color: #1f7da0; }
QProgressBar { background: #0b1424; border: 1px solid #2b3b58; border-radius: 7px; text-align: center; min-height: 16px; color: #eaf8ff; }
QProgressBar::chunk { background: #1cc5e8; border-radius: 6px; }
QTableWidget { background: #0f192b; alternate-background-color: #131f34; border: 1px solid #253651; border-radius: 10px; gridline-color: #253651; }
QHeaderView::section { background: #1a2942; border: 0; padding: 9px; color: #afc6e9; font-weight: 700; }
QTableWidget::item { padding: 5px; border-bottom: 1px solid #202f49; }
QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 18px; height: 18px; }
QScrollArea { border: none; }
"""


# All theme styles are recolors of the same tested base stylesheet; this keeps the layout consistent.
THEME_COLORS = {
    "emerald": {
        "#0a1020":"#071b14", "#0d1528":"#0b241a", "#121d32":"#102d21",
        "#202c45":"#244a37", "#243451":"#28523d", "#ecf4ff":"#e8fff2",
        "#8ea3c4":"#91b8a0", "#f5f9ff":"#f4fff8", "#62e4ff":"#5fffc0",
        "#65e7ff":"#5fffc0", "#69f0ae":"#74f8b7", "#202f4b":"#1b3b2a",
        "#344866":"#315b43", "#2a3e61":"#26543a", "#5a7ca8":"#4b976a",
        "#16a9d0":"#19c985", "#04121d":"#03180e", "#48d6f5":"#56edaa",
        "#472538":"#48262a", "#75405a":"#85504d", "#ffd9e6":"#ffe8e2",
        "#9dafce":"#a1c6ae", "#1b2d4b":"#173b2a", "#0c1628":"#0b2118",
        "#2b3c59":"#2a503b", "#139dca":"#15c881", "#1f7da0":"#24885b",
        "#0b1424":"#081b13", "#2b3b58":"#28513b", "#eaf8ff":"#effff5",
        "#1cc5e8":"#21db91", "#0f192b":"#0d251b", "#131f34":"#123022",
        "#253651":"#254a37", "#1a2942":"#193b2a", "#afc6e9":"#b3dfc0",
        "#202f49":"#1b3928"
    },
    "purple": {
        "#0a1020":"#140b20", "#0d1528":"#1c102d", "#121d32":"#251638",
        "#202c45":"#3c2850", "#243451":"#49305f", "#ecf4ff":"#fbf1ff",
        "#8ea3c4":"#b7a0ce", "#f5f9ff":"#fff7ff", "#62e4ff":"#e0a5ff",
        "#65e7ff":"#e0a5ff", "#69f0ae":"#d8a0ff", "#202f4b":"#37214b",
        "#344866":"#55366b", "#2a3e61":"#4a2b64", "#5a7ca8":"#805ba0",
        "#16a9d0":"#ad58e8", "#04121d":"#160620", "#48d6f5":"#cc8aff",
        "#472538":"#4c244d", "#75405a":"#8b4f91", "#ffd9e6":"#ffe6ff",
        "#9dafce":"#c0add5", "#1b2d4b":"#3a2050", "#0c1628":"#1b1029",
        "#2b3c59":"#4b3060", "#139dca":"#a94bde", "#1f7da0":"#7c39a8",
        "#0b1424":"#180d25", "#2b3b58":"#472b5c", "#eaf8ff":"#fff5ff",
        "#1cc5e8":"#be67f1", "#0f192b":"#20132f", "#131f34":"#291a3a",
        "#253651":"#3c2750", "#1a2942":"#342044", "#afc6e9":"#d1b9e7",
        "#202f49":"#382146"
    },
    "white": {
        "#0a1020":"#f4f7fb", "#0d1528":"#e7edf5", "#121d32":"#ffffff",
        "#202c45":"#d5dfeb", "#243451":"#d5dfeb", "#ecf4ff":"#1c2738",
        "#8ea3c4":"#566579", "#f5f9ff":"#182235", "#62e4ff":"#087fa4",
        "#65e7ff":"#087fa4", "#69f0ae":"#167b51", "#202f4b":"#e5edf6",
        "#344866":"#c4d0df", "#2a3e61":"#d6e2f0", "#5a7ca8":"#7a9abb",
        "#16a9d0":"#087fa4", "#04121d":"#ffffff", "#48d6f5":"#139ec4",
        "#472538":"#f7e5e9", "#75405a":"#d6aab5", "#ffd9e6":"#72283a",
        "#9dafce":"#566579", "#1b2d4b":"#dbe6f2", "#0c1628":"#ffffff",
        "#2b3c59":"#c5d1df", "#139dca":"#1585a8", "#1f7da0":"#138caf",
        "#0b1424":"#edf2f8", "#2b3b58":"#c7d4e2", "#eaf8ff":"#1c2738",
        "#1cc5e8":"#159ac1", "#0f192b":"#ffffff", "#131f34":"#f4f7fb",
        "#253651":"#d5dfeb", "#1a2942":"#e5edf6", "#afc6e9":"#40536b",
        "#202f49":"#dce5ef"
    },
    "black": {
        "#0a1020":"#050607", "#0d1528":"#090b0e", "#121d32":"#101216",
        "#202c45":"#202328", "#243451":"#262a30", "#ecf4ff":"#e6e8ec",
        "#8ea3c4":"#969ba5", "#f5f9ff":"#f0f1f4", "#62e4ff":"#63b9ff",
        "#65e7ff":"#63b9ff", "#69f0ae":"#65d7a1", "#202f4b":"#181b20",
        "#344866":"#30363e", "#2a3e61":"#252a32", "#5a7ca8":"#485360",
        "#16a9d0":"#167fac", "#04121d":"#ffffff", "#48d6f5":"#58b4ed",
        "#472538":"#2c1b23", "#75405a":"#4b303a", "#ffd9e6":"#f4dce4",
        "#9dafce":"#a4aab4", "#1b2d4b":"#171a20", "#0c1628":"#0b0d10",
        "#2b3c59":"#292e36", "#139dca":"#167fac", "#1f7da0":"#166084",
        "#0b1424":"#080a0c", "#2b3b58":"#252a31", "#eaf8ff":"#e8edf3",
        "#1cc5e8":"#348fc8", "#0f192b":"#0b0d10", "#131f34":"#12151a",
        "#253651":"#252a31", "#1a2942":"#171a20", "#afc6e9":"#bdc5d0",
        "#202f49":"#171a1f"
    },
    "red": {
        "#0a1020":"#1b070c", "#0d1528":"#290b12", "#121d32":"#351019",
        "#202c45":"#5c1c28", "#243451":"#632330", "#ecf4ff":"#fff0f2",
        "#8ea3c4":"#d0a0a8", "#f5f9ff":"#fff7f8", "#62e4ff":"#ff687d",
        "#65e7ff":"#ff657a", "#69f0ae":"#ff95a6", "#202f4b":"#4a1721",
        "#344866":"#71303d", "#2a3e61":"#5e2430", "#5a7ca8":"#a64a5a",
        "#16a9d0":"#e42d4f", "#04121d":"#1c0509", "#48d6f5":"#ff6278",
        "#472538":"#53202b", "#75405a":"#894052", "#ffd9e6":"#ffe4eb",
        "#9dafce":"#d4a5ad", "#1b2d4b":"#411723", "#0c1628":"#25090f",
        "#2b3c59":"#602332", "#139dca":"#d91f41", "#1f7da0":"#9e1830",
        "#0b1424":"#1f070c", "#2b3b58":"#57202b", "#eaf8ff":"#fff1f4",
        "#1cc5e8":"#ff405e", "#0f192b":"#2b0d13", "#131f34":"#3b141d",
        "#253651":"#56202c", "#1a2942":"#431722", "#afc6e9":"#efb6c1",
        "#202f49":"#431722"
    }
}


def theme_stylesheet(theme: str) -> str:
    palette = THEME_COLORS.get(theme, THEME_COLORS["emerald"])
    pattern = re.compile("|".join(re.escape(k) for k in sorted(palette, key=len, reverse=True)))
    return pattern.sub(lambda match: palette[match.group(0)], STYLE)


_TRANSLATIONS = {
    "◈   Обзор": "◈   Overview", "♙   Профили": "♙   Profiles",
    "✦   База тренировок": "✦   Training database", "◷   История": "◷   History",
    "⚙   Настройки": "⚙   Settings", "BLOX FRUITS  •  COMPANION": "BLOX FRUITS  •  COMPANION",
    "ТВОЙ ПРОГРЕСС": "YOUR PROGRESS", "Локальная база SQLite\nДанные хранятся на ПК": "Local SQLite database\nData is stored on this PC",
    "Версия 2.4.0 ADMIN · SQLite\nДанные хранятся на ПК": "Version 2.4.0 ADMIN · SQLite\nData is stored on this PC",
    "Обзор": "Overview", "Профили": "Profiles", "База тренировок": "Training database", "История": "History", "Настройки": "Settings",
    "Твой прогресс по Race V4": "Your Race V4 progress", "РАСА": "RACE", "УРОВЕНЬ ИГРОКА": "PLAYER LEVEL",
    "ФРАГМЕНТЫ": "FRAGMENTS", "ВРЕМЯ В V4": "V4 TIME", "Выбранный профиль": "Selected profile",
    "Максимум: 3000": "Maximum: 3000", "Баланс аккаунта": "Account balance", "По выбранной расе": "For selected race",
    "Время V4": "V4 time", "Активации (~)": "Activations (approx.)", "Длительность": "Activation duration",
    "Улучшение Race V4 — уровень 1": "Race V4 upgrade — Tier 1",
    "Улучшение Race V4 — уровень 2": "Race V4 upgrade — Tier 2",
    "Улучшение Race V4 — уровень 3": "Race V4 upgrade — Tier 3",
    "Улучшение Race V4 — уровень 4": "Race V4 upgrade — Tier 4",
    "Улучшение Race V4 — уровень 5 (MAX)": "Race V4 upgrade — Tier 5 (MAX)",
    "Следующая тренировка": "Next upgrade", "Добавь профиль, чтобы начать": "Add a profile to get started",
    "Стоимость и требования появятся здесь.": "Cost and requirements will appear here.", "Время этапа: 00:00:00 / —": "Stage time: 00:00:00 / —",
    "Фрагменты: —": "Fragments: —", "Испытание: —": "Trial: —", "ОЖИДАЕТ ДАННЫХ": "WAITING FOR DATA",
    "Отметить тренировку выполненной": "Mark upgrade as completed", "Таймер времени в V4": "V4 time tracker",
    "Горячая клавиша: —": "Hotkey: —", "Запускай отсчёт при входе в V4 и останавливай при выходе. Важна длительность, а не число активаций.": "Start tracking when entering V4 and stop when leaving. Duration matters, not activation count.",
    "● Таймер остановлен": "● Timer stopped", "▶   Старт V4": "▶   Start V4", "■   Стоп и сохранить время": "■   Stop and save time",
    "Повторное нажатие горячей клавиши переключает таймер Старт/Стоп.": "Press the hotkey again to toggle the timer.",
    "Последние события": "Recent events", "Вся история →": "Full history →", "Событие": "Event", "Детали": "Details", "Дата": "Date",
    "Один профиль = один аккаунт. Внутри можно вести несколько рас с отдельным прогрессом.": "One profile equals one account. Track several races with independent progress.",
    "＋  Добавить профиль": "＋  Add profile", "Изменить выбранный": "Edit selected", "Удалить профиль": "Delete profile",
    "Профиль": "Profile", "Расы": "Races", "Уровень": "Level", "Прогресс рас": "Race progress", "Общее время": "Total time",
    "Справочник улучшений Race V4. Время и число активаций приблизительные; длительность одной активации указана отдельно.": "Race V4 upgrade reference. Time and activation count are estimates; typical duration per activation is shown separately.",
    "Tier": "Tier", "Название": "Name", "Нужно времени в V4": "V4 time required", "Испытание": "Trial",
    "Таймер не считывает игру автоматически: после каждой трансформации сохрани сессию. Расы и их время хранятся отдельно.": "The tracker does not read the game automatically. Save each V4 session manually; race times are stored separately.",
    "История выбранной расы. Можно удалить ошибочную сессию или отменить последнюю тренировку.": "History for the selected race. Delete an incorrect session or undo the latest upgrade.",
    "Удалить выбранную запись / отменить изменение": "Delete selected entry / undo change", "Очистить записи времени этой расы": "Clear this race's time records",
    "Тип события": "Event type", "Длительность / расход": "Duration / cost", "Дата и время": "Date and time", "ID": "ID",
    "Горячая клавиша таймера": "Timer hotkey", "Глобальная клавиша работает, даже когда открыта игра. Нажми её один раз для старта V4 и повторно — для остановки и сохранения.": "The global hotkey works while the game is active. Press once to start V4 tracking and again to stop and save.",
    "Сохранить горячую клавишу": "Save hotkey", "Новая комбинация:": "New shortcut:", "Статус регистрации клавиши появится здесь.": "Hotkey status will appear here.",
    "Интерфейс": "Interface", "Язык интерфейса": "Interface language", "Тема оформления": "Theme", "Русский": "Russian", "Изумрудная": "Emerald", "Пурпурная": "Purple", "Белая": "White", "Чёрная": "Black", "Красная": "Red",
    "Админские инструменты": "Admin tools", "Экспортировать историю (CSV)": "Export history (CSV)", "Экспортировать прогресс (CSV)": "Export progress (CSV)", "Проверить целостность базы": "Check database integrity",
    "Экспорт истории": "Export history", "Экспорт прогресса": "Export progress", "CSV-файлы (*.csv)": "CSV files (*.csv)", "Нет данных для экспорта.": "There is no data to export.",
    "CSV-файл успешно сохранён:": "CSV file saved:", "Записей:": "Rows:", "Проверка целостности БД": "Database integrity check", "База данных исправна.": "Database integrity check passed.",
    "База данных сообщила об ошибке:": "Database reported an integrity issue:", "Профилей:": "Profiles:", "Рас в прогрессе:": "Race entries:", "Сессий:": "Sessions:", "Тренировок:": "Upgrades:",
    "Уровень игрока": "Player level", "V4 открыта": "V4 unlocked", "Активации этапа": "Stage activations", "Время этапа": "Stage time", "Общее время расы": "Total race time",
    "Длительность (сек.)": "Duration (sec.)", "Да": "Yes", "Нет": "No",
    "Уведомления": "Notifications", "Уведомлять при готовности к улучшению": "Notify when an upgrade is ready", "Звуковой сигнал вместе с уведомлением": "Play a sound with notifications",
    "Профиль:": "Profile:", "Раса:": "Race:",
    "Дополнительные настройки": "Additional settings", "Запускать вместе с Windows": "Launch with Windows", "Сворачивать в трей при закрытии окна": "Minimize to tray when closing the window",
    "Создать резервную копию базы": "Create database backup", "Открыть папку данных": "Open data folder", "Создавать резервную копию перед очисткой времени": "Create a backup before clearing time records",
    "Инструменты базы данных": "Database tools", "Сообщество и поддержка": "Community and support", "Открыть Discord-сервер": "Open Discord server",
    "Данные и настройки хранятся локально на этом ПК.": "Data and settings are stored locally on this PC.", "Discord: discord.gg/SvYqcks5Pz": "Discord: discord.gg/SvYqcks5Pz",
    "Создай профиль, чтобы отслеживать прогресс Race V4.": "Create a profile to track Race V4 progress.",
    "Сначала добавь профиль": "Add a profile first", "Профили и прогресс сохраняются локально на компьютере.": "Profiles and progress are saved locally on this PC.",
    "НЕТ ПРОФИЛЯ": "NO PROFILE", "Нет рас": "No races", "Профиль:": "Profile:", "Раса:": "Race:",
    "Профиль игрока": "Player profile", "Настройки профиля": "Profile settings", "Название / аккаунт": "Profile name / account",
    "Например, Основной аккаунт": "For example, Main account", "Уровень игрока": "Player level", "Фрагменты (общие для аккаунта)": "Fragments (shared by account)",
    "Расы этого аккаунта": "Races on this account", "Имя": "Name", "V4 не открыта": "V4 not unlocked", "Пройдено испытаний": "Trials completed",
    "Отметь все расы, прогресс которых хочешь хранить в этом профиле.": "Select each race you want to track in this profile.",
    "Race V4 открыта для выбранной расы": "Race V4 unlocked for selected race", "Настраиваемая раса": "Race to configure",
    "Статус V4": "V4 status", "Уровень тренировок V4": "V4 upgrade tier", "Пройдено испытаний (1–5)": "Trials completed (1–5)",
    "Уровни, испытания и время хранятся отдельно для каждой расы. Фрагменты и уровень игрока общие для аккаунта.": "Tier, trials, and time are stored separately for each race. Fragments and player level are shared by the account.",
    "Профиль:": "Profile:", "Раса:": "Race:", "Сначала добавь профиль": "Add a profile first", "Нет рас": "No races",
    "ВРЕМЯ V4": "V4 TIME", "● Время сессии сохранено": "● Session time saved", "Race V4 для этой расы ещё не открыта": "Race V4 is not unlocked for this race yet",
    "Все 5 улучшений завершены ✦": "All 5 upgrades completed ✦", "НУЖНО ОТКРЫТЬ V4": "UNLOCK V4 FIRST", "МАКСИМАЛЬНЫЙ УРОВЕНЬ": "MAXIMUM TIER",
    "✓ МОЖНО ТРЕНИРОВАТЬСЯ": "✓ UPGRADE AVAILABLE", "МОЖНО ТРЕНИРОВАТЬСЯ": "UPGRADE AVAILABLE", "MAX": "MAX",
    "V4-сессия": "V4 session", "Тренировка": "Upgrade", "фрагментов": "fragments", "фрагменты": "fragments", "Фрагменты": "Fragments",
    "Отметь открытие V4 в настройках профиля, когда оно будет доступно.": "Mark V4 as unlocked in profile settings when available.",
    "Готово": "Done", "Сохранить": "Save", "Отмена": "Cancel", "Создать": "Create", "Удалить": "Delete",
    "Нет выбранных рас": "No races selected", "Отметь хотя бы одну расу для этого профиля.": "Select at least one race for this profile.",
    "Подтвердить изменение": "Confirm change", "Удалить профиль?": "Delete profile?", "Неподдерживаемая клавиша": "Unsupported hotkey",
    "Выбери другой файл: нельзя перезаписать открытую базу данных.": "Choose a different file: the open database cannot be overwritten.",
    "Старт/Стоп таймера V4.": "Start/stop the V4 timer.", "Нужно пройти испытание": "Trial required", "сначала останови таймер": "stop the timer first",
    "Не удалось изменить автозапуск:": "Could not change Windows startup:", "Сохранить активную сессию?": "Save active session?",
    "Таймер V4 ещё запущен. Сохранить прошедшее время?": "The V4 timer is still running. Save the elapsed time?",
    "Таймер активен": "Timer is active", "Сначала останови текущую V4-сессию, затем переключай профиль.": "Stop the current V4 session before switching profiles.",
    "Сначала останови таймер, затем переключай расу.": "Stop the timer before switching races.", "Не удалось сохранить": "Could not save",
    "Останови таймер перед удалением профиля.": "Stop the timer before deleting the profile.", "Удалить профиль?": "Delete profile?",
    "V4 не открыта": "V4 is not unlocked", "В настройках профиля отметь, что V4 этой расы уже открыта.": "Mark V4 as unlocked for this race in profile settings.",
    "Короткая сессия": "Short session", "Прошло меньше секунды. Сохранить это время? Подсчёт идёт по секундам, не по количеству активаций.": "Less than one second has elapsed. Save this time? Tracking is based on seconds, not activation count.",
    "Пока рано": "Not ready yet", "Условия не выполнены:\n• ": "Requirements not met:\n• ", "Подтвердить тренировку": "Confirm upgrade",
    "Запись не выбрана": "No entry selected", "Сначала выбери строку в истории.": "Select a row in the history first.",
    "Подтвердить изменение": "Confirm change", "Не удалось изменить историю": "Could not change history", "Автозапуск": "Startup",
    "Резервная копия создана": "Backup created", "Данные сохранены в:": "Backup saved to:", "Ошибка резервного копирования": "Backup error",
    "Останови таймер перед очисткой записей.": "Stop the timer before clearing records.", "Очистить время этой расы?": "Clear this race's time?",
    "Неподдерживаемая клавиша": "Unsupported hotkey", "Неподдерживаемая комбинация": "Unsupported shortcut", "Готово": "Done",
    "Сохранить активную сессию?": "Save active session?", "Таймер V4 ещё запущен. Сохранить прошедшее время?": "The V4 timer is still running. Save the elapsed time?",
}

_REPLACEMENTS = [
    ("Время V4 на этом этапе:", "V4 time for this stage:"),
    ("Общее время расы", "Total time for race"), ("Время этапа:", "Stage time:"),
    ("Улучшение до Tier", "Upgrade to Tier"), ("Стоимость", "Cost"),
    ("фрагментов", "fragments"), ("фрагменты", "fragments"), ("не хватает", "missing"),
    ("ещё ", "remaining "), ("времени в V4", "of V4 time"), ("нужно испытание", "trial required"),
    ("Испытание ", "Trial "), ("не пройдено", "not completed"), ("пройдено", "completed"),
    ("у тебя ", "you have "), ("останови таймер перед подтверждением", "stop the timer before confirming"),
    (" / 5", " / 5"), ("Аккаунт:", "Account:"), ("Раса:", "Race:"),
    ("V4 открыта", "V4 unlocked"), ("V4 ещё не открыта", "V4 not unlocked"),
    ("Нужно время в V4:", "V4 time required:"), ("По выбранной расе", "For selected race"),
    ("Отметить тренировку выполненной", "Mark upgrade as completed"),
    ("Идёт отсчёт:", "Tracking:"), ("Фрагменты аккаунта:", "Account fragments:"),
    ("Пройдено испытаний:", "Trials completed:"), ("Отметь открытие V4", "Mark V4 as unlocked"),
    ("Удалить «", "Delete “"), ("» и всю историю всех его рас? Это действие нельзя отменить.", "” and all its race history? This cannot be undone."),
    ("Отметить ", "Mark "), (" для расы ", " for race "), ("Будет списано ", "Will spend "),
    (" фрагментов.", " fragments."), ("Время этапа сбросится для следующей тренировки.", "Stage time will reset for the next upgrade."),
    ("удалить сессию и вычесть её время", "delete the session and subtract its time"),
    ("отменить тренировку и вернуть потраченные фрагменты", "undo the upgrade and refund the fragments"),
    ("Ты точно хочешь ", "Are you sure you want to "), ("Если это тренировка, отменить можно только последнюю тренировку без более новых записей.", "Upgrades can only be undone if no newer records depend on them."),
    ("Данные сохранены в:", "Backup saved to:"), ("Не удалось изменить автозапуск:", "Could not change Windows startup:"),
    ("Не удалось распознать эту клавишу. Попробуй ", "Could not recognize this key. Try "),
    ("Выбери одну клавишу или комбинацию, например ", "Choose one key or a shortcut, for example "),
    ("Комбинация ", "Shortcut "), (" сохранена. Отслеживание работает в фоне.", " saved. Tracking works in the background."),
    ("Глобальная клавиша Windows: отслеживается в фоне, даже когда Roblox активен.", "Global Windows hotkey: works in the background while Roblox is active."),
    ("Вне Windows клавиша работает, только когда окно трекера активно.", "Outside Windows, the hotkey works only while the tracker window is active."),
]


def localize_text(text: str, language: str) -> str:
    value = str(text)
    reverse = {v: k for k, v in _TRANSLATIONS.items()}
    if language == "en":
        value = _TRANSLATIONS.get(value, value)
        for ru, en in _REPLACEMENTS:
            value = value.replace(ru, en)
        return value
    value = reverse.get(value, value)
    for ru, en in reversed(_REPLACEMENTS):
        value = value.replace(en, ru)
    return value


class ProfileDialog(QDialog):
    """Account-wide settings plus independent settings for each selected race."""

    def __init__(self, parent=None, data=None, race_progresses=None):
        super().__init__(parent)
        self.setWindowTitle("Профиль игрока")
        self.setMinimumWidth(530)
        selected_theme = parent.db.setting("theme", "emerald") if parent is not None and hasattr(parent, "db") else "emerald"
        self.setStyleSheet(theme_stylesheet(selected_theme))
        self.data = data or {}
        self.race_data = race_progresses or {}
        for race in RACES:
            self.race_data.setdefault(race, {
                "race": race, "active": 0, "v4_unlocked": 0, "v4_tier": 0,
                "trials_completed": 0, "training_activations": 0,
                "training_seconds": 0.0, "total_v4_seconds": 0.0,
            })

        layout = QVBoxLayout(self)
        heading = QLabel("Настройки профиля")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        form = QFormLayout(); form.setVerticalSpacing(10)
        self.name = QLineEdit(self.data.get("name", ""))
        self.name.setPlaceholderText("Например, Основной аккаунт")
        self.level = QSpinBox(); self.level.setRange(1, 3000); self.level.setValue(int(self.data.get("player_level", 3000)))
        self.fragments = QSpinBox(); self.fragments.setRange(0, 999999999); self.fragments.setValue(int(self.data.get("fragments", 0)))
        form.addRow("Название / аккаунт", self.name)
        form.addRow("Уровень игрока", self.level)
        form.addRow("Фрагменты (общие для аккаунта)", self.fragments)
        layout.addLayout(form)

        race_box = QFrame(); race_box.setObjectName("panel")
        race_layout = QVBoxLayout(race_box); race_layout.setContentsMargins(14, 14, 14, 14); race_layout.setSpacing(8)
        race_title = QLabel("Расы этого аккаунта"); race_title.setStyleSheet("font-size:12pt;font-weight:750;")
        race_layout.addWidget(race_title)
        race_grid = QGridLayout(); self.race_checks = {}
        existing = {r for r, v in self.race_data.items() if v.get("active")}
        if not existing:
            fallback = self.data.get("race", "Human")
            existing.add(fallback if fallback in RACES else "Human")
        for index, race in enumerate(RACES):
            check = QCheckBox(race); check.setChecked(race in existing)
            check.stateChanged.connect(self._race_check_changed)
            self.race_checks[race] = check
            race_grid.addWidget(check, index // 4, index % 4)
        race_layout.addLayout(race_grid)
        hint = QLabel("Отметь все расы, прогресс которых хочешь хранить в этом профиле.")
        hint.setObjectName("muted"); hint.setWordWrap(True); race_layout.addWidget(hint)
        layout.addWidget(race_box)

        race_form = QFormLayout(); race_form.setVerticalSpacing(10)
        self.edit_race = QComboBox()
        self._last_edit_race = ""
        self.edit_race.currentTextChanged.connect(self._edit_race_changed)
        self.unlocked = QCheckBox("Race V4 открыта для выбранной расы")
        self.tier = QSpinBox(); self.tier.setRange(0, len(TRAININGS))
        self.trials = QSpinBox(); self.trials.setRange(0, 5)
        self.unlocked.stateChanged.connect(self._toggle_unlocked)
        race_form.addRow("Настраиваемая раса", self.edit_race)
        race_form.addRow("Статус V4", self.unlocked)
        race_form.addRow("Уровень тренировок V4", self.tier)
        race_form.addRow("Пройдено испытаний (1–5)", self.trials)
        layout.addLayout(race_form)
        note = QLabel("Уровни, испытания и время хранятся отдельно для каждой расы. Фрагменты и уровень игрока общие для аккаунта.")
        note.setObjectName("muted"); note.setWordWrap(True); layout.addWidget(note)

        buttons = QHBoxLayout(); buttons.addStretch()
        cancel = QPushButton("Отмена"); cancel.clicked.connect(self.reject)
        save = QPushButton("Сохранить"); save.setObjectName("primary"); save.clicked.connect(self._accept_if_valid)
        buttons.addWidget(cancel); buttons.addWidget(save); layout.addLayout(buttons)
        self._rebuild_race_editor(preferred=next((r for r in RACES if r in existing), RACES[0]))
        language = parent.db.setting("language", "ru") if parent is not None and hasattr(parent, "db") else "ru"
        if language == "en":
            for widget in self.findChildren(QWidget):
                if isinstance(widget, QLabel): widget.setText(localize_text(widget.text(), language))
                elif isinstance(widget, QPushButton): widget.setText(localize_text(widget.text(), language))
                elif isinstance(widget, QCheckBox): widget.setText(localize_text(widget.text(), language))
                if isinstance(widget, QLineEdit): widget.setPlaceholderText(localize_text(widget.placeholderText(), language))
            self.setWindowTitle(localize_text(self.windowTitle(), language))

    def _enabled_races(self):
        return [r for r in RACES if self.race_checks[r].isChecked()]

    def _store_visible_race(self):
        race = self.edit_race.currentText()
        if not race or race not in self.race_data:
            return
        self.race_data[race]["v4_unlocked"] = int(self.unlocked.isChecked())
        self.race_data[race]["v4_tier"] = self.tier.value() if self.unlocked.isChecked() else 0
        self.race_data[race]["trials_completed"] = self.trials.value() if self.unlocked.isChecked() else 0
        self.race_data[race]["active"] = int(self.race_checks[race].isChecked())

    def _load_race(self, race):
        if not race:
            self.unlocked.setChecked(False); self.tier.setValue(0); self.trials.setValue(0)
            return
        state = self.race_data[race]
        self.unlocked.blockSignals(True); self.tier.blockSignals(True); self.trials.blockSignals(True)
        self.unlocked.setChecked(bool(state.get("v4_unlocked", 0)))
        self.tier.setValue(int(state.get("v4_tier", 0)))
        self.trials.setValue(int(state.get("trials_completed", 0)))
        self.unlocked.blockSignals(False); self.tier.blockSignals(False); self.trials.blockSignals(False)
        self._toggle_unlocked()

    def _rebuild_race_editor(self, preferred=None):
        current = self.edit_race.currentText()
        self.edit_race.blockSignals(True); self.edit_race.clear()
        enabled = self._enabled_races()
        self.edit_race.addItems(enabled)
        target = preferred if preferred in enabled else current if current in enabled else (enabled[0] if enabled else "")
        if target:
            self.edit_race.setCurrentText(target)
        self.edit_race.blockSignals(False)
        self._last_edit_race = target
        self._load_race(target)

    def _edit_race_changed(self, race):
        previous = self._last_edit_race
        if previous and previous != race:
            self.race_data[previous]["v4_unlocked"] = int(self.unlocked.isChecked())
            self.race_data[previous]["v4_tier"] = self.tier.value() if self.unlocked.isChecked() else 0
            self.race_data[previous]["trials_completed"] = self.trials.value() if self.unlocked.isChecked() else 0
            self.race_data[previous]["active"] = int(self.race_checks[previous].isChecked())
        self._load_race(race)
        self._last_edit_race = race

    def _race_check_changed(self, *_):
        old_race = self.edit_race.currentText()
        self._store_visible_race()
        enabled = self._enabled_races()
        self._rebuild_race_editor(preferred=old_race if old_race in enabled else (enabled[0] if enabled else None))

    def _toggle_unlocked(self, *_):
        enabled = self.unlocked.isChecked()
        self.tier.setEnabled(enabled); self.trials.setEnabled(enabled)
        if not enabled:
            self.tier.setValue(0); self.trials.setValue(0)

    def _accept_if_valid(self):
        self._store_visible_race()
        if not self._enabled_races():
            parent = self.parent()
            language = parent.db.setting("language", "ru") if parent is not None and hasattr(parent, "db") else "ru"
            QMessageBox.warning(self, localize_text("Нет выбранных рас", language),
                                localize_text("Отметь хотя бы одну расу для этого профиля.", language))
            return
        self.accept()

    def values(self):
        self._store_visible_race()
        for race in RACES:
            self.race_data[race]["active"] = int(self.race_checks[race].isChecked())
        return {
            "name": self.name.text().strip() or "Мой аккаунт",
            "player_level": self.level.value(),
            "fragments": self.fragments.value(),
            "race_progresses": self.race_data,
        }


class StatCard(QFrame):
    def __init__(self, title: str, value: str, subtitle: str, accent: str = "#62e4ff"):
        super().__init__(); self.setObjectName("statCard")
        layout = QVBoxLayout(self); layout.setContentsMargins(17, 14, 17, 14); layout.setSpacing(7)
        top = QLabel(title); top.setObjectName("muted")
        self.value = QLabel(value); self.value.setObjectName("statNumber"); self.value.setStyleSheet(f"color:{accent};")
        self.subtitle = QLabel(subtitle); self.subtitle.setObjectName("muted")
        layout.addWidget(top); layout.addWidget(self.value); layout.addWidget(self.subtitle); layout.addStretch()


# Map Qt portable key names to Windows virtual keys for background polling.
def parse_windows_hotkey(text: str):
    parts = [part.strip() for part in text.split("+") if part.strip()]
    if not parts:
        return None
    modifiers = 0
    for part in parts[:-1]:
        low = part.casefold()
        if low in ("ctrl", "control"):
            modifiers |= 0x0002
        elif low == "alt":
            modifiers |= 0x0001
        elif low == "shift":
            modifiers |= 0x0004
        elif low in ("meta", "win", "windows", "cmd"):
            modifiers |= 0x0008
        else:
            return None
    key = parts[-1]
    low = key.casefold()
    named = {
        "backspace": 0x08, "tab": 0x09, "return": 0x0D, "enter": 0x0D,
        "esc": 0x1B, "escape": 0x1B, "space": 0x20, "pageup": 0x21,
        "pagedown": 0x22, "end": 0x23, "home": 0x24, "left": 0x25,
        "up": 0x26, "right": 0x27, "down": 0x28, "insert": 0x2D,
        "delete": 0x2E, "capslock": 0x14, "numlock": 0x90,
        "scrolllock": 0x91, "pause": 0x13, "print": 0x2A,
    }
    if low in named:
        vk = named[low]
    elif len(key) == 1 and key.upper() in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
        vk = ord(key.upper())
    elif low.startswith("f") and low[1:].isdigit() and 1 <= int(low[1:]) <= 24:
        vk = 0x70 + int(low[1:]) - 1
    else:
        return None
    return modifiers | 0x4000, vk  # MOD_NOREPEAT


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        # The admin edition uses the red theme on its first launch, then respects future choices.
        if self.db.setting("admin_red_theme_applied", "0") != "1":
            self.db.set_setting("theme", "red")
            self.db.set_setting("admin_red_theme_applied", "1")
        self.current_profile_id: Optional[int] = None
        self.current_race: str = "Human"
        self.timer_running = False
        self.timer_started_at: Optional[float] = None
        self.timer_profile_id: Optional[int] = None
        self.timer_race: Optional[str] = None
        self.timer_stage_tier = 0
        self.hotkey_registered = False
        self.hotkey_key: Optional[str] = None
        self.local_hotkey: Optional[QShortcut] = None
        self._hotkey_was_down = False
        self._really_quit = False
        self._ready_states = {}
        self.setWindowTitle(f"{APP_NAME} · ADMIN EDITION")
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1250, 850)
        self.setMinimumSize(1000, 700)
        self.setStyleSheet(theme_stylesheet(self.db.setting("theme", "red")))

        root = QWidget(); root.setObjectName("root")
        outer = QHBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        self.setCentralWidget(root)
        outer.addWidget(self._build_sidebar())
        right = QWidget(); right_layout = QVBoxLayout(right); right_layout.setContentsMargins(28, 22, 28, 22); right_layout.setSpacing(18)
        outer.addWidget(right, 1)
        top = QHBoxLayout()
        self.page_title = QLabel("Обзор"); self.page_title.setObjectName("pageTitle")
        self.profile_picker = QComboBox(); self.profile_picker.setMinimumWidth(210); self.profile_picker.currentIndexChanged.connect(self._profile_changed)
        self.profile_picker.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.race_picker = QComboBox(); self.race_picker.setMinimumWidth(125); self.race_picker.currentTextChanged.connect(self._race_changed)
        top.addWidget(self.page_title); top.addStretch(); top.addWidget(QLabel("Профиль:")); top.addWidget(self.profile_picker)
        top.addWidget(QLabel("Раса:")); top.addWidget(self.race_picker)
        right_layout.addLayout(top)
        self.stack = QStackedWidget(); right_layout.addWidget(self.stack, 1)
        self.dashboard = self._build_dashboard()
        self.profiles_page = self._build_profiles_page()
        self.training_page = self._build_training_page()
        self.history_page = self._build_history_page()
        self.settings_page = self._build_settings_page()
        for page in (self.dashboard, self.profiles_page, self.training_page, self.history_page, self.settings_page):
            self.stack.addWidget(page)

        self.tray_icon = QSystemTrayIcon(QIcon(str(ICON_PATH)), self)
        self.tray_icon.setToolTip(f"{APP_NAME} v{APP_VERSION}")
        tray_menu = QMenu(self)
        self.tray_menu = tray_menu
        tray_open = QAction("Открыть / Open", self); tray_open.triggered.connect(self._restore_from_tray)
        tray_exit = QAction("Выход / Exit", self); tray_exit.triggered.connect(self._quit_from_tray)
        tray_menu.addAction(tray_open); tray_menu.addSeparator(); tray_menu.addAction(tray_exit)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()

        self.refresh_timer = QTimer(self); self.refresh_timer.timeout.connect(self._tick); self.refresh_timer.start(1000)
        # Poll the Windows key state instead of handling native Qt window messages.
        # This avoids unstable Python nativeEvent callbacks on some PyQt/Python builds,
        # while keeping a global hotkey usable when Roblox is the active window.
        self.hotkey_poll_timer = QTimer(self)
        self.hotkey_poll_timer.timeout.connect(self._poll_global_hotkey)
        self.hotkey_poll_timer.start(30)
        self._refresh_profiles()
        if not self.db.profiles():
            QTimer.singleShot(100, self.add_profile)
        else:
            self._refresh_all()
        self._refresh_settings_page()
        self._apply_language()
        QTimer.singleShot(250, self._register_saved_hotkey)

    def _build_sidebar(self):
        sidebar = QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(218)
        lay = QVBoxLayout(sidebar); lay.setContentsMargins(15, 22, 15, 18); lay.setSpacing(10)
        brand = QLabel("V4 TRACKER"); brand.setObjectName("brand")
        admin_badge = QLabel("ADMIN EDITION"); admin_badge.setObjectName("adminBadge")
        sub = QLabel("BLOX FRUITS  •  PERSONAL BUILD"); sub.setObjectName("muted"); sub.setStyleSheet("font-size:8pt; letter-spacing:1px;")
        lay.addWidget(brand); lay.addWidget(admin_badge); lay.addWidget(sub); lay.addSpacing(28)
        self.nav_buttons = []
        nav_items = [("◈   Обзор", 0), ("♙   Профили", 1), ("✦   База тренировок", 2), ("◷   История", 3), ("⚙   Настройки", 4)]
        for label, idx in nav_items:
            btn = QPushButton(label); btn.setObjectName("nav"); btn.setCheckable(True)
            btn.clicked.connect(lambda checked=False, page=idx: self.go_page(page))
            lay.addWidget(btn); self.nav_buttons.append(btn)
        self.nav_buttons[0].setChecked(True); lay.addStretch()
        info = QFrame(); info.setObjectName("panel")
        il = QVBoxLayout(info); il.setContentsMargins(12, 12, 12, 12)
        info_title = QLabel("ТВОЙ ПРОГРЕСС"); info_title.setObjectName("accent")
        info_text = QLabel("Таймер по времени\nНесколько рас на аккаунт\nИстория с отменой записей")
        info_text.setObjectName("muted"); info_text.setWordWrap(True)
        il.addWidget(info_title); il.addWidget(info_text); lay.addWidget(info)
        ver = QLabel(f"Версия {APP_VERSION} · SQLite\nДанные хранятся на ПК")
        ver.setObjectName("muted"); ver.setStyleSheet("font-size:8pt;"); lay.addWidget(ver)
        return sidebar

    def _build_dashboard(self):
        page = QWidget(); outer = QVBoxLayout(page); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(16)
        self.welcome = QLabel("Твой прогресс по Race V4"); self.welcome.setObjectName("muted"); outer.addWidget(self.welcome)
        cards = QGridLayout(); cards.setSpacing(12)
        self.card_race = StatCard("РАСА", "—", "Выбранный профиль", "#62e4ff")
        self.card_level = StatCard("УРОВЕНЬ ИГРОКА", "—", "Максимум: 3000", "#b4a1ff")
        self.card_fragments = StatCard("ФРАГМЕНТЫ", "—", "Баланс аккаунта", "#69f0ae")
        self.card_time = StatCard("ВРЕМЯ В V4", "00:00:00", "По выбранной расе", "#ffca70")
        cards.addWidget(self.card_race, 0, 0); cards.addWidget(self.card_level, 0, 1)
        cards.addWidget(self.card_fragments, 0, 2); cards.addWidget(self.card_time, 0, 3); outer.addLayout(cards)
        mid = QHBoxLayout(); mid.setSpacing(14)
        self.training_panel = QFrame(); self.training_panel.setObjectName("panel")
        tl = QVBoxLayout(self.training_panel); tl.setContentsMargins(19, 18, 19, 18); tl.setSpacing(11)
        title_row = QHBoxLayout(); title = QLabel("Следующая тренировка"); title.setStyleSheet("font-size:14pt;font-weight:750;")
        self.training_badge = QLabel("V4"); self.training_badge.setObjectName("accent")
        title_row.addWidget(title); title_row.addStretch(); title_row.addWidget(self.training_badge); tl.addLayout(title_row)
        self.next_training_title = QLabel("Добавь профиль, чтобы начать"); self.next_training_title.setStyleSheet("font-size:12pt;font-weight:700;")
        self.training_meta = QLabel("Стоимость и требования появятся здесь."); self.training_meta.setObjectName("muted"); self.training_meta.setWordWrap(True)
        self.act_progress = QProgressBar(); self.act_progress.setRange(0, 100); self.act_progress.setValue(0)
        self.act_caption = QLabel("Время этапа: 00:00:00 / —"); self.act_caption.setObjectName("muted")
        self.fragment_caption = QLabel("Фрагменты: —"); self.fragment_caption.setObjectName("muted")
        self.trial_caption = QLabel("Испытание: —"); self.trial_caption.setObjectName("muted")
        self.can_train_label = QLabel("ОЖИДАЕТ ДАННЫХ"); self.can_train_label.setObjectName("warning")
        self.train_button = QPushButton("Отметить тренировку выполненной"); self.train_button.setObjectName("primary"); self.train_button.clicked.connect(self.complete_training)
        for item in (self.next_training_title, self.training_meta, self.act_progress, self.act_caption,
                     self.fragment_caption, self.trial_caption, self.can_train_label):
            tl.addWidget(item)
        tl.addStretch(); tl.addWidget(self.train_button)

        self.timer_panel = QFrame(); self.timer_panel.setObjectName("panel")
        tr = QVBoxLayout(self.timer_panel); tr.setContentsMargins(19, 18, 19, 18); tr.setSpacing(12)
        timer_title = QLabel("Таймер времени в V4"); timer_title.setStyleSheet("font-size:14pt;font-weight:750;")
        self.hotkey_hint = QLabel("Горячая клавиша: —"); self.hotkey_hint.setObjectName("accent")
        timer_sub = QLabel("Запускай отсчёт при входе в V4 и останавливай при выходе. Важна длительность, а не число активаций.")
        timer_sub.setObjectName("muted"); timer_sub.setWordWrap(True)
        self.clock_label = QLabel("00:00:00"); self.clock_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clock_label.setStyleSheet("font-size:30pt;font-weight:800;color:#62e4ff;padding:14px 0;")
        self.timer_status = QLabel("● Таймер остановлен"); self.timer_status.setObjectName("muted"); self.timer_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.start_button = QPushButton("▶   Старт V4"); self.start_button.setObjectName("primary"); self.start_button.clicked.connect(self.start_timer)
        self.stop_button = QPushButton("■   Стоп и сохранить время"); self.stop_button.clicked.connect(self.stop_timer); self.stop_button.setEnabled(False)
        self.timer_note = QLabel("Повторное нажатие горячей клавиши переключает таймер Старт/Стоп.")
        self.timer_note.setObjectName("muted"); self.timer_note.setWordWrap(True)
        for item in (timer_title, self.hotkey_hint, timer_sub): tr.addWidget(item)
        tr.addStretch()
        for item in (self.clock_label, self.timer_status, self.start_button, self.stop_button): tr.addWidget(item)
        tr.addStretch(); tr.addWidget(self.timer_note)
        mid.addWidget(self.training_panel, 3); mid.addWidget(self.timer_panel, 2); outer.addLayout(mid, 1)
        self.recent_panel = QFrame(); self.recent_panel.setObjectName("panel")
        rl = QVBoxLayout(self.recent_panel); rl.setContentsMargins(17, 12, 17, 14)
        rt = QHBoxLayout(); rtitle = QLabel("Последние события"); rtitle.setStyleSheet("font-size:12pt;font-weight:750;")
        view_history = QPushButton("Вся история →"); view_history.clicked.connect(lambda: self.go_page(3))
        rt.addWidget(rtitle); rt.addStretch(); rt.addWidget(view_history); rl.addLayout(rt)
        self.recent_table = self._make_table(["Событие", "Детали", "Дата"]); self.recent_table.setMaximumHeight(155)
        rl.addWidget(self.recent_table); outer.addWidget(self.recent_panel)
        return page

    def _build_profiles_page(self):
        page = QWidget(); lay = QVBoxLayout(page); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(14)
        intro = QLabel("Один профиль = один аккаунт. Внутри можно вести несколько рас с отдельным прогрессом.")
        intro.setObjectName("muted"); lay.addWidget(intro)
        row = QHBoxLayout()
        self.add_profile_btn = QPushButton("＋  Добавить профиль"); self.add_profile_btn.setObjectName("primary"); self.add_profile_btn.clicked.connect(self.add_profile)
        self.edit_profile_btn = QPushButton("Изменить выбранный"); self.edit_profile_btn.clicked.connect(self.edit_profile)
        self.delete_profile_btn = QPushButton("Удалить профиль"); self.delete_profile_btn.setObjectName("danger"); self.delete_profile_btn.clicked.connect(self.delete_profile)
        row.addWidget(self.add_profile_btn); row.addWidget(self.edit_profile_btn); row.addWidget(self.delete_profile_btn); row.addStretch(); lay.addLayout(row)
        self.profiles_table = self._make_table(["Профиль", "Расы", "Уровень", "Прогресс рас", "Фрагменты", "Общее время"])
        self.profiles_table.itemSelectionChanged.connect(self._profile_table_selected); lay.addWidget(self.profiles_table, 1)
        return page

    def _build_training_page(self):
        page = QWidget(); lay = QVBoxLayout(page); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(14)
        intro = QLabel("Справочник улучшений Race V4. Время и число активаций приблизительные; длительность одной активации указана отдельно.")
        intro.setObjectName("muted"); lay.addWidget(intro)
        self.training_table = self._make_table(["Tier", "Название", "Фрагменты", "Время V4", "Активации (~)", "Длительность", "Испытание"])
        steps = self.db.training_steps()
        self.training_table.setRowCount(len(steps))
        for row, step in enumerate(steps):
            values = [
                str(step["tier"]),
                step["title"],
                fmt_num(step["cost"]),
                f"{step['minutes_required']} мин",
                f"~{step['activations_required']}",
                f"{step['activation_duration_seconds']} с",
                str(step["trial_required"]),
            ]
            for col, value in enumerate(values): self.training_table.setItem(row, col, QTableWidgetItem(value))
        lay.addWidget(self.training_table, 1)
        note = QLabel("Таймер не считывает игру автоматически: после каждой трансформации сохрани сессию. Расы и их время хранятся отдельно.")
        note.setObjectName("muted"); note.setWordWrap(True); lay.addWidget(note)
        return page

    def _build_history_page(self):
        page = QWidget(); lay = QVBoxLayout(page); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(14)
        intro = QLabel("История выбранной расы. Можно удалить ошибочную сессию или отменить последнюю тренировку.")
        intro.setObjectName("muted"); lay.addWidget(intro)
        buttons = QHBoxLayout()
        self.delete_history_btn = QPushButton("Удалить выбранную запись / отменить изменение")
        self.delete_history_btn.setObjectName("danger"); self.delete_history_btn.clicked.connect(self.delete_history_entry)
        self.clear_sessions_btn = QPushButton("Очистить записи времени этой расы")
        self.clear_sessions_btn.clicked.connect(self.clear_race_sessions)
        buttons.addWidget(self.delete_history_btn); buttons.addWidget(self.clear_sessions_btn); buttons.addStretch(); lay.addLayout(buttons)
        self.history_table = self._make_table(["Тип события", "Длительность / расход", "Tier", "Дата и время", "ID"])
        self.history_table.setColumnHidden(4, True); lay.addWidget(self.history_table, 1)
        return page

    def _build_settings_page(self):
        # Settings contain several stacked panels. Put them in a resizable scroll area
        # so their minimum heights are respected on smaller windows and no controls
        # overlap or get clipped near the bottom of the page.
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setObjectName("settingsScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(12)
        # Ensure the scroll area uses the natural height of its complete contents.
        lay.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        hotkey_panel = QFrame(); hotkey_panel.setObjectName("panel")
        box = QVBoxLayout(hotkey_panel); box.setContentsMargins(18, 15, 18, 15); box.setSpacing(9)
        title = QLabel("Горячая клавиша таймера"); title.setStyleSheet("font-size:14pt;font-weight:750;")
        description = QLabel("Глобальная клавиша работает, даже когда открыта игра. Нажми её один раз для старта V4 и повторно — для остановки и сохранения.")
        description.setObjectName("muted"); description.setWordWrap(True)
        self.hotkey_editor = QKeySequenceEdit(QKeySequence(self.db.setting("global_hotkey", DEFAULT_HOTKEY))); self.hotkey_editor.setMaximumWidth(280)
        self.hotkey_save_button = QPushButton("Сохранить горячую клавишу"); self.hotkey_save_button.setObjectName("primary"); self.hotkey_save_button.clicked.connect(self.save_hotkey)
        self.hotkey_status = QLabel("Статус регистрации клавиши появится здесь."); self.hotkey_status.setObjectName("muted"); self.hotkey_status.setWordWrap(True)
        box.addWidget(title); box.addWidget(description); box.addWidget(QLabel("Новая комбинация:")); box.addWidget(self.hotkey_editor)
        box.addWidget(self.hotkey_save_button); box.addWidget(self.hotkey_status)
        lay.addWidget(hotkey_panel)

        appearance = QFrame(); appearance.setObjectName("panel")
        appbox = QGridLayout(appearance); appbox.setContentsMargins(18, 15, 18, 15); appbox.setHorizontalSpacing(12); appbox.setVerticalSpacing(10)
        appearance_title = QLabel("Интерфейс"); appearance_title.setStyleSheet("font-size:14pt;font-weight:750;")
        self.language_combo = QComboBox(); self.language_combo.addItem("Русский", "ru"); self.language_combo.addItem("English", "en")
        self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(self.db.setting("language", "ru"))))
        self.theme_combo = QComboBox()
        for label, key in [("Красная", "red"), ("Изумрудная", "emerald"), ("Пурпурная", "purple"), ("Белая", "white"), ("Чёрная", "black")]: self.theme_combo.addItem(label, key)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(self.db.setting("theme", "red"))))
        appbox.addWidget(appearance_title, 0, 0, 1, 2)
        appbox.addWidget(QLabel("Язык интерфейса"), 1, 0); appbox.addWidget(self.language_combo, 1, 1)
        appbox.addWidget(QLabel("Тема оформления"), 2, 0); appbox.addWidget(self.theme_combo, 2, 1)
        lay.addWidget(appearance)

        notifications = QFrame(); notifications.setObjectName("panel")
        nbox = QVBoxLayout(notifications); nbox.setContentsMargins(18, 15, 18, 15); nbox.setSpacing(8)
        nt = QLabel("Уведомления"); nt.setStyleSheet("font-size:14pt;font-weight:750;")
        self.notify_ready_checkbox = QCheckBox("Уведомлять при готовности к улучшению")
        self.notify_ready_checkbox.setChecked(self.db.setting("notify_ready", "1") == "1")
        self.notify_sound_checkbox = QCheckBox("Звуковой сигнал вместе с уведомлением")
        self.notify_sound_checkbox.setChecked(self.db.setting("notify_sound", "0") == "1")
        nbox.addWidget(nt); nbox.addWidget(self.notify_ready_checkbox); nbox.addWidget(self.notify_sound_checkbox)
        lay.addWidget(notifications)

        extras = QFrame(); extras.setObjectName("panel")
        ebox = QVBoxLayout(extras); ebox.setContentsMargins(18, 15, 18, 15); ebox.setSpacing(9)
        et = QLabel("Дополнительные настройки"); et.setStyleSheet("font-size:14pt;font-weight:750;")
        self.launch_startup_checkbox = QCheckBox("Запускать вместе с Windows")
        self.launch_startup_checkbox.setChecked(self.db.setting("launch_at_startup", "0") == "1")
        self.launch_startup_checkbox.setEnabled(os.name == "nt")
        self.minimize_tray_checkbox = QCheckBox("Сворачивать в трей при закрытии окна")
        self.minimize_tray_checkbox.setChecked(self.db.setting("minimize_to_tray", "0") == "1")
        self.minimize_tray_checkbox.setEnabled(QSystemTrayIcon.isSystemTrayAvailable())
        self.backup_before_clear_checkbox = QCheckBox("Создавать резервную копию перед очисткой времени")
        self.backup_before_clear_checkbox.setChecked(self.db.setting("backup_before_clear", "1") == "1")
        tools_title = QLabel("Инструменты базы данных")
        tools_title.setStyleSheet("font-size:11pt;font-weight:700;")
        tools_row = QHBoxLayout()
        self.backup_button = QPushButton("Создать резервную копию базы")
        self.backup_button.setMinimumHeight(42)
        self.backup_button.clicked.connect(self.backup_database)
        self.open_data_button = QPushButton("Открыть папку данных")
        self.open_data_button.setMinimumHeight(42)
        self.open_data_button.clicked.connect(self.open_data_folder)
        self.discord_button = QPushButton("Открыть Discord-сервер")
        self.discord_button.setMinimumHeight(42)
        self.discord_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.discord_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DISCORD_URL)))
        tools_row.addWidget(self.backup_button, 1); tools_row.addWidget(self.open_data_button, 1)

        admin_tools_title = QLabel("Админские инструменты")
        admin_tools_title.setStyleSheet("font-size:11pt;font-weight:750;")
        admin_tools_row = QHBoxLayout()
        self.export_history_button = QPushButton("Экспортировать историю (CSV)")
        self.export_history_button.setMinimumHeight(42)
        self.export_history_button.clicked.connect(self.export_history_csv)
        self.export_progress_button = QPushButton("Экспортировать прогресс (CSV)")
        self.export_progress_button.setMinimumHeight(42)
        self.export_progress_button.clicked.connect(self.export_progress_csv)
        admin_tools_row.addWidget(self.export_history_button, 1)
        admin_tools_row.addWidget(self.export_progress_button, 1)
        self.check_database_button = QPushButton("Проверить целостность базы")
        self.check_database_button.setMinimumHeight(42)
        self.check_database_button.clicked.connect(self.check_database_integrity)

        community_title = QLabel("Сообщество и поддержка")
        community_title.setStyleSheet("font-size:11pt;font-weight:700;")
        discord_link = QLabel('<a href="https://discord.gg/SvYqcks5Pz">Discord: discord.gg/SvYqcks5Pz</a>')
        discord_link.setOpenExternalLinks(True)
        discord_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        discord_link.setObjectName("muted")
        local_note = QLabel("Данные и настройки хранятся локально на этом ПК.")
        local_note.setObjectName("muted"); local_note.setWordWrap(True)
        ebox.addWidget(et)
        ebox.addWidget(self.launch_startup_checkbox)
        ebox.addWidget(self.minimize_tray_checkbox)
        ebox.addWidget(self.backup_before_clear_checkbox)
        ebox.addWidget(tools_title)
        ebox.addLayout(tools_row)
        ebox.addWidget(admin_tools_title)
        ebox.addLayout(admin_tools_row)
        ebox.addWidget(self.check_database_button)
        ebox.addWidget(community_title)
        ebox.addWidget(self.discord_button)
        ebox.addWidget(discord_link)
        ebox.addWidget(local_note)
        lay.addWidget(extras)
        lay.addStretch()

        self.language_combo.currentIndexChanged.connect(self.save_language_setting)
        self.theme_combo.currentIndexChanged.connect(self.save_theme_setting)
        self.notify_ready_checkbox.stateChanged.connect(self.save_notification_settings)
        self.notify_sound_checkbox.stateChanged.connect(self.save_notification_settings)
        self.launch_startup_checkbox.stateChanged.connect(self.save_startup_setting)
        self.minimize_tray_checkbox.stateChanged.connect(self.save_tray_setting)
        self.backup_before_clear_checkbox.stateChanged.connect(self.save_backup_before_clear_setting)
        return page

    def _make_table(self, headers):
        table = QTableWidget(0, len(headers)); table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True); table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); table.setShowGrid(False)
        return table

    def go_page(self, idx: int):
        self.stack.setCurrentIndex(idx)
        self.page_title.setText(["Обзор", "Профили", "База тренировок", "История", "Настройки"][idx])
        for i, btn in enumerate(self.nav_buttons): btn.setChecked(i == idx)
        if idx == 1: self._refresh_profiles_table()
        elif idx == 3: self._refresh_history()
        elif idx == 4: self._refresh_settings_page()
        self._apply_language()

    def _refresh_profiles(self):
        current_id = self.current_profile_id
        self.profile_picker.blockSignals(True); self.profile_picker.clear()
        for p in self.db.profiles(): self.profile_picker.addItem(p["name"], p["id"])
        if current_id is not None:
            index = self.profile_picker.findData(current_id)
            if index >= 0: self.profile_picker.setCurrentIndex(index)
        elif self.profile_picker.count():
            self.profile_picker.setCurrentIndex(0)
        self.profile_picker.blockSignals(False)
        self.current_profile_id = self.profile_picker.currentData() if self.profile_picker.count() else None
        self._refresh_race_picker()
        self._refresh_all()

    def _refresh_race_picker(self):
        self.race_picker.blockSignals(True); self.race_picker.clear()
        races = self.db.active_races(self.current_profile_id) if self.current_profile_id is not None else []
        if not races:
            self.race_picker.addItem("Нет рас", None); self.current_race = "Human"
        else:
            if self.current_race not in races: self.current_race = races[0]
            for race in races: self.race_picker.addItem(race, race)
            self.race_picker.setCurrentIndex(max(0, races.index(self.current_race)))
        self.race_picker.blockSignals(False)

    def _profile_changed(self, _index):
        next_id = self.profile_picker.currentData()
        if self.timer_running and self.current_profile_id != next_id:
            QMessageBox.warning(self, self._t("Таймер активен"), self._t("Сначала останови текущую V4-сессию, затем переключай профиль."))
            self.profile_picker.blockSignals(True); old_idx = self.profile_picker.findData(self.current_profile_id)
            if old_idx >= 0: self.profile_picker.setCurrentIndex(old_idx)
            self.profile_picker.blockSignals(False); return
        self.current_profile_id = next_id
        self.current_race = "Human"
        self._refresh_race_picker(); self._refresh_all()

    def _race_changed(self, race):
        next_race = self.race_picker.currentData()
        if not next_race: return
        if self.timer_running and next_race != self.current_race:
            QMessageBox.warning(self, self._t("Таймер активен"), self._t("Сначала останови таймер, затем переключай расу."))
            self.race_picker.blockSignals(True); idx = self.race_picker.findData(self.current_race)
            if idx >= 0: self.race_picker.setCurrentIndex(idx)
            self.race_picker.blockSignals(False); return
        self.current_race = next_race; self._refresh_all()

    def _refresh_all(self):
        self._refresh_dashboard(); self._refresh_profiles_table(); self._refresh_history(); self._update_timer_display()
        self._apply_language()

    def _refresh_dashboard(self):
        p = self.db.profile(self.current_profile_id, self.current_race) if self.current_profile_id is not None else None
        if not p:
            self.welcome.setText("Создай профиль, чтобы отслеживать прогресс Race V4.")
            for card in (self.card_race, self.card_level, self.card_fragments, self.card_time): card.value.setText("—")
            self.next_training_title.setText("Сначала добавь профиль"); self.training_meta.setText("Профили и прогресс сохраняются локально на компьютере.")
            self.act_progress.setValue(0); self.act_caption.setText("Время этапа: 00:00:00 / —")
            self.fragment_caption.setText("Фрагменты: —"); self.trial_caption.setText("Испытание: —")
            self.can_train_label.setText("НЕТ ПРОФИЛЯ"); self.can_train_label.setObjectName("warning")
            self.train_button.setEnabled(False); self.start_button.setEnabled(False); self.stop_button.setEnabled(False)
            self.recent_table.setRowCount(0); return
        self.welcome.setText(f"Аккаунт: {p['name']}  •  Раса: {self.current_race}")
        self.card_race.value.setText(self.current_race); self.card_race.subtitle.setText(f"V4 {'открыта' if p['v4_unlocked'] else 'ещё не открыта'}")
        self.card_level.value.setText(fmt_num(p["player_level"])); self.card_fragments.value.setText(fmt_num(p["fragments"]))
        self.card_time.value.setText(fmt_time(p["total_v4_seconds"]))
        self.card_time.subtitle.setText(f"Общее время расы {self.current_race}")
        step = self.db.current_training(p["v4_tier"]) if p["v4_unlocked"] else None
        if not p["v4_unlocked"]:
            self.next_training_title.setText("Race V4 для этой расы ещё не открыта")
            self.training_meta.setText("Отметь открытие V4 в настройках профиля, когда оно будет доступно.")
            self.act_progress.setValue(0); self.act_caption.setText("Время этапа: 00:00:00 / —")
            self.fragment_caption.setText("Фрагменты аккаунта: " + fmt_num(p["fragments"]))
            self.trial_caption.setText(f"Пройдено испытаний: {p['trials_completed']} / 5")
            self.can_train_label.setText("НУЖНО ОТКРЫТЬ V4"); self.can_train_label.setObjectName("warning")
            self.train_button.setEnabled(False); self.start_button.setEnabled(False)
        elif not step:
            self.next_training_title.setText("Все 5 улучшений завершены ✦")
            self.training_meta.setText("Для этой расы V4 максимального уровня. Таймер и история всё ещё доступны.")
            self.act_progress.setValue(100); self.act_caption.setText("Время этапа: MAX")
            self.fragment_caption.setText("Фрагменты аккаунта: " + fmt_num(p["fragments"]))
            self.trial_caption.setText(f"Пройдено испытаний: {p['trials_completed']} / 5")
            self.can_train_label.setText("МАКСИМАЛЬНЫЙ УРОВЕНЬ"); self.can_train_label.setObjectName("success")
            self.train_button.setEnabled(False); self.start_button.setEnabled(not self.timer_running)
        else:
            required_seconds = int(step["minutes_required"]) * 60
            got_seconds = float(p["training_seconds"])
            if self.timer_running and self.timer_profile_id == p["id"] and self.timer_race == self.current_race and self.timer_started_at is not None:
                got_seconds += time.monotonic() - self.timer_started_at
            cost = int(step["cost"]); trial = int(step["trial_required"])
            time_ready = got_seconds >= required_seconds
            self.next_training_title.setText(step["title"])
            self.training_meta.setText(f"Улучшение до Tier {step['tier']}  •  {fmt_num(cost)} фрагментов  •  ~{step['activations_required']} активаций по {step['activation_duration_seconds']} с")
            ratio = got_seconds / max(1, required_seconds)
            self.act_progress.setValue(min(100, round(ratio * 100)))
            self.act_caption.setText(f"Время V4 на этом этапе: {fmt_time(got_seconds)} / {fmt_time(required_seconds)}")
            self.fragment_caption.setText(f"Фрагменты: {fmt_num(p['fragments'])} / {fmt_num(cost)}")
            self.trial_caption.setText(f"Испытание {trial}: {'пройдено' if p['trials_completed'] >= trial else 'не пройдено'}  •  у тебя {p['trials_completed']} / 5")
            missing = []
            if not time_ready: missing.append(f"ещё {fmt_time(required_seconds - got_seconds)} времени в V4")
            if p["fragments"] < cost: missing.append(f"не хватает {fmt_num(cost - p['fragments'])} фрагментов")
            if p["trials_completed"] < trial: missing.append(f"нужно испытание {trial}")
            if self.timer_running: missing.append("останови таймер перед подтверждением")
            can = bool(p["v4_unlocked"] and not missing)
            self.can_train_label.setText("✓ МОЖНО ТРЕНИРОВАТЬСЯ" if can else "⌛ " + "  •  ".join(missing))
            self.can_train_label.setObjectName("success" if can else "warning")
            self.train_button.setEnabled(can); self.start_button.setEnabled(not self.timer_running)
        self.can_train_label.style().unpolish(self.can_train_label); self.can_train_label.style().polish(self.can_train_label)
        if p and p.get("v4_unlocked"):
            notify_step = self.db.current_training(int(p["v4_tier"]))
            if notify_step:
                seconds = float(p["training_seconds"])
                if self.timer_running and self.timer_profile_id == p["id"] and self.timer_race == self.current_race and self.timer_started_at is not None:
                    seconds += time.monotonic() - self.timer_started_at
                ready_for_notification = (seconds >= int(notify_step["minutes_required"]) * 60
                    and int(p["fragments"]) >= int(notify_step["cost"])
                    and int(p["trials_completed"]) >= int(notify_step["trial_required"])
                    and not self.timer_running)
                self._check_ready_notification(int(p["id"]), self.current_race, int(notify_step["tier"]), ready_for_notification)
        self._fill_recent()

    def _fill_recent(self):
        if self.current_profile_id is None or not self.current_race:
            self.recent_table.setRowCount(0); return
        rows = self.db.history(self.current_profile_id, self.current_race, 5)
        self.recent_table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            detail = fmt_time(item["amount"]) if item["event_type"] == "session" else f"−{fmt_num(item['amount'])} фрагментов · Tier {item['tier']}"
            for c, value in enumerate([item["kind"], detail, item["when_at"]]):
                self.recent_table.setItem(r, c, QTableWidgetItem(str(value)))

    def _refresh_profiles_table(self):
        if not hasattr(self, "profiles_table"): return
        profiles = self.db.profiles(); self.profiles_table.setRowCount(len(profiles))
        for row, base in enumerate(profiles):
            pid = int(base["id"]); races = self.db.active_races(pid)
            summaries = []
            total_time = 0
            for race in races:
                state = self.db.profile(pid, race)
                total_time += float(state["total_v4_seconds"] if state else 0)
                summaries.append(f"{race}: {state['v4_tier']}/10" if state and state["v4_unlocked"] else f"{race}: —")
            vals = [base["name"], ", ".join(races) or "Нет рас", str(base["player_level"]), " · ".join(summaries), fmt_num(base["fragments"]), fmt_time(total_time)]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val); item.setData(Qt.ItemDataRole.UserRole, pid); self.profiles_table.setItem(row, col, item)

    def _refresh_history(self):
        if not hasattr(self, "history_table"): return
        if self.current_profile_id is None or not self.current_race:
            self.history_table.setRowCount(0); return
        rows = self.db.history(self.current_profile_id, self.current_race, 1000)
        self.history_table.setRowCount(len(rows))
        for r, entry in enumerate(rows):
            details = fmt_time(entry["amount"]) if entry["event_type"] == "session" else f"−{fmt_num(entry['amount'])} фрагм."
            tier = f"Tier {entry['tier']}" if entry["tier"] is not None else "—"
            values = [entry["kind"], details, tier, entry["when_at"], str(entry["event_id"])]
            for col, value in enumerate(values): self.history_table.setItem(r, col, QTableWidgetItem(str(value)))
            # Store the stable event type separately from its translated display label.
            # This avoids treating an English "V4 session" as a training row when deleting.
            self.history_table.item(r, 4).setData(Qt.ItemDataRole.UserRole, entry["event_type"])
        self.history_table.setColumnHidden(4, True)
        self.delete_history_btn.setEnabled(bool(rows) and not self.timer_running)

    def _profile_table_selected(self):
        selected = self.profiles_table.selectedItems()
        if not selected: return
        pid = selected[0].data(Qt.ItemDataRole.UserRole)
        idx = self.profile_picker.findData(pid)
        if idx >= 0: self.profile_picker.setCurrentIndex(idx)

    def add_profile(self):
        dlg = ProfileDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                pid = self.db.save_profile(None, dlg.values())
            except ValueError as exc:
                QMessageBox.warning(self, self._t("Не удалось сохранить"), self._t(str(exc))); return
            self.current_profile_id = pid
            self.current_race = next(iter(self.db.active_races(pid)), "Human")
            self._refresh_profiles(); self.go_page(0)

    def edit_profile(self):
        if self.current_profile_id is None: return
        base = self.db.profile_base(self.current_profile_id)
        races = self.db.race_progresses(self.current_profile_id)
        dlg = ProfileDialog(self, base, races)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                self.db.save_profile(self.current_profile_id, dlg.values())
            except ValueError as exc:
                QMessageBox.warning(self, self._t("Не удалось сохранить"), self._t(str(exc))); return
            active = self.db.active_races(self.current_profile_id)
            if self.current_race not in active: self.current_race = active[0]
            self._refresh_profiles()

    def delete_profile(self):
        if self.current_profile_id is None: return
        if self.timer_running:
            QMessageBox.warning(self, self._t("Таймер активен"), self._t("Останови таймер перед удалением профиля.")); return
        p = self.db.profile_base(self.current_profile_id)
        answer = QMessageBox.question(self, self._t("Удалить профиль?"), self._t(f"Удалить «{p['name']}» и всю историю всех его рас? Это действие нельзя отменить."))
        if answer == QMessageBox.StandardButton.Yes:
            self.db.delete_profile(self.current_profile_id); self.current_profile_id = None
            self._refresh_profiles(); self.go_page(1)

    def start_timer(self):
        p = self.db.profile(self.current_profile_id, self.current_race) if self.current_profile_id is not None else None
        if not p: return
        if not p["v4_unlocked"]:
            QMessageBox.information(self, self._t("V4 не открыта"), self._t("В настройках профиля отметь, что V4 этой расы уже открыта.")); return
        if self.timer_running: return
        self.timer_running = True
        self.timer_started_at = time.monotonic()
        self.timer_profile_id = self.current_profile_id; self.timer_race = self.current_race
        self.timer_stage_tier = int(p["v4_tier"])
        self.start_button.setEnabled(False); self.stop_button.setEnabled(True)
        self.timer_status.setText(f"● Идёт отсчёт: {self.timer_race}")
        self.timer_status.setStyleSheet("color:#69f0ae;font-weight:700;")
        self.profile_picker.setEnabled(False); self.race_picker.setEnabled(False)
        self._tick()

    def stop_timer(self, confirm_short=True):
        if not self.timer_running or self.timer_profile_id is None or self.timer_race is None or self.timer_started_at is None:
            return
        elapsed = max(0.0, time.monotonic() - self.timer_started_at)
        if elapsed < 1 and confirm_short:
            ask = QMessageBox.question(self, self._t("Короткая сессия"), self._t("Прошло меньше секунды. Сохранить это время? Подсчёт идёт по секундам, не по количеству активаций."))
            if ask != QMessageBox.StandardButton.Yes: return
        self.db.add_session(self.timer_profile_id, self.timer_race, elapsed, self.timer_stage_tier)
        self.timer_running = False; self.timer_started_at = None; self.timer_profile_id = None; self.timer_race = None
        self.start_button.setEnabled(True); self.stop_button.setEnabled(False)
        self.timer_status.setText("● Время сессии сохранено"); self.timer_status.setStyleSheet("color:#8ea3c4;font-weight:600;")
        self.profile_picker.setEnabled(True); self.race_picker.setEnabled(True)
        self._refresh_all()

    def _toggle_timer_hotkey(self):
        # Avoid opening a modal confirmation over Roblox for an accidental very-short press.
        if self.timer_running: self.stop_timer(confirm_short=False)
        else: self.start_timer()

    def _tick(self):
        if self.timer_running: self._refresh_dashboard()
        self._update_timer_display()
        if self.db.setting("language", "ru") == "en": self._apply_language()

    def _update_timer_display(self):
        if self.timer_running and self.timer_started_at is not None:
            elapsed = time.monotonic() - self.timer_started_at
            self.clock_label.setText(fmt_time(elapsed))
            p = self.db.profile(self.timer_profile_id, self.timer_race) if self.timer_profile_id is not None else None
            self.card_time.value.setText(fmt_time((float(p["total_v4_seconds"]) if p else 0) + elapsed))
        else:
            p = self.db.profile(self.current_profile_id, self.current_race) if self.current_profile_id is not None else None
            self.clock_label.setText("00:00:00" if not p else fmt_time(p["total_v4_seconds"]))

    def complete_training(self):
        if self.current_profile_id is None: return
        p = self.db.profile(self.current_profile_id, self.current_race)
        if not p or not p["v4_unlocked"]: return
        step = self.db.current_training(p["v4_tier"])
        if not step: return
        missing = []
        required_seconds = int(step["minutes_required"]) * 60
        if float(p["training_seconds"]) < required_seconds:
            missing.append(f"нужно время в V4: ещё {fmt_time(required_seconds - float(p['training_seconds']))}")
        if p["fragments"] < step["cost"]: missing.append("не хватает фрагментов аккаунта")
        if p["trials_completed"] < step["trial_required"]: missing.append(f"нужно пройти испытание {step['trial_required']}")
        if self.timer_running: missing.append("сначала останови таймер")
        if missing:
            QMessageBox.warning(self, self._t("Пока рано"), self._t("Условия не выполнены:\n• " + "\n• ".join(missing))); return
        answer = QMessageBox.question(self, self._t("Подтвердить тренировку"),
            self._t(f"Отметить {step['title']} для расы {self.current_race}?\n\nБудет списано {fmt_num(step['cost'])} фрагментов.\nВремя этапа сбросится для следующей тренировки."))
        if answer == QMessageBox.StandardButton.Yes:
            self.db.log_training(self.current_profile_id, self.current_race, int(step["tier"]), int(step["cost"]),
                                 int(p["v4_tier"]), float(p["training_seconds"]), int(p["training_activations"]))
            self._refresh_all()

    def delete_history_entry(self):
        if self.timer_running:
            QMessageBox.warning(self, self._t("Таймер активен"), self._t("Останови таймер перед изменением истории.")); return
        row = self.history_table.currentRow()
        if row < 0:
            QMessageBox.information(self, self._t("Запись не выбрана"), self._t("Сначала выбери строку в истории.")); return
        kind_item = self.history_table.item(row, 0); id_item = self.history_table.item(row, 4)
        if kind_item is None or id_item is None: return
        event_type = id_item.data(Qt.ItemDataRole.UserRole)
        if event_type not in ("session", "training"):
            # Compatibility with rows created before event types were attached as item data.
            event_type = "session" if kind_item.text() in ("V4-сессия", "V4 session") else "training"
        event_id = int(id_item.text())
        description = "удалить сессию и вычесть её время" if event_type == "session" else "отменить тренировку и вернуть потраченные фрагменты"
        answer = QMessageBox.question(self, self._t("Подтвердить изменение"), self._t(f"Ты точно хочешь {description}?\n\nЕсли это тренировка, отменить можно только последнюю тренировку без более новых записей."))
        if answer != QMessageBox.StandardButton.Yes: return
        try:
            self.db.delete_history_entry(self.current_profile_id, self.current_race, event_type, event_id)
        except ValueError as exc:
            QMessageBox.warning(self, self._t("Не удалось изменить историю"), self._t(str(exc))); return
        self._refresh_all()

    def _check_ready_notification(self, profile_id: int, race: str, tier: int, ready: bool):
        key = (profile_id, race, tier)
        previous = self._ready_states.get(key)
        self._ready_states[key] = bool(ready)
        if previous is False and ready and self.db.setting("notify_ready", "1") == "1":
            title = "Улучшение V4 готово" if self.db.setting("language", "ru") != "en" else "V4 upgrade ready"
            body = f"{race}: можно переходить к Tier {tier}." if self.db.setting("language", "ru") != "en" else f"{race}: ready for Tier {tier}."
            if QSystemTrayIcon.isSystemTrayAvailable():
                self.tray_icon.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 7000)
            if self.db.setting("notify_sound", "0") == "1": QApplication.beep()

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._restore_from_tray()

    def _restore_from_tray(self):
        self.showNormal(); self.raise_(); self.activateWindow()

    def _quit_from_tray(self):
        self._really_quit = True
        self.close()

    def _t(self, text: str) -> str:
        return localize_text(text, self.db.setting("language", "ru"))

    def save_language_setting(self, *_):
        if not hasattr(self, "language_combo"): return
        self.db.set_setting("language", str(self.language_combo.currentData() or "ru"))
        self._apply_language()
        self._refresh_all()

    def save_theme_setting(self, *_):
        if not hasattr(self, "theme_combo"): return
        theme = str(self.theme_combo.currentData() or "emerald")
        self.db.set_setting("theme", theme)
        self.setStyleSheet(theme_stylesheet(theme))
        # Update inline accent styles where practical and refresh the window/taskbar icon.
        self.setWindowIcon(QIcon(str(ICON_PATH)))

    def save_notification_settings(self, *_):
        self.db.set_setting("notify_ready", "1" if self.notify_ready_checkbox.isChecked() else "0")
        self.db.set_setting("notify_sound", "1" if self.notify_sound_checkbox.isChecked() else "0")

    def _set_windows_startup(self, enabled: bool):
        if os.name != "nt":
            raise OSError("Автозапуск доступен только в Windows.")
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        value_name = "Blox Fruits V4 Tracker"
        if IS_FROZEN:
            command = f'"{sys.executable}"'
        else:
            script = APP_DIR / "run_without_console.vbs"
            command = f'wscript.exe "{script}"'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, command)
            else:
                try: winreg.DeleteValue(key, value_name)
                except FileNotFoundError: pass

    def save_startup_setting(self, *_):
        enabled = self.launch_startup_checkbox.isChecked()
        try:
            self._set_windows_startup(enabled)
        except OSError as exc:
            QMessageBox.warning(self, self._t("Автозапуск"), self._t(f"Не удалось изменить автозапуск: {exc}"))
            self.launch_startup_checkbox.blockSignals(True); self.launch_startup_checkbox.setChecked(not enabled); self.launch_startup_checkbox.blockSignals(False)
            return
        self.db.set_setting("launch_at_startup", "1" if enabled else "0")

    def save_tray_setting(self, *_):
        self.db.set_setting("minimize_to_tray", "1" if self.minimize_tray_checkbox.isChecked() else "0")

    def save_backup_before_clear_setting(self, *_):
        self.db.set_setting("backup_before_clear", "1" if self.backup_before_clear_checkbox.isChecked() else "0")

    def _create_auto_backup_before_clear(self) -> Path:
        """Make a SQLite-consistent backup and retain at most five automatic backups."""
        backup_dir = DB_PATH.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = backup_dir / f"before_time_clear_{stamp}.db"
        with sqlite3.connect(str(backup_path)) as target:
            self.db.conn.backup(target)
        backups = sorted(backup_dir.glob("before_time_clear_*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
        for stale in backups[5:]:
            try:
                stale.unlink()
            except OSError:
                # Keep the successful backup even if cleanup of an older one fails.
                pass
        return backup_path

    def backup_database(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Сохранить резервную копию", str(Path.home() / "blox_fruits_v4_backup.db"), "SQLite database (*.db)")
        if not filename: return
        if Path(filename).resolve() == DB_PATH.resolve():
            QMessageBox.warning(self, self._t("Ошибка резервного копирования"), self._t("Выбери другой файл: нельзя перезаписать открытую базу данных."))
            return
        try:
            with sqlite3.connect(filename) as target:
                self.db.conn.backup(target)
            QMessageBox.information(self, self._t("Резервная копия создана"), self._t(f"Данные сохранены в:\n{filename}"))
        except (sqlite3.Error, OSError) as exc:
            QMessageBox.critical(self, self._t("Ошибка резервного копирования"), self._t(str(exc)))

    def export_history_csv(self):
        try:
            rows = self.db.conn.execute("""
                SELECT p.name AS profile_name, s.race AS race, 'V4-сессия' AS event_type,
                       s.stage_tier AS tier, s.duration_seconds AS duration_seconds,
                       NULL AS fragments, s.ended_at AS event_at
                FROM sessions s JOIN profiles p ON p.id=s.profile_id
                UNION ALL
                SELECT p.name AS profile_name, h.race AS race, 'Тренировка' AS event_type,
                       h.tier AS tier, NULL AS duration_seconds,
                       h.cost AS fragments, h.completed_at AS event_at
                FROM training_history h JOIN profiles p ON p.id=h.profile_id
                ORDER BY event_at DESC
            """).fetchall()
        except sqlite3.Error as exc:
            QMessageBox.critical(self, self._t("Экспорт истории"), str(exc))
            return
        if not rows:
            QMessageBox.information(self, self._t("Экспорт истории"), self._t("Нет данных для экспорта."))
            return
        suggested = Path.home() / f"blox_fruits_v4_history_{datetime.now():%Y%m%d}.csv"
        filename, _ = QFileDialog.getSaveFileName(
            self, self._t("Экспорт истории"), str(suggested), self._t("CSV-файлы (*.csv)")
        )
        if not filename:
            return
        target = Path(filename)
        if not target.suffix:
            target = target.with_suffix(".csv")
        if target.resolve() == DB_PATH.resolve():
            QMessageBox.warning(self, self._t("Экспорт истории"),
                                self._t("Выбери другой файл: нельзя перезаписать открытую базу данных."))
            return
        headers = [self._t("Профиль"), self._t("Раса"), self._t("Тип события"), "Tier",
                   self._t("Длительность (сек.)"), self._t("Фрагменты"), self._t("Дата и время")]
        try:
            with target.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(headers)
                for item in rows:
                    duration = "" if item["duration_seconds"] is None else round(float(item["duration_seconds"]), 1)
                    fragments = "" if item["fragments"] is None else int(item["fragments"])
                    tier = "" if item["tier"] is None or int(item["tier"]) < 0 else int(item["tier"])
                    writer.writerow([
                        item["profile_name"], item["race"], self._t(str(item["event_type"])),
                        tier, duration, fragments, item["event_at"]
                    ])
            QMessageBox.information(
                self, self._t("Готово"),
                f"{self._t('CSV-файл успешно сохранён:')}\n{target}\n{self._t('Записей:')} {len(rows)}"
            )
        except (OSError, csv.Error) as exc:
            QMessageBox.critical(self, self._t("Экспорт истории"), str(exc))

    def export_progress_csv(self):
        export_rows = []
        for base in self.db.profiles():
            profile_id = int(base["id"])
            races = self.db.active_races(profile_id)
            if not races:
                races = [str(base["race"])]
            for race in races:
                progress = self.db.profile(profile_id, race)
                if not progress:
                    continue
                export_rows.append([
                    base["name"], race, int(base["player_level"]), int(base["fragments"]),
                    self._t("Да") if progress["v4_unlocked"] else self._t("Нет"),
                    int(progress["v4_tier"]), int(progress["trials_completed"]),
                    int(progress["training_activations"]), fmt_time(progress["training_seconds"]),
                    fmt_time(progress["total_v4_seconds"])
                ])
        if not export_rows:
            QMessageBox.information(self, self._t("Экспорт прогресса"), self._t("Нет данных для экспорта."))
            return
        suggested = Path.home() / f"blox_fruits_v4_progress_{datetime.now():%Y%m%d}.csv"
        filename, _ = QFileDialog.getSaveFileName(
            self, self._t("Экспорт прогресса"), str(suggested), self._t("CSV-файлы (*.csv)")
        )
        if not filename:
            return
        target = Path(filename)
        if not target.suffix:
            target = target.with_suffix(".csv")
        if target.resolve() == DB_PATH.resolve():
            QMessageBox.warning(self, self._t("Экспорт прогресса"),
                                self._t("Выбери другой файл: нельзя перезаписать открытую базу данных."))
            return
        headers = [
            self._t("Профиль"), self._t("Раса"), self._t("Уровень игрока"), self._t("Фрагменты"),
            self._t("V4 открыта"), "Tier", self._t("Пройдено испытаний"),
            self._t("Активации этапа"), self._t("Время этапа"), self._t("Общее время расы")
        ]
        try:
            with target.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(headers)
                writer.writerows(export_rows)
            QMessageBox.information(
                self, self._t("Готово"),
                f"{self._t('CSV-файл успешно сохранён:')}\n{target}\n{self._t('Записей:')} {len(export_rows)}"
            )
        except (OSError, csv.Error) as exc:
            QMessageBox.critical(self, self._t("Экспорт прогресса"), str(exc))

    def check_database_integrity(self):
        try:
            integrity = str(self.db.conn.execute("PRAGMA integrity_check").fetchone()[0])
            profiles = int(self.db.conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0])
            race_entries = int(self.db.conn.execute("SELECT COUNT(*) FROM race_progress WHERE active=1").fetchone()[0])
            sessions = int(self.db.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
            upgrades = int(self.db.conn.execute("SELECT COUNT(*) FROM training_history").fetchone()[0])
            summary = "\n".join([
                f"{self._t('Профилей:')} {profiles}",
                f"{self._t('Рас в прогрессе:')} {race_entries}",
                f"{self._t('Сессий:')} {sessions}",
                f"{self._t('Тренировок:')} {upgrades}",
            ])
            if integrity.casefold() == "ok":
                QMessageBox.information(
                    self, self._t("Проверка целостности БД"),
                    f"{self._t('База данных исправна.')}\n\n{summary}"
                )
            else:
                QMessageBox.warning(
                    self, self._t("Проверка целостности БД"),
                    f"{self._t('База данных сообщила об ошибке:')}\n{integrity}\n\n{summary}"
                )
        except sqlite3.Error as exc:
            QMessageBox.critical(self, self._t("Проверка целостности БД"), str(exc))

    def open_data_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(DB_PATH.parent)))

    def clear_race_sessions(self):
        if self.current_profile_id is None or not self.current_race: return
        if self.timer_running:
            QMessageBox.warning(self, self._t("Таймер активен"), self._t("Останови таймер перед очисткой записей.")); return
        if self.db.setting("language", "ru") == "en":
            prompt = (f"Delete every V4 time record for {self.current_race}?\n\n"
                      "Lifetime and current-stage time will be recalculated from the database and should become 00:00:00. "
                      "V4 tier, trials, fragments and upgrade history will be preserved.")
        else:
            prompt = (f"Удалить все записи времени V4 для расы {self.current_race}?\n\n"
                      "Общее время и время этапа будут пересчитаны по базе данных и должны стать 00:00:00. "
                      "Уровень V4, испытания, фрагменты и история тренировок сохранятся.")
        answer = QMessageBox.question(self, self._t("Очистить время этой расы?"), prompt)
        if answer != QMessageBox.StandardButton.Yes: return

        backup_path = None
        if self.db.setting("backup_before_clear", "1") == "1":
            try:
                backup_path = self._create_auto_backup_before_clear()
            except (sqlite3.Error, OSError) as exc:
                QMessageBox.critical(self, self._t("Ошибка резервного копирования"),
                                     self._t(f"Не удалось создать резервную копию, очистка отменена: {exc}"))
                return
        try:
            deleted_count = self.db.clear_session_history(self.current_profile_id, self.current_race)
        except sqlite3.Error as exc:
            QMessageBox.critical(self, self._t("Не удалось изменить историю"), self._t(str(exc)))
            return

        current = self.db.profile(self.current_profile_id, self.current_race)
        next_step = self.db.current_training(int(current["v4_tier"])) if current and current.get("v4_unlocked") else None
        if next_step:
            self._ready_states[(int(self.current_profile_id), self.current_race, int(next_step["tier"]))] = False
        self._refresh_all()
        if self.db.setting("language", "ru") == "en":
            message = f"Cleared {deleted_count} time record(s).\nV4 lifetime and stage time: 00:00:00."
            if backup_path:
                message += f"\nBackup: {backup_path}"
        else:
            message = f"Удалено записей времени: {deleted_count}.\nОбщее время V4 и время этапа: 00:00:00."
            if backup_path:
                message += f"\nРезервная копия: {backup_path}"
        QMessageBox.information(self, self._t("Готово"), message)

    def _apply_language(self):
        lang = self.db.setting("language", "ru")
        # Translate existing widget text in-place; user-entered profile names are not modified.
        for widget in self.findChildren(QWidget):
            if isinstance(widget, QLabel):
                widget.setText(localize_text(widget.text(), lang))
            elif isinstance(widget, QPushButton):
                widget.setText(localize_text(widget.text(), lang))
            elif isinstance(widget, QCheckBox):
                widget.setText(localize_text(widget.text(), lang))
            if isinstance(widget, QComboBox) and widget in (getattr(self, "language_combo", None), getattr(self, "theme_combo", None)):
                for i in range(widget.count()):
                    widget.setItemText(i, localize_text(widget.itemText(i), lang))
            if isinstance(widget, QTableWidget):
                for col in range(widget.columnCount()):
                    item = widget.horizontalHeaderItem(col)
                    if item: item.setText(localize_text(item.text(), lang))
                for row in range(widget.rowCount()):
                    for col in range(widget.columnCount()):
                        # Never translate the user's profile name in the profile list.
                        should_translate_cell = (widget in (getattr(self, "history_table", None), getattr(self, "recent_table", None))
                                                 or (widget is getattr(self, "profiles_table", None) and col > 0))
                        item = widget.item(row, col)
                        if item and should_translate_cell:
                            item.setText(localize_text(item.text(), lang))
            if isinstance(widget, QLineEdit):
                widget.setPlaceholderText(localize_text(widget.placeholderText(), lang))
        self.page_title.setText(localize_text(["Обзор", "Профили", "База тренировок", "История", "Настройки"][self.stack.currentIndex()], lang))
        self.setWindowTitle(f"{APP_NAME} · ADMIN EDITION")
        # Re-apply action labels explicitly after the recursive translator. This also
        # prevents empty button captions on some Qt/Windows stylesheet combinations.
        for button, key in (
            (getattr(self, "backup_button", None), "Создать резервную копию базы"),
            (getattr(self, "open_data_button", None), "Открыть папку данных"),
            (getattr(self, "export_history_button", None), "Экспортировать историю (CSV)"),
            (getattr(self, "export_progress_button", None), "Экспортировать прогресс (CSV)"),
            (getattr(self, "check_database_button", None), "Проверить целостность базы"),
            (getattr(self, "discord_button", None), "Открыть Discord-сервер"),
        ):
            if button is not None:
                button.setText(self._t(key))
                button.setMinimumHeight(42)
                theme = self.db.setting("theme", "emerald")
                text_color = {"emerald": "#e8fff2", "purple": "#fbf1ff",
                              "white": "#1c2738", "black": "#e6e8ec", "red": "#fff0f2"}.get(theme, "#ecf4ff")
                button.setStyleSheet(
                    f"QPushButton {{ color: {text_color}; min-height: 32px; padding: 8px 12px; }}"
                )

    def _refresh_settings_page(self):
        if not hasattr(self, "hotkey_editor"): return
        hotkey = self.db.setting("global_hotkey", DEFAULT_HOTKEY)
        seq = QKeySequence(hotkey)
        self.hotkey_editor.setKeySequence(seq)
        self.hotkey_hint.setText(f"Горячая клавиша: {hotkey}")
        if os.name == "nt":
            self.hotkey_status.setText("Глобальная клавиша Windows: отслеживается в фоне, даже когда Roblox активен.")
        else:
            self.hotkey_status.setText("Вне Windows клавиша работает, только когда окно трекера активно.")

    def save_hotkey(self):
        sequence = self.hotkey_editor.keySequence()
        hotkey = sequence.toString(QKeySequence.SequenceFormat.PortableText).strip()
        parsed = parse_windows_hotkey(hotkey)
        if not hotkey or parsed is None:
            QMessageBox.warning(self, self._t("Неподдерживаемая клавиша"), self._t("Выбери одну клавишу или комбинацию, например F8, Ctrl+F8 или Alt+Q."))
            return
        old = self.db.setting("global_hotkey", DEFAULT_HOTKEY)
        if not self._register_hotkey(hotkey):
            self._register_hotkey(old)
            QMessageBox.warning(self, self._t("Неподдерживаемая комбинация"), self._t("Не удалось распознать эту клавишу. Попробуй F8, Ctrl+F8 или Alt+Q."))
            return
        self.db.set_setting("global_hotkey", hotkey)
        self.hotkey_hint.setText(f"Горячая клавиша: {hotkey}")
        self.hotkey_status.setText(f"Комбинация {hotkey} сохранена. Отслеживание работает в фоне.")
        QMessageBox.information(self, self._t("Готово"), self._t(f"Горячая клавиша {hotkey} сохранена. Нажатие переключает Старт/Стоп таймера V4."))

    def _register_saved_hotkey(self):
        hotkey = self.db.setting("global_hotkey", DEFAULT_HOTKEY)
        if self._register_hotkey(hotkey):
            self.hotkey_hint.setText(f"Горячая клавиша: {hotkey}")
            self.hotkey_status.setText(f"Активна комбинация {hotkey}.")
        else:
            self.hotkey_status.setText(f"Комбинация {hotkey} не поддерживается. Открой настройки и выбери F8, Ctrl+F8 или Alt+Q.")

    def _unregister_hotkey(self):
        # No Win32 RegisterHotKey/nativeEvent callback is used on Windows anymore.
        # The background timer polls GetAsyncKeyState, avoiding native callback crashes.
        self.hotkey_registered = False
        self.hotkey_key = None
        self._hotkey_was_down = False
        if self.local_hotkey is not None:
            self.local_hotkey.setEnabled(False)
            self.local_hotkey.deleteLater()
            self.local_hotkey = None

    def _register_hotkey(self, hotkey: str) -> bool:
        parsed = parse_windows_hotkey(hotkey)
        if not parsed:
            return False
        self._unregister_hotkey()
        self.hotkey_key = hotkey
        self.hotkey_registered = True
        if os.name != "nt":
            self.local_hotkey = QShortcut(QKeySequence(hotkey), self)
            self.local_hotkey.activated.connect(self._toggle_timer_hotkey)
        return True

    @staticmethod
    def _windows_key_down(vk: int) -> bool:
        try:
            return bool(ctypes.windll.user32.GetAsyncKeyState(int(vk)) & 0x8000)
        except Exception:
            return False

    def _poll_global_hotkey(self):
        """Poll a configurable global hotkey without overriding Qt's nativeEvent."""
        if os.name != "nt" or not self.hotkey_key:
            return
        parsed = parse_windows_hotkey(self.hotkey_key)
        if parsed is None:
            return
        modifiers, vk = parsed
        expected_modifiers = modifiers & 0x000F  # Ignore MOD_NOREPEAT.
        actual_modifiers = 0
        if self._windows_key_down(0x12):  # VK_MENU / Alt
            actual_modifiers |= 0x0001
        if self._windows_key_down(0x11):  # VK_CONTROL
            actual_modifiers |= 0x0002
        if self._windows_key_down(0x10):  # VK_SHIFT
            actual_modifiers |= 0x0004
        if self._windows_key_down(0x5B) or self._windows_key_down(0x5C):  # left/right Win
            actual_modifiers |= 0x0008
        down = self._windows_key_down(vk) and actual_modifiers == expected_modifiers
        if down and not self._hotkey_was_down:
            self._hotkey_was_down = True
            self._toggle_timer_hotkey()
        elif not down:
            self._hotkey_was_down = False

    def closeEvent(self, event: QCloseEvent):
        if (not self._really_quit and self.db.setting("minimize_to_tray", "0") == "1"
                and QSystemTrayIcon.isSystemTrayAvailable()):
            self.hide()
            if self.db.setting("language", "ru") == "en":
                self.tray_icon.showMessage(APP_NAME, "The tracker is still running in the system tray.", QSystemTrayIcon.MessageIcon.Information, 3500)
            else:
                self.tray_icon.showMessage(APP_NAME, "Трекер продолжает работать в системном трее.", QSystemTrayIcon.MessageIcon.Information, 3500)
            event.ignore()
            return
        if self.timer_running and self.timer_profile_id is not None and self.timer_race and self.timer_started_at is not None:
            elapsed = max(0.0, time.monotonic() - self.timer_started_at)
            answer = QMessageBox.question(self, self._t("Сохранить активную сессию?"), self._t("Таймер V4 ещё запущен. Сохранить прошедшее время?"))
            if answer == QMessageBox.StandardButton.Yes:
                self.db.add_session(self.timer_profile_id, self.timer_race, elapsed, self.timer_stage_tier)
            self.timer_running = False
        self._unregister_hotkey()
        self.tray_icon.hide()
        self.db.close()
        event.accept()
        app = QApplication.instance()
        if app is not None: app.quit()


def main():
    # Helps preserve a Python traceback if a fatal native exception occurs on supported builds.
    try:
        import faulthandler
        faulthandler.enable()
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow(); window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
