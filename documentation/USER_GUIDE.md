# Healthcare SLA Dashboard — User Guide

This guide explains how to use the web dashboard: how to connect, what each section shows, how to read the results, and how to use the Log tab to understand what the tool did during a run.

---

## Getting Started

Open the dashboard in your browser by running:

```bash
streamlit run sla-app/streamlit_app.py
```

The sidebar on the left is where you log in and control the run.

### Connecting to Jira

There are two ways to provide credentials.

#### Option A — Environment variables (no prompts)

Set the following three environment variables before starting the app. The easiest way is a `.env` file in the `sla-app/` directory:

```
JIRA_BASE_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=you@yourcompany.com
JIRA_API_TOKEN=your_token_here
```

When all three are set, the sidebar shows a green **"Credentials loaded from environment variables"** message and no form is shown. Just click **▶ Run SLA Checks**.

#### Option B — Sidebar form

If the environment variables are not set, fill in three fields in the sidebar:

| Field | What to enter |
|---|---|
| **Jira URL** | Your company's Jira address, e.g. `https://yourcompany.atlassian.net` |
| **Email** | The email address you use to log in to Jira |
| **API Token** | A personal API token (not your password) — see below |

Your Jira URL and email are saved automatically after the first run so you don't have to re-enter them. Your API token is **never** saved — you will need to paste it each session.

**Getting an API token:**
1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click **Create API token**, give it a name, and copy it
3. Paste it into the API Token field in the sidebar (or set it as `JIRA_API_TOKEN`)

### How the app connects to Jira

When you provide a Jira URL (e.g. `https://yourcompany.atlassian.net`), the app automatically looks up your Atlassian **cloud ID** and routes all API calls through the Atlassian API gateway (`api.atlassian.com`). This is required for scoped service account tokens. You always provide your normal company URL — the gateway translation happens invisibly in the background.

### Connection Errors

If the app cannot connect to Jira, it will display a specific error message:

| Error | Likely cause |
|---|---|
| *Cannot reach Jira* | Wrong URL or no network access |
| *Authentication failed (401)* | Wrong email address or API token |
| *Access denied (403)* | Account lacks permission for this Jira instance |
| *Jira URL not found (404)* | The URL path is incorrect |

### Filtering by Date (Optional)

Below the credentials, you can set a **Start date** and/or **End date** to limit results to tickets created within that range. Leave both blank to include all tickets.

### Running the Checks

Click **▶ Run SLA Checks**. The dashboard will connect to Jira, run all four SLA checks in sequence, and display the results. This typically takes 30–90 seconds depending on how many tickets exist.

While the checks are running, a live status display shows:
- Which SLA is active (e.g. **SLA 2 of 4 — Identification of Resolution**)
- Which ticket is currently being evaluated and how many remain (e.g. **Checking ticket 7 of 23 · ACS-456**)
- A running tally of results so far (✅ met, 🔴 breached, 🟡 in progress)
- A progress bar that advances ticket-by-ticket within each SLA

---

## The Dashboard Tab

After a run, the **📊 Dashboard** tab shows all results.

### Executive Summary

At the top you will see five KPI cards:

- **Overall Compliance** — the combined compliance rate across all four SLAs (met tickets ÷ all resolved tickets)
- **One card per SLA** — the compliance rate for each individual SLA, with a count of how many resolved tickets met vs. total resolved

Below the KPIs, a stacked bar chart shows ticket volumes across all four SLAs so you can see at a glance which SLA has the most activity or the most breaches.

### Understanding Compliance Rate

The compliance rate only counts tickets that have a definitive outcome:

- **Met** — the SLA milestone was reached within the target number of business days ✅
- **Breached** — the SLA milestone was reached, but it took longer than the target 🔴

Tickets that are still in progress (the milestone hasn't been reached yet) are shown separately and are **not** included in the compliance rate calculation. This means the rate reflects only completed cases.

### SLA Sections

Each of the four SLAs has its own section. Each section contains:

**Plain-English description** — a light blue box explaining exactly what this SLA measures and where the clock starts and stops, in plain language.

**KPI cards** — Total tickets, Met, Breached, In Progress, and Compliance Rate for this SLA specifically.

**Bar chart** — shows business days elapsed per ticket (up to the 20 most recent), with a dashed red line marking the SLA target. Bars are colored green (met), red (breached), or amber (in progress).

**Gauge** — a dial showing the compliance rate at a glance. Green = above 90%, yellow = 70–90%, red = below 70%.

**Ticket tabs** — the tickets are split into three tabs:

| Tab | What it shows |
|---|---|
| 🔴 Breached | Tickets that exceeded the SLA target |
| 🟡 In Progress | Tickets still open; the clock is still running |
| ✅ Met | Tickets that were resolved within the target |

Each tab contains a table with one row per ticket. Ticket keys in the table are clickable links that open the ticket directly in Jira (when a Jira URL is set).

### Sorting the Ticket Table

Each SLA section has a **Sort by** dropdown above the charts. You can sort by:

- Days elapsed (high → low or low → high)
- Created date (newest or oldest first)
- Ticket number (high → low or low → high)
- Status (breached tickets first)

The sort applies to both the chart and the table.

### Excluding a Ticket

If a ticket should not be counted (e.g. it was created in error or is a known exception):

1. Check the **Excl.** checkbox on any row — you can check as many as you like across all tabs and SLA sections without the page recalculating
2. When you are done selecting, click **🔄 Recalculate** in the sidebar

The sidebar's **Ticket Exclusions** section shows:
- **Pending** — tickets you have checked but not yet applied
- **Applied** — tickets that have already been excluded from the current results

Clicking **Recalculate** moves all pending tickets into the applied set and immediately re-filters the results — no need to re-run the Jira checks. The **Clear All Exclusions** button removes all applied exclusions and resets the display.

### Overriding the Linked LPM Ticket (SLAs 2 and 3)

When an ACS ticket is linked to more than one LPM ticket, the calculator automatically picks the one with the most recent status transition. If you want to use a different linked ticket, an **Override linked LPM ticket** expander appears at the top of SLAs 2 and 3. Open it to manually select which LPM ticket should be used for that ACS ticket. The change takes effect immediately without re-running.

---

## The Log Tab

The **📋 Log** tab shows a complete record of everything the calculator did during the last run — every Jira query it sent, every ticket it evaluated, and the outcome for each one. It is useful for verifying results, understanding unexpected outcomes, and troubleshooting errors.

### Summary Metrics

At the top of the Log tab, four counters give a quick overview of the run:

| Metric | Meaning |
|---|---|
| **Total entries** | Total number of log lines recorded |
| **Info** | Queries sent, section headers, status transitions found |
| **OK** | Successful matches and ticket counts |
| **Errors** | Any API errors or failed data fetches |

### Searching the Log

The **Search logs** box filters the log in real time. Type any text and only matching entries will be shown.

**Tip: searching by ticket key** (e.g. `ACS-123`) is especially useful — it will expand and show **every log line for that ticket**, not just the lines that happen to contain those characters. This makes it easy to trace exactly what happened for a specific ticket.

### Filtering by Level

The **Filter by level** multiselect lets you choose which types of entries to show:

| Level | Color | What it contains |
|---|---|---|
| **INFO** | Blue | JQL queries sent to Jira, section headers, status transitions found |
| **OK** | Green | Ticket counts returned, successful matches |
| **DETAIL** | Gray | Per-ticket field values, link checks, intermediate steps |
| **ERROR** | Red | API errors, failed comment or changelog fetches |

If you only care about problems, deselect INFO, OK, and DETAIL to see only errors. If you want to see every step, keep all four selected.

### Reading the Grouped Entries

Log entries are organized into collapsible groups. Click any group to expand it.

**⚙️ SLA N — [name]** groups contain the setup activity for that SLA: the JQL query that was sent to Jira, the field IDs used, and how many tickets were returned. These are collapsed by default since they are mostly useful for troubleshooting.

**Ticket groups** each contain all the log lines for one specific ticket. The group title shows:
- The ticket key (e.g. `ACS-123`)
- The result: `✅ Met`, `🔴 Breached`, or `🟡 In Progress`

Example: `✅  ACS-123  —  Met`

Inside a ticket group you will typically see:

1. Which linked LPM (or SR) tickets were found
2. Whether each linked ticket reached the required status
3. The date that status was reached (if found)
4. The final business-day count and outcome

**Error entries** (red) inside a ticket group mean the calculator could not fetch data for that ticket — usually a temporary Jira API issue. The ticket may show as In Progress as a result.

---

## Common Questions

**Why is a ticket showing as In Progress when it seems resolved?**
The calculator looks for a specific Jira status (e.g. "Ready for Config" for SLA 2). If the linked LPM ticket never officially reached that status in Jira's history, the calculator will not count it as complete. Open that ticket's log group to see exactly what statuses were found.

**Why is the compliance rate different from what I expected?**
The rate only includes resolved tickets (Met + Breached). In-progress tickets are not counted. If most tickets are still open, the rate may be based on a small sample.

**A ticket appears in the wrong SLA section.**
Each SLA pulls tickets independently from Jira using its own query. A ticket can appear in multiple SLA sections if it is relevant to more than one.

**The run took a long time.**
Each ticket requires one or more additional Jira API calls (to fetch comments, changelogs, or linked tickets). Runs with many tickets can take several minutes. The live status display shows exactly which ticket is being processed so you can see that work is progressing.

**I see errors in the Log tab.**
Errors are usually temporary Jira API issues (rate limiting or network timeouts). The calculator retries automatically. If a ticket repeatedly errors, open its log group and copy the error message for your Jira administrator.
