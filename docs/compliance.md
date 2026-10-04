# Privacy & Compliance Rules — GDPR and California (CCPA/CPRA)

Oct 3, 2026 · @Lorenz

Read this before any frontend, backend or end-to-end task on the Rare Disease Atlas: every feature must satisfy both sections, and where they differ, the stricter rule wins. These are engineering guidelines, not legal advice; have counsel review before a real launch.

## GDPR (EU General Data Protection Regulation)

The atlas processes health and genetic data of EU residents, often about children, so GDPR applies in full and the Article 9 rules for special-category data govern every upload, patient profile and contribution.

### What counts as personal data here

- **Account data:** email, name, ChatGPT or Google identity, ORCID iD, IP addresses, session and log data. For doctors and researchers who add them, the optional work details: first and last name, up to three institutions, ORCID iD and a private link to their own entry in the atlas; and, if they ask for it, the verification record (method, time, the name from ORCID or the review, a confirmed ORCID iD, a manual review request with an institutional e-mail and a profile link, the operator's reason) and the settings of their opt-in public card.
- **Special-category data (Art. 9):** patient profiles, chat messages about symptoms or diagnoses, uploaded documents, extracted findings, patient contributions. Health and genetic data, always.
- **Professional nodes:** researchers and doctors built from public sources are still personal data; Art. 14 (data not collected from the person) applies.
- **Not personal data:** the graph built from public literature and databases, as long as it contains no individual patients.

### Lawful basis

- **Health and genetic data:** explicit consent (Art. 9(2)(a)). One general consent (`health_data`) covers all processing of the user's own health and genetic data for the service: chat messages, the patient profile, uploaded documents and extracted findings, and the diseases the user follows with the in-app notifications about them (a followed disease is health data for every role). A purpose that goes beyond the user's own use MUST have its own separate consent; today that is `contribute` (sharing into the shared graph) and `connect` (contact with other people: messaging between patients and verified professionals, later suggestions and sign-ups). No further consent types. Consent MUST NOT be bundled with sign-up, is asked just in time before the first such processing, and is as easy to withdraw as to give (Art. 7(3)). Store consent type, text version and timestamp.
- **Children:** many patients are minors. Accounts are for users aged 16 or older (the strictest age of digital consent in the EU, Art. 8). When a user uploads or describes data about a child, they MUST confirm they hold parental responsibility.
- **Messaging (`connect`):** a patient or caregiver writes to a verified, visible professional who accepts messages, addressed by card, never by user ID; the first message is a request the professional accepts or declines; professionals can never start a conversation with a patient; at most 5 new conversations per day. At the first connect action the user states an age group (18 or older, or 16 or 17; self-declared, correctable). A user aged 16 or 17 ticks one more required box on their first message in each conversation ("A parent or guardian knows about this and agrees …"), stored with text version and time. Bodies are encrypted with their own key (`MESSAGE_ENCRYPTION_KEY`), plain text only, never logged, never sent to a model, never rewritten. The other side sees only the chosen display name and the text. Withdrawing `connect` deletes the user's messages and age group and closes their conversations; withdrawing `health_data` keeps them.
- **Account and core service:** performance of a contract (Art. 6(1)(b)).
- **Calls (surveys, studies, trials):** performance of a contract (Art. 6(1)(b), publisher terms); no consent type. Only a verified doctor or researcher with a visible card can write one; the Amber team reviews wording, ethics approval and registry number (not scientific quality) through the operator CLI, every action logged in `call_reviews`; the database lets only that review publish (trigger `calls_guard`). Published calls are visible to every signed-in user, never to guests, and nothing about who read a call is stored. A call never offers, promises, sells, supplies, prices or ranks a treatment: a wording check refuses such phrases on submit and again on approval, and calls only point to registry entries ("Ask your doctor whether this trial or study could apply to you"). Readers are not asked for or shown any health data; the disease filter runs in the browser so disease IDs stay out of URLs.
- **Work details of doctors and researchers:** performance of a contract (Art. 6(1)(b)): a feature the user sets up and can delete at any time (`DELETE /me/professional`). No new consent type. The details are self-declared and private to the account: never part of the atlas data, never sent to a model, never logged, and never shown to other users unless the person verifies and switches on the public card (next item). Saving them verifies nothing.
- **Verification and the public card:** performance of a contract (Art. 6(1)(b)); no consent type. Verification is the person's own request: ORCID sign-in (confirms the ORCID iD and the public name on the record, not a medical licence) or a manual review by the Amber team of an institutional e-mail and a public profile page (decided with a logged reason in the operator CLI). The card is a separate switch, off by default, with its own choices (headline, institutions shown or not, atlas entry shown or not, "accepts messages from patients", which lets patients send a message request). Others see a card only while the person is a doctor or researcher, verified and has the switch on; only signed-in users see it; it never shows the e-mail, the ChatGPT identity, a self-declared ORCID iD or an atlas link matched by name. Switching it off, deleting the work details, switching the role to patient or deleting the account removes it at once; a role change between doctor and researcher ends the verification. Withdrawing `health_data` does not touch it.
- **Security logs and abuse prevention:** legitimate interest (Art. 6(1)(f)).
- **Researcher and doctor nodes:** legitimate interest, limited to public professional information (papers, grants, institution pages, trial listings). Provide a public "about this data" page (Art. 14 notice) and a claim-or-remove flow (right to object, Art. 21).

### Engineering rules from the GDPR principles (Art. 5 and 25)

- **Data minimization:** collect only the fields in `PatientProfile`. Health data and the patient profile never ask for names, birth dates (age in years or an age range is enough), addresses or patient IDs. The one exception to the name rule is the optional, private work details of doctors and researchers (see Lawful basis), which are kept apart from the patient profile. Country is optional and used only to find nearby patient groups.
- **Purpose limitation:** user data is used only to find connections for that user. Never for advertising, profiling, analytics resale or model training. Contributions go into the shared graph only with "contribute" consent.
- **Storage limitation:** raw uploads deleted immediately after extraction; anonymous sessions purged after 30 days of inactivity; application logs and traces kept at most 30 days; full-account data kept until the user deletes it or withdraws consent. Keep this retention table in `/docs/retention.md`.
- **Accuracy:** extracted findings are confirmed by the user before use; every profile field is editable (Art. 16).
- **Privacy by default:** every sharing option off by default; nothing public unless the user opts in.
- **Agent state:** a chat turn's saved state (checkpoints) is health data like the chat itself: it lives in a user table under row-level security, holds redacted content only (never raw text, the profile or tokens), is deleted when the turn ends and with the session, the `health_data` consent and the account, and is part of the export while it exists. No third-party checkpoint store; LangSmith tracing (`LANGSMITH_TRACING`) is never configured.
- **Integrity and confidentiality (Art. 32):** TLS everywhere, encryption at rest, row-level security on every user table, service-role key server-side only, least-privilege API keys, Presidio redaction before any LLM call.

### Processors and international transfers (Art. 28 and 44–49)

- Every vendor that touches personal data needs a data processing agreement: Supabase, OpenAI, Vercel, the API host (Railway or Fly), Langfuse.
- Prefer EU hosting: Supabase project in an EU region, Langfuse EU cloud or self-hosted, and OpenAI's zero-data-retention or EU data-residency options where available (verify what your account supports).
- Transfers to US vendors rely on the vendor's EU–US Data Privacy Framework certification or Standard Contractual Clauses; record which one per vendor.
- **Bright Data, web search and PubMed receive no user data.** The gap-search agent builds queries from graph IDs and public terms only, never from profile text or chat messages.
- Never send unredacted documents to any LLM. Langfuse traces store redacted text only.

### User rights as product features (Art. 12–22)

Respond within one month. Signed-in users are verified by their session; never ask for extra identity documents.

| Right | Implementation |
| --- | --- |
| Access and portability (Art. 15, 20) | `GET /me/export`: all user data as machine-readable JSON |
| Rectification (Art. 16) | Edit profile and findings in the app |
| Erasure (Art. 17) | `DELETE /me` with cascade; contributions removed from the shared graph; deleted from backups within the backup cycle |
| Withdraw consent (Art. 7(3)) | `DELETE /consents/{type}`: stops processing and deletes data held under that consent (`health_data`: profile, chats including running turns and their checkpoints, documents, findings, followed diseases and notifications; `contribute`: contributions; `connect`: the user's messages and age group, their conversations close). The public card is not held under a consent: it is withdrawn with its own switch (`PUT /me/professional/card`) |
| Object (Art. 21) | Researchers and doctors: claim-or-remove flow for their node. Linking one's account to an atlas entry in the work details is not a claim and proves nothing; any change to a node still goes through this flow |
| Automated decisions (Art. 22) | The atlas makes no decisions with legal or similarly significant effect. It shows information, never a diagnosis or trial eligibility verdict; such questions are labeled "needs expert review" |

### Transparency (Art. 12–14)

- A layered privacy notice in plain language and in the user's language: what is collected, why, legal basis, processors, transfers, retention, rights, contact.
- Just-in-time notices in the health-data consent dialog (shown before the first chat message, profile save or upload) and the contribute dialog.
- Make it unmistakable that users are talking to an AI system. The EU AI Act's transparency duty for AI systems that interact with people (Art. 50) applies alongside GDPR.

### Security incidents (Art. 33–34)

- A personal-data breach is reported to the supervisory authority within 72 hours (for a team established in Austria, the Austrian Data Protection Authority, DSB), and to affected users without undue delay when the risk is high.
- Keep a one-page incident runbook in `/docs/incident.md`: who decides, how to contain, how to notify.

### Documentation

- **DPIA (Art. 35):** large-scale processing of health data with new technology requires a data protection impact assessment. Keep a short one in `/docs/dpia.md`.
- **Record of processing (Art. 30):** `/docs/ropa.md` listing each processing purpose, data categories, legal basis, recipients, transfers and retention.

### MUST NOT

- Put health data in URLs, query strings, analytics events, logs, error messages or exception trackers.
- Use third-party trackers, ad pixels or non-essential cookies (aim for no cookie banner because nothing optional is set).
- Train or fine-tune any model on user data, or allow vendors to.
- Store raw uploaded files.
- State or imply a diagnosis.
- Read or reuse another user's data, including in admin tooling, without a logged reason.
- Let professionals list, search or count patients. Professionals have no API that returns patient rows or counts; cards exist for verified doctors and researchers only.
- Read messages, except a conversation a participant reported (the report is the authorization), through `backend.cli read-reported-thread` with the operator's name and reason written to `admin_access_log` first. No model, job or tool reads message bodies.
- Publish a call that offers, promises, prices or promotes a treatment, or publish any call without the operator's logged review.
- Show anything on a public card that the person did not switch on, or show a card that is not both verified and switched on.
- Let the demo shortcuts run anywhere but a local demo. With `ORCID_MOCK` on (refused unless API and frontend are loopback), ORCID sign-in is simulated and manual verification requests are approved at once; anything verified this way is labelled "demo, verification simulated".

### Per-feature checklist

Before merging any feature, answer in the PR description:

- [ ] Which personal data does it touch, and is any of it special-category?
- [ ] Who else can see it, and did the person switch that on?
- [ ] What is the legal basis, and is consent checked where required?
- [ ] Is every collected field necessary?
- [ ] Where is it stored, for how long, and is it covered by the retention table?
- [ ] Which vendors receive it, and is it redacted first?
- [ ] Is it included in export and deleted by account deletion?
- [ ] Is it protected by RLS, with a test proving user A cannot read user B's data?

## California: CCPA as amended by CPRA (plus CMIA)

For California users, the CCPA/CPRA governs personal information and treats health and genetic data as "sensitive personal information"; a product built to the GDPR rules above already meets most of it, so the additions below are mainly notices, opt-out signals and response times.

### Does it apply?

- The CCPA applies to for-profit businesses that meet a threshold, roughly: annual gross revenue above about $25M (inflation-adjusted), or buying, selling or sharing personal information of 100,000+ California consumers or households, or earning half or more of revenue from selling or sharing it (figures approximate; check the current values).
- A hackathon prototype is likely below these thresholds. Build as if covered anyway: partners, funders and acquirers will expect it, and retrofitting is expensive.
- **CMIA (California Confidentiality of Medical Information Act):** businesses offering software designed to maintain medical information so consumers can manage their own health information can be treated as health-care providers under the CMIA. Treat uploaded reports, findings and patient profiles as medical information: no disclosure to anyone without the user's written authorization. Have counsel confirm whether the CMIA applies.
- HIPAA most likely does not apply (the atlas is not a covered entity or business associate), but do not claim "HIPAA compliant" in any copy.

### Sensitive personal information

- Health data, genetic data, account login credentials and precise geolocation are sensitive personal information.
- Use it only to provide the service the user asked for (finding connections, explanations, document extraction). Keeping use to that purpose means the right to limit its use is satisfied by design; document this in the privacy policy.
- Never collect precise geolocation; country or region typed by the user is enough.

### No selling, no sharing

- Never sell personal information and never "share" it for cross-context behavioral advertising: no ad pixels, retargeting, data brokers or lookalike audiences.
- State this plainly in the privacy policy.
- Honor the **Global Privacy Control** signal: read the `Sec-GPC: 1` request header (and `navigator.globalPrivacyControl` in the browser), record it on the profile, and treat it as an opt-out of sale and sharing.
- Vendors (Supabase, OpenAI, Vercel, API host, Langfuse) act as service providers with written contracts that restrict them to the business purpose. The same no-user-data rule applies to Bright Data and web search.

### Notice at collection

- At or before collection (sign-up dialog, health-data consent dialog, contribute dialog), show: categories of personal and sensitive information collected, purposes, that nothing is sold or shared, retention period per category, and a link to the privacy policy.
- The privacy policy describes California rights and how to use them, and is reviewed at least every 12 months.

### Consumer rights as product features

| Right | Implementation |
| --- | --- |
| Know and access | `GET /me/export`, including specific pieces of information |
| Delete | `DELETE /me` with cascade |
| Correct | Edit profile and findings in the app |
| Opt out of sale or sharing | Nothing is sold or shared; GPC is honored and recorded |
| Limit use of sensitive information | Satisfied by design: used only to provide the requested service |
| Non-discrimination | Identical service whether or not a user exercises any right |

- Accept requests in the app and via a privacy email address; support authorized agents.
- Confirm receipt within 10 business days and respond within 45 days (one 45-day extension with notice).
- Signed-in users are verified by their session; never demand extra personal information to verify.

### Minimization and retention

- Collection and use must be reasonably necessary and proportionate to the purpose: the GDPR minimization rules above satisfy this.
- Disclose retention periods per category; use the same retention table (`/docs/retention.md`).

### Security and breaches

- Maintain reasonable security (the GDPR Art. 32 measures above). A breach of health or genetic data caused by inadequate security can expose the business to a private right of action with statutory damages under the CCPA.
- California's breach-notification law requires notifying affected residents without unreasonable delay, and the Attorney General when more than 500 California residents are affected. Extend the incident runbook to cover both.

### Automated decisions and risk assessments

- Newer CPPA regulations add risk assessments for processing sensitive personal information and rules for automated decision-making technology used for significant decisions, including about healthcare services.
- The atlas provides information, not decisions: no diagnosis, no trial-eligibility verdicts, no ranking of who receives care. Keep it that way, and reuse the DPIA as the risk assessment.

### Minors

- Never sell or share any data, which also covers the opt-in rule for users under 16. Data about children entered by parents is sensitive personal information and medical information, handled with the same rules.

### Where California differs from GDPR

Follow the stricter column for each row.

| Topic | GDPR | California |
| --- | --- | --- |
| Legal basis | Explicit consent for health data | Notice at collection + opt-outs; CMIA authorization before any disclosure |
| Response time | One month | Acknowledge in 10 business days, respond in 45 days |
| Browser opt-out signal | Not required | Honor Global Privacy Control |
| Breach notice | Authority within 72 hours; users if high risk | Affected residents without unreasonable delay; Attorney General if more than 500 residents |
| Sensitive data | Processing prohibited unless an Art. 9 exception applies | Use limited to providing the requested service |
| Children | Age of digital consent up to 16 | Opt-in before selling or sharing data of under-16s |

### MUST NOT (in addition to the GDPR list)

- Label the product "HIPAA compliant" or imply medical certification.
- Use dark patterns in consent or rights flows: opting out or deleting must take no more steps than opting in.
- Disclose any medical information to a third party (including patient groups or researchers) without the user's explicit authorization for that disclosure.
