import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "skill_cron.py"
SPEC = importlib.util.spec_from_file_location("skill_cron", MODULE_PATH)
scheduler = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(scheduler)


class SkillCronResultTests(unittest.TestCase):
    def test_reads_and_removes_valid_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "event": "changed",
                "title": "Changed title",
                "message": "A change occurred",
                "details": {"added": 1},
            }))
            result = scheduler.read_command_result(path)
            self.assertEqual(result["event"], "changed")
            self.assertFalse(path.exists())

    def test_rejects_unknown_result_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(json.dumps({"schema_version": 1, "event": "arbitrary"}))
            self.assertIsNone(scheduler.read_command_result(path))
            self.assertFalse(path.exists())

    def test_notification_can_match_event_and_job(self):
        notification = {"events": ["changed"], "job_ids": ["site-a"]}
        self.assertTrue(scheduler.notification_matches(notification, {"job_id": "site-a", "status": "success", "event": "changed"}))
        self.assertFalse(scheduler.notification_matches(notification, {"job_id": "site-b", "status": "success", "event": "changed"}))
        self.assertFalse(scheduler.notification_matches(notification, {"job_id": "site-a", "status": "success", "event": "unchanged"}))

    def test_existing_completion_match_remains(self):
        notification = {"events": ["completion"]}
        self.assertTrue(scheduler.notification_matches(notification, {"job_id": "job", "status": "success"}))
        self.assertTrue(scheduler.notification_matches(notification, {"job_id": "job", "status": "failed"}))

    def test_notification_rejects_unknown_job_id(self):
        with self.assertRaisesRegex(scheduler.ConfigError, "unknown values"):
            scheduler.validate_notification(
                {"id": "phone", "provider": "ntfy", "events": ["changed"], "job_ids": ["missing"], "url": "https://example.com", "topic": "topic"},
                set(),
                {"known"},
            )


if __name__ == "__main__":
    unittest.main()
