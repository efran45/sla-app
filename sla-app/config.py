"""
Configuration for Healthcare SLA CLI

To find custom field IDs, look at a Jira ticket's JSON via:
  https://yourcompany.atlassian.net/rest/api/3/issue/ACS-123
"""

# =============================================================================
# JIRA CUSTOM FIELD IDS - UPDATE THESE
# =============================================================================
# "Health plan" field on ACS tickets
HEALTH_PLAN_FIELD_ID = "customfield_10151"  # <-- CHANGE THIS

# "category" field on LPM tickets
CATEGORY_FIELD_ID = "customfield_10356"     # <-- CHANGE THIS

# "source of identification" field on ACS tickets
SOURCE_OF_ID_FIELD_ID = "customfield_10358"

# "config done date" field on LPM tickets
CONFIG_DONE_DATE_FIELD_ID = "customfield_10728"
# =============================================================================

# Project configuration
PROJECT_A = "ACS"  # Source project (tickets start here)
PROJECT_B = "LPM"  # Target project (linked tickets created here)
PROJECT_C = "SR"   # Third project (sub-tasks linked to LPM tickets)

# SLA Definitions
SLA_DEFINITIONS = {
    "identification_resolution_config": {
        "name": "Identification of Resolution for Configuration Issues",
        "description": "Time from ACS ticket creation to linked LPM ticket reaching 'ready for config' status",
        "source_project": PROJECT_A,
        "target_project": PROJECT_B,
        "health_plan_field": "Health plan",
        "health_plan_value": "LA Blue",
        "target_status": "ready for config",
        "target_days": 30,  # Business days
        "use_business_days": True,
    },
    "resolution_config": {
        "name": "Resolution of Configuration Issues",
        "description": "Time from ACS ticket creation to linked LPM ticket reaching 'deployed to UAT', 'waiting for UAT signoff', or 'done'",
        "source_project": PROJECT_A,
        "target_project": PROJECT_B,
        "health_plan_field": "Health plan",
        "health_plan_value": "LA Blue",
        "target_statuses": ["deployed to UAT", "waiting for UAT signoff", "done"],
        "target_days": 60,  # Business days
        "use_business_days": True,
    },
    "first_response": {
        "name": "Time to First Response",
        "description": "Time from ACS ticket creation to first public comment by an internal (Atlassian) user",
        "source_project": PROJECT_A,
        "health_plan_field": "Health plan",
        "health_plan_value": "LA Blue",
        "target_days": 2,  # Business days
        "use_business_days": True,
    },
    "impact_report_delivery": {
        "name": "Impact Report Delivery",
        "description": (
            "Time from SR sub-task creation (child of SR ticket linked to LA Blue LPM ticket) "
            "to public comment with impact report attachment on linked ACS ticket"
        ),
        "lpm_project": PROJECT_B,
        "sr_project": PROJECT_C,
        "acs_project": PROJECT_A,
        "health_plan_field": "Health plan",
        "health_plan_value": "LA Blue",
        "target_days": 30,  # Business days
        "use_business_days": True,
    },
}

# Jira field mapping (uses the constants above)
JIRA_FIELDS = {
    "health_plan": HEALTH_PLAN_FIELD_ID,
    "category": CATEGORY_FIELD_ID,
    "source_of_identification": SOURCE_OF_ID_FIELD_ID,
    "config_done_date": CONFIG_DONE_DATE_FIELD_ID,
}
