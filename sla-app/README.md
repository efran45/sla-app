# Healthcare SLA Dashboard

Tracks SLA compliance for LA Blue healthcare tickets across three Jira projects (ACS → LPM → SR). Available as a browser-based dashboard or a terminal CLI.

## SLAs Monitored

| # | Name | Measures | Target |
|---|------|----------|--------|
| 1 | Time to First Response | ACS ticket created → first public comment posted | 2 business days |
| 2 | Identification of Resolution | ACS ticket created → linked LPM ticket reaches "Ready for Config" | 30 business days |
| 3 | Resolution of Configuration Issues | ACS ticket created → linked LPM ticket reaches "Deployed to UAT", "Waiting for UAT Signoff", or "Done" | 60 business days |
| 4 | Impact Report Delivery | SR sub-task created → public comment containing "impact report" on the linked ACS ticket | 30 business days |

All measurements use business days (Monday–Friday). Weekends are excluded.

## Setup

```bash
cd sla-app
pip install -r requirements.txt
```

Before first use, open `config.py` and set the four custom field IDs to match your Jira instance:

```python
HEALTH_PLAN_FIELD_ID    = "customfield_XXXXX"   # "Health plan" field on ACS tickets
CATEGORY_FIELD_ID       = "customfield_XXXXX"   # "Category" field on LPM tickets
SOURCE_OF_ID_FIELD_ID   = "customfield_XXXXX"   # "Source of Identification" on ACS tickets
CONFIG_DONE_DATE_FIELD_ID = "customfield_XXXXX" # "Config done date" on LPM tickets
```

To find a field ID, open any ticket's raw JSON in your browser:
```
https://yourcompany.atlassian.net/rest/api/3/issue/ACS-123
```

## Usage

### Web Dashboard (recommended)

```bash
streamlit run streamlit_app.py
```

Opens in your browser. Enter your Jira credentials in the sidebar and click **Run SLA Checks**.

Features:
- Executive summary with overall compliance rate
- Per-SLA KPI cards, bar charts, and compliance gauges
- Breached / In Progress / Met tabs per SLA with sortable, filterable tables
- Clickable ticket links back to Jira
- **Log tab** — full run log grouped by ticket, searchable, with collapsible expanders per ticket showing each step of the calculation

### Terminal CLI

```bash
python main.py
```

Add `-v` / `--verbose` to print JQL queries and per-ticket processing steps.

The CLI will:
1. Prompt for your Jira credentials (URL and email are saved for next time; API token is never saved)
2. Test the connection
3. Optionally filter by date range
4. Print each SLA dashboard to the terminal

## Getting Your API Token

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click **Create API token**
3. Give it a name and copy the token
4. Paste it when prompted (web) or when asked at startup (CLI)
