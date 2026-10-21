"""Regression tests for important SQLite behaviors used by the desktop app."""
import tempfile
import unittest
from pathlib import Path

from main import Database, RACES, training_requirements_met


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

    def test_all_ten_upgrades_cover_stages_two_through_five(self):
        steps = self.db.training_steps()
        self.assertEqual(len(steps), 10)
        actual = [
            (int(x["tier"]), int(x["cost"]), int(x["minutes_required"]),
             int(x["activations_required"]), int(x["trial_required"]),
             int(x["activation_duration_seconds"])) for x in steps
        ]
        self.assertEqual(actual, [
            (1, 1000, 3, 3, 1, 50),
            (2, 1500, 5, 6, 2, 55),
            (3, 2000, 4, 5, 3, 65),
            (4, 2250, 5, 5, 3, 70),
            (5, 2500, 10, 9, 3, 75),
            (6, 3000, 8, 7, 4, 80),
            (7, 3250, 10, 8, 4, 85),
            (8, 3500, 13, 10, 4, 85),
            (9, 3750, 15, 11, 4, 90),
            (10, 4000, 18, 12, 4, 110),
        ])

    def test_five_row_database_migrates_to_all_ten_without_losing_history(self):
        self.db.conn.execute("DELETE FROM training_steps WHERE tier > 5")
        self.db.conn.execute("UPDATE race_progress SET v4_tier=5 WHERE profile_id=? AND race='Ghoul'", (self.profile_id,))
        self.db.conn.execute("UPDATE profiles SET v4_tier=5 WHERE id=?", (self.profile_id,))
        self.db.conn.execute("INSERT INTO sessions(profile_id,race,stage_tier,duration_seconds,ended_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP)",
                             (self.profile_id, "Ghoul", 5, 420))
        self.db.conn.commit()
        self.db.close()
        self.db = Database(self.db_path)
        steps = self.db.training_steps()
        self.assertEqual([int(step["tier"]) for step in steps], list(range(1, 11)))
        self.assertEqual(int(steps[0]["cost"]), 1000)
        self.assertEqual(int(steps[9]["cost"]), 4000)
        self.assertEqual(int(self.db.profile(self.profile_id, "Ghoul")["v4_tier"]), 5)
        self.assertEqual(int(self.db.profile(self.profile_id, "Ghoul")["total_v4_seconds"]), 420)

    def test_training_readiness_accepts_time_or_activations(self):
        step = self.db.current_training(0)
        required_seconds = int(step["minutes_required"]) * 60
        required_activations = int(step["activations_required"])
        self.assertEqual(required_seconds, 180)
        self.assertEqual(required_activations, 3)
        self.assertTrue(training_requirements_met(step, 180, 0))
        self.assertTrue(training_requirements_met(step, 0, 3))
        self.assertFalse(training_requirements_met(step, 179, 2))


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
