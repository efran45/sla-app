"""
Healthcare SLA Dashboard - Streamlit Web App
"""
import json
import sys
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from pathlib import Path
from datetime import datetime, date

sys.path.insert(0, str(Path(__file__).parent))

from config import JIRA_FIELDS
from jira_client import JiraClient
from sla_checker import SLAChecker
from sla_calculator import SLASummary, SLAResult

CONFIG_FILE = Path(__file__).parent / ".config.json"

# ── Colors ────────────────────────────────────────────────────────────────────
C_MET       = "#16a34a"   # green
C_BREACHED  = "#dc2626"   # red
C_PROGRESS  = "#d97706"   # amber
C_NEUTRAL   = "#2563eb"   # blue
C_BG_CARD   = "#ffffff"
C_DARK      = "#f8fafc"

SLA_LABELS = [
    "Time to\nFirst Response",
    "Identification\nof Resolution",
    "Resolution of\nConfig Issues",
    "Impact Report\nDelivery",
]
SLA_TARGETS = [2, 30, 60, 30]

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Healthcare SLA Dashboard",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* Global font */
html, body, [class*="css"] { font-family: 'Inter', 'Segoe UI', sans-serif; }

/* Hide Streamlit default header clutter */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

/* Page background — light */
.stApp { background-color: #f1f5f9; }
section[data-testid="stSidebar"] { background-color: #1e293b !important; }
section[data-testid="stSidebar"] * { color: #e2e8f0 !important; }
section[data-testid="stSidebar"] .stTextInput input { background: #334155; color: #f1f5f9 !important; border-color: #475569; }
section[data-testid="stSidebar"] hr { border-color: #334155 !important; }

/* KPI cards */
.kpi-card {
    background: #ffffff;
    border-radius: 14px;
    padding: 22px 18px 18px 18px;
    text-align: center;
    border-top: 4px solid var(--card-color, #2563eb);
    box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    height: 140px;
    display: flex;
    flex-direction: column;
    justify-content: center;
}
.kpi-label {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #64748b;
    margin-bottom: 8px;
    font-weight: 600;
}
.kpi-value {
    font-size: 2.4rem;
    font-weight: 800;
    line-height: 1;
    color: var(--card-color, #1e293b);
}
.kpi-sub {
    font-size: 0.75rem;
    color: #94a3b8;
    margin-top: 6px;
}

/* Section header */
.sla-section-header {
    background: linear-gradient(90deg, #e0f2fe 0%, transparent 100%);
    border-left: 4px solid #2563eb;
    padding: 10px 16px;
    border-radius: 0 8px 8px 0;
    margin: 24px 0 12px 0;
}
.sla-section-title {
    font-size: 1.1rem;
    font-weight: 700;
    color: #1e293b;
    margin: 0;
}
.sla-section-sub {
    font-size: 0.78rem;
    color: #64748b;
    margin: 2px 0 0 0;
}

/* Divider */
hr { border-color: #e2e8f0; }
</style>
""", unsafe_allow_html=True)


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


def compliance_color(pct: float) -> str:
    if pct >= 90:
        return C_MET
    if pct >= 70:
        return C_PROGRESS
    return C_BREACHED


def kpi_card(label: str, value: str, sub: str = "", color: str = C_NEUTRAL):
    st.markdown(f"""
    <div class="kpi-card" style="--card-color:{color}">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        {"<div class='kpi-sub'>" + sub + "</div>" if sub else ""}
    </div>
    """, unsafe_allow_html=True)


def donut_chart(met: int, breached: int, in_progress: int, compliance: float) -> go.Figure:
    labels = ["Met", "Breached", "In Progress"]
    values = [met, breached, in_progress]
    colors = [C_MET, C_BREACHED, C_PROGRESS]

    # Remove zero slices
    filtered = [(l, v, c) for l, v, c in zip(labels, values, colors) if v > 0]
    if not filtered:
        filtered = [("No Data", 1, "#e2e8f0")]
    fl, fv, fc = zip(*filtered)

    fig = go.Figure(go.Pie(
        labels=fl,
        values=fv,
        hole=0.65,
        marker=dict(colors=fc, line=dict(color="#f1f5f9", width=2)),
        textinfo="percent",
        textfont=dict(size=12, color="white"),
        hovertemplate="%{label}: %{value} tickets<extra></extra>",
        sort=False,
    ))
    fig.add_annotation(
        text=f"<b>{compliance:.0f}%</b><br><span style='font-size:10px'>compliant</span>",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=16, color="#1e293b"),
        align="center",
    )
    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5,
                    font=dict(color="#64748b", size=11)),
        margin=dict(t=10, b=10, l=10, r=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=220,
    )
    return fig


def days_bar_chart(results: list[SLAResult], target_days: int) -> go.Figure:
    if not results:
        return None

    df = pd.DataFrame([{
        "label": (
            f"{r.source_ticket}<br>"
            f"<span style='font-size:9px'>{r.created_date.strftime('%b %d, %Y') if r.created_date else ''}</span>"
        ),
        "days": r.days_elapsed,
        "status": r.status,
        "ticket": r.source_ticket,
        "created": r.created_date.strftime("%b %d, %Y") if r.created_date else "",
    } for r in results]).sort_values("days", ascending=False).head(20)

    color_map = {"met": C_MET, "breached": C_BREACHED, "in_progress": C_PROGRESS}
    colors = [color_map.get(s, C_NEUTRAL) for s in df["status"]]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["label"],
        y=df["days"],
        marker_color=colors,
        hovertemplate="<b>%{customdata[0]}</b><br>Created: %{customdata[1]}<br>Days elapsed: %{y}<extra></extra>",
        customdata=df[["ticket", "created"]].values,
        name="Days Elapsed",
    ))
    fig.add_hline(
        y=target_days,
        line_dash="dash",
        line_color="#e74c3c",
        annotation_text=f"Target: {target_days}d",
        annotation_font_color="#e74c3c",
        annotation_position="top right",
    )
    fig.update_layout(
        xaxis=dict(tickfont=dict(color="#64748b", size=10), title=None, tickangle=-30),
        yaxis=dict(tickfont=dict(color="#64748b"), title="Business Days",
                   title_font=dict(color="#64748b"), gridcolor="#e2e8f0"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=10, b=40, l=40, r=10),
        height=240,
        showlegend=False,
    )
    return fig


def overview_bar(summaries: list[SLASummary | None]) -> go.Figure:
    labels = [f"SLA {i+1}" for i in range(4)]
    short_labels = ["First Response", "ID Resolution", "Config Resolution", "Impact Report"]

    met_vals      = [s.met_count if s else 0 for s in summaries]
    breached_vals = [s.breached_count if s else 0 for s in summaries]
    progress_vals = [s.in_progress_count if s else 0 for s in summaries]
    compliance    = [s.compliance_rate if s else 0 for s in summaries]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Met",         x=short_labels, y=met_vals,      marker_color=C_MET,      hovertemplate="%{y} tickets met<extra></extra>"))
    fig.add_trace(go.Bar(name="Breached",    x=short_labels, y=breached_vals, marker_color=C_BREACHED, hovertemplate="%{y} tickets breached<extra></extra>"))
    fig.add_trace(go.Bar(name="In Progress", x=short_labels, y=progress_vals, marker_color=C_PROGRESS, hovertemplate="%{y} in progress<extra></extra>"))

    fig.update_layout(
        barmode="stack",
        xaxis=dict(tickfont=dict(color="#1e293b", size=12), title=None),
        yaxis=dict(tickfont=dict(color="#64748b"), title="Ticket Count",
                   title_font=dict(color="#64748b"), gridcolor="#e2e8f0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(color="#64748b")),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=40, b=10, l=40, r=10),
        height=300,
    )
    return fig


def compliance_gauge(pct: float) -> go.Figure:
    color = compliance_color(pct)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=pct,
        number=dict(suffix="%", font=dict(size=28, color="#1e293b")),
        gauge=dict(
            axis=dict(range=[0, 100], tickcolor="#64748b", tickfont=dict(color="#64748b", size=10)),
            bar=dict(color=color, thickness=0.25),
            bgcolor="#f8fafc",
            borderwidth=0,
            steps=[
                dict(range=[0, 70],  color="#fee2e2"),
                dict(range=[70, 90], color="#fef9c3"),
                dict(range=[90, 100], color="#dcfce7"),
            ],
            threshold=dict(line=dict(color=color, width=3), thickness=0.75, value=pct),
        ),
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"),
        margin=dict(t=20, b=10, l=20, r=20),
        height=160,
    )
    return fig


def _ticket_url(base_url: str, key) -> str:
    """Return a Jira browse URL if key is valid, else the raw value."""
    if not key or key == "—" or not base_url:
        return key or "—"
    return f"{base_url.rstrip('/')}/browse/{key}"


def styled_df(results: list[SLAResult], sla_num: int = 1, jira_url: str = "") -> pd.DataFrame:
    rows = []
    fmt = "%b %d, %Y"
    for r in results:
        status_icon = {"met": "✅ Met", "breached": "🔴 Breached", "in_progress": "🟡 In Progress"}.get(r.status, r.status)
        created  = r.created_date.strftime(fmt)  if r.created_date  else "—"
        resolved = r.resolved_date.strftime(fmt) if r.resolved_date else "—"

        if sla_num == 1:
            rows.append({
                "ACS Ticket":         _ticket_url(jira_url, r.source_ticket),
                "ACS Created":        created,
                "First Comment Date": resolved,
                "Business Days":      r.days_elapsed,
                "Target":             r.target_days,
                "Status":             status_icon,
            })
        elif sla_num in (2, 3):
            resolution_label = "Ready for Config Date" if sla_num == 2 else "LPM Status Date"
            rows.append({
                "ACS Ticket":      _ticket_url(jira_url, r.source_ticket),
                "ACS Created":     created,
                "LPM Ticket":      _ticket_url(jira_url, r.target_ticket),
                resolution_label:  resolved,
                "Business Days":   r.days_elapsed,
                "Target":          r.target_days,
                "Status":          status_icon,
            })
        else:  # SLA 4 — Impact Report
            rows.append({
                "SR Sub-task":          _ticket_url(jira_url, r.source_ticket),
                "Sub-task Created":     created,
                "LPM Ticket":           _ticket_url(jira_url, r.lpm_category),
                "ACS Ticket":           _ticket_url(jira_url, r.target_ticket),
                "Impact Report Date":   resolved,
                "Business Days":        r.days_elapsed,
                "Target":               r.target_days,
                "Status":               status_icon,
            })
    return pd.DataFrame(rows)


def _link_col(label: str) -> st.column_config.LinkColumn:
    return st.column_config.LinkColumn(label, display_text=r"[^/]+$")


def _sla_column_config(sla_num: int, jira_url: str) -> dict:
    if not jira_url:
        return {}
    if sla_num == 1:
        return {"ACS Ticket": _link_col("ACS Ticket")}
    elif sla_num in (2, 3):
        return {
            "ACS Ticket": _link_col("ACS Ticket"),
            "LPM Ticket": _link_col("LPM Ticket"),
        }
    else:
        return {
            "SR Sub-task": _link_col("SR Sub-task"),
            "LPM Ticket":  _link_col("LPM Ticket"),
            "ACS Ticket":  _link_col("ACS Ticket"),
        }


def display_sla_section(summary: SLASummary, sla_num: int, title: str, caption: str, target_days: int, jira_url: str = ""):
    compliance = summary.compliance_rate
    cc = compliance_color(compliance)

    st.markdown(f"""
    <div class="sla-section-header">
        <p class="sla-section-title">SLA {sla_num} &nbsp;·&nbsp; {title}</p>
        <p class="sla-section-sub">{caption}</p>
    </div>
    """, unsafe_allow_html=True)

    if summary.total_count == 0:
        st.warning("No tickets found matching this SLA criteria.")
        return

    # KPI row
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: kpi_card("Total Tickets", str(summary.total_count), color=C_NEUTRAL)
    with c2: kpi_card("Met SLA", str(summary.met_count), color=C_MET)
    with c3: kpi_card("Breached", str(summary.breached_count), color=C_BREACHED if summary.breached_count else "#e2e8f0")
    with c4: kpi_card("In Progress", str(summary.in_progress_count), color=C_PROGRESS if summary.in_progress_count else "#e2e8f0")
    with c5: kpi_card("Compliance Rate", f"{compliance:.0f}%", sub=f"Target: {target_days}d", color=cc)

    # Charts row
    chart_col, gauge_col = st.columns([3, 1])
    with chart_col:
        bar = days_bar_chart(summary.results, target_days)
        if bar:
            st.plotly_chart(bar, use_container_width=True, config={"displayModeBar": False}, key=f"bar_{sla_num}")
    with gauge_col:
        st.plotly_chart(compliance_gauge(compliance), use_container_width=True, config={"displayModeBar": False}, key=f"gauge_{sla_num}")

    col_cfg = _sla_column_config(sla_num, jira_url)

    # Tables
    tab_b, tab_p, tab_m = st.tabs([
        f"🔴 Breached ({summary.breached_count})",
        f"🟡 In Progress ({summary.in_progress_count})",
        f"✅ Met ({summary.met_count})",
    ])
    with tab_b:
        if summary.breached_results:
            st.dataframe(styled_df(summary.breached_results, sla_num, jira_url), use_container_width=True, hide_index=True, column_config=col_cfg)
        else:
            st.success("No breached tickets!")
    with tab_p:
        if summary.in_progress_results:
            st.dataframe(styled_df(summary.in_progress_results, sla_num, jira_url), use_container_width=True, hide_index=True, column_config=col_cfg)
        else:
            st.info("No in-progress tickets.")
    with tab_m:
        if summary.met_results:
            st.dataframe(styled_df(summary.met_results, sla_num, jira_url), use_container_width=True, hide_index=True, column_config=col_cfg)
        else:
            st.info("No resolved tickets in this range.")


# ── Sidebar ────────────────────────────────────────────────────────────────────
saved = load_config()

with st.sidebar:
    st.markdown("## 🏥 SLA Dashboard")
    st.markdown("---")
    st.markdown("### Jira Credentials")

    jira_url = st.text_input(
        "Jira URL",
        value=saved.get("jira_base_url", "https://yourcompany.atlassian.net"),
        placeholder="https://yourcompany.atlassian.net",
    )
    jira_email = st.text_input("Email", value=saved.get("jira_email", ""))
    jira_token = st.text_input(
        "API Token", type="password",
        help="Get yours at https://id.atlassian.com/manage-profile/security/api-tokens",
    )

    st.markdown("---")
    st.markdown("### Date Range *(optional)*")
    date_from = st.date_input("Start date", value=None)
    date_to   = st.date_input("End date",   value=None)

    st.markdown("---")
    st.markdown("### Exclude Tickets *(optional)*")
    exclude_input = st.text_area(
        "Ticket keys to exclude",
        placeholder="ACS-123, LPM-456, SR-789",
        help="Comma-separated ticket keys to omit from all SLA calculations",
        height=80,
    )

    st.markdown("---")
    run_btn = st.button("▶ Run SLA Checks", type="primary", use_container_width=True)
    verbose = st.checkbox("Verbose logging")

    st.markdown("---")
    st.markdown("""
<div style='color:#64748b;font-size:0.72rem;line-height:1.6'>
<b>SLA Targets</b><br>
⏱ First Response: 2 bd<br>
🔍 ID Resolution: 30 bd<br>
🔧 Config Resolution: 60 bd<br>
📊 Impact Report: 30 bd
</div>
""", unsafe_allow_html=True)


# ── Main ───────────────────────────────────────────────────────────────────────
st.markdown("""
<h1 style='font-size:2rem;font-weight:800;margin-bottom:2px'>
  🏥 Healthcare SLA Dashboard
</h1>
<p style='color:#64748b;margin-top:0'>LA Blue &nbsp;·&nbsp; ACS → LPM → SR &nbsp;·&nbsp; Business-day tracking</p>
""", unsafe_allow_html=True)

if not run_btn:
    st.markdown("---")
    st.markdown("""
<div style='background:linear-gradient(135deg,#ffffff,#f1f5f9);border-radius:14px;padding:32px;text-align:center;border:1px solid #e2e8f0'>
  <div style='font-size:3rem;margin-bottom:12px'>📋</div>
  <h3 style='color:#1e293b;margin:0 0 8px 0'>Ready to run</h3>
  <p style='color:#64748b;margin:0'>Enter your Jira credentials in the sidebar and click <b style='color:#2563eb'>▶ Run SLA Checks</b></p>
</div>
""", unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    with c1: kpi_card("First Response", "2 bd", "Target", C_NEUTRAL)
    with c2: kpi_card("ID Resolution",  "30 bd", "Target", C_NEUTRAL)
    with c3: kpi_card("Config Resolution", "60 bd", "Target", C_NEUTRAL)
    with c4: kpi_card("Impact Report", "30 bd", "Target", C_NEUTRAL)
    st.stop()

# Validate
if not jira_url or not jira_email or not jira_token:
    st.error("Please fill in all three Jira credential fields in the sidebar.")
    st.stop()

save_config({"jira_base_url": jira_url, "jira_email": jira_email})

# Connect
with st.spinner("Connecting to Jira..."):
    try:
        client = JiraClient(base_url=jira_url, email=jira_email, token=jira_token)
        user_info = client.test_connection()
    except Exception as e:
        st.error(f"Connection failed: {e}")
        st.stop()

date_from_str = date_from.strftime("%Y-%m-%d") if date_from else None
date_to_str   = date_to.strftime("%Y-%m-%d")   if date_to   else None

checker = SLAChecker(client, verbose=verbose, date_from=date_from_str, date_to=date_to_str)
checker.set_field_id("health_plan", JIRA_FIELDS["health_plan"])
checker.set_field_id("category",    JIRA_FIELDS["category"])

# ── Fetch all four SLAs ───────────────────────────────────────────────────────
summaries = [None, None, None, None]
errors    = [None, None, None, None]

progress_bar = st.progress(0, text="Fetching SLA data from Jira...")

with st.spinner("Checking SLA 1: Time to First Response..."):
    try:
        summaries[0] = checker.check_first_response()
    except Exception as e:
        errors[0] = str(e)
progress_bar.progress(25, text="SLA 1 done · Checking SLA 2...")

with st.spinner("Checking SLA 2: Identification of Resolution..."):
    try:
        summaries[1] = checker.check_identification_resolution_config()
    except Exception as e:
        errors[1] = str(e)
progress_bar.progress(50, text="SLA 2 done · Checking SLA 3...")

with st.spinner("Checking SLA 3: Resolution of Config Issues..."):
    try:
        summaries[2] = checker.check_resolution_config()
    except Exception as e:
        errors[2] = str(e)
progress_bar.progress(75, text="SLA 3 done · Checking SLA 4...")

with st.spinner("Checking SLA 4: Impact Report Delivery..."):
    try:
        summaries[3] = checker.check_impact_report_delivery()
    except Exception as e:
        errors[3] = str(e)
progress_bar.progress(100, text="Done!")
progress_bar.empty()

# ── Apply ticket exclusions ───────────────────────────────────────────────────
excluded_keys: set[str] = set()
if exclude_input:
    excluded_keys = {k.strip().upper() for k in exclude_input.split(",") if k.strip()}

if excluded_keys:
    for s in summaries:
        if s:
            s.results = [
                r for r in s.results
                if (r.source_ticket or "").upper() not in excluded_keys
                and (r.target_ticket or "").upper() not in excluded_keys
                and (r.lpm_category or "").upper() not in excluded_keys
            ]

# ── Executive summary ─────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(f"""
<div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:4px'>
  <h2 style='margin:0;font-size:1.3rem;color:#1e293b'>Executive Summary</h2>
  <span style='color:#64748b;font-size:0.8rem'>
    Connected as <b style='color:#2563eb'>{user_info.get("displayName", jira_email)}</b>
    {"&nbsp;·&nbsp; " + date_from_str + " → " + (date_to_str or "today") if date_from_str else ""}
  </span>
</div>
""", unsafe_allow_html=True)

# Overall compliance
valid = [s for s in summaries if s and s.total_count > 0]
if valid:
    total_resolved = sum(s.met_count + s.breached_count for s in valid)
    total_met      = sum(s.met_count for s in valid)
    overall_pct    = (total_met / total_resolved * 100) if total_resolved else 100.0
else:
    overall_pct = 0.0

oc1, oc2, oc3, oc4, oc5 = st.columns(5)
with oc1:
    kpi_card("Overall Compliance", f"{overall_pct:.0f}%",
             sub="All 4 SLAs combined", color=compliance_color(overall_pct))
for i, (s, label, target) in enumerate(zip(summaries, SLA_LABELS, SLA_TARGETS)):
    col = [oc2, oc3, oc4, oc5][i]
    with col:
        if s and s.total_count > 0:
            pct = s.compliance_rate
            kpi_card(label.replace("\n", " "), f"{pct:.0f}%",
                     sub=f"{s.met_count}/{s.met_count+s.breached_count} resolved", color=compliance_color(pct))
        elif errors[i]:
            kpi_card(label.replace("\n", " "), "ERR", sub="See below", color=C_BREACHED)
        else:
            kpi_card(label.replace("\n", " "), "—", sub="No data", color="#e2e8f0")

# Overview stacked bar
if any(s and s.total_count > 0 for s in summaries):
    st.markdown("#### Ticket Volume by SLA")
    st.plotly_chart(overview_bar(summaries), use_container_width=True, config={"displayModeBar": False}, key="overview_bar")

st.markdown("---")

# ── Individual SLA sections ───────────────────────────────────────────────────
SLA_DEFS = [
    (1, "Time to First Response",                         "ACS creation → first public comment (any author)",                          2,  summaries[0], errors[0], checker.check_first_response),
    (2, "Identification of Resolution for Config Issues", "ACS creation → linked LPM ticket reaches 'Ready for Config'",              30, summaries[1], errors[1], None),
    (3, "Resolution of Configuration Issues",             "ACS creation → linked LPM ticket reaches 'Deployed to UAT' / 'Done'",     60, summaries[2], errors[2], None),
    (4, "Impact Report Delivery",                         "SR sub-task creation → 'impact report' comment on linked ACS ticket",      30, summaries[3], errors[3], None),
]

for sla_num, title, caption, target, summary, error, _ in SLA_DEFS:
    if error:
        st.error(f"SLA {sla_num} error: {error}")
        continue

    if sla_num == 4 and summary and summary.total_count == 0:
        st.markdown(f"""
        <div class="sla-section-header">
            <p class="sla-section-title">SLA 4 &nbsp;·&nbsp; {title}</p>
            <p class="sla-section-sub">{caption}</p>
        </div>
        """, unsafe_allow_html=True)
        st.info("No SR sub-tasks found via direct LPM links. Showing fix version tickets instead.")
        fix_version_data = checker.get_recent_fix_version_lpm_tickets()
        if fix_version_data:
            st.dataframe(fix_version_data, use_container_width=True, hide_index=True)
        else:
            st.warning("No fix version tickets found either.")
    else:
        display_sla_section(summary, sla_num, title, caption, target, jira_url=jira_url)

    st.markdown("<br>", unsafe_allow_html=True)
