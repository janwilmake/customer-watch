# HubSpot adapter (CRM: emails, calls, meetings, notes)

Needs: a HubSpot private app token. No MCP server. **Untested against a live portal**: built from
HubSpot's public CRM v3 and v4 API. Please report what works.

## Setup

1. HubSpot → Settings → Integrations → Private Apps → Create. Scopes: `crm.objects.contacts.read`,
   `sales-email-read`, and the calls, meetings and notes read scopes your portal offers.
2. Keep the token in the Keychain: `security add-generic-password -s customer-watch-hubspot -a hubspot -w`
3. In `config.json`: add `"adapters/hubspot"` to `"adapter"`, and
   `"hubspot": {"token": {"keychain": "customer-watch-hubspot"}, "owner_id": "<your owner id>"}`.

## Sources

- Every engagement logged in HubSpot, matched through its associated contacts' emails or the
  customer's name in its title. A `NEW` item has `hubspot_id`; read it in full with HubSpot's MCP
  server or the API.
- When your inbox and calendar already log to HubSpot, this one adapter covers email, calls and
  meetings. Add `adapters/imap` too when not every mail is logged.

## Drafting

HubSpot has no API for a one-to-one email draft. Draft through the IMAP adapter or your mail
connector.
