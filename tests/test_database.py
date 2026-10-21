"""Regression tests for important SQLite behaviors used by the desktop app."""
import tempfile
import unittest
from pathlib import Path

from main import Database, RACES


class DatabaseRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_tracker.db"
        self.db = Database(self.db_path)
        races = {}
        for race in RACES:
            races[race] = {
                "active": race in {"Ghoul", "Cyborg"},
                "v4_unlocked": 1,
                "v4_tier": 0,
                "trials_completed": 0,
                "training_activations": 0,
                "training_seconds": 0.0,
                "total_v4_seconds": 0.0,
            }
        self.profile_id = self.db.save_profile(None, {
            "name": "Test Profile",
            "player_level": 3000,
            "fragments": 50000,
            "race_progresses": races,
        })

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_clear_time_history_resets_selected_race_only(self):
        self.db.add_session(self.profile_id, "Ghoul", 20, 0)
        self.db.add_session(self.profile_id, "Ghoul", 40, 0)
        self.db.add_session(self.profile_id, "Cyborg", 90, 0)

        deleted = self.db.clear_session_history(self.profile_id, "Ghoul")

        self.assertEqual(deleted, 2)
        ghoul = self.db.profile(self.profile_id, "Ghoul")
        cyborg = self.db.profile(self.profile_id, "Cyborg")
        self.assertEqual(ghoul["total_v4_seconds"], 0)
        self.assertEqual(ghoul["training_seconds"], 0)
        self.assertEqual(ghoul["training_activations"], 0)
        self.assertEqual(cyborg["total_v4_seconds"], 90)
        self.assertEqual(cyborg["training_seconds"], 90)

        self.db.close()
        self.db = Database(self.db_path)
        ghoul_after_restart = self.db.profile(self.profile_id, "Ghoul")
        self.assertEqual(ghoul_after_restart["total_v4_seconds"], 0)
        self.assertEqual(ghoul_after_restart["training_seconds"], 0)

    def test_deleting_one_session_recalculates_remaining_time(self):
        self.db.add_session(self.profile_id, "Ghoul", 10, 0)
        self.db.add_session(self.profile_id, "Ghoul", 25, 0)
        rows = self.db.conn.execute(
            "SELECT id FROM sessions WHERE profile_id=? AND race=? ORDER BY id",
            (self.profile_id, "Ghoul"),
        ).fetchall()

        self.db.delete_history_entry(self.profile_id, "Ghoul", "session", int(rows[1]["id"]))

        ghoul = self.db.profile(self.profile_id, "Ghoul")
        self.assertEqual(ghoul["total_v4_seconds"], 10)
        self.assertEqual(ghoul["training_seconds"], 10)
        self.assertEqual(ghoul["training_activations"], 1)

    def test_profile_settings_persist(self):
        self.db.set_setting("theme", "purple")
        self.db.set_setting("language", "en")
        self.assertEqual(self.db.setting("theme"), "purple")
        self.assertEqual(self.db.setting("language"), "en")


if __name__ == "__main__":
    unittest.main()
