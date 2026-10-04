# Data Retention

Required by [`compliance.md`](compliance.md) (GDPR Art. 5(1)(e), CCPA notice at collection). Describes what the code does today; update it with every change to storage or deletion.

All user tables live in Postgres under row-level security. Every row references `users.id` with `ON DELETE CASCADE`, so deleting the account deletes everything listed under "Account data".

There are three consents (Art. 9(2)(a)), each with a text version the server pins:

- `health_data`: one consent to process the user's own health and genetic data. Required for chat, saving the patient profile, document upload and confirming or rejecting findings; not for reading, exporting or deleting one's own data. It also covers following diseases and the in-app notifications about them. Withdrawing it (`DELETE /consents/health_data`) stops that processing (running chat turns are stopped first) and deletes the patient profile, chat sessions, messages and running turns, documents, findings, document extraction jobs, followed diseases and notifications. The account, settings, the work details of doctors and researchers with their verification and public card, the `contribute` consent and contributions stay.
- `contribute`: sharing de-identified data with the atlas, a separate purpose. Withdrawing it deletes every contribution.
- `connect`: contact with other people (messaging between patients and verified professionals). Required to start, accept, decline and send; not for reading, hiding, deleting one's own messages, blocking or reporting. Withdrawing it deletes the user's messages and stated age group and closes their conversations; blocks and reports stay until account deletion (reports: at most 12 months).

## Guests

| Data | Where | How long | How it is deleted |
| --- | --- | --- | --- |
| Nothing | — | — | Guests are stateless: no user rows, no cookies besides the strictly necessary sign-in state. Graph search and views read only public graph tables. |

## Account data (signed-in users)

| Data | Where | How long | How it is deleted |
| --- | --- | --- | --- |
| Account: ChatGPT subject ID, e-mail, name, sign-in times | `users` | Until account deletion | `DELETE /me` |
| Settings: role, language, expert mode, 16+ confirmation time, GPC opt-out | `profiles` | Until account deletion | `DELETE /me` |
| Work details of doctors and researchers (optional, self-declared, private): first and last name, up to three institutions, ORCID iD, linked atlas entry | `profiles` | Until the user clears them, switches the role to patient, or deletes the account | `DELETE /me/professional`, `PATCH /me/settings` (role switch to patient), `DELETE /me` |
| Verification of doctors and researchers: method, time, name from ORCID or the review, confirmed ORCID iD, verified atlas link, the operator's reason | `profiles` | Until the work details are cleared, the role changes (any change ends it), the operator revokes it, or the account is deleted. Editing a manually reviewed name or institution ends it | `DELETE /me/professional`, `PATCH /me/settings`, `backend verify-professional --revoke`, `DELETE /me` |
| Manual verification request: institutional e-mail, profile link, request time | `profiles.verification_request` | E-mail and link until the operator decides (then deleted; a rejection keeps only status and times) or the user withdraws it; not stored at all in local demo settings, where the request is approved at once | Operator decision, `DELETE /me/professional/verification-request`, `DELETE /me/professional`, `DELETE /me` |
| Public card settings (off by default): card ID, visible and since when, headline, institutions and atlas entry shown or not, accepts messages from patients | `profiles`; others see the card only through `professional_cards()` while it is verified and switched on | Settings until the work details are cleared, the role switches to patient, or the account is deleted; visibility ends at once when switched off | `PUT /me/professional/card`, `DELETE /me/professional`, `PATCH /me/settings`, `DELETE /me` |
| Followed diseases (atlas disease IDs, follow time, data version) | `follows` | Until the user unfollows, withdraws `health_data` consent, or deletes the account | `DELETE /me/follows/{node_id}`, `DELETE /consents/health_data`, `DELETE /me` |
| Connect age group (18 or older / 16 or 17, self-declared) and when stated | `profiles` | Until corrected, `connect` is withdrawn, or the account is deleted | `PUT /me/connect/age-group`, `DELETE /consents/connect`, `DELETE /me` |
| Conversations: participants, origin, status, display-name snapshots, times | `threads` (both participants can read) | Until 12 months without a message; a deleted account's ID and name are removed at once and the conversation closes | Purged when a participant next reads their conversations and by `backend.cli purge-messages` (daily); `DELETE /me` |
| Messages (body encrypted with `MESSAGE_ENCRYPTION_KEY`) | `messages` (both participants can read) | Until the sender deletes it, withdraws `connect`, deletes the account, or the conversation is purged | `DELETE /me/threads/{id}/messages/{id}`, `DELETE /consents/connect`, `DELETE /me` |
| Read markers, hidden flag, guardian agreement of 16- and 17-year-olds (text version, time) | `thread_reads` (own rows) | As the conversation, or account deletion | As above |
| Blocks (blocked account, name snapshot) | `blocks` (own rows) | Until unblocked or either account is deleted | `DELETE /me/blocks/{id}`, `DELETE /me` |
| Reports (conversation, message, reason, authorization version) | `reports` (own rows) | 12 months, or account deletion | `backend.cli purge-messages`, `DELETE /me` |
| In-app notifications (kind, atlas IDs, data version, read time; no stored text) | `notifications` | 90 days, or earlier on withdrawal of `health_data` consent or account deletion | Purged when the user next reads notifications; `DELETE /consents/health_data`, `DELETE /me` |
| OpenAI tokens (encrypted), scopes, expiry | `openai_tokens` | Until logout, failed refresh or account deletion | `POST /auth/logout` revokes (best effort) and deletes; `DELETE /me` does the same, then cascades |
| Consent records: type, text version, granted and revoked times, child flags | `consents` | Until account deletion (kept after revocation as proof of consent history) | `DELETE /me` |
| Patient profile (diseases, genes, variants, phenotypes, age, country) | `patient_profiles` | Until the user edits it, withdraws `health_data` consent, or deletes the account | `PUT /profile`, `DELETE /consents/health_data`, `DELETE /me` |
| Chat sessions and messages (redacted text only) | `chat_sessions`, `chat_messages` | Until the user deletes the session, withdraws `health_data` consent, or deletes the account | `DELETE /chat/sessions/{id}`, `DELETE /consents/health_data`, `DELETE /me` |
| Running chat turn: redacted message, status steps, extraction results, draft or checked reply (latest LangGraph checkpoint; never raw text, the profile or tokens) | `chat_runs` (one row per running turn); its events also in API process memory | Until the turn ends (reply or failed turn stored, which deletes the row), or the user stops it; events in memory 60 s more. A turn whose API process died is closed the next time the user opens chat | Turn end, `DELETE /chat/runs/{id}`, `DELETE /chat/sessions/{id}`, `DELETE /consents/health_data`, `DELETE /me` (all stop the run first) |
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
| Rate-limit counters (user ID or IP, request counts) | API process memory | At most 1 day (the verification request limit counts per day) | Expire automatically; lost on restart |
| ORCID sign-in state (used state markers; no tokens) and simulated ORCID codes (local demo only) | API process memory | At most 10 minutes | Expire automatically; lost on restart. ORCID access tokens are never stored |
| Public card cache (the visible cards only) | API process memory | Refreshed after every card change, at most 60 seconds old | Replaced on refresh; lost on restart |
| Operator access log for reported conversations (operator, reason, report and conversation IDs; no content) | `admin_access_log` (no API access) | 24 months | `backend.cli purge-messages` |
| Database backups | Postgres backups of the deployment | One backup cycle (≤ 30 days) | Deleted rows disappear when the oldest backup containing them expires |

## Public graph data

Graph tables (`nodes`, `edges`, `evidence`, …) hold public literature and database content and no individual patients. They are replaced on every pipeline load. Researcher and doctor nodes contain only public professional information and can be claimed or removed (Art. 14, 21).
