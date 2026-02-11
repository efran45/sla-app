# Healthcare SLA CLI

Command-line tool for monitoring healthcare SLA compliance from Jira.

## SLA Monitored

### Identification of Resolution for Configuration Issues
- **Start**: Ticket created in ACS project with "Health plan (migrated)" = "BCBSLA"
- **Stop**: Linked ticket created in LPM project with category = "break fix"
- **Target**: 30 business days

## Setup

```bash
cd ~/Desktop/healthcare-sla-cli
pip install -r requirements.txt
```

## Usage

Just run:

```bash
python main.py
```

The program will:
1. Prompt for your Jira credentials
2. Test the connection
3. Help you discover the custom field IDs (first time only)
4. Save your settings for next time (API token is never saved)
5. Display the SLA results

That's it - no config files to edit, no environment variables to set.

## Getting Your API Token

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Give it a name and copy the token
4. Paste it when prompted
