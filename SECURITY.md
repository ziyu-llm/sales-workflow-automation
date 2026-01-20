# Security & Data Handling

- This demo is designed to avoid storing sensitive personal information (PII).
- By default it redacts emails and phone-like strings before writing outputs.
- Recommended: store only redacted excerpts and a hash of the raw input.
- If integrating with external services (CRM, chat apps), ensure secrets are kept in env vars and do not expose admin endpoints to the public internet.
