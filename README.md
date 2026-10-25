# ATS Resume Analyzer & Optimizer

A Streamlit application for local resume/job-description matching, optional
LLM-assisted coaching, candidate history, and admin-only analytics/configuration.
It is a coaching aid, not a hiring decision system or a guarantee of ATS outcomes.

## Run locally

1. Use Python 3.10 or newer, then create and activate a virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. Configure at least one administrator account as described below.
4. Start the app: `streamlit run app.py`

The app creates `data/ats_analyzer.sqlite3` by default. Set
`ATS_DATABASE_PATH` to move the SQLite database. The database stores score
summaries and audit events only; uploaded resume content is not persisted.
Use encrypted storage, backups, access controls, and a managed database before
deploying across multiple app instances.

## Authentication and roles

There are no default passwords. Generate a PBKDF2 hash with:

```powershell
python -c "from auth import hash_password; print(hash_password('replace-with-a-long-unique-password'))"
```

Set `ATS_ADMIN_USERNAME` (optional; defaults to `admin`) and
`ATS_ADMIN_PASSWORD_HASH` to that value. Candidate accounts, and optional
additional admins, are supplied as a JSON object in `ATS_USERS_JSON`:

```json
{
  "candidate1": {
    "password_hash": "pbkdf2_sha256$310000$...$...",
    "role": "candidate"
  }
}
```

Generate a separate hash for every account. Put environment variables in the
hosting platform's secret manager; do not commit them to source control. Admin
and candidate access is enforced by the application router. For internet-facing
production use, put the app behind an identity-aware proxy/SSO and HTTPS, and
use a centrally managed user store and persistent database.

## Optional AI coaching

Set `OPENAI_API_KEY` in the hosting secret manager to enable the opt-in AI
coaching toggle. Resume text and the target job description are sent to the
configured OpenAI API only when the user enables that toggle. The local
keyword/similarity report works without an API key.

## Notes

- PDF uploads are size/page limited and processed in memory.
- Local similarity uses TF-IDF vectors; it is not a semantic embedding model.
- Admin prompt and weights are persisted in the app database and are visible to
  users only through the administrator dashboard.
- Password hashes use PBKDF2-HMAC-SHA256. Streamlit's built-in session mechanism
  is not a substitute for SSO, secure cookie controls, or a production identity
  provider.
