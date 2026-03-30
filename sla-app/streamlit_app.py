"""
Healthcare SLA Dashboard - Streamlit Web App
"""
import json
import sys
import streamlit as st
from pathlib import Path
from datetime import datetime, date

# Add the app directory to path so imports work
sys.path.insert(0, str(Path(__file__).parent))

from config import JIRA_FIELDS
from jira_client import JiraClient
from sla_checker import SLAChecker
from sla_calculator import SLASummary, SLAResult

CONFIG_FILE = Path(__file__).parent / ".config.json"

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Healthcare SLA Dashboard",
    page_icon="🏥",
    layout="wide",
)

# ── Helpers ───────────────────────────────────────────────────────────────────
def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def result_to_row(r: SLAResult) -> dict:
    return {
        "Source Ticket": r.source_ticket,
        "Target Ticket": r.target_ticket or "—",
        "Created": r.created_date.strftime("%Y-%m-%d") if r.created_date else "—",
        "Resolved": r.resolved_date.strftime("%Y-%m-%d") if r.resolved_date else "—",
        "Days Elapsed": r.days_elapsed,
        "Target Days": r.target_days,
        "Status": r.status.capitalize(),
        "Category": r.lpm_category or "—",
        "Source of ID": r.source_of_identification or "—",
    }


def display_sla_section(summary: SLASummary):
    """Render one SLA block: metrics row + expandable tables."""
    compliance = summary.compliance_rate
    color = "normal" if compliance >= 90 else ("off" if compliance >= 70 else "inverse")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Tickets", summary.total_count)
    col2.metric("Met", summary.met_count, delta=None)
    col3.metric("Breached", summary.breached_count, delta=None)
    col4.metric("In Progress", summary.in_progress_count, delta=None)
    col5.metric("Compliance", f"{compliance:.1f}%")

    if summary.breached_results:
        with st.expander(f"Breached ({summary.breached_count})", expanded=True):
            st.dataframe(
                [result_to_row(r) for r in summary.breached_results],
                use_container_width=True,
                hide_index=True,
            )

    if summary.in_progress_results:
        with st.expander(f"In Progress ({summary.in_progress_count})"):
            st.dataframe(
                [result_to_row(r) for r in summary.in_progress_results],
                use_container_width=True,
                hide_index=True,
            )

    if summary.met_results:
        with st.expander(f"Met ({summary.met_count})"):
            st.dataframe(
                [result_to_row(r) for r in summary.met_results],
                use_container_width=True,
                hide_index=True,
            )


# ── Sidebar: credentials & filters ───────────────────────────────────────────
saved = load_config()

with st.sidebar:
    st.title("🏥 SLA Dashboard")
    st.subheader("Jira Credentials")

    jira_url = st.text_input(
        "Jira URL",
        value=saved.get("jira_base_url", "https://yourcompany.atlassian.net"),
        placeholder="https://yourcompany.atlassian.net",
    )
    jira_email = st.text_input(
        "Email",
        value=saved.get("jira_email", ""),
    )
    jira_token = st.text_input(
        "API Token",
        type="password",
        help="Get yours at https://id.atlassian.com/manage-profile/security/api-tokens",
    )

    st.divider()
    st.subheader("Date Range (optional)")
    date_from = st.date_input("Start date", value=None)
    date_to = st.date_input("End date", value=None)

    st.divider()
    run_btn = st.button("Run SLA Checks", type="primary", use_container_width=True)
    verbose = st.checkbox("Verbose logging")

# ── Main area ─────────────────────────────────────────────────────────────────
st.title("Healthcare SLA Dashboard")
st.caption("ACS → LPM → SR | BCBSLA | Business-day SLA tracking")

if not run_btn:
    st.info("Fill in your Jira credentials in the sidebar and click **Run SLA Checks**.")
    st.markdown("""
**Tracked SLAs:**

| # | SLA | Target |
|---|-----|--------|
| 1 | Time to First Response | 2 business days |
| 2 | Identification of Resolution for Config Issues | 30 business days |
| 3 | Resolution of Configuration Issues | 60 business days |
| 4 | Impact Report Delivery | 30 business days |
""")
    st.stop()

# Validate inputs
if not jira_url or not jira_email or not jira_token:
    st.error("Please fill in all three Jira credential fields.")
    st.stop()

# Save URL + email for next time (never save the token)
save_config({"jira_base_url": jira_url, "jira_email": jira_email})

# Connect
with st.spinner("Connecting to Jira..."):
    try:
        client = JiraClient(base_url=jira_url, email=jira_email, token=jira_token)
        user_info = client.test_connection()
        st.success(f"Connected as **{user_info.get('displayName', jira_email)}**")
    except Exception as e:
        st.error(f"Connection failed: {e}")
        st.stop()

# Build date strings
date_from_str = date_from.strftime("%Y-%m-%d") if date_from else None
date_to_str = date_to.strftime("%Y-%m-%d") if date_to else None

if date_from_str or date_to_str:
    st.info(f"Filtering tickets created: {date_from_str or 'beginning'} → {date_to_str or 'now'}")

checker = SLAChecker(
    client,
    verbose=verbose,
    date_from=date_from_str,
    date_to=date_to_str,
)
checker.set_field_id("health_plan", JIRA_FIELDS["health_plan"])
checker.set_field_id("category", JIRA_FIELDS["category"])

# ── SLA 1 ─────────────────────────────────────────────────────────────────────
st.header("1 · Time to First Response", divider="blue")
st.caption("Target: **2 business days** from ACS ticket creation to first internal comment")
with st.spinner("Checking Time to First Response..."):
    try:
        summary1 = checker.check_first_response()
        if summary1.total_count == 0:
            st.warning("No tickets found matching the First Response SLA criteria.")
        else:
            display_sla_section(summary1)
    except Exception as e:
        st.error(f"Error: {e}")

# ── SLA 2 ─────────────────────────────────────────────────────────────────────
st.header("2 · Identification of Resolution for Config Issues", divider="blue")
st.caption("Target: **30 business days** from ACS creation to linked LPM 'break fix' ticket")
with st.spinner("Checking Identification of Resolution..."):
    try:
        summary2 = checker.check_identification_resolution_config()
        if summary2.total_count == 0:
            st.warning("No tickets found matching the Identification SLA criteria.")
        else:
            display_sla_section(summary2)
    except Exception as e:
        st.error(f"Error: {e}")

# ── SLA 3 ─────────────────────────────────────────────────────────────────────
st.header("3 · Resolution of Configuration Issues", divider="blue")
st.caption("Target: **60 business days** from ACS creation to LPM 'config done date'")
with st.spinner("Checking Resolution of Config Issues..."):
    try:
        summary3 = checker.check_resolution_config()
        if summary3.total_count == 0:
            st.warning("No tickets found matching the Resolution SLA criteria.")
        else:
            display_sla_section(summary3)
    except Exception as e:
        st.error(f"Error: {e}")

# ── SLA 4 ─────────────────────────────────────────────────────────────────────
st.header("4 · Impact Report Delivery", divider="blue")
st.caption("Target: **30 business days** from SR sub-task creation to impact report attachment on ACS")
with st.spinner("Checking Impact Report Delivery..."):
    try:
        summary4 = checker.check_impact_report_delivery()
        if summary4.total_count == 0:
            st.info("No SR sub-tasks found via direct LPM links. Checking fix versions...")
            fix_version_data = checker.get_recent_fix_version_lpm_tickets()
            if fix_version_data:
                st.subheader("Recent LPM Fix Version Tickets")
                st.dataframe(fix_version_data, use_container_width=True, hide_index=True)
            else:
                st.warning("No fix version tickets found either.")
        else:
            display_sla_section(summary4)
    except Exception as e:
        st.error(f"Error: {e}")
