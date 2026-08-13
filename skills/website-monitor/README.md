# Website Monitor

Deterministically monitor website documents and paginated listings. Unchanged checks require no LLM. Optional semantic evaluation runs only after extracted content changes.

## Installation

```bash
python3 -m venv ~/.local/share/website-monitor/venv
~/.local/share/website-monitor/venv/bin/pip install -r requirements.txt
```

For browser-backed watches:

```bash
~/.local/share/website-monitor/venv/bin/playwright install chromium
```

Copy `website_monitor.example.toml` to a machine-local configuration directory. Do not put personal watches or secrets in the skill repository.

## Monitor Modes

- `items`: extracts records with stable keys and reports added, removed, and modified items.
- `document`: extracts selected page regions and reports canonical text changes.

## Pagination

Pagination settings belong to one monitor. Each website can use its own selector and URL restriction.

```toml
[monitors.pagination]
enabled = true
link_selector = "nav.pagination a"
allowed_path_regex = "^/results(?:/page-[0-9]+)?$"
max_pages = 20
```

The crawler follows discovered links only, remains on the initial host, tracks visited URLs, stops on repeated page item sets, and enforces page/item limits.

## Browser Fetching

Set `fetcher = "browser"` only when direct HTML does not contain the target content. Browser watches support `wait_for_selector` and constrained `click` steps. Arbitrary JavaScript is not supported.

```toml
[monitors.browser]
wait_for_selector = ".results-loaded"

[[monitors.browser.steps]]
action = "click"
selector = "button.load-more"
optional = true
```

## Semantic Evaluation

Set `relevance.semantic_intent` to evaluate a real delta. The configured evaluator receives bounded JSON on stdin. It must return the schema in `relevance.schema.json`. The `{output_file}` placeholder supports CLIs that write their final response to a file.

For item changes, notifications summarize added, removed, and modified listings. A single added item uses its extracted `url` as the notification tap target; otherwise the monitor source URL is used.

## State

Each monitor stores a versioned `state.json` and append-only `history.jsonl` under `settings.state_dir`. Configuration changes rebaseline without alerting. Fetch or extraction failures never replace a valid baseline.
