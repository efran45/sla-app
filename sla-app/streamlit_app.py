"""
SLA Dashboard - Streamlit Web App
"""
import json
import logging
import os
import re
import sys
import requests
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from pathlib import Path
from datetime import datetime, date

logging.basicConfig(level=logging.INFO, format="[SLA] %(levelname)s %(message)s")
_log = logging.getLogger(__name__)

_REQUIRED_KEYS = {"JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"}

def _validate_env_file(env_path: Path):
    _log.info("Looking for .env at: %s", env_path)
    if not env_path.exists():
        _log.warning(".env file not found — will use interactive form or existing env vars")
        return
    _log.info(".env file found")
    for i, raw in enumerate(env_path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            _log.warning(".env line %d has no '=' sign: %r", i, line)
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if key not in _REQUIRED_KEYS:
            _log.info(".env line %d: unrecognised key %r (ignored)", i, key)
            continue
        if val and val[0] in ('"', "'") and val[-1] == val[0]:
            _log.warning(
                ".env line %d: value for %s is wrapped in quotes — remove them. "
                "Correct format: %s=yourvalue", i, key, key
            )
        elif not val:
            _log.warning(".env line %d: %s has no value", i, key)
        else:
            _log.info(".env line %d: %s looks OK (length %d)", i, key, len(val))

_validate_env_file(Path(__file__).parent / ".env")

try:
    from dotenv import load_dotenv
    loaded = load_dotenv(Path(__file__).parent / ".env")
    _log.info("dotenv load_dotenv returned: %s", loaded)
except ImportError:
    _log.warning("python-dotenv is not installed — .env file will not be loaded")

sys.path.insert(0, str(Path(__file__).parent))

from config import JIRA_FIELDS
from jira_client import JiraClient
from sla_checker import SLAChecker
from sla_calculator import SLASummary, SLAResult, get_business_days, get_business_days_elapsed

# Credentials from environment variables (all three required to skip the sidebar form)
_ENV_URL    = os.environ.get("JIRA_BASE_URL", "").strip()
_ENV_EMAIL  = os.environ.get("JIRA_EMAIL", "").strip()
_ENV_TOKEN  = os.environ.get("JIRA_API_TOKEN", "").strip()
_USING_ENV  = bool(_ENV_URL and _ENV_EMAIL and _ENV_TOKEN)

_log.info("JIRA_BASE_URL set: %s", bool(_ENV_URL))
_log.info("JIRA_EMAIL set: %s", bool(_ENV_EMAIL))
_log.info("JIRA_API_TOKEN set: %s", bool(_ENV_TOKEN))
_log.info("Using environment credentials: %s", _USING_ENV)

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
    page_title="SLA Dashboard",
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


SORT_OPTIONS = [
    "Days (high → low)",
    "Days (low → high)",
    "Created (newest first)",
    "Created (oldest first)",
    "Ticket # (high → low)",
    "Ticket # (low → high)",
    "Status (breached first)",
]

def _ticket_num(r: SLAResult) -> int:
    parts = (r.source_ticket or "").rsplit("-", 1)
    return int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else 0

def sort_results(results: list[SLAResult], sort_by: str) -> list[SLAResult]:
    STATUS_ORDER = {"breached": 0, "in_progress": 1, "met": 2}
    if sort_by == "Days (high → low)":
        return sorted(results, key=lambda r: r.days_elapsed, reverse=True)
    if sort_by == "Days (low → high)":
        return sorted(results, key=lambda r: r.days_elapsed)
    if sort_by == "Created (newest first)":
        return sorted(results, key=lambda r: r.created_date or datetime.min, reverse=True)
    if sort_by == "Created (oldest first)":
        return sorted(results, key=lambda r: r.created_date or datetime.min)
    if sort_by == "Ticket # (high → low)":
        return sorted(results, key=_ticket_num, reverse=True)
    if sort_by == "Ticket # (low → high)":
        return sorted(results, key=_ticket_num)
    if sort_by == "Status (breached first)":
        return sorted(results, key=lambda r: STATUS_ORDER.get(r.status, 3))
    return results


def apply_lpm_overrides(results: list[SLAResult], overrides: dict) -> list[SLAResult]:
    """Return results with any user-selected LPM ticket substituted in."""
    if not overrides:
        return results
    from copy import copy
    out = []
    for r in results:
        chosen = overrides.get(r.source_ticket)
        if chosen and r.lpm_candidates:
            for lpm_key, transition_date in r.lpm_candidates:
                if lpm_key == chosen:
                    rc = copy(r)
                    rc.target_ticket = lpm_key
                    rc.resolved_date = transition_date
                    if transition_date:
                        rc.days_elapsed = get_business_days(r.created_date, transition_date)
                        rc.status = "met" if rc.days_elapsed <= r.target_days else "breached"
                    else:
                        rc.days_elapsed = get_business_days_elapsed(r.created_date)
                        rc.status = "breached" if rc.days_elapsed > r.target_days else "in_progress"
                    out.append(rc)
                    break
            else:
                out.append(r)
        else:
            out.append(r)
    return out


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
    } for r in results]).head(20)

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
    short_labels = ["First Response", "ID Resolution", "Config Resolution", "Impact Report Delivery"]

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


def _ticket_cell(base_url: str, key: str) -> str:
    """Cell value for a ticket column: full browse URL when available, else plain key."""
    if not key or key == "—":
        return "—"
    if base_url:
        return f"{base_url.rstrip('/')}/browse/{key}"
    return key


def styled_df(results: list[SLAResult], sla_num: int = 1, jira_url: str = "") -> pd.DataFrame:
    rows = []
    fmt = "%b %d, %Y"
    excluded = st.session_state.get("excluded_keys", set())
    for r in results:
        status_icon = {"met": "✅ Met", "breached": "🔴 Breached", "in_progress": "🟡 In Progress"}.get(r.status, r.status)
        created  = r.created_date.strftime(fmt) if r.created_date  else "—"
        resolved = r.resolved_date.strftime(fmt) if r.resolved_date else "—"
        key = r.source_ticket or ""
        is_excluded = key.upper() in excluded

        if sla_num == 1:
            rows.append({
                "Exclude":        is_excluded,
                "_key":           key,
                "ACS Ticket":     _ticket_cell(jira_url, r.source_ticket),
                "ACS Category":   r.category_migrated or "—",
                "ACS Created":    created,
                "First Comment":  resolved,
                "Business Days":  r.days_elapsed,
                "Status":         status_icon,
            })
        elif sla_num in (2, 3):
            lpm_date_label = "Ready for Config" if sla_num == 2 else "LPM Status Date"
            rows.append({
                "Exclude":         is_excluded,
                "_key":            key,
                "ACS Ticket":      _ticket_cell(jira_url, r.source_ticket),
                "ACS Category":    r.category_migrated or "—",
                "ACS Created":     created,
                "LPM Ticket":      _ticket_cell(jira_url, r.target_ticket),
                "LPM Category":    r.target_category or "—",
                lpm_date_label:    resolved,
                "Business Days":   r.days_elapsed,
                "Status":          status_icon,
            })
        else:  # SLA 4 — Impact Report Delivery
            rows.append({
                "Exclude":            is_excluded,
                "_key":               key,
                "SR Sub-task":        _ticket_cell(jira_url, r.source_ticket),
                "SR Created":         created,
                "SR Parent":          _ticket_cell(jira_url, r.lpm_category),
                "ACS Ticket":         _ticket_cell(jira_url, r.target_ticket),
                "Impact Report Date": resolved,
                "Business Days":      r.days_elapsed,
                "Status":             status_icon,
            })
    return pd.DataFrame(rows)


def _sla_column_config(sla_num: int, jira_url: str) -> dict:
    """LinkColumn config for ticket key columns — display_text regex shows just the key."""
    if not jira_url:
        return {}
    lnk = lambda lbl: st.column_config.LinkColumn(lbl, display_text=r".*/browse/(.+)")
    if sla_num == 1:
        return {"ACS Ticket": lnk("ACS Ticket")}
    elif sla_num in (2, 3):
        return {"ACS Ticket": lnk("ACS Ticket"), "LPM Ticket": lnk("LPM Ticket")}
    else:
        return {
            "SR Sub-task": lnk("SR Sub-task"),
            "SR Parent":   lnk("SR Parent"),
            "ACS Ticket":  lnk("ACS Ticket"),
        }


_SLA_PLAIN_ENGLISH = {
    1: (
        "When a new support ticket arrives from an LA Blue member, the team has <b>2 business days</b> to post "
        "the first public reply. We pull every LA Blue ticket from the ACS project and measure the time from "
        "when the ticket was created to when the first visible comment was added — by anyone on the team."
    ),
    2: (
        "After an LA Blue support ticket is opened, the SEE teams have <b>30 business days</b> to identify a fix. "
        "We track this by watching for when a linked work ticket in the LPM project first reaches "
        "<b>'Ready for Config'</b> status. The clock starts the moment the ACS support ticket is created "
        "and stops when that status is reached."
    ),
    3: (
        "The full configuration fix must be completed within <b>60 business days</b> of the original support "
        "ticket opening. We watch the linked LPM work ticket and stop the clock when it reaches "
        "<b>'Deployed to UAT'</b>, <b>'Waiting for Client UAT/Signoff'</b>, or <b>'Done'</b> — whichever comes first. "
        "The clock starts at ACS ticket creation."
    ),
    4: (
        "When a software release affects LA Blue members, an impact report must be delivered within "
        "<b>30 business days</b>. The clock starts when an SR sub-task is created for that release. "
        "It stops when a public comment containing the words <b>'impact report'</b> is posted on the "
        "linked ACS support ticket."
    ),
}


def display_sla_section(summary: SLASummary, sla_num: int, title: str, caption: str, target_days: int, jira_url: str = ""):
    st.markdown(f"""
    <div class="sla-section-header">
        <p class="sla-section-title">SLA {sla_num} &nbsp;·&nbsp; {title}</p>
        <p class="sla-section-sub">{caption}</p>
    </div>
    """, unsafe_allow_html=True)

    desc = _SLA_PLAIN_ENGLISH.get(sla_num)
    if desc:
        st.markdown(
            f'<div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;'
            f'padding:11px 16px;margin:4px 0 18px 0;color:#0c4a6e;font-size:0.88rem;line-height:1.65">'
            f'{desc}</div>',
            unsafe_allow_html=True,
        )

    if summary.total_count == 0:
        st.warning("No tickets found matching this SLA criteria.")
        return

    # ── LPM override expander (SLAs 2 & 3 only) ──────────────────────────────
    if sla_num in (2, 3):
        multi = [r for r in summary.results if len(r.lpm_candidates) > 1]
        if multi:
            with st.expander(f"🔗 Override linked LPM ticket ({len(multi)} ticket{'s' if len(multi) != 1 else ''} with multiple candidates)"):
                st.caption("The calculator auto-selects the most recent LPM transition. Pick a different one here — takes effect immediately.")
                for r in multi:
                    cand_keys = [k for k, _ in r.lpm_candidates]
                    current = st.session_state.lpm_overrides.get(r.source_ticket, cand_keys[0])
                    if current not in cand_keys:
                        current = cand_keys[0]
                    label_col, sel_col = st.columns([1, 3])
                    with label_col:
                        st.markdown(f"**{r.source_ticket}**")
                    with sel_col:
                        chosen = st.selectbox(
                            f"lpm_for_{r.source_ticket}",
                            options=cand_keys,
                            index=cand_keys.index(current),
                            format_func=lambda k, r=r: (
                                f"{k}  —  "
                                + next((d.strftime('%b %d %Y') for lk, d in r.lpm_candidates if lk == k and d), "no date")
                            ),
                            key=f"lpm_override_{sla_num}_{r.source_ticket}",
                            label_visibility="collapsed",
                        )
                    st.session_state.lpm_overrides[r.source_ticket] = chosen

    # Apply overrides and compute effective results
    effective = apply_lpm_overrides(summary.results, st.session_state.lpm_overrides)
    disp = SLASummary(summary.sla_name, summary.target_days)
    for r in effective:
        disp.add_result(r)

    compliance = disp.compliance_rate
    cc = compliance_color(compliance)

    # ── Sort control ──────────────────────────────────────────────────────────
    sort_col, _ = st.columns([2, 5])
    with sort_col:
        current_sort = st.session_state.sla_sort.get(sla_num, SORT_OPTIONS[0])
        if current_sort not in SORT_OPTIONS:
            current_sort = SORT_OPTIONS[0]
        sort_by = st.selectbox(
            "Sort by",
            options=SORT_OPTIONS,
            index=SORT_OPTIONS.index(current_sort),
            key=f"sort_{sla_num}",
        )
    st.session_state.sla_sort[sla_num] = sort_by

    sorted_all = sort_results(disp.results, sort_by)

    # ── KPI row ───────────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: kpi_card("Total Tickets", str(disp.total_count), color=C_NEUTRAL)
    with c2: kpi_card("Met SLA", str(disp.met_count), color=C_MET)
    with c3: kpi_card("Breached", str(disp.breached_count), color=C_BREACHED if disp.breached_count else "#e2e8f0")
    with c4: kpi_card("In Progress", str(disp.in_progress_count), color=C_PROGRESS if disp.in_progress_count else "#e2e8f0")
    with c5: kpi_card("Compliance Rate", f"{compliance:.0f}%", sub=f"Target: {target_days}d", color=cc)

    # ── Charts row ────────────────────────────────────────────────────────────
    chart_col, gauge_col = st.columns([3, 1])
    with chart_col:
        bar = days_bar_chart(sorted_all, target_days)
        if bar:
            st.plotly_chart(bar, use_container_width=True, config={"displayModeBar": False, "scrollZoom": False, "staticPlot": True}, key=f"bar_{sla_num}")
    with gauge_col:
        st.plotly_chart(compliance_gauge(compliance), use_container_width=True, config={"displayModeBar": False, "scrollZoom": False, "staticPlot": True}, key=f"gauge_{sla_num}")

    link_cfg = _sla_column_config(sla_num, jira_url)

    def _show_table(results: list[SLAResult], tab_key: str) -> bool:
        if not results:
            return False
        sorted_tab = sort_results(results, sort_by)
        df = styled_df(sorted_tab, sla_num, jira_url)
        visible = ["Exclude"] + [c for c in df.columns if c not in ("Exclude", "_key")]
        col_cfg = {
            "_key": None,
            "Exclude": st.column_config.CheckboxColumn(
                "Excl.",
                help="Check to exclude this ticket on the next run",
                default=False,
                width="small",
            ),
            **link_cfg,
        }
        edited = st.data_editor(
            df,
            column_config=col_cfg,
            column_order=visible,
            disabled=[c for c in df.columns if c != "Exclude"],
            hide_index=True,
            use_container_width=True,
            key=f"tbl_{sla_num}_{tab_key}",
        )
        for _, row in edited.iterrows():
            k = str(row.get("_key", "")).strip().upper()
            if not k:
                continue
            if row.get("Exclude", False):
                st.session_state.excluded_keys.add(k)
            else:
                st.session_state.excluded_keys.discard(k)
        return True

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_b, tab_p, tab_m = st.tabs([
        f"🔴 Breached ({disp.breached_count})",
        f"🟡 In Progress ({disp.in_progress_count})",
        f"✅ Met ({disp.met_count})",
    ])
    with tab_b:
        if not _show_table(disp.breached_results, "b"):
            st.success("No breached tickets!")
    with tab_p:
        if not _show_table(disp.in_progress_results, "p"):
            st.info("No in-progress tickets.")
    with tab_m:
        if not _show_table(disp.met_results, "m"):
            st.info("No resolved tickets in this range.")


# ── Session state ─────────────────────────────────────────────────────────────
if "excluded_keys" not in st.session_state:
    st.session_state.excluded_keys = set()
if "lpm_overrides" not in st.session_state:
    st.session_state.lpm_overrides = {}
if "sla_sort" not in st.session_state:
    st.session_state.sla_sort = {}

# ── Sidebar ────────────────────────────────────────────────────────────────────
saved = load_config()

with st.sidebar:
    st.markdown("## 🏥 SLA Dashboard")
    st.markdown("---")
    st.markdown("### Jira Credentials")

    if _USING_ENV:
        st.success("Credentials loaded from environment variables.")
        jira_url   = _ENV_URL
        jira_email = _ENV_EMAIL
        jira_token = _ENV_TOKEN
    else:
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
    excl = st.session_state.excluded_keys
    excl_count = len(excl)
    st.markdown(f"### Excluded Tickets ({excl_count})")
    if excl_count:
        st.caption(", ".join(sorted(excl)))
        if st.button("Clear All Exclusions", use_container_width=True):
            st.session_state.excluded_keys = set()
            st.rerun()
    else:
        st.caption("Check the **Excl.** box on any ticket row to exclude it from the next run.")

    st.markdown("---")
    run_btn = st.button("▶ Run SLA Checks", type="primary", use_container_width=True)

    st.markdown("---")
    st.markdown("""
<div style='color:#64748b;font-size:0.72rem;line-height:1.6'>
<b>SLA Targets</b><br>
⏱ First Response: 2 business days<br>
🔍 ID Resolution: 30 business days<br>
🔧 Config Resolution: 60 business days<br>
📊 Impact Report Delivery: 30 business days
</div>
""", unsafe_allow_html=True)


# ── Main ───────────────────────────────────────────────────────────────────────
st.markdown("""
<h1 style='font-size:2rem;font-weight:800;margin-bottom:2px'>
  SLA Dashboard
</h1>
<p style='color:#64748b;margin-top:0'>LA Blue &nbsp;·&nbsp; ACS → LPM → SR &nbsp;·&nbsp; Business-day tracking</p>
""", unsafe_allow_html=True)

if run_btn:
    if not jira_url or not jira_email or not jira_token:
        st.error("Please fill in all three Jira credential fields in the sidebar.")
        st.stop()

    if not _USING_ENV:
        save_config({"jira_base_url": jira_url, "jira_email": jira_email})

    with st.spinner("Connecting to Jira..."):
        try:
            client = JiraClient(base_url=jira_url, email=jira_email, token=jira_token)
            user_info = client.test_connection()
        except requests.exceptions.ConnectionError:
            st.error(
                f"Cannot reach Jira at '{jira_url}'. "
                "Check your Jira URL and network connection."
            )
            st.stop()
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            if status == 401:
                st.error("Authentication failed (HTTP 401). Check your email address and API token.")
            elif status == 403:
                st.error("Access denied (HTTP 403). Your account may not have permission to access this Jira instance.")
            elif status == 404:
                st.error(f"Jira URL not found (HTTP 404). Verify that '{jira_url}' is correct.")
            else:
                st.error(f"Jira returned HTTP {status}: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Connection failed: {e}")
            st.stop()

    date_from_str = date_from.strftime("%Y-%m-%d") if date_from else None
    date_to_str   = date_to.strftime("%Y-%m-%d")   if date_to   else None

    log_collector = []
    checker = SLAChecker(client, verbose=True, log_collector=log_collector, date_from=date_from_str, date_to=date_to_str)
    checker.set_field_id("health_plan", JIRA_FIELDS["health_plan"])
    checker.set_field_id("category",    JIRA_FIELDS["category"])

    summaries = [None, None, None, None]
    errors    = [None, None, None, None]

    progress_bar = st.progress(0, text="Fetching SLA data from Jira...")

    def _section(msg):
        log_collector.append({"level": "section", "message": msg, "time": datetime.now().strftime("%H:%M:%S")})

    with st.spinner("Checking SLA 1: Time to First Response..."):
        try:
            _section("SLA 1 — Time to First Response")
            summaries[0] = checker.check_first_response()
        except Exception as e:
            errors[0] = str(e)
    progress_bar.progress(25, text="SLA 1 done · Checking SLA 2...")

    with st.spinner("Checking SLA 2: Identification of Resolution..."):
        try:
            _section("SLA 2 — Identification of Resolution")
            summaries[1] = checker.check_identification_resolution_config()
        except Exception as e:
            errors[1] = str(e)
    progress_bar.progress(50, text="SLA 2 done · Checking SLA 3...")

    with st.spinner("Checking SLA 3: Resolution of Config Issues..."):
        try:
            _section("SLA 3 — Resolution of Config Issues")
            summaries[2] = checker.check_resolution_config()
        except Exception as e:
            errors[2] = str(e)
    progress_bar.progress(75, text="SLA 3 done · Checking SLA 4...")

    with st.spinner("Checking SLA 4: Impact Report Delivery..."):
        try:
            _section("SLA 4 — Impact Report Delivery")
            summaries[3] = checker.check_impact_report_delivery()
        except Exception as e:
            errors[3] = str(e)
    progress_bar.progress(100, text="Done!")
    progress_bar.empty()

    # Apply any accumulated exclusions
    excl = st.session_state.excluded_keys
    if excl:
        for s in summaries:
            if s:
                s.results = [
                    r for r in s.results
                    if (r.source_ticket or "").upper() not in excl
                    and (r.target_ticket or "").upper() not in excl
                    and (r.lpm_category or "").upper() not in excl
                ]

    # Pre-fetch fix-version fallback if SLA 4 is empty
    fix_version_data = None
    if summaries[3] is not None and summaries[3].total_count == 0:
        fix_version_data = checker.get_recent_fix_version_lpm_tickets()

    st.session_state.sla_summaries     = summaries
    st.session_state.sla_errors        = errors
    st.session_state.fix_version_data  = fix_version_data
    st.session_state.run_logs          = log_collector
    st.session_state.run_meta          = {
        "user": user_info.get("displayName", jira_email),
        "jira_url": jira_url,
        "date_from_str": date_from_str,
        "date_to_str": date_to_str,
    }

# Show placeholder if no data yet
if "sla_summaries" not in st.session_state:
    st.markdown("---")
    st.markdown("""
<div style='background:linear-gradient(135deg,#ffffff,#f1f5f9);border-radius:14px;padding:32px;text-align:center;border:1px solid #e2e8f0'>
  <div style='font-size:3rem;margin-bottom:12px'>📋</div>
  <h3 style='color:#1e293b;margin:0 0 8px 0'>Ready to run</h3>
  <p style='color:#64748b;margin:0'>Enter your Jira credentials in the sidebar and click <b style='color:#2563eb'>▶ Run SLA Checks</b></p>
</div>
""", unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    with c1: kpi_card("First Response", "2 business days", "Target", C_NEUTRAL)
    with c2: kpi_card("ID Resolution",  "30 business days", "Target", C_NEUTRAL)
    with c3: kpi_card("Config Resolution", "60 business days", "Target", C_NEUTRAL)
    with c4: kpi_card("Impact Report Delivery", "30 business days", "Target", C_NEUTRAL)
    st.stop()

summaries        = st.session_state.sla_summaries
errors           = st.session_state.sla_errors
fix_version_data = st.session_state.get("fix_version_data")
run_logs         = st.session_state.get("run_logs", [])
run_meta         = st.session_state.run_meta

tab_dashboard, tab_log = st.tabs(["📊 Dashboard", "📋 Log"])

# ── Dashboard tab ─────────────────────────────────────────────────────────────
with tab_dashboard:
    st.markdown("---")
    st.markdown(f"""
<div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:4px'>
  <h2 style='margin:0;font-size:1.3rem;color:#1e293b'>Executive Summary</h2>
  <span style='color:#64748b;font-size:0.8rem'>
    Connected as <b style='color:#2563eb'>{run_meta["user"]}</b>
    {"&nbsp;·&nbsp; " + run_meta["date_from_str"] + " → " + (run_meta["date_to_str"] or "today") if run_meta.get("date_from_str") else ""}
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
        st.plotly_chart(overview_bar(summaries), use_container_width=True, config={"displayModeBar": False, "scrollZoom": False, "staticPlot": True}, key="overview_bar")

    st.markdown("---")

    # ── Individual SLA sections ───────────────────────────────────────────────
    SLA_DEFS = [
        (1, "Time to First Response",                         "ACS creation → first public comment (any author)",                      2,  summaries[0], errors[0]),
        (2, "Identification of Resolution for Config Issues", "ACS creation → linked LPM ticket reaches 'Ready for Config'",          30, summaries[1], errors[1]),
        (3, "Resolution of Configuration Issues",             "ACS creation → linked LPM ticket reaches 'Deployed to UAT' / 'Waiting for Client UAT/Signoff' / 'Done'", 60, summaries[2], errors[2]),
        (4, "Impact Report Delivery",                         "SR sub-task (LA Blue) creation → 'impact report' comment on linked ACS ticket",  30, summaries[3], errors[3]),
    ]

    for sla_num, title, caption, target, summary, error in SLA_DEFS:
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
            if fix_version_data:
                st.dataframe(fix_version_data, use_container_width=True, hide_index=True)
            else:
                st.warning("No fix version tickets found either.")
        else:
            display_sla_section(summary, sla_num, title, caption, target, jira_url=jira_url)

        st.markdown("<br>", unsafe_allow_html=True)

# ── Log tab ───────────────────────────────────────────────────────────────────
with tab_log:
    _LEVEL_STYLE = {
        "error":   {"border": "#dc2626", "bg": "#fee2e2", "badge_bg": "#dc2626", "badge_fg": "#ffffff", "label": "ERROR"},
        "success": {"border": "#16a34a", "bg": "#dcfce7", "badge_bg": "#16a34a", "badge_fg": "#ffffff", "label": "OK"},
        "info":    {"border": "#2563eb", "bg": "#dbeafe", "badge_bg": "#2563eb", "badge_fg": "#ffffff", "label": "INFO"},
        "detail":  {"border": "#cbd5e1", "bg": "#f8fafc", "badge_bg": "#94a3b8", "badge_fg": "#ffffff", "label": "DETAIL"},
    }
    _STATUS_ICON  = {"met": "✅", "breached": "🔴", "in_progress": "🟡"}
    _TICKET_RE    = re.compile(r'---.*?([A-Z]+-\d+).*?---')
    _RESULT_RE    = re.compile(r'Result:\s*(met|breached|in_progress)')

    def _entry_html(e):
        s   = _LEVEL_STYLE.get(e["level"], _LEVEL_STYLE["detail"])
        msg = e["message"].strip().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return (
            f'<div style="display:flex;align-items:flex-start;gap:8px;padding:4px 10px;'
            f'border-left:3px solid {s["border"]};background:{s["bg"]};margin:1px 0;border-radius:0 3px 3px 0">'
            f'<span style="color:#94a3b8;font-family:monospace;font-size:0.73rem;white-space:nowrap;padding-top:2px">{e["time"]}</span>'
            f'<span style="background:{s["badge_bg"]};color:{s["badge_fg"]};font-size:0.63rem;font-weight:700;'
            f'padding:1px 5px;border-radius:3px;white-space:nowrap;letter-spacing:0.05em;margin-top:2px">{s["label"]}</span>'
            f'<span style="font-family:monospace;font-size:0.80rem;color:#1e293b;word-break:break-word">{msg}</span>'
            f'</div>'
        )

    if not run_logs:
        st.info("No log data yet. Run SLA Checks to generate a log.")
    else:
        content_logs  = [e for e in run_logs if e.get("level") != "section"]
        total         = len(content_logs)
        error_count   = sum(1 for e in content_logs if e["level"] == "error")
        success_count = sum(1 for e in content_logs if e["level"] == "success")
        info_count    = sum(1 for e in content_logs if e["level"] == "info")

        lc1, lc2, lc3, lc4 = st.columns(4)
        lc1.metric("Total entries", total)
        lc2.metric("Info",          info_count)
        lc3.metric("OK",            success_count)
        lc4.metric("Errors",        error_count)

        st.markdown("---")

        search = st.text_input(
            "Search logs",
            placeholder="Type a ticket number, keyword, or status to filter…",
            help="Searching by ticket key (e.g. ACS-123) shows every line for that ticket.",
        )
        level_filter = st.multiselect(
            "Filter by level",
            options=["INFO", "OK", "DETAIL", "ERROR"],
            default=["INFO", "OK", "DETAIL", "ERROR"],
        )
        level_map      = {"INFO": "info", "OK": "success", "DETAIL": "detail", "ERROR": "error"}
        selected_levels = {level_map[l] for l in level_filter}

        # ── Group entries: section markers → SLA groups, ticket headers → ticket groups ──
        groups        = []
        current_group = None

        for entry in run_logs:
            msg = entry["message"]
            if entry.get("level") == "section":
                if current_group and current_group["entries"]:
                    groups.append(current_group)
                current_group = {"key": None, "label": f"⚙️  {msg}", "entries": [], "is_ticket": False}
            elif _TICKET_RE.search(msg):
                m = _TICKET_RE.search(msg)
                if current_group and current_group["entries"]:
                    groups.append(current_group)
                current_group = {"key": m.group(1), "label": m.group(1), "entries": [entry], "is_ticket": True}
            else:
                if current_group is None:
                    current_group = {"key": None, "label": "⚙️  General", "entries": [], "is_ticket": False}
                current_group["entries"].append(entry)

        if current_group and current_group["entries"]:
            groups.append(current_group)

        # Resolve result label for each ticket group
        for group in groups:
            if not group["is_ticket"]:
                continue
            for entry in group["entries"]:
                rm = _RESULT_RE.search(entry["message"])
                if rm:
                    status = rm.group(1)
                    icon   = _STATUS_ICON.get(status, "📋")
                    label  = status.replace("_", " ").title()
                    group["label"] = f"{icon}  {group['key']}  —  {label}"
                    break
            else:
                group["label"] = f"📋  {group['key']}"

        # ── Filter per group, then render ─────────────────────────────────────
        def _filter_group(group):
            lvl_ok = lambda e: e["level"] in selected_levels
            if not search:
                return [e for e in group["entries"] if lvl_ok(e)]
            # Ticket-key match → show all level-filtered entries for that ticket
            if group["key"] and search.lower() in group["key"].lower():
                return [e for e in group["entries"] if lvl_ok(e)]
            return [e for e in group["entries"] if lvl_ok(e) and search.lower() in e["message"].lower()]

        visible = [(g, _filter_group(g)) for g in groups]
        visible = [(g, ents) for g, ents in visible if ents]

        ticket_count = sum(1 for g, _ in visible if g["is_ticket"])
        entry_count  = sum(len(ents) for _, ents in visible)
        st.caption(f"Showing {ticket_count} tickets · {entry_count} log entries")

        for group, entries in visible:
            if group["is_ticket"]:
                expander_label = group["label"]
            else:
                expander_label = f"{group['label']}  ({len(entries)} entries)"
            with st.expander(expander_label, expanded=False):
                st.markdown(
                    '<div style="border:1px solid #e2e8f0;border-radius:6px;padding:4px">'
                    + "".join(_entry_html(e) for e in entries)
                    + "</div>",
                    unsafe_allow_html=True,
                )

        if not visible:
            st.info("No entries match your search.")
