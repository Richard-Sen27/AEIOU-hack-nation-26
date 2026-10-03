# Data Retention

Required by [`compliance.md`](compliance.md) (GDPR Art. 5(1)(e), CCPA notice at collection). Describes what the code does today; update it with every change to storage or deletion.

All user tables live in Postgres under row-level security. Every row references `users.id` with `ON DELETE CASCADE`, so deleting the account deletes everything listed under "Account data".

There are two consents (Art. 9(2)(a)), each with a text version the server pins:

- `health_data`: one consent to process the user's own health and genetic data. Required for chat, saving the patient profile, document upload and confirming or rejecting findings; not for reading, exporting or deleting one's own data. Withdrawing it (`DELETE /consents/health_data`) stops that processing and deletes the patient profile, chat sessions and messages, documents, findings and document extraction jobs. The account, settings, the `contribute` consent and contributions stay.
- `contribute`: sharing de-identified data with the atlas, a separate purpose. Withdrawing it deletes every contribution.

## Guests

| Data | Where | How long | How it is deleted |
| --- | --- | --- | --- |
| Nothing | — | — | Guests are stateless: no user rows, no cookies besides the strictly necessary sign-in state. Graph search and views read only public graph tables. |

## Account data (signed-in users)

| Data | Where | How long | How it is deleted |
| --- | --- | --- | --- |
| Account: ChatGPT subject ID, e-mail, name, sign-in times | `users` | Until account deletion | `DELETE /me` |
| Settings: role, language, expert mode, 16+ confirmation time, GPC opt-out | `profiles` | Until account deletion | `DELETE /me` |
| OpenAI tokens (encrypted), scopes, expiry | `openai_tokens` | Until logout, failed refresh or account deletion | `POST /auth/logout` revokes (best effort) and deletes; `DELETE /me` does the same, then cascades |
| Consent records: type, text version, granted and revoked times, child flags | `consents` | Until account deletion (kept after revocation as proof of consent history) | `DELETE /me` |
| Patient profile (diseases, genes, variants, phenotypes, age, country) | `patient_profiles` | Until the user edits it, withdraws `health_data` consent, or deletes the account | `PUT /profile`, `DELETE /consents/health_data`, `DELETE /me` |
| Chat sessions and messages (redacted text only) | `chat_sessions`, `chat_messages` | Until the user deletes the session, withdraws `health_data` consent, or deletes the account | `DELETE /chat/sessions/{id}`, `DELETE /consents/health_data`, `DELETE /me` |
| Raw uploaded files | Process memory only, never on disk or in the database | Until extraction finishes or fails (job timeout) | Reference dropped in `finally`; `documents.raw_deleted_at` records the time |
| Document metadata (status, type, page count; no file name) | `documents` | Until the user deletes the document, withdraws `health_data` consent, or deletes the account | `DELETE /documents/{id}`, `DELETE /consents/health_data`, `DELETE /me` |
| Extracted findings (redacted snippets) and extraction jobs | `findings`, `jobs` | As documents | As documents |
| Gap-search jobs (public graph terms only) | `jobs` | Until account deletion | `DELETE /me` |
| Contributions (de-identified phenotype profiles, assets, candidate edges) | `contributions`; visible to others only through `shared_contributions()` while the `contribute` consent is active, without user ID | Until the user deletes it, withdraws `contribute` consent, or deletes the account | `DELETE /contributions/{id}`, `DELETE /consents/contribute`, `DELETE /me` |
| Edge flags (edge ID, short screened reason) | `edge_flags`; others see only the open-flag count per edge | Until account deletion | `DELETE /me` |

## Operational data

| Data | Where | How long | How it is deleted |
| --- | --- | --- | --- |
| Application logs (no user content, IDs or tokens; error types only) | Container stdout, collected by the host | At most 30 days | Host log rotation; must be configured to ≤ 30 days on the deployment platform |
| LLM traces (redacted text only) | Self-hosted Langfuse, off unless configured | At most 30 days | Langfuse data retention set to ≤ 30 days |
| Rate-limit counters (user ID or IP, request counts) | API process memory | At most 1 hour | Expire automatically; lost on restart |
| Database backups | Postgres backups of the deployment | One backup cycle (≤ 30 days) | Deleted rows disappear when the oldest backup containing them expires |

## Public graph data

Graph tables (`nodes`, `edges`, `evidence`, …) hold public literature and database content and no individual patients. They are replaced on every pipeline load. Researcher and doctor nodes contain only public professional information and can be claimed or removed (Art. 14, 21).
