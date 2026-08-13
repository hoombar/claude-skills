import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "website_monitor.py"
SPEC = importlib.util.spec_from_file_location("website_monitor", MODULE_PATH)
monitor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(monitor)


class FixtureHandler(BaseHTTPRequestHandler):
    pages = {}

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/events")
            self.end_headers()
            return
        body = self.pages.get(self.path)
        if body is None:
            self.send_error(404)
            return
        encoded = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        pass


class WebsiteMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def config(self):
        return {
            "settings": {"state_dir": self.temp.name, "timeout_seconds": 2},
            "monitors": [],
        }

    def item_monitor(self):
        return {
            "id": "events",
            "title": "Events",
            "url": f"{self.base_url}/events",
            "fetcher": "http",
            "mode": "items",
            "pagination": {
                "enabled": True,
                "link_selector": "nav a",
                "allowed_path_regex": r"^/events(?:/page-[0-9]+)?$",
                "max_pages": 5,
            },
            "items": {
                "selector": "article",
                "key_field": "url",
                "fields": {
                    "url": {"selector": "a", "output": "attribute", "attribute": "href", "resolve_url": True},
                    "title": {"selector": "h2", "output": "text"},
                },
            },
            "relevance": {"events": ["items_added"]},
        }

    def write_config(self, config):
        path = Path(self.temp.name) / "config.toml"
        path.write_text("placeholder", encoding="utf-8")
        return path

    def test_normalize_text_removes_noise(self):
        value = "  Price   available  \r\n Updated: 123 \n"
        self.assertEqual(
            monitor.normalize_text(value, {"remove_patterns": [r"Updated: \d+"]}),
            "Price available",
        )

    def test_paginated_items_are_collected_and_deduplicated(self):
        FixtureHandler.pages = {
            "/events": '<article><a href="/event/a"><h2>A</h2></a></article><nav><a href="/events/page-2">2</a></nav>',
            "/events/page-2": '<article><a href="/event/b"><h2>B</h2></a></article><nav><a href="/events">1</a></nav>',
        }
        items = monitor.extract_items(self.config(), self.item_monitor())
        self.assertEqual(list(items), [f"{self.base_url}/event/a", f"{self.base_url}/event/b"])

    def test_item_delta_ignores_reordering(self):
        before = {"a": {"title": "A"}, "b": {"title": "B"}}
        after = {"b": {"title": "B"}, "a": {"title": "A"}}
        self.assertEqual(
            monitor.calculate_delta("items", before, after),
            {"kind": "items", "added": [], "removed": [], "modified": []},
        )

    def test_item_summary_and_click_url_use_single_added_item(self):
        watched = self.item_monitor()
        delta = {
            "kind": "items",
            "added": [{"title": "New comedian", "url": "https://example.com/events/new"}],
            "removed": [],
            "modified": [],
        }
        self.assertEqual(monitor.deterministic_summary(delta), "Listings changed: 1 added\nAdded: New comedian")
        self.assertEqual(monitor.change_click_url(watched, delta), "https://example.com/events/new")

    def test_click_url_falls_back_to_monitor_page(self):
        watched = self.item_monitor()
        delta = {"kind": "items", "added": [{"title": "A"}, {"title": "B"}], "removed": [], "modified": []}
        self.assertEqual(monitor.change_click_url(watched, delta), watched["url"])

    def test_conflicting_duplicate_item_keys_fail(self):
        FixtureHandler.pages = {
            "/events": '<article><a href="/event/a"><h2>A</h2></a></article><nav><a href="/events/page-2">2</a></nav>',
            "/events/page-2": '<article><a href="/event/a"><h2>Different A</h2></a></article>',
        }
        with self.assertRaisesRegex(monitor.MonitorError, "Conflicting duplicate item key"):
            monitor.extract_items(self.config(), self.item_monitor())

    def test_baseline_unchanged_and_added_item(self):
        FixtureHandler.pages = {
            "/events": '<article><a href="/event/a"><h2>A</h2></a></article>',
        }
        config = self.config()
        watched = self.item_monitor()
        watched.pop("pagination")
        config["monitors"] = [watched]
        path = self.write_config(config)
        first = monitor.run_monitor(config, path, watched)
        second = monitor.run_monitor(config, path, watched)
        FixtureHandler.pages["/events"] = '<article><a href="/event/a"><h2>A</h2></a></article><article><a href="/event/b"><h2>B</h2></a></article>'
        third = monitor.run_monitor(config, path, watched)
        self.assertEqual(first["event"], "initialized")
        self.assertEqual(second["event"], "unchanged")
        self.assertEqual(third["event"], "changed")
        self.assertEqual(third["details"]["delta"]["added"][0]["title"], "B")

    def test_configuration_change_reinitializes(self):
        FixtureHandler.pages = {"/events": '<article><a href="/event/a"><h2>A</h2></a></article>'}
        config = self.config()
        watched = self.item_monitor()
        watched.pop("pagination")
        config["monitors"] = [watched]
        path = self.write_config(config)
        monitor.run_monitor(config, path, watched)
        watched["headers"] = {"Accept-Language": "en-GB"}
        result = monitor.run_monitor(config, path, watched)
        self.assertEqual(result["event"], "initialized")

    def test_scheduler_result_file(self):
        result_path = Path(self.temp.name) / "result.json"
        previous = os.environ.get("SKILL_SCHEDULER_RESULT_FILE")
        os.environ["SKILL_SCHEDULER_RESULT_FILE"] = str(result_path)
        try:
            monitor.write_result("changed", "Title", "Message", {"count": 1}, "https://example.com/item")
        finally:
            if previous is None:
                os.environ.pop("SKILL_SCHEDULER_RESULT_FILE", None)
            else:
                os.environ["SKILL_SCHEDULER_RESULT_FILE"] = previous
        value = json.loads(result_path.read_text())
        self.assertEqual(value["event"], "changed")
        self.assertEqual(value["details"], {"count": 1})
        self.assertEqual(value["click_url"], "https://example.com/item")

    def test_scheduler_result_file_bounds_large_details(self):
        result_path = Path(self.temp.name) / "large-result.json"
        previous = os.environ.get("SKILL_SCHEDULER_RESULT_FILE")
        os.environ["SKILL_SCHEDULER_RESULT_FILE"] = str(result_path)
        try:
            monitor.write_result("changed", "Title", "Message", {"delta": {"kind": "document", "diff": ["x" * 1000] * 100}})
        finally:
            if previous is None:
                os.environ.pop("SKILL_SCHEDULER_RESULT_FILE", None)
            else:
                os.environ["SKILL_SCHEDULER_RESULT_FILE"] = previous
        value = json.loads(result_path.read_text())
        self.assertLess(result_path.stat().st_size, 65536)
        self.assertTrue(value["details"]["truncated"])

    def test_http_redirect_is_blocked(self):
        config = self.config()
        watched = self.item_monitor()
        watched["url"] = f"{self.base_url}/redirect"
        with self.assertRaisesRegex(monitor.MonitorError, "HTTP 302"):
            monitor.request_url(watched["url"], config, watched)

    def test_provider_neutral_evaluator_output_file(self):
        evaluator = Path(self.temp.name) / "evaluator.py"
        evaluator.write_text(
            "import json,sys\n"
            "json.dump({'relevant': True, 'summary': 'Relevant update', 'reason': 'Matched intent'}, open(sys.argv[1], 'w'))\n",
            encoding="utf-8",
        )
        config = self.config()
        config["evaluator"] = {
            "enabled": True,
            "argv": [sys.executable, str(evaluator), "{output_file}"],
            "timeout_seconds": 5,
        }
        watched = self.item_monitor()
        watched["relevance"]["semantic_intent"] = "Notify for useful additions"
        relevant, summary, reason = monitor.evaluate(config, watched, {"kind": "items", "added": [{"title": "A"}], "removed": [], "modified": []})
        self.assertTrue(relevant)
        self.assertEqual(summary, "Relevant update")
        self.assertEqual(reason, "Matched intent")

    def test_large_semantic_delta_fails_open_without_evaluator(self):
        config = self.config()
        config["evaluator"] = {"enabled": True, "argv": ["/does/not/exist"]}
        watched = self.item_monitor()
        watched["relevance"]["semantic_intent"] = "Notify for important additions"
        delta = {"kind": "items", "added": [{"title": "x" * 20_000}], "removed": [], "modified": []}
        relevant, summary, reason = monitor.evaluate(config, watched, delta)
        self.assertTrue(relevant)
        self.assertIn("too large", summary)
        self.assertEqual(reason, "Fail-open relevance decision")


if __name__ == "__main__":
    unittest.main()
