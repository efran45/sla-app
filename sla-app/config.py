"""
Configuration for Healthcare SLA CLI

To find custom field IDs, look at a Jira ticket's JSON via:
  https://yourcompany.atlassian.net/rest/api/3/issue/ACS-123
"""

# =============================================================================
# JIRA CUSTOM FIELD IDS - UPDATE THESE
# =============================================================================
# "Health plan (migrated)" field on ACS tickets
HEALTH_PLAN_FIELD_ID = "customfield_10151"  # <-- CHANGE THIS

# "category" field on LPM tickets
CATEGORY_FIELD_ID = "customfield_10356"     # <-- CHANGE THIS

# "source of identification" field on ACS tickets
SOURCE_OF_ID_FIELD_ID = "customfield_10358"
# =============================================================================

# Project configuration
PROJECT_A = "ACS"  # Source project (tickets start here)
PROJECT_B = "LPM"  # Target project (linked tickets created here)

# SLA Definitions
SLA_DEFINITIONS = {
    "identification_resolution_config": {
        "name": "Identification of Resolution for Configuration Issues",
        "description": "Time from ACS ticket creation to linked LPM ticket with category 'break fix'",
        "source_project": PROJECT_A,
        "target_project": PROJECT_B,
        "health_plan_field": "Health plan (migrated)",
        "health_plan_value": "BCBSLA",
        "target_category": "break fix",
        "target_days": 30,  # Business days
        "use_business_days": True,
    },
    "resolution_config": {
        "name": "Resolution of Configuration Issues",
        "description": "Time from ACS ticket creation to linked LPM ticket reaching 'ready to build' status",
        "source_project": PROJECT_A,
        "target_project": PROJECT_B,
        "health_plan_field": "Health plan (migrated)",
        "health_plan_value": "BCBSLA",
        "target_status": "ready to build",
        "target_days": 60,  # Business days
        "use_business_days": True,
    },
}

# Jira field mapping (uses the constants above)
JIRA_FIELDS = {
    "health_plan": HEALTH_PLAN_FIELD_ID,
    "category": CATEGORY_FIELD_ID,
    "source_of_identification": SOURCE_OF_ID_FIELD_ID,
}
