# smsf-hub
Enterprise SMSF Audit Verification &amp; Analytics Engine
## Required secrets (.streamlit/secrets.toml)
GEMINI_API_KEY = "..."
SUPABASE_URL = "..."
SUPABASE_KEY = "..."

[gcp_service_account]
textkey = "<GCP service account JSON as a string>"

## Backends
- Supabase tables: property_register, unlisted_register
- Supabase storage bucket: pdfs (public)
- Firestore collection: type2_reports
