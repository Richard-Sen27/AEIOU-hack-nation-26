# Privacy & Compliance Rules — GDPR and California (CCPA/CPRA)

Oct 3, 2026 · @Lorenz

Read this before any frontend, backend or end-to-end task on the Rare Disease Atlas: every feature must satisfy both sections, and where they differ, the stricter rule wins. These are engineering guidelines, not legal advice; have counsel review before a real launch.

## GDPR (EU General Data Protection Regulation)

The atlas processes health and genetic data of EU residents, often about children, so GDPR applies in full and the Article 9 rules for special-category data govern every upload, patient profile and contribution.

### What counts as personal data here

- **Account data:** email, name, ChatGPT or Google identity, ORCID iD, IP addresses, session and log data.
- **Special-category data (Art. 9):** patient profiles, chat messages about symptoms or diagnoses, uploaded documents, extracted findings, patient contributions. Health and genetic data, always.
- **Professional nodes:** researchers and doctors built from public sources are still personal data; Art. 14 (data not collected from the person) applies.
- **Not personal data:** the graph built from public literature and databases, as long as it contains no individual patients.

### Lawful basis

- **Health and genetic data:** explicit consent (Art. 9(2)(a)). MUST be separate for "upload" and "contribute", granular, not bundled with sign-up, and as easy to withdraw as to give (Art. 7(3)). Store consent type, text version and timestamp.
- **Children:** many patients are minors. Accounts are for users aged 16 or older (the strictest age of digital consent in the EU, Art. 8). When a user uploads or describes data about a child, they MUST confirm they hold parental responsibility.
- **Account and core service:** performance of a contract (Art. 6(1)(b)).
- **Security logs and abuse prevention:** legitimate interest (Art. 6(1)(f)).
- **Researcher and doctor nodes:** legitimate interest, limited to public professional information (papers, grants, institution pages, trial listings). Provide a public "about this data" page (Art. 14 notice) and a claim-or-remove flow (right to object, Art. 21).

### Engineering rules from the GDPR principles (Art. 5 and 25)

- **Data minimization:** collect only the fields in `PatientProfile`. Never ask for names, birth dates (age in years or an age range is enough), addresses or patient IDs. Country is optional and used only to find nearby patient groups.
- **Purpose limitation:** user data is used only to find connections for that user. Never for advertising, profiling, analytics resale or model training. Contributions go into the shared graph only with "contribute" consent.
- **Storage limitation:** raw uploads deleted immediately after extraction; anonymous sessions purged after 30 days of inactivity; application logs and traces kept at most 30 days; full-account data kept until the user deletes it or withdraws consent. Keep this retention table in `/docs/retention.md`.
- **Accuracy:** extracted findings are confirmed by the user before use; every profile field is editable (Art. 16).
- **Privacy by default:** every sharing option off by default; nothing public unless the user opts in.
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
| Withdraw consent (Art. 7(3)) | `DELETE /consents/{type}`: stops processing and deletes data held under that consent |
| Object (Art. 21) | Researchers and doctors: claim-or-remove flow for their node |
| Automated decisions (Art. 22) | The atlas makes no decisions with legal or similarly significant effect. It shows information, never a diagnosis or trial eligibility verdict; such questions are labeled "needs expert review" |

### Transparency (Art. 12–14)

- A layered privacy notice in plain language and in the user's language: what is collected, why, legal basis, processors, transfers, retention, rights, contact.
- Just-in-time notices in the upload and contribute dialogs.
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

### Per-feature checklist

Before merging any feature, answer in the PR description:

- [ ] Which personal data does it touch, and is any of it special-category?
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

- At or before collection (sign-up dialog, upload dialog, contribute dialog), show: categories of personal and sensitive information collected, purposes, that nothing is sold or shared, retention period per category, and a link to the privacy policy.
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
