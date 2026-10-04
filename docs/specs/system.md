# Amber — Rare Disease Atlas: System Spec

Source of truth for the product, frontend, backend, pipeline and database. Converted from the team's "AEIOU Ideas" doc. The agent design in [`agent.md`](agent.md) follows this document; where they differ, this one wins. Privacy rules are in [`../compliance.md`](../compliance.md).

## Challenge 05: AI Atlas for the World's Rare Diseases

Hack-Nation 7th Global AI Hackathon, supported by OpenAI and the Buffalo Initiative. Track prizes require using OpenAI models or tools.

### Problem

- About 10,000 rare diseases affect 350M people, and fewer than 5% have an approved treatment.
- Relevant knowledge is scattered across papers, databases, trials and patient groups.
- Patient groups rebuild registries and models that already exist elsewhere.
- Organizing by disease name hides shared mechanisms: different genes can disrupt the same pathway, and one gene can cause different effects.

### What to build

A knowledge graph whose nodes are diseases, genes and variants, mechanisms, phenotypes, patient groups, papers, trials, funding and research assets. Every edge is sourced and carries a confidence level. LLMs extract and reconcile the data, graph analytics clusters diseases by mechanism and phenotype rather than by name, and a patient-friendly UI sits on top.

### Questions it answers for a patient leader

1. Who shares our disease characteristics?
2. What useful work already exists (registries, models, studies)?
3. What should we do together next?

### Modules

- **Graph builder:** pulls from OMIM, ClinVar, HPO, MONDO, PubMed, ClinicalTrials.gov, NIH RePORTER, NORD and Orphanet. Resolves synonyms to stable IDs and records source, date and confidence for each relationship.
- **Trust layer:** shows the source of every edge, separates observed links from inferred ones, and surfaces contradicting findings. If there is no supported route, it says so and names the missing evidence.
- **Action layer:** finds mechanistic overlap, assets that can be shared (registries, natural history studies, models, biomarkers), and researchers or funders that two unrelated communities already have in common.

### Personas

- **Maria, patient-group leader (main persona):** needs related clusters, reusable assets, partners and a next experiment.
- **Devon, newly diagnosed caregiver:** needs their exact patient community, or the closest related ones, in plain language.
- **Priya, biotech scout:** needs a ranked list of disease clusters her therapeutic mechanism could treat.
- **Dr. Osei, academic researcher:** needs to find others working on the same mechanism under different gene names.

### UX principles

- One global search: disease, gene, symptom, patient group or mechanism all open the same graph.
- Summary first, detail on click.
- Every edge shows its source, relationship type, confidence and contradicting evidence.
- An action view that separates viable leads from unsupported links.

### 24-hour goal

One complete journey from a disease, to a cited connection, to a shared action, plus a case for how this speeds up a treatment milestone 10× and what still needs validation.

### Judging criteria

- **Graph quality:** node and edge design, defensible clustering, counterexamples, handling of uncertainty.
- **Evidence integrity:** sourced, cross-checked claims that separate data from hypotheses.
- **Patient progress:** a family moves from isolated diagnosis to collaboration, reusable asset and next milestone.
- **10× impact:** current timeline versus the proposed route, with assumptions.
- **Ambition and product craft:** an intuitive experience for collaboration across communities.

### Deliverables

- Working prototype that judges can search and explore live.
- Source code repository with a README covering architecture and how to reproduce the dataset.
- Team video and a 1-minute walkthrough of one family's journey through the graph.

## Tech stack

Everything is **dockerized**. Initial development runs everything locally via docker compose.

| Area | Choice |
| --- | --- |
| Frontend | Next.js, [shadcn/ui](https://ui.shadcn.com/), [Aceternity UI](https://ui.aceternity.com/components) |
| Visualization | Zoomed out (Atlas): Sigma.js · Disease view: Cytoscape.js · Disease path: React Flow + Framer Motion / GSAP |
| Accessibility | React Aria, `@react-aria/live-announcer` |
| Frontend ↔ API | Hey API (generated TypeScript client from the FastAPI OpenAPI spec) |
| Backend | FastAPI + Pydantic |
| Ingestion pipeline | Typer (CLI), aiolimiter + tenacity (rate limiting, retries), pronto + pyhpo + Entrez (biomedical parsing), polars (data), httpx + hishel (HTTP + cache) |
| AI layer | openai, Langfuse, textstat |
| Database | Postgres + pgvector (no Supabase; auth in FastAPI, RLS in Postgres) |

**Login with ChatGPT** is the only sign-in method. It is used for identity *and* to bill OpenAI API usage to the signed-in user's own ChatGPT plan; that is the main reason for using it. Guests can explore the graph but get no agent features (see Sign-in).

## Frontend

### Chat-based input for symptoms and disease

**What the user sees.** One input box on the landing page: *"Tell us about the diagnosis, a gene, or the symptoms, in your own words. Or drop a report here."* They can type the way they'd text someone, for example:

> "My daughter is 2, diagnosed with STXBP1 last month. Lots of seizures, not walking yet, no problems with eating."

**After the input:** an interactive graph (symptoms, similar diseases, disease communities, doctors, researchers).

### Hierarchies: zoom levels within the graph

Every node is visible to every user, and you can follow any connection from anywhere. Clicking a hospital shows its teams and doctors; clicking a doctor shows their studies. Nothing is collapsed away or locked behind a role. These are the main chains of connections in the graph:

- **Biology:** mechanism cluster → pathway → gene → variant → disease → symptoms
- **Research:** research field → funded program/grant → lab/research group → researcher → papers and claims
- **Clinical:** reference network (e.g. European Reference Networks) → hospital / center of expertise → department or team → doctor → clinical studies
- **Community:** umbrella organization (EURORDIS, NORD) → patient organization → registry / natural history study

**The Atlas enters the graph through a tree.** The Amber logo sits in the middle as a hub, with one tree per category around it, clockwise from the top: researchers, hospitals & universities, literature, community, pathways, genes, diseases, symptoms, doctors. Every node is always visible and appears exactly once; the trees are never collapsed. Only tree lines are drawn by default. Clicking a node draws its real connections and opens its summary. The tree is navigation only: it gives every node a place to be found and does not change how nodes are connected. The chains above are followed along the real connections and through the summary panel, not along the tree.

**The role decides where you start and how things are explained, never what you can see:**

- **Patients** start at their disease, with similar diseases and patient communities highlighted, explained in plain language.
- **Doctors** start with the symptom profile, with centers of expertise, clinical studies and variant classifications highlighted, explained in clinical terms.
- **Researchers** start with mechanism clusters, with variants, pathways, papers and funding highlighted, explained technically with IDs shown.
- **Guests** start with a guided tour in very simple language. They can explore everything but have no agent features (see Sign-in).

In the Atlas, patients and researchers start framed on the Diseases tree, doctors on the Symptoms tree, guests on the whole map.

### Atlas view

- **Map:** the hub and the nine trees, with positions from the API (see Graph service). Hovering a node shows its label and its line back to the hub, never its connections. Clicking an entity draws its real connections (dashed when inferred, flagged when under review) and dims the rest; clicking a group highlights its branch; clicking the logo resets the view. Filters choose which connection families are drawn on click and hold the key.
- **Search bar** over the map ("Search the map", `/` focuses it): matches every tree node, groups included, with the branch it sits in. Text that looks like a name also runs the synonym search (`GET /search`); free text is never sent there and never put into a URL. It is offered to Dr. Wu instead.
- **List:** an outline of the same trees as an ARIA tree (arrow keys, Home/End, Enter, typeahead, a filter box). It is the accessible alternative to the canvas, and here branches can be opened and closed.
- **Summary panel** on the right (a bottom sheet on mobile): for an entity, its place in the tree, a headline and its connections grouped by type (researchers, doctors, papers, trials, hospitals and universities, patient groups, genes, symptoms, similar conditions, …), each with the chain it is reached by, data vs. hypothesis and review flags. Picking an item selects it on the map and draws that chain. **Write a summary** streams a written summary of these connections from `POST /explain` (cached ones for anyone, new ones signed in). For a group, the panel explains how it was formed and lists its children.
- **Dr. Wu dock** in the bottom-left corner: guests see the sign-in offer; signed-in users chat with Dr. Wu under the same `health_data` consent as the chat page. The nodes his reply points to are highlighted and framed on the map and listed as "Dr. Wu found N". What the user typed and the found node IDs stay in memory only: never in the URL, never in browser storage.

**How the trees are grouped.** Every level below a category comes from stored data; a node that lacks what a level needs goes into a "… not recorded" group, nothing is dropped, and a group with more than 30 entries is split into alphabetical ranges. Three groupings are choices rather than facts, and the group panel says so:

- **Diseases** are grouped by the computed mechanism clusters (Stage 5), which are inferred.
- **Hospitals & universities** are one tree, split by keywords in the institution's name into hospitals and clinics (checked first, so "University Hospital …" counts as clinical), universities and research institutes, and other organisations, then by country. The data has no hospital or university type.
- **Symptoms** follow the HPO classification (organ system, then the HPO hierarchy with one parent per term) when phenotype nodes carry `attrs.hpo_lineage`. Without it they fall back to one "Classification not loaded" group in alphabetical ranges; the pipeline does not write `hpo_lineage` yet.

### Handling uncertainty

If a variant is a VUS (variant of uncertain significance), show that clearly: *"This result is uncertain. Discuss it with a genetic counselor before acting on it."* This doubles as an example of the "clear treatment of uncertainty" criterion.

### File dump for findings or other documents

1. **Upload** (PDF, image, DOCX, text) into a drop zone that's also available inside the chat.
2. **Text extraction** with the tools listed under Backend services → Documents.
3. **Personal data redaction.** Names, birth dates, addresses and patient IDs are removed with **Microsoft Presidio** *before* anything is sent to an LLM. For photos: local OCR first, then redact, then LLM, so the raw image never leaves the server.
4. **Document classification:** genetic report, clinical letter, research paper, or registry/study document.
5. **Structured extraction** with OpenAI Structured Outputs. Genetic report: gene, variant (HGVS notation), zygosity, classification (pathogenic / likely pathogenic / VUS), test date. Clinical letter: diagnoses and symptoms mapped to HPO.
6. **Findings review screen.** Each extracted item is shown next to the highlighted snippet in the original document it came from. The user confirms or rejects each one before it goes into the profile. Nothing is used unconfirmed.
7. **Merge into the profile**, then into the graph query.

## Backend

The backend has two halves: an offline pipeline that builds a sourced knowledge graph for one disease cluster, and a FastAPI service that serves that graph, explains it per user role, and handles chat, document uploads and sign-in.

### Architecture

An offline pipeline builds the graph; FastAPI serves it live.

```
Offline pipeline · make all
  Data sources                         Pipeline + Postgres (psql)              Snapshot
  MONDO, HGNC, HPO, ClinVar,     ──▶   fetch, resolve, LLM extract,     ──▶   Parquet + manifest
  PubMed, trials, Bright Data          cluster, validate                      data_version
                                                                                  │ load
Live service · per request                                                        ▼
  Next.js frontend               ◀──▶  FastAPI services                 ◀──▶  Postgres + pgvector
  graph views, chat,                   search, path, explain, chat,           graph + evidence tables,
  uploads, sign-in                     documents, gap agent, auth             user tables with RLS
                                         ▲                    │
                               callback  │                    │ LLM calls
  Sign in with ChatGPT ──────────────────┘                    ▼
  OIDC + PKCE                                              OpenAI API
                                                           extract, explain, agent
```

### Guiding principles

- **Provenance first.** Every edge carries its sources, confidence and an observed/inferred label. Nothing is stored without a source.
- **Precompute everything possible.** Extraction, clustering, layouts and demo-path explanations run offline. Only search, chat, uncached explanations, uploads and the gap agent run live.
- **One graph, four lenses.** Guest, patient, doctor and researcher see the same evidence, explained differently. The role changes presentation, never the facts.
- **Nothing unconfirmed reaches a profile.** Findings from chat or documents are confirmed by the user first.
- **Nothing unverified becomes trusted evidence.** Agent findings and user contributions stay `pending_review` or `patient_reported`.
- **Privacy by default.** Raw uploads are deleted after extraction, personal data is redacted before any LLM call, and every user-owned row is protected by row-level security.

## Ingestion pipeline

Eight stages, each a `make` target and a Typer command, idempotent and cached, so the README's "reproduce the dataset" is one command.

### Stage 0: Scope

`seeds.yaml` lists the seed diseases and genes of the chosen cluster plus expansion rules, for example "include diseases within 2 hops via shared gene, shared pathway, or HPO similarity above a threshold." Scaling up later means editing this file only.

### Stage 1: Fetch

Every connector implements `fetch()` and writes to `data/raw/<source>/` with a metadata record: URL, retrieval timestamp, SHA-256, source version. All HTTP goes through `httpx` with the `hishel` cache and an `aiolimiter` rate limit; `tenacity` retries transient failures.

| Connector | Pulls | Access |
| --- | --- | --- |
| `mondo` | `mondo.json`: disease IDs, synonyms, cross-references | Public download |
| `hgnc` | Complete gene set: symbols, aliases, previous symbols | Public download |
| `hpo` | `hp.json`, `phenotype.hpoa`, `genes_to_phenotype.txt` | Public download |
| `clinvar` | `variant_summary.txt.gz`, filtered to genes in scope | Public FTP |
| `clingen` | Dosage sensitivity and gene–disease validity CSVs | Public download |
| `reactome` / `go` | Gene → pathway mappings | Public download |
| `orphanet` | Open scientific files: gene associations, phenotypes, epidemiology | Public, CC BY 4.0 |
| `pubmed` | Per gene/disease search → abstracts, authors, affiliations | E-utilities + free NCBI key |
| `clinicaltrials` | Studies by condition: status, design, eligibility, locations, investigators | REST API v2 |
| `reporter` | Grants by gene/disease terms: PIs, institutions, abstracts | REST API, ~1 req/s |
| `patient_orgs` | Bright Data SERP queries → page fetch → `trafilatura` clean text | Bright Data |
| `omim` (optional) | `genemap2`, `morbidmap` | Needs registered key |

### Stage 2: Normalize and resolve identities

- Parse everything into Parquet tables with standard IDs: `MONDO:`, `HGNC:`, `HP:`, `PMID:`, `NCT`.
- Map OMIM and Orphanet IDs to MONDO through MONDO's cross-references; map gene names and aliases to HGNC.
- Build one `synonyms` table holding every name variant for every node.
- **LLM-assisted linking for leftovers:** generate candidates by trigram and embedding similarity, then the model picks one candidate or "none" via Structured Outputs. Accept above a threshold; log every decision.

### Stage 3: LLM extraction

- **From abstracts:** entities and relations from the fixed relation enum, each with `quote` (exact supporting span), `claim_type` (patient observation, experimental, review, hypothesis), `polarity` (supports, contradicts) and `confidence`.
- **Quote verification:** programmatically check that every `quote` occurs in the source text; reject the edge otherwise.
- **Investigators come from PubMed metadata**, never from the model.
- **From patient org pages:** organization name, diseases served, country, registry yes/no, natural history study yes/no, contact URL, always with the source URL.
- Use a small model for bulk extraction with async calls and a concurrency limit. The Batch API is cheaper but can take up to 24 hours, so use it only if extraction starts early.

### Stage 4: Build the graph

Evidence for the same relation merges into one edge with many evidence rows. Each evidence item gets a tier weight: curated database 0.9, peer-reviewed primary 0.7, review 0.5, preprint 0.4, LLM-inferred 0.3, patient-reported 0.2.

$$
\text{confidence} = 1 - \prod_{i \in \text{supporting}} (1 - w_i) \; - \; p \cdot n_{\text{contradicting}}
$$

The result is clamped to 0–1 and shown in the UI as High / Medium / Low, with the breakdown on click.

### Stage 5: Analytics

- **Symptom similarity:** `pyhpo` best-match-average similarity between diseases. Keep the top-k above a threshold as `similar_symptoms` edges, storing the shared HPO terms and their specificity.
- **Mechanism features per gene:** share of pathogenic ClinVar variants that are truncating vs. missense, ClinGen haploinsufficiency score, pathway memberships. These produce `shared_pathway`, `same_gene_same_mechanism` and `same_gene_different_mechanism` edges, labeled `inferred`, with their features stored.
- **Research overlap:** shared authors or PIs across diseases produce `shared_researcher` edges.
- **Clustering:** Leiden (`igraph` + `leidenalg`) on the combined weighted similarity graph. The model writes each cluster's label from members' shared genes and pathways, marked inferred.
- **Layout and centrality:** precompute ForceAtlas2 positions for the ring views and the old whole-graph Atlas layout, plus centrality scores. The Atlas view no longer draws these positions: its tree layout is computed by the API (see Graph service).

### Stage 6: Validate

The build fails unless all checks pass:

- Every edge has at least one evidence row; no orphan nodes.
- Quote-verification pass rate and rejection counts are reported.
- A golden set of known facts exists (e.g. SCN1A → Dravet syndrome).
- A known counterexample holds: SCN2A gain- and loss-of-function diseases do not share a mechanism cluster.

### Stage 7: Load and snapshot

Load into Postgres, then export a snapshot (Parquet + manifest with source versions, hashes, counts and `data_version`). Pre-generate explanations for the demo paths in every role and language you will show.

## Graph data model

A fixed set of node types and relation types, shared as enums between pipeline, API and frontend.

**Node types:** disease, gene, variant, mechanism, pathway, phenotype, paper, claim, researcher, doctor, institution, network, grant, trial/study, patient organization, registry, cluster. Individual patients are never nodes.

**Relation types**

| Family | Relation | From → to |
| --- | --- | --- |
| Biology | `caused_by_variant_in` | disease → gene |
| Biology | `acts_via` | gene → mechanism (loss of function, gain of function, dominant-negative) |
| Biology | `participates_in` | gene → pathway |
| Biology | `has_phenotype` | disease → phenotype, with frequency |
| Disease–disease (DNA) | `same_gene_same_mechanism` | disease ↔ disease |
| Disease–disease (DNA) | `same_gene_different_mechanism` | disease ↔ disease (the counterexample case, e.g. SCN2A, SCN1A) |
| Disease–disease (DNA) | `shared_pathway` | disease ↔ disease |
| Disease–disease (symptoms) | `similar_symptoms` | disease ↔ disease, with shared HPO terms; labeled "similar experience, possibly different cause" |
| Disease–disease (research) | `shared_researcher` | disease ↔ disease |
| Research | `asserts` | paper → claim |
| Research | `authored` | researcher → paper |
| Research | `pi_of` | researcher → grant |
| Research | `funds_research_on` | grant → disease |
| Community and clinical | `serves` | organization → disease |
| Community and clinical | `runs` | organization → registry or study |
| Community and clinical | `studies` | trial → disease |
| Community and clinical | `investigator_of` | doctor → trial |
| Community and clinical | `affiliated_with` | person → institution |

**Edge attributes:** `id`, `source_id`, `target_id`, `relation`, `family` (dna / symptoms / research / community), `confidence`, `origin` (observed / inferred / patient_reported / user_contributed), `status` (active / pending_review / under_review), `features` (JSON, for inferred edges), `data_version`.

**Evidence tiers:** `curated_db`, `peer_reviewed`, `review`, `preprint`, `llm_inferred`, `patient_reported`, with the weights from Stage 4.

**Privacy rule for people nodes:** researchers and doctors appear only with public professional information (papers, grants, institution pages, trial listings), and every profile can be claimed or removed.

## Database

One database: Postgres (with pgvector) holds the pipeline's staging schema, the served graph and all user data; the pipeline talks to it with psql. There is no Supabase: auth is handled by FastAPI (see Sign-in) and row-level security is plain Postgres.

- **Local development:** the `pgvector/pgvector:pg18` container from `deploy/compose/docker-compose.yml`.
- **Deployed:** the Zalando-operated Postgres 18 (Spilo, pgvector available) on the ionvo Kubernetes cluster, with a dedicated database for the atlas.

**Pipeline staging (psql).** Raw dumps are bulk-loaded with `psql \copy` into a separate staging schema; joins, cleaning and graph building run as SQL there, and `make load` promotes the result into the graph tables. User data never touches the staging schema.

**Extensions:** `pgvector` (HNSW index on embeddings, for entity linking and semantic search), `pg_trgm` (GIN index on synonyms, for typo-tolerant search), `unaccent` ("Ménière" matches "Meniere").

**Graph tables** (written only by the pipeline, read-only for the API)

| Table | Key columns |
| --- | --- |
| `nodes` | `id` (`MONDO:…`, `HGNC:…`), `type`, `label`, `description`, `cluster_id`, `x`, `y`, `centrality`, `embedding` |
| `node_synonyms` | `node_id`, `synonym`, `source` |
| `edges` | see edge attributes in Graph data model |
| `evidence` | `edge_id`, `tier`, `source_type`, `source_id` (PMID, NCT…), `url`, `quote`, `retrieved_at`, `polarity` |
| `clusters` | `id`, `label`, `mechanism_summary`, `member_count` |
| `explanations_cache` | `path_id`, `role`, `language`, `text`, `citations`, `data_version` |
| `ingestion_runs` | `data_version`, pipeline commit, source versions, counts, `created_at` |

**User tables** (row-level security on every one). Only signed-in users have rows; guests are stateless.

| Table | Key columns |
| --- | --- |
| `users` | `id` (UUID), `chatgpt_sub` (unique), `email`, `name`, `created_at`, `last_login_at` |
| `openai_tokens` | `user_id`, encrypted access and refresh token, `expires_at`, `scopes` (used to bill LLM calls to the user's ChatGPT plan) |
| `profiles` | `user_id`, `role` (patient / doctor / researcher), `role_verified`, `orcid_id`, `language`, `gpc_opt_out` |
| `consents` | `user_id`, `consent_type` (health_data / contribute), `version`, `granted_at`, `revoked_at` |
| `patient_profiles` | `user_id`, `profile` (JSON matching the `PatientProfile` schema), `updated_at` |
| `chat_sessions` / `chat_messages` | `user_id`, session and message content |
| `documents` | `id`, `user_id`, `status`, `doc_type`, `created_at`, `raw_deleted_at` |
| `findings` | `id`, `document_id`, `user_id`, `type`, `value`, `normalized_id`, `page`, `snippet`, `confirmed` |
| `contributions` | `id`, `user_id`, `kind`, `payload`, `status`, `consent_id` |
| `edge_flags` | `edge_id`, `user_id`, `reason`, `status` |
| `jobs` | `id`, `user_id`, `kind`, `status`, `progress`, `result` |

**Rules**

- **Row-level security** on every user table, with `FORCE ROW LEVEL SECURITY` and the policy `user_id = current_setting('app.user_id', true)::uuid` (on `users`: `id = …`). FastAPI runs `SELECT set_config('app.user_id', :user_id, true)` at the start of every request transaction, so the setting is scoped to that transaction. A bug in the API still cannot leak one user's rows to another; a request without a user sees no user rows at all.
- **Database roles:**
  - `atlas_owner` owns the schema and runs Alembic migrations.
  - `atlas_app` is what FastAPI connects as: not the table owner, no `BYPASSRLS`, read-only on graph tables, read/write on user tables (subject to RLS).
  - `atlas_pipeline` writes the staging schema and graph tables, and has no access to user tables.
- **Auth bridge exception:** sign-in must look up a user by `chatgpt_sub` before `app.user_id` is known. This one query runs through a narrow `SECURITY DEFINER` function (`auth_find_or_create_user(sub, email, name)`) instead of bypassing RLS for the whole connection.
- `ON DELETE CASCADE` from `users`, so account deletion removes everything.
- Access from FastAPI via `asyncpg` through SQLAlchemy 2.0 async; migrations are managed with Alembic in `apps/backend/migrations` (autogenerate from the SQLAlchemy models; extensions, roles, RLS policies and other raw SQL go in via `op.execute`).
- At startup the API loads `nodes` and `edges` into memory; Postgres serves search, evidence lookups and all writes.

## Sign-in

**Continue with ChatGPT is the only sign-in method.** Everyone else uses the app as a guest.

| | Guest | Signed in with ChatGPT |
| --- | --- | --- |
| Search, graph views, paths, evidence, clusters, graph export | Yes | Yes |
| Cached (precomputed) explanations | Yes | Yes |
| Chat orchestrator, uncached explanations, gap search, document upload, profile, contributions, flags, proposals | No — prompts sign-in | Yes |
| LLM calls | None | Billed to the user's own ChatGPT plan |
| Stored data | None (stateless, no user rows) | User tables under RLS |

Guests never trigger an LLM call, so there is no team key for guests; the team's own OpenAI key is used only by the offline pipeline (extraction, linking, precomputed explanations). For guests, the landing-page input box works as the global search; typing free text there offers sign-in to use the agent.

### Flow

1. A guest uses search and the graph, then clicks something that needs the agent ("Ask Dr. Wu", "Upload a report", …).
2. An inline dialog offers **Continue with ChatGPT** with OpenAI's approved branding ([OpenAI quickstart](https://developers.openai.com/siwc/quickstart)). No passwords to manage.
3. **Continue with ChatGPT** runs OpenID Connect with PKCE:
   1. `GET /auth/chatgpt/start` creates `state`, `nonce` and a PKCE verifier, stores them in a short-lived signed cookie, and redirects to OpenAI. It requests the identity scopes (`openid profile email`) plus whatever OpenAI requires for API usage on the user's plan (to be confirmed against OpenAI's docs).
   2. `GET /auth/chatgpt/callback` validates `state`, exchanges the code, and verifies the ID token: signature against OpenAI's published keys, `iss`, `aud`, `exp`, `nonce`.
   3. The backend calls `auth_find_or_create_user` with `sub`, `email`, `name`: a known `chatgpt_sub` signs into the existing user, a new one creates a user. The OpenAI tokens are stored encrypted in `openai_tokens`.
   4. The backend sets the session cookie (below) and redirects back to where the user was.
4. First sign-in: the user picks a role (patient, doctor, researcher). Before the first chat message, profile save or upload, whichever comes first, one consent screen covers all processing of the user's own health and genetic data (`health_data`). It explains what is processed, that personal data is redacted, that raw files are deleted after extraction, and that nothing is shared without the separate `contribute` opt-in. The consent is stored with timestamp and text version (GDPR Article 9).
5. The requested feature proceeds.

### Sessions

- FastAPI issues its own session: a signed, `HttpOnly`, `Secure`, `SameSite=Lax` cookie holding a short-lived JWT (`sub` = user id), signed with a server secret (`SESSION_SECRET`), refreshed on activity. Logout clears it.
- The Next.js frontend never handles tokens; it calls the API with the cookie (same site, behind the same domain or with credentials enabled).
- OpenAI access tokens are refreshed server-side with the stored refresh token; if refresh fails, the user is asked to sign in again.

**Availability caveat:** Sign in with ChatGPT for websites is currently a limited trial for selected partners and needs a requested client ID. Request it immediately; there is no other sign-in method, so if approval is late the demo runs in guest mode only. Billing API usage to the user's ChatGPT plan is in scope and the main reason for this sign-in method.

### FastAPI dependencies

- `get_optional_user`: verifies the session cookie; returns the user (`user_id`, `role`, `role_verified`) or `None` for guests, and sets `app.user_id` on the request's database transaction.
- `require_user`: `401` with code `sign_in_required` for guests.
- `require_consent(type)`: `403` with code `consent_required` if no active consent of that type. There are two types: `health_data` (one general consent for chat, profile and uploads) and `contribute` (sharing into the shared graph).

### Role lenses

The role travels with every request and selects a lens: starting view, label style, explanation template and reading-level target. A lens never hides a node, edge or source.

## Backend services

Ten services, each a module under `/api/services`; the `PatientProfile` schema is the shared contract between chat, documents and graph search.

### Search

- Combines trigram matches on `node_synonyms`, vector matches on `nodes.embedding`, and a ranking boost by node type and centrality.
- Returns typed results (disease, gene, symptom, group, mechanism) with the synonym that matched, so the UI can show "Ohtahara syndrome → STXBP1 encephalopathy."

### Graph

- Loads nodes and edges into memory at startup (NetworkX for queries, positions precomputed).
- `neighborhood(node, role)` returns the same full neighborhood for every role; the role only adds presentation hints (starting layout, label style, which edge family is highlighted first).
- `clusters()` serves cluster metadata.
- **Atlas tree** (`GET /atlas/tree.json`): built from the in-memory graph on the first request after startup and cached, with its layout, until the graph changes (shared contributions or flags are reloaded). Each category gets its own angular sector and its tree grows outward without overlaps; the layout is deterministic. The payload carries every tree node with its position, the category sectors and label positions, and all real edges, which the frontend draws only for a clicked node. Its ETag is keyed on the data version and the layout version. The old whole-graph layout (`GET /atlas.json`, pipeline positions) is still served but no longer used by the frontend.
- **Atlas summary** (`GET /atlas/summary/{id}`): what a node is connected to, deterministic and without a model, read from the in-memory graph on every click. Direct links plus fixed chains of up to three hops per node type (for example a disease's researchers via its papers). Items are grouped into sections by type and ranked by the number of chains that reach them, then by the weakest link of the best chain; each section keeps its top 10. Each item carries the edge IDs of its best chain and a short "via …" label; membership of a computed cluster is marked as grouped by the atlas, not a direct link. The response also lists up to 20 edge IDs for "Write a summary".

### Path

- Top-k weighted paths with edge cost `−log(confidence)`, so the most trustworthy route wins rather than the shortest.
- Filters by edge family: DNA links, symptom links, research links, or all.
- When no path passes the confidence threshold, returns `status: "no_supported_route"` with a coverage report: sources queried and result counts, the closest partial path, which link is missing, and a suggested next question.

### Explanation

- Role-specific prompt template and output language; streams over SSE.
- The model may cite only edge IDs present in the path; the output is validated and regenerated if it cites anything else.
- `textstat` reading-level gate per role (regenerate with a "simpler" instruction if above target).
- Cached in `explanations_cache` by `(path_id, role, language, data_version)`.
- With `subject_node_id`, it writes a summary of one node's connections instead of a path explanation: the edges are the ones the Atlas summary lists for it, strongest first, and the model may cite only those. Same access rule; cached under its own `path_id` (over `subject:<id>` plus the edges), so it never collides with a path over the same edges.

### Chat orchestrator

Detailed design in [`agent.md`](agent.md).

- SSE chat with tools: `extract_entities`, `resolve_to_ids`, `search_graph`, `get_neighborhood`, `find_path`, `ask_followup`.
- Live entity extraction for chips: diseases → MONDO, genes → HGNC, variants (HGVS) → ClinVar, symptoms → HPO, with negation ("no feeding problems" = excluded), age, onset and country.
- Maintains the `PatientProfile`; chips are confirmed, corrected or removed by the user before they count.
- `ask_followup` asks at most one question at a time, chosen by which answer best separates the remaining candidate clusters, with quick-reply options, always skippable.
- Replies include tool results the frontend renders as cards (mini graph, patient group, evidence chips, "Open in Atlas").
- Safety rules in the system prompt and a post-check: no diagnosis (symptoms-only input maps to clusters "to discuss with a clinical geneticist"), emergency detection first ("call emergency services"), no prognosis or mortality figures unless asked.
- Replies in the user's language; an expert mode, open to everyone and the default for researchers, accepts mechanism queries ("AAV gene replacement for loss-of-function") and returns ranked clusters.

### Documents

- Requires `require_user` and `require_consent("health_data")`.
- Upload limits: 20 MB, 30 pages; type checked with `python-magic` (PDF, PNG, JPEG, HEIC, DOCX); `slowapi` limit of 10 uploads per user per hour.
- Pipeline per job: extract text (PyMuPDF for text PDFs, docTR or Tesseract OCR for scans and photos) → Presidio redaction of names, birth dates, addresses, patient IDs → classify (genetic report, clinical letter, research paper, registry or study document) → structured extraction with Structured Outputs → findings with page and snippet.
- Raw bytes live only in memory or a temp file deleted in `finally`; `raw_deleted_at` is set on completion.
- Genetic reports: gene, HGVS variant, zygosity, classification (pathogenic, likely pathogenic, VUS), test date. A VUS is flagged "uncertain, discuss with a genetic counselor."
- Findings reach the `PatientProfile` only after the user confirms each one.
- Papers from researchers become candidate edges with `origin = user_contributed`, `status = pending_review`.

### Gap-search agent

- OpenAI Agents SDK with tools `pubmed_search`, `clinicaltrials_search`, `web_search` (Bright Data), `fetch_page`.
- Triggered from a `no_supported_route` result; streams progress over SSE.
- Hard budgets: maximum steps, maximum tokens, 90-second timeout.
- Outputs candidate edges with quotes and sources, always `pending_review`; never promoted automatically.

### Contributions

- Patient-reported phenotype profiles and assets, only with an active `contribute` consent.
- Stored as `origin = patient_reported`, separate from cited evidence; shown with their own label and never mixed into confidence beyond the patient-reported tier.

### Feedback

- Any signed-in user can flag an edge with a reason; the edge moves to `under_review` and shows a visible flag.

### Proposal export and data rights

- Generates a one-page sourced proposal from a path, its assets and contacts (HTML for print-to-PDF).
- `GET /me/export` returns all user data as JSON; `DELETE /me` deletes the account with cascade.

## API

| Method | Path | Access | Returns |
| --- | --- | --- | --- |
| GET | `/auth/chatgpt/start` | Anyone | Redirect to OpenAI (OIDC + PKCE) |
| GET | `/auth/chatgpt/callback` | Anyone | Session cookie, redirect back |
| POST | `/auth/logout` | Signed in | Session cleared |
| GET | `/search?q=` | Anyone | Typed matches with matched synonym |
| GET | `/node/{id}` | Anyone | Node details + summary for the side panel |
| GET | `/neighborhood/{id}` | Anyone | Full neighborhood with positions + role presentation hints |
| GET | `/clusters` | Anyone | Cluster IDs, labels, sizes |
| GET | `/atlas/tree.json` | Anyone | Atlas hub and category trees with positions, all edges, clusters (ETag) |
| GET | `/atlas/summary/{id}?role=` | Anyone | A node's place in the tree, headline, ranked connections by section, edge IDs for a written summary |
| GET | `/path?from=&to=&family=` | Anyone | Ordered path steps, or `no_supported_route` + coverage report |
| GET | `/edge/{id}/evidence` | Anyone | Sources, quotes, tiers, contradictions |
| POST | `/explain` (SSE) | Anyone for cached explanations; signed in to generate new ones | Streamed role-specific explanation of a path with citation IDs; with `subject_node_id`, a summary of that node's connections |
| POST | `/chat` (SSE) | Signed in + health-data consent | Streamed reply, chips, cards, follow-up question |
| POST | `/gap-search` (SSE) | Signed in, rate-limited | Agent progress + candidate edges |
| GET | `/export/graph` | Anyone | CSV / GraphML of the requested subgraph |
| GET / PUT | `/profile` | Signed in (PUT: + health-data consent) | The `PatientProfile` |
| POST | `/documents` | Signed in + health-data consent | `job_id` |
| GET | `/documents` | Owner | Own documents |
| GET | `/documents/{id}/findings` | Owner | Findings with page and snippet |
| POST | `/findings/{id}/confirm` · `/reject` | Owner + health-data consent | Updated profile |
| DELETE | `/documents/{id}` | Owner | Document and findings removed |
| GET | `/jobs/{id}` (SSE) | Owner | Job progress |
| POST / DELETE | `/consents` · `/consents/{type}` | Signed in | Grant or revoke |
| POST | `/contributions` | Signed in + contribute consent | Contribution with status |
| POST | `/edges/{id}/flag` | Signed in | Flag recorded, edge `under_review` |
| POST | `/proposal` | Signed in | One-page sourced proposal (HTML) |
| GET | `/me/export` · DELETE `/me` | Signed in | Data export · account deletion |

## Build order

Build the graph and the read path first, so the frontend can integrate early; auth, uploads and the agent come after the demo story works.

1. Request the Sign in with ChatGPT client ID and the OMIM key (both have lead time); set up the database roles, Alembic migrations, extensions and RLS.
2. `mondo`, `hgnc`, `hpo` connectors + load → searchable diseases, genes and symptoms.
3. Symptom similarity, ClinVar/ClinGen mechanism edges, Reactome pathways, clustering, layout → the graph exists; validation with golden set and counterexample.
4. Search, graph and path services + generated TypeScript client → frontend integrates.
5. PubMed extraction with quote verification, evidence table, confidence formula → trustworthy edges.
6. Patient orgs (Bright Data), ClinicalTrials.gov, RePORTER → communities, assets, researchers, doctors.
7. Explanation service with role lenses and caching → the demo story works end to end; turn on `DEMO_MODE`.
8. Sign in with ChatGPT, sessions, OpenAI token storage, guest gating, consent → auth complete.
9. Chat orchestrator with chips, profile and follow-ups.
10. Document service with redaction and findings review.
11. Gap-search agent, contributions, edge flags, proposal export → stretch features.

## Backlog (not in the 24h build)

**Data and community.** Collect much more data into the database. Users log in to upload their data and join the network and community. It should be possible to join anonymously, to share a backstory and treatment plan without revealing who they are.

**Ideas**

- Anonymous data upload to add more data, without disclosing the private person.
- Autonomous ingestion engine for existing papers and resources.
- Automatic reach-out from patients to other patients and doctors.
- Automatic warm introductions between research groups.
- Automatically connecting patients to studies and trials.

## Project names

- **Amber — Rare Disease Atlas.** Logo: amber with a DNA sequence inside.
- **Dr. Wu** for the AI assistant (Jurassic Park reference; check trademark risk before submission).
