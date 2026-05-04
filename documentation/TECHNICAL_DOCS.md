# Healthcare SLA Dashboard — Technical Documentation

## Overview

A Python web application that measures SLA compliance for LA Blue healthcare tickets in Jira. It tracks four SLAs across three Jira projects (ACS → LPM → SR) and displays results in an interactive Streamlit dashboard.

---

## Architecture

```
streamlit_app.py      ← Web UI (entry point for browser users)
main.py               ← CLI entry point (terminal users)
sla_checker.py        ← Business logic: queries Jira, evaluates SLAs
jira_client.py        ← Jira REST API wrapper
sla_calculator.py     ← Data classes and date/business-day utilities
config.py             ← All configuration constants and SLA definitions
display.py            ← Terminal output formatting (Rich library)
requirements.txt      ← Python dependencies
```

The app has two separate entry points that share the same core logic:
- **`streamlit_app.py`** — browser-based dashboard, run with `streamlit run streamlit_app.py`
- **`main.py`** — terminal CLI, run with `python main.py`

---

## File Reference

---

### `config.py`

Central configuration file. **This is the first file to edit when setting up the app in a new environment.**

#### Jira Custom Field IDs

Jira stores custom fields under internal IDs (e.g. `customfield_10151`). These must be set to match your Jira instance. To find a field ID, fetch any ticket's raw JSON:

```
https://yourcompany.atlassian.net/rest/api/3/issue/ACS-123
```

| Constant | Purpose |
|---|---|
| `HEALTH_PLAN_FIELD_ID` | The "Health plan" field on ACS tickets — used to filter for LA Blue tickets |
| `CATEGORY_FIELD_ID` | The "Category" field on LPM tickets — displayed in the dashboard tables |
| `SOURCE_OF_ID_FIELD_ID` | The "Source of Identification" field on ACS tickets |
| `CONFIG_DONE_DATE_FIELD_ID` | The "Config done date" field on LPM tickets |

#### Project Constants

```python
PROJECT_A = "ACS"   # Source project — tickets originate here
PROJECT_B = "LPM"   # Target project — linked from ACS tickets
PROJECT_C = "SR"    # Sub-task project — linked from LPM tickets
```

#### `SLA_DEFINITIONS`

A dictionary defining each of the four SLAs. Each entry contains:

| Key | Description |
|---|---|
| `name` | Display name shown in the UI |
| `source_project` / `lpm_project` | Jira project key where the query starts |
| `target_project` / `sr_project` / `acs_project` | Downstream project keys |
| `health_plan_field` / `health_plan_value` | Field name and value used to filter for LA Blue tickets |
| `target_status` / `target_statuses` | The Jira status(es) that mark SLA completion |
| `target_days` | SLA deadline in business days |
| `use_business_days` | Always `True`; business days are used throughout |

#### `JIRA_FIELDS`

A convenience dictionary that maps human-readable names to the field ID constants above. Used by `SLAChecker` to look up field IDs at runtime.

---

### `jira_client.py`

Low-level HTTP client for the Jira REST API (v3). Handles authentication, URL resolution, pagination, and rate limiting. Does not contain any SLA logic.

#### `JiraClient(base_url, email, token, use_gateway=True)`

Initialized with Jira credentials. On construction it:

1. Fetches `{base_url}/_edge/tenant_info` (no auth required) to retrieve the Atlassian cloud ID
2. Rewrites `base_url` to `https://api.atlassian.com/ex/jira/{cloudId}` — the Atlassian API gateway required for scoped service account tokens
3. Constructs a Basic Auth header from `email:token`

Set `use_gateway=False` to skip the cloud ID lookup and use the instance URL directly (useful if you are already passing a gateway URL).

Raises `ValueError` if `base_url`, `email`, or `token` are missing.

#### `_resolve_base_url(instance_url, token)`

Module-level helper called during `__init__`. Hits `/_edge/tenant_info`, extracts the `cloudId`, and returns the gateway URL. If the lookup fails for any reason (network error, unexpected response), it logs a warning and returns the original instance URL unchanged so the app can still attempt a connection.

#### Key Methods

**`search_issues(jql, fields, max_results)`**
Runs a JQL search and pages through all results using `nextPageToken`. Returns a flat list of all matching issue dicts.

**`get_issue(issue_key, fields)`**
Fetches a single issue by key. Optionally limits which fields are returned to reduce payload size.

**`get_issue_changelog(issue_key)`**
Returns the full changelog for an issue, paging through all entries. Used to find when a ticket first transitioned to a specific status.

**`get_status_transition_date(issue_key, target_status)`**
Scans the changelog and returns the timestamp of the first time the issue reached the given status (or any status in a list). Returns `None` if the status was never reached.

**`get_issue_comments(issue_key)`**
Returns all comments on an issue, paging through all results.

**`test_connection()`**
Calls `/rest/api/3/myself` to verify credentials. Returns the authenticated user's profile.

#### Rate Limiting

All requests use `_make_request` and `_post_request`, which retry up to 5 times on HTTP 429 responses, waiting the number of seconds specified in the `Retry-After` header (or exponential backoff if not present).

---

### `sla_calculator.py`

Pure data utilities — no Jira API calls, no UI code. Contains the data classes used throughout the app and date calculation helpers.

#### Business Day Functions

**`get_business_days(start_date, end_date)`**
Returns the number of business days (Monday–Friday) between two dates using `numpy.busday_count`. Excludes weekends but not holidays.

**`get_business_days_elapsed(start_date)`**
Convenience wrapper that calls `get_business_days(start_date, datetime.now())`.

**`parse_jira_date(date_field)`**
Parses a Jira date string (which can be in several formats) into a timezone-naive `datetime`. Returns `None` if parsing fails.

**`extract_field_value(field, default)`**
Safely extracts a display value from a Jira field, which may be a string, a dict with a `value`/`name`/`key` key, or a list.

**`format_elapsed_time(start, end)`**
Formats a time delta as `"Xd Xh Xm"` — used for the First Response SLA which measures hours/minutes, not just days.

#### `SLAResult`

Represents the SLA evaluation result for a single ticket.

| Attribute | Type | Description |
|---|---|---|
| `source_ticket` | `str` | The ACS (or SR sub-task) ticket key |
| `target_ticket` | `str \| None` | The linked LPM or ACS ticket key |
| `created_date` | `datetime` | When the source ticket was created (SLA start) |
| `resolved_date` | `datetime \| None` | When the SLA milestone was reached (SLA end) |
| `days_elapsed` | `int` | Business days from creation to resolution (or today) |
| `target_days` | `int` | The SLA deadline in business days |
| `status` | `str` | `"met"`, `"breached"`, or `"in_progress"` |
| `source_of_identification` | `str` | Value of the Source of ID custom field |
| `category_migrated` | `str` | Category of the ACS ticket |
| `lpm_category` | `str` | Overloaded: parent SR ticket key for SLA 4 (Impact Report) — shown as "SR Parent" in the UI |
| `elapsed_time_str` | `str \| None` | Formatted elapsed time (SLA 1 only, e.g. `"1d 4h 32m"`) |
| `lpm_candidates` | `list` | List of `(lpm_key, transition_date)` tuples for all LPM tickets that reached the target status — used by the override picker |
| `target_category` | `str` | Category field value of the winning LPM ticket |

`status` properties: `.is_met`, `.is_breached`, `.is_in_progress` return booleans.

#### `SLASummary`

A collection of `SLAResult` objects for one SLA run.

| Property | Description |
|---|---|
| `total_count` | All results |
| `met_count` / `breached_count` / `in_progress_count` | Filtered counts |
| `met_results` / `breached_results` / `in_progress_results` | Filtered lists |
| `compliance_rate` | `met / (met + breached) * 100` — excludes in-progress tickets |

---

### `sla_checker.py`

The core business logic layer. Queries Jira via `JiraClient` and returns `SLASummary` objects. Contains one public method per SLA plus internal helpers.

#### `SLAChecker(jira_client, verbose, date_from, date_to, log_collector)`

- `verbose`: if `True`, prints detailed JQL queries and per-ticket processing steps to the terminal
- `date_from` / `date_to`: optional `YYYY-MM-DD` strings that restrict the ACS ticket query by creation date
- `log_collector`: optional list; when provided, every `_log` call appends a dict `{"level", "message", "time"}` to this list in addition to (or instead of) printing to the terminal. Used by the Streamlit app to populate the Log tab.

#### `_date_filter_jql()`

Builds the JQL suffix appended to every query. Always excludes cancelled tickets. Appends `created >= ...` and/or `created <= ...` clauses if a date range is set.

#### `check_first_response()` → `SLASummary`

**SLA 1 — Time to First Response (target: 2 business days)**

1. Queries all LA Blue ACS tickets within the date range
2. For each ticket, fetches all comments
3. Finds the first public comment (where `jsdPublic = true`, or no `visibility` restriction)
4. Measures business days from ticket creation to that comment
5. Status: `met` / `breached` (if comment exists), `in_progress` (if no comment yet and within target), `breached` (if no comment and past target)

#### `check_identification_resolution_config()` → `SLASummary`

**SLA 2 — Identification of Resolution (target: 30 business days)**

1. Queries all LA Blue ACS tickets
2. For each ticket, inspects all linked issues for LPM project tickets
3. Skips canceled LPM tickets
4. Calls `get_status_transition_date` to find when each linked LPM ticket first reached `"Ready for Config"`
5. If multiple LPM tickets qualify, selects the one with the most recent transition date (user can override this in the UI)
6. Fetches the winning LPM ticket's category field
7. Excludes ACS tickets that have no qualifying LPM link and are already closed/resolved/canceled

#### `check_resolution_config()` → `SLASummary`

**SLA 3 — Resolution of Configuration Issues (target: 60 business days)**

Same logic as SLA 2, but looks for LPM tickets that reached any of: `"Deployed to UAT"`, `"Waiting for UAT Signoff"`, or `"Done"`.

#### `check_impact_report_delivery()` → `SLASummary`

**SLA 4 — Impact Report Delivery (target: 30 business days)**

Queries the SR project directly for LA Blue sub-tasks:

1. JQL: `project = SR AND issuetype = Sub-task AND "Health Plan" = "LA Blue"` (plus any date filters)
2. Skips canceled sub-tasks
3. Uses each sub-task's creation date as the SLA start
4. Looks up the sub-task's parent SR ticket and finds all ACS tickets linked to it
5. Scans those ACS tickets for a public comment containing the text "impact report"
6. Measures business days from sub-task creation to that comment

#### `_evaluate_ticket()` and `_evaluate_ticket_resolution()`

Internal helpers used by SLAs 2 and 3 respectively. Each evaluates a single ACS ticket against its linked LPM tickets and returns an `SLAResult`. Logic is the same as described above in `check_identification_resolution_config` / `check_resolution_config`.

#### `get_recent_fix_version_lpm_tickets()`

Fallback used when SLA 4 finds no SR sub-tasks. Queries LA Blue LPM tickets that have a `fixVersion` set, groups them by version, and returns a structured list for display. Versions are sorted: unreleased first (ascending by release date), then released (descending by release date).

---

### `streamlit_app.py`

The browser-based UI. Built with Streamlit and Plotly. This is what users interact with.

#### Session State

Three keys are persisted across reruns (e.g. when a user checks a checkbox):

| Key | Type | Purpose |
|---|---|---|
| `excluded_keys` | `set[str]` | Ticket keys to exclude from results on the next run |
| `lpm_overrides` | `dict[str, str]` | Maps ACS ticket key → user-selected LPM ticket key (overrides auto-selection) |
| `sla_sort` | `dict[int, str]` | Maps SLA number → current sort selection |
| `sla_summaries` | `list` | Cached `SLASummary` results from the last run |
| `sla_errors` | `list` | Error strings from the last run, one per SLA |
| `fix_version_data` | `list \| None` | SLA 4 fallback data if no SR sub-tasks found |
| `run_logs` | `list` | All log entries collected during the last run — displayed in the Log tab |
| `run_meta` | `dict` | Connected user, Jira URL, and date range from the last run |

#### Credential Loading

The app checks for credentials in this order:

1. **Environment variables** — if `JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN` are all set (or present in a `.env` file loaded by `python-dotenv`), the sidebar form is hidden and a green confirmation banner is shown instead. The `.config.json` file is not written in this path.
2. **Sidebar form** — if any environment variable is missing, the user fills in the three fields manually.

Module-level constants `_ENV_URL`, `_ENV_EMAIL`, `_ENV_TOKEN`, and `_USING_ENV` are evaluated once on startup and control which path is taken.

#### Configuration Persistence

`load_config()` and `save_config()` read/write a `.config.json` file in the same directory. This saves the Jira URL and email (but never the API token) so the fields are pre-filled on the next visit. This file is only written when credentials come from the sidebar form — not when environment variables are in use.

#### Key Functions

**`_ticket_cell(base_url, key)`**
Returns a full Jira browse URL (`https://.../browse/KEY`) when a base URL is available, otherwise returns the plain ticket key. This value is stored in the DataFrame and rendered as a clickable link via Streamlit's `LinkColumn`.

**`styled_df(results, sla_num, jira_url)`**
Converts a list of `SLAResult` objects into a Pandas DataFrame ready for display. Column structure varies by SLA number. Ticket key columns hold full URLs; the `_key` column holds the raw key and is hidden from the user (used internally for checkbox exclusion logic).

**`_sla_column_config(sla_num, jira_url)`**
Returns a Streamlit column config dict that applies `LinkColumn` to ticket key columns. Uses `display_text=r".*/browse/(.+)"` so Streamlit extracts just the ticket key from the URL path and renders it as the clickable link text.

**`sort_results(results, sort_by)`**
Sorts a list of `SLAResult` objects by one of seven criteria. The selected sort is stored in `sla_sort` session state and persists across reruns within a session.

**`apply_lpm_overrides(results, overrides)`**
Returns a new list of results with any user-selected LPM ticket substituted in for the auto-selected one. Uses `copy.copy()` (shallow copy) so the original cached `SLASummary` is not mutated.

**`_SLA_PLAIN_ENGLISH`**
Module-level dict keyed by SLA number (1–4). Each value is an HTML string with a plain-language explanation of what the SLA measures and how the calculation works — written for readers with no Jira knowledge. Rendered as a light blue info card inside `display_sla_section`.

**`display_sla_section(summary, sla_num, title, caption, target_days, jira_url)`**
Renders a complete SLA section including:
- Section header with title and caption
- Plain-English description card (from `_SLA_PLAIN_ENGLISH`) explaining the SLA in non-technical terms
- LPM override picker (SLAs 2 and 3 only, when multiple candidates exist)
- Sort control
- Five KPI cards (Total, Met, Breached, In Progress, Compliance Rate)
- Bar chart (days elapsed per ticket) and gauge chart (compliance %)
- Three tabs: Breached / In Progress / Met, each with a `st.data_editor` table

#### Charts

| Function | Type | Description |
|---|---|---|
| `donut_chart()` | Plotly Pie | Met/Breached/In Progress breakdown with compliance % in the center |
| `days_bar_chart()` | Plotly Bar | Days elapsed per ticket with a dashed target line; capped at 20 tickets |
| `compliance_gauge()` | Plotly Indicator | Gauge showing compliance %; colored red/yellow/green by threshold |
| `overview_bar()` | Plotly Bar (stacked) | Cross-SLA comparison of ticket volumes |

All charts are rendered as static (non-interactive) with `staticPlot: True`.

#### Sidebar

- Credential section: either a green "Credentials loaded from environment variables" banner (when env vars are set) or Jira URL, email, and API token form fields
- Optional start/end date filter
- Excluded Tickets list with a Clear All button
- Run SLA Checks button
- SLA target reference card

#### Run Flow

1. User clicks **Run SLA Checks** (credentials come from env vars or the sidebar form)
2. `JiraClient` is initialized and `test_connection()` is called; specific HTTP error messages are shown for 401, 403, 404, and network failures
3. A `log_collector` list is created and passed to `SLAChecker` (verbose mode is always on)
4. Before each SLA check, a `section` marker entry is appended to `log_collector` (e.g. `"SLA 1 — Time to First Response"`) — used by the Log tab to group entries by SLA
5. All four SLA checks run sequentially with a progress bar; every internal `_log` call appends to `log_collector`
6. Excluded tickets are filtered out of results
7. If SLA 4 is empty, fix-version fallback data is pre-fetched
8. All results, errors, and the log are stored in `st.session_state`
9. The page renders two top-level tabs — **📊 Dashboard** and **📋 Log** — from session state; subsequent checkbox/sort interactions do not re-query Jira

#### Log Tab

Displays all entries captured in `run_logs` during the last run, grouped by ticket with collapsible expanders:

- **Summary metrics** — total entries (excluding section markers), info, OK, and error counts
- **Search box** — filters entries by message text; searching by ticket key (e.g. `ACS-123`) reveals all lines for that ticket, not just lines that literally contain the search text
- **Level filter** — multiselect to show/hide INFO, OK, DETAIL, and ERROR entries
- **Grouped expanders** — each ticket gets its own collapsible row labelled with the ticket key and result (e.g. `✅ ACS-123 — Met`); JQL queries and other setup lines collapse under a `⚙️ SLA N —` expander for that SLA

Log entry levels and their meaning:

| Level | Color | Triggered by |
|---|---|---|
| INFO | Blue | JQL queries, section headers, status transitions found |
| OK | Green | Ticket counts, successful matches |
| DETAIL | Gray | Per-ticket field values, link checks, intermediate steps |
| ERROR | Red | API errors, failed comment/changelog fetches |

---

### `display.py`

Terminal output formatting for the CLI (`main.py`). Uses the [Rich](https://github.com/Textualize/rich) library to render styled tables and panels. Not used by the Streamlit app.

#### Functions

**`display_sla_dashboard(summary)`**
Renders a full SLA dashboard in the terminal: a header panel, KPI panels (Met / Breached / In Progress / Total), compliance rate, a description, and a sortable ticket table.

**`display_fix_version_tickets(version_data)`**
Renders the SLA 4 fallback view — a table of LPM fix-version tickets with their linked keys, grouped by version.

**`display_error(message)`** / **`display_info(message)`** / **`display_success(message)`**
Styled single-line output helpers used throughout `main.py`.

---

### `main.py`

CLI entry point. Resolves Jira credentials, connects, runs all four SLA checks, and prints results to the terminal using `display.py`.

#### Flow

1. Parses `--verbose` flag
2. Calls `get_env_credentials()` — returns a dict if all three env vars are set, otherwise `None`
3. If env vars are present: prints a confirmation and uses them directly, skipping all prompts and config file reads
4. If env vars are absent: loads `.config.json`, prompts for credentials (offering to reuse saved values), saves URL and email (not token) back to `.config.json`
5. Calls `connect_to_jira()`, which tests the connection and exits with a specific error message on failure (401, 403, 404, or network error)
6. Prompts for optional date range
7. Calls `run_sla_checks()` which runs all four SLA checks and displays each dashboard in sequence
8. If SLA 4 returns no results, falls back to `display_fix_version_tickets()`

#### `get_env_credentials()`

Reads `JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN` from the environment (after `python-dotenv` has loaded any `.env` file). Returns a credentials dict if all three are non-empty, otherwise `None`.

#### `connect_to_jira(creds)`

Creates a `JiraClient` and calls `test_connection()`. On failure, maps exception types to actionable error messages and exits:

| Exception | Message shown |
|---|---|
| `ConnectionError` | Cannot reach Jira — check URL and network |
| `HTTPError 401` | Authentication failed — check email and token |
| `HTTPError 403` | Access denied — check account permissions |
| `HTTPError 404` | URL not found — check `JIRA_BASE_URL` |
| Other | Raw exception message |

Run with `--verbose` (`-v`) to see JQL queries, field values, and per-ticket processing steps.

---

### `requirements.txt`

| Package | Purpose |
|---|---|
| `requests` | HTTP calls to the Jira REST API |
| `rich` | Terminal formatting for the CLI |
| `numpy` | Business day calculations via `numpy.busday_count` |
| `streamlit` | Web UI framework |
| `plotly` | Interactive charts (bar, gauge, donut, stacked bar) |
| `pandas` | DataFrame construction for `st.data_editor` tables |
| `python-dotenv` | Loads a `.env` file into environment variables on startup |

---

## The Four SLAs

| # | Name | Start | End | Target |
|---|---|---|---|---|
| 1 | Time to First Response | ACS ticket created | First public comment on ACS ticket | 2 business days |
| 2 | Identification of Resolution | ACS ticket created | Linked LPM ticket reaches "Ready for Config" | 30 business days |
| 3 | Resolution of Configuration Issues | ACS ticket created | Linked LPM ticket reaches "Deployed to UAT", "Waiting for UAT Signoff", or "Done" | 60 business days |
| 4 | Impact Report Delivery | SR sub-task created | Public comment containing "impact report" on linked ACS ticket | 30 business days |

All measurements use business days (Monday–Friday). Weekends are excluded. Public holidays are not currently excluded.

---

## Data Flow

```
Jira API
   │
   ├─ JiraClient          ← HTTP, auth, pagination, rate limiting
   │
   ├─ SLAChecker          ← JQL queries, changelog inspection, comment scanning
   │       │
   │       └─ SLAResult / SLASummary  ← structured results
   │
   ├─ streamlit_app.py    ← web dashboard (DataFrame, Plotly charts, data_editor)
   └─ main.py + display.py ← terminal output (Rich tables and panels)
```

---

## Configuration Checklist (New Environment)

1. Open `config.py`
2. Update `HEALTH_PLAN_FIELD_ID` to the custom field ID for "Health plan" in your Jira
3. Update `CATEGORY_FIELD_ID` to the custom field ID for "Category" on LPM tickets
4. Confirm `SOURCE_OF_ID_FIELD_ID` and `CONFIG_DONE_DATE_FIELD_ID` match your Jira
5. Confirm `PROJECT_A`, `PROJECT_B`, `PROJECT_C` match your Jira project keys
6. Confirm `health_plan_value` in `SLA_DEFINITIONS` matches the exact label used in your Jira ("LA Blue")
7. Create `sla-app/.env` with your Jira credentials (see README for format), or be ready to enter them interactively
8. Run `pip install -r requirements.txt`
9. Launch: `streamlit run sla-app/streamlit_app.py` (web) or `python sla-app/main.py` (CLI)
