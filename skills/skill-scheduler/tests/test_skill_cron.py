import importlib.util
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "skill_cron.py"
SPEC = importlib.util.spec_from_file_location("skill_cron", MODULE_PATH)
scheduler = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(scheduler)


class SkillCronResultTests(unittest.TestCase):
    def test_skill_job_uses_default_executor_once(self):
        config = {
            "settings": {"default_skill_executor": "opencode"},
            "skill_executors": {
                "opencode": {
                    "argv": ["opencode", "run", "--model", "openai/gpt-5.5", "--variant", "default"],
                    "timeout_seconds": 1800,
                }
            },
        }
        job = {"id": "retro", "title": "Weekly Retro", "skill": "braindump-retro", "instructions": "Use the vault workflow."}
        command = scheduler.command_for_job(config, job)
        self.assertEqual(command["argv"][:6], config["skill_executors"]["opencode"]["argv"])
        self.assertEqual(command["argv"][-3:-1], ["--title", "Scheduled skill: Weekly Retro"])
        self.assertIn("Run the braindump-retro skill", command["argv"][-1])
        self.assertEqual(command["timeout_seconds"], 1800)

    def test_skill_job_requires_configured_executor(self):
        with self.assertRaisesRegex(scheduler.ConfigError, "unknown skill executor"):
            scheduler.validate_job(
                {"id": "retro", "skill": "braindump-retro", "schedule": {"weekly": "sun 18:00"}},
                {},
                {},
                None,
                set(),
            )

    def test_reads_and_removes_valid_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "event": "changed",
                "title": "Changed title",
                "message": "A change occurred",
                "details": {"added": 1},
                "click_url": "https://example.com/item",
            }))
            result = scheduler.read_command_result(path)
            self.assertEqual(result["event"], "changed")
            self.assertEqual(result["click_url"], "https://example.com/item")
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

    def test_ntfy_sets_click_and_view_action(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b""
        with mock.patch.object(scheduler.urllib.request, "urlopen", return_value=response) as urlopen:
            scheduler.send_ntfy_notification(
                {"url": "https://ntfy.example", "topic": "alerts"},
                "Title",
                "Message",
                "success",
                "https://example.com/item",
            )
        request = urlopen.call_args.args[0]
        self.assertEqual(request.headers["Click"], "https://example.com/item")
        self.assertEqual(request.headers["Actions"], "view, Open page, https://example.com/item, clear=true")

    def test_notification_summary_precedes_metadata(self):
        title, message = scheduler.notification_payload(
            {"title": "Example"},
            {
                "job_id": "site",
                "status": "success",
                "event": "changed",
                "event_message": "Added: New comedian",
                "click_url": "https://example.com/item",
                "started_at": "start",
                "finished_at": "finish",
            },
        )
        self.assertEqual(title, "Skill Scheduler: Example changed")
        self.assertTrue(message.startswith("Added: New comedian\n\nOpen: https://example.com/item"))


if __name__ == "__main__":
    unittest.main()
