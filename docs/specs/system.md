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

**Login with ChatGPT** is the default sign-in method. It is used for identity *and* to bill OpenAI API usage to the signed-in user's own ChatGPT plan; that is the main reason for using it. An operator can also enable **Continue with Google**, whose model calls run on a server API key (see Sign-in). Guests can explore the graph but get no agent features (see Sign-in).

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

**The Atlas enters the graph through a tree.** The Amber logo sits in the middle as a hub, with one tree per category around it, clockwise from the top: researchers, hospitals & universities, literature, community, pathways, genes, diseases, symptoms, doctors. Every node on the map is always visible and appears exactly once; the trees are never collapsed. The map holds the focus tier only (see Stage 0): diseases, genes, symptoms and pathways of the core tier are not drawn and are found through search and Dr. Wu. This is a temporary exception to "every node once". Only tree lines are drawn by default. Clicking a node draws its real connections and opens its summary. The tree is navigation only: it gives every node a place to be found and does not change how nodes are connected. The chains above are followed along the real connections and through the summary panel, not along the tree.

**The role decides where you start and how things are explained, never what you can see:**

- **Patients** start at their disease, with similar diseases and patient communities highlighted, explained in plain language.
- **Doctors** start with the symptom profile, with centers of expertise, clinical studies and variant classifications highlighted, explained in clinical terms.
- **Researchers** start with mechanism clusters, with variants, pathways, papers and funding highlighted, explained technically with IDs shown.
- **Guests** start with a guided tour in very simple language. They can explore everything but have no agent features (see Sign-in).

In the Atlas, patients and researchers start framed on the Diseases tree, doctors on the Symptoms tree, guests on the whole map. The role comes from the user's settings; a role change there applies on the next opening of the Atlas.

### Atlas view

- **Map:** the hub and the nine trees, with positions from the API (see Graph service). Hovering a node shows its label and its line back to the hub, never its connections. Clicking an entity draws its real connections (dashed when inferred, flagged when under review) and dims the rest; clicking a group highlights its branch; clicking the logo resets the view. Filters choose which connection families are drawn on click and hold the key.
- **Search bar** over the map ("Search the map", `/` focuses it): matches every tree node, groups included, with the branch it sits in. Text that looks like a name also runs the synonym search (`GET /search`); free text is never sent there and never put into a URL. It is offered to Dr. Wu instead. Search hits that are not on the map are marked "Not on the map yet"; picking one opens its summary panel without moving the map.
- **List:** an outline of the same trees as an ARIA tree (arrow keys, Home/End, Enter, typeahead, a filter box). It is the accessible alternative to the canvas, and here branches can be opened and closed.
- **Summary panel** on the right (a bottom sheet on mobile): for an entity, its place in the tree, a headline and its connections grouped by type (researchers, doctors, papers, trials, hospitals and universities, patient groups, genes, symptoms, similar conditions, …), each with the chain it is reached by, data vs. hypothesis and review flags. Picking an item selects it on the map and draws that chain. **Write a summary** streams a written summary of these connections from `POST /explain` (cached ones for anyone, new ones signed in). For a group, the panel explains how it was formed and lists its children. For a core-tier node the panel says that literature, trials, researchers and patient groups are collected only for the focus diseases (`coverage` and `focus_disease_count` from the summary). A computed item shows its confidence and its one-line explanation, labelled a hypothesis.
- **Dr. Wu dock** in the bottom-left corner: guests see the sign-in offer; signed-in users chat with Dr. Wu under the same `health_data` consent as the chat page. The nodes his reply points to are highlighted and framed on the map and listed as "Dr. Wu found N"; finds that are not on the map are listed too and open the panel. What the user typed and the found node IDs stay in memory only: never in the URL, never in browser storage.

**How the trees are grouped.** Every level below a category comes from stored data; a node that lacks what a level needs goes into a "… not recorded" group, nothing is dropped, and a group with more than 30 entries is split into alphabetical ranges. Three groupings are choices rather than facts, and the group panel says so:

- **Diseases** are grouped by the computed clusters (Stage 5), which are inferred. The clusters hang under HPO groups from each cluster's `lineage` (organ system down to the group above the cluster); a group is kept at the top or where it branches, single-child chains are left out, and clusters without a lineage sit directly under the category.
- **Hospitals & universities** are one tree, split by keywords in the institution's name into hospitals and clinics (checked first, so "University Hospital …" counts as clinical), universities and research institutes, and other organisations, then by country. The data has no hospital or university type.
- **Symptoms** follow the HPO classification (organ system, then the HPO hierarchy with one parent per term) when phenotype nodes carry `attrs.hpo_lineage`. The pipeline writes `hpo_lineage` on every phenotype node; without it the trunk falls back to one "Classification not loaded" group in alphabetical ranges.

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

The backend has two halves: an offline pipeline that builds a sourced knowledge graph (every qualifying rare disease with its genes and symptoms, plus literature, people and communities for a focus set), and a FastAPI service that serves that graph, explains it per user role, and handles chat, document uploads and sign-in.

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

Ten steps, each a `make` target and a Typer command (`atlas-pipeline <stage>`), idempotent and cached, so the README's "reproduce the dataset" is one command. `atlas-pipeline all` runs them in this order: fetch (bulk) → scope → fetch (scoped) → normalize (with linking) → extract → build → analytics → validate → load → snapshot → explain. Between steps the data lives in Parquet files under `apps/pipeline/data`; only `load` writes to Postgres.

### Stage 0: Scope

`seeds.yaml` sets `scope.mode`. In `qualify` mode (the one in use) the scope has two tiers:

- **Core:** every rare disease the open sources describe with a gene and a symptom. Inputs: Orphanet product6 associations whose type starts with "Disease-causing germline" and whose status is Assessed, HPO `genes_to_phenotype` and `phenotype.hpoa`, approved HGNC genes. Diseases map to MONDO through MONDO's exact matches and Orphanet product1; the MONDO term must be live and have at least one approved gene and one phenotype. Excluded: labels with "susceptibility" or "protection against", terms with more than 30 MONDO descendants, OMIM-only entries labelled cancer or carcinoma, and anything not rare (rare = in MONDO's rare subset, or with an ORPHA or OMIM key). OMIM's own files are never read for the scope.
- **Focus:** the seed expansion (seed genes and diseases plus the expansion rules: up to 2 hops via shared gene, shared pathway or HPO similarity, with caps) plus the diseases listed under `focus_diseases`. Only focus entries get literature, trials, grants, people, patient organisations, variant nodes and GO pathways. Adding a focus disease means adding its name and rerunning the scoped fetch; nothing is fetched on click.

`attrs.tier` (`focus` or `core`) is set on disease, gene, phenotype and pathway nodes; a pathway is focus when a focus gene takes part in it. Nodes of every other type exist only for the focus set. The `expand` mode (the seed expansion alone) is still available.

### Stage 1: Fetch

Every connector implements `fetch()` and writes to `data/raw/<source>/` with a metadata record: URL, retrieval timestamp, SHA-256, source version. All HTTP goes through `httpx` with the `hishel` cache and an `aiolimiter` rate limit; `tenacity` retries transient failures. Bulk connectors need no scope; scoped connectors run after Stage 0 and iterate the focus entries (ClinVar also counts variants for every gene).

| Connector | Phase | Pulls | Access |
| --- | --- | --- | --- |
| `mondo` | bulk | `mondo.json`: disease IDs, synonyms, cross-references | Public download |
| `hgnc` | bulk | Complete gene set: symbols, aliases, previous symbols, cytoband | Public download |
| `hpo` | bulk | `hp.json`, `phenotype.hpoa`, `genes_to_phenotype.txt` | Public download |
| `mane` | bulk | NCBI MANE summary: gene coordinates on GRCh38 | Public download |
| `clingen` | bulk | Dosage sensitivity and gene–disease validity CSVs | Public download |
| `reactome`, `go` | bulk | Gene → pathway mappings | Public download |
| `orphanet` | bulk | product1 (disorders and cross-references), product4 (phenotypes), product6 (gene associations), product9 (prevalence) | Public, CC BY 4.0 |
| `curated` | bulk | PubMed summaries of the PMIDs cited in `curated/*.yaml` | E-utilities |
| `omim` (optional) | bulk | `genemap2`, only with `OMIM_API_KEY`; not used for the scope | Needs registered key |
| `clinvar` | scoped | `variant_summary.txt.gz`, GRCh38 rows: all rows of focus genes, pathogenic / likely pathogenic rows of every gene, per-gene counts | Public FTP |
| `pubmed` | scoped | Per gene/disease search → abstracts, authors, affiliations | E-utilities + free NCBI key |
| `clinicaltrials` | scoped | Studies by condition: status, design, eligibility, locations, investigators | REST API v2 |
| `reporter` | scoped | Grants by gene/disease terms: PIs, institutions, abstracts | REST API, ~1 req/s |
| `patient_orgs` | scoped | Curated list, plus Bright Data SERP queries → page fetch → `trafilatura` clean text when configured | Bright Data |

### Stage 2: Normalize and resolve identities

- Parse everything into Parquet tables with standard IDs: `MONDO:`, `HGNC:`, `HP:`, `CLINVAR:`, `PMID:`, `NCT`.
- The disease node id is the MONDO id. ORPHA and OMIM ids (from MONDO exact matches and Orphanet product1) are stored as `orpha_ids` and `omim_ids` and added as synonyms, so `ORPHA:337` or `OMIM:135100` finds the disease. Gene names and aliases map to HGNC.
- Positions: genes get `chromosome`, `cytoband`, `start`, `end`, `strand` and `assembly` (GRCh38) from MANE; genes without MANE coordinates are reported, not dropped. Variants get `vcv`, `chromosome`, `start`, `stop`, `cytoband`, `assembly`, `ref`, `alt` and `position_vcf` from ClinVar.
- Build one `synonyms` table holding every name variant for every node.
- **LLM-assisted linking for leftovers:** generate candidates by trigram and embedding similarity, then the model picks one candidate or "none" via Structured Outputs (a trigram match of 0.95 or more skips the model). Every decision is logged in `data/logs/linking.jsonl`; without a model the leftover stays unlinked.

### Stage 3: LLM extraction

Runs on the focus set only.

- **From abstracts:** entities and relations from the fixed relation enum, each with `quote` (exact supporting span), `claim_type` (patient observation, experimental, review, hypothesis), `polarity` (supports, contradicts) and `confidence`.
- **Quote verification:** programmatically check that every `quote` occurs in the source text; reject the edge otherwise.
- **Investigators come from PubMed metadata**, never from the model.
- **From patient org pages:** organization name, diseases served, country, registry yes/no, natural history study yes/no, contact URL, always with the source URL.
- Use a small model for bulk extraction with async calls and a concurrency limit. The Batch API is cheaper but can take up to 24 hours, so use it only if extraction starts early.

**Model steps and their limits.** The pipeline calls a model in five places: abstract extraction, patient-organisation pages, linking decisions (Stage 2), cluster labels (Stage 5) and the precomputed explanations (`explain`). They run on the plan of whoever ran `make pipeline-login`; there is no team key. Extraction and cluster labels go through one disk cache (`data/cache/llm/`, keyed by a hash of the model kind, schema, instructions and input; cached results are served without a login) and one budget: `PIPELINE_LLM_MAX_CALLS` (default 300) caps the uncached calls per run, and the run stops calling, but keeps building, when the budget or the plan's usage limit is reached. Linking calls the model directly, without this cache and budget. `PIPELINE_LLM_DISABLED=true` turns every model call off. Without a model the run still finishes: cached results only, leftovers unlinked, template cluster labels, template explanations.

### Stage 4: Build the graph

Evidence for the same relation merges into one edge with many evidence rows. Each evidence item gets a tier weight: curated database 0.9, peer-reviewed primary 0.7, review 0.5, preprint 0.4, LLM-inferred 0.3, patient-reported 0.2. A computed link (tier `computed`) counts by its own score, at most 0.79.

$$
\text{confidence} = 1 - \prod_{i \in \text{supporting}} (1 - w_i) \; - \; p \cdot n_{\text{contradicting}}
$$

with $p = 0.1$. The result is clamped to 0–1 and shown in the UI as High (≥ 0.8) / Medium (≥ 0.5) / Low, with the breakdown on click. Computed links are then capped per relation: `near_on_chromosome` 0.45, `candidate_phenotype` and `suggested_by_neighbour` 0.55, every other computed relation 0.79, so no computed link reaches High. When an edge also has observed evidence, its hypothesis features are dropped.

### Stage 5: Analytics

Every computed link has `origin = inferred`, evidence with tier `computed` and `claim_type = hypothesis`, and the features `explanation` (one line on why the link exists), `method`, `confidence_basis` and `score`.

- **Phenotype data:** each phenotype node gets `hpo_lineage` (organ system down to its primary parent), `ic` (information content over every disease in `phenotype.hpoa`, not only the scope) and `ancestors`. The `hpo_terms` table (every HPO term under "Phenotypic abnormality", with label, synonyms, direct parents and `ic`, including terms that are not nodes) is written here for symptom matching.
- **Symptom similarity (`similar_symptoms`):** a frequency-weighted, IC-weighted symmetric best-match average (`apps/backend/src/backend/phenotype_similarity.py`, shared with the API so Dr. Wu ranks with the same code; a missing frequency counts as 0.5). Candidates are each disease's top 25 by IC-weighted cosine; a link needs similarity ≥ 0.45 and at least 2 shared specific terms (IC ≥ 2.0); top 8 per disease. The threshold is raised if it sits below the 95th percentile of random disease pairs, which validation checks. Confidence = min(0.30 + 0.55 · similarity, 0.75).
- **Mechanism per gene** (focus genes): the share of truncating pathogenic ClinVar variants gives inferred `acts_via` gene → mechanism links. Diseases caused by the same gene get `same_gene_same_mechanism` or `same_gene_different_mechanism`; genes with more than 25 diseases keep only pairs with a mechanism record.
- **`shared_gene`:** two diseases linked to variants in the same gene where no `same_gene_*` link exists; genes with more than 25 diseases are skipped. Confidence = 0.85 × the weaker gene–disease confidence. Its explanation says that a shared mechanism is not established.
- **`shared_pathway`:** genes of two diseases in the same Reactome or GO pathway (at most 60 genes; diseases with more than 8 genes and pairs that already share a gene are skipped); smaller pathways weigh more; top 5 per disease.
- **`near_on_chromosome`** (gene ↔ gene): same chromosome, at most 1 Mb apart on MANE coordinates, the 3 nearest per gene; without coordinates, the same cytoband sub-band. Confidence 0.20, or 0.45 when at least 2 pathogenic or likely pathogenic ClinVar copy-number variants of at most 1 Mb span both genes (larger events say nothing about a specific pair). No disease ↔ disease proximity link.
- **Research overlap:** shared authors or PIs across diseases produce `shared_researcher` links (fixed 0.40).
- `candidate_phenotype` and `suggested_by_neighbour` (hypotheses for little-studied diseases from their well-studied neighbours) are defined, capped and validated, but not produced yet.
- **Clustering:** Leiden (`igraph` + `leidenalg`, seed 42) on the weighted disease links (resolution 1, or 10 from 1,000 diseases), with `same_gene_different_mechanism` as a negative layer so such a pair never shares a cluster; `shared_gene` and `near_on_chromosome` are left out. Each cluster stores `members`, `top_genes`, `top_pathways`, `top_phenotypes`, `distinctive_phenotypes`, `mechanisms` and a `lineage`: the HPO groups from organ system down, which the Atlas uses for the Diseases trunk. The label is a template from the most distinctive HPO term plus the top gene; with a model the model writes it (`label_origin`). Clusters are marked inferred.
- **Layout, centrality, embeddings:** precomputed DrL positions (refined with ForceAtlas2 up to 3,000 nodes), PageRank as `centrality`. The Atlas tree layout is computed by the API (see Graph service). Embeddings are computed locally for every node except core-tier genes and phenotypes.

### Stage 6: Validate

The build fails unless all checks pass:

- Every edge has at least one evidence row and valid endpoints; no orphan nodes; enums and relation families are valid; every disease has a cluster.
- Every computed link has a one-line explanation, a method and a confidence basis, stays within its relation's cap, carries only `computed` / hypothesis evidence, and no proximity or candidate link reaches the 0.6 of a supported path.
- Every phenotype has a valid `hpo_lineage`; every cluster has a lineage; every disease, gene, phenotype and pathway has `attrs.tier`; `hpo_terms` covers every phenotype node; at least 7,000 diseases with a gene and a symptom. Missing gene coordinates are reported, not failed.
- A golden set of known facts holds at confidence ≥ 0.6 (e.g. SCN1A → Dravet syndrome, fibrodysplasia ossificans progressiva → ACVR1, primary ciliary dyskinesia 25 → chronic cough).
- Known counterexamples hold: SCN2A and SCN1A gain- and loss-of-function diseases do not share a cluster and are linked by `same_gene_different_mechanism`.
- The quote-verification pass rate and rejection counts are reported.

### Stage 7: Load and snapshot

`load` and `snapshot` refuse to run unless validation passed for the same data version. `load` copies the tables into the `staging` schema with `psql \copy` and promotes them in one transaction: it records `graph_changes` (compared with the live tables), deletes cached explanations of other versions, replaces `nodes`, `node_synonyms`, `edges`, `evidence`, `clusters` and `hpo_terms`, and records the run in `ingestion_runs`. `snapshot` exports the same tables as Parquet plus a manifest with source versions, hashes, counts, thresholds and `data_version`. `explain` pre-generates explanations for the demo paths in every role, in English and German.

## Graph data model

A fixed set of node types and relation types, shared as enums between pipeline, API and frontend.

**Node types:** disease, gene, variant, mechanism, pathway, phenotype, paper, claim, researcher, doctor, institution, network, grant, trial/study, patient organization, registry, cluster. Individual patients are never nodes. Positions on the genome are attributes, not nodes.

**Node attributes** (in `attrs`, the ones the pipeline and API rely on):

- All disease, gene, phenotype and pathway nodes: `tier` (`focus` or `core`, see Stage 0).
- Disease: `orpha_ids`, `omim_ids` (also searchable as synonyms), `xrefs`, `rare`, `excluded_phenotypes` (terms a source records as absent, with their sources; used by symptom ranking, not drawn as edges), `orphanet_prevalence`.
- Gene: `chromosome`, `cytoband`, `start`, `end`, `strand`, `assembly` (GRCh38, from MANE), ClinGen scores, `clinvar_plp`, `clinvar_vus`, `clinvar_truncating_share`.
- Variant (focus genes only): `vcv`, HGVS, classification, review status, consequence, `chromosome`, `start`, `stop`, `cytoband`, `assembly`, `ref`, `alt`.
- Phenotype: `hpo_lineage`, `ic`, `ancestors`.
- Cluster: see Stage 5 (`lineage`, `distinctive_phenotypes`, `top_genes`, …).

**Relation types**

| Family | Relation | From → to |
| --- | --- | --- |
| Biology | `caused_by_variant_in` | disease → gene |
| Biology | `acts_via` | gene → mechanism (loss of function, gain of function, dominant-negative) |
| Biology | `participates_in` | gene → pathway |
| Biology | `has_phenotype` | disease → phenotype, with `frequency` (0–1, the highest source wins), `frequency_label`, `frequency_by_source` (HPO, Orphanet) and `onset` when recorded |
| Disease–disease (DNA) | `same_gene_same_mechanism` | disease ↔ disease |
| Disease–disease (DNA) | `same_gene_different_mechanism` | disease ↔ disease (the counterexample case, e.g. SCN2A, SCN1A) |
| Disease–disease (DNA) | `shared_pathway` | disease ↔ disease |
| Disease–disease (symptoms) | `similar_symptoms` | disease ↔ disease, with shared HPO terms; labeled "similar experience, possibly different cause" |
| Disease–disease (research) | `shared_researcher` | disease ↔ disease |
| Disease–disease (DNA) | `shared_gene` | disease ↔ disease, computed: linked to the same gene, mechanism not established |
| Gene–gene (DNA) | `near_on_chromosome` | gene ↔ gene, computed: at most 1 Mb apart |
| Symptoms | `candidate_phenotype` | disease → phenotype, computed hypothesis from similar diseases (defined, not produced yet) |
| Symptoms | `suggested_by_neighbour` | disease → disease, computed hypothesis (defined, not produced yet) |
| Research | `asserts` | paper → claim |
| Research | `authored` | researcher → paper |
| Research | `pi_of` | researcher → grant |
| Research | `funds_research_on` | grant → disease |
| Community and clinical | `serves` | organization → disease |
| Community and clinical | `runs` | organization → registry or study |
| Community and clinical | `studies` | trial → disease |
| Community and clinical | `investigator_of` | doctor → trial |
| Community and clinical | `affiliated_with` | person → institution |

Further structural relations: `variant_of`, `observed_in`, `about` and `member_of`. Every relation from `same_gene_same_mechanism` to `suggested_by_neighbour` above, plus the inferred `acts_via` links, is computed by the pipeline (Stage 5): `origin = inferred`, a one-line `explanation`, a confidence capped below High, always drawn dashed and labelled a hypothesis, never presented as fact.

**Edge attributes:** `id`, `source_id`, `target_id`, `relation`, `family` (dna / symptoms / research / community), `confidence`, `origin` (observed / inferred / patient_reported / user_contributed), `status` (active / pending_review / under_review), `features` (JSON; for computed edges `explanation`, `method`, `confidence_basis`, `score`; the API exposes `explanation` on edges, path steps and summary items), `data_version`.

**Evidence tiers:** `curated_db`, `peer_reviewed`, `review`, `preprint`, `llm_inferred`, `patient_reported`, `computed` (links the atlas works out itself; weight = the link's score, at most 0.79), with the weights from Stage 4.

**Privacy rule for people nodes:** researchers and doctors appear only with public professional information (papers, grants, institution pages, trial listings), and every profile can be claimed or removed.

## Database

One database: Postgres (with pgvector) holds the pipeline's staging schema, the served graph and all user data; the pipeline talks to it with psql. There is no Supabase: auth is handled by FastAPI (see Sign-in) and row-level security is plain Postgres.

- **Local development:** the `pgvector/pgvector:pg18` container from `deploy/compose/docker-compose.yml`.
- **Deployed:** the Zalando-operated Postgres 18 (Spilo, pgvector available) on the ionvo Kubernetes cluster, with a dedicated database for the atlas.

**Pipeline staging (psql).** The pipeline builds the graph in Parquet files; `make load` bulk-loads the final tables with `psql \copy` into a separate staging schema and promotes them into the graph tables in one transaction. User data never touches the staging schema.

**Extensions:** `pgvector` (HNSW index on embeddings, for entity linking and semantic search), `pg_trgm` (GIN index on synonyms, for typo-tolerant search), `unaccent` ("Ménière" matches "Meniere").

**Graph tables** (written only by the pipeline, read-only for the API)

| Table | Key columns |
| --- | --- |
| `nodes` | `id` (`MONDO:…`, `HGNC:…`), `type`, `label`, `description`, `url`, `attrs` (JSON, see Graph data model), `cluster_id`, `x`, `y`, `centrality`, `embedding` |
| `node_synonyms` | `node_id`, `synonym`, `source` |
| `edges` | see edge attributes in Graph data model |
| `evidence` | `edge_id`, `tier`, `source_type`, `source_id` (PMID, NCT…), `url`, `quote`, `retrieved_at`, `polarity` |
| `clusters` | `id`, `label`, `mechanism_summary`, `member_count`, `attrs` (lineage, distinctive phenotypes, top genes) |
| `hpo_terms` | `id`, `label`, `synonyms`, `parents` (direct is_a), `ic`: every HPO term under "Phenotypic abnormality", including terms that are not nodes; read into memory for symptom matching |
| `graph_changes` | `data_version`, `previous_version`, `disease_id`, `node_id`, `node_type`, `change` (`added`, `now_recruiting`), `edge_id`: written at load time by comparing the new tables with the live ones, for diseases that already existed (new trials, patient organisations, grants and recent papers, trials that started recruiting); at most 20 per disease, the last 10 versions kept |
| `explanations_cache` | `path_id`, `role`, `language`, `text`, `citations`, `data_version` |
| `ingestion_runs` | `data_version`, pipeline commit, source versions, counts, `created_at` |

**User tables** (row-level security on every one). Only signed-in users have rows; guests are stateless.

| Table | Key columns |
| --- | --- |
| `users` | `id` (UUID), `auth_provider` (`openai` \| `google`), `auth_subject` (the provider's `sub`; unique together with `auth_provider`), `email`, `name`, `created_at`, `last_login_at` |
| `openai_tokens` | `user_id`, encrypted access and refresh token, `expires_at`, `scopes` (used to bill LLM calls to the user's ChatGPT plan) |
| `profiles` | `user_id`, `role` (patient / doctor / researcher), `role_verified`, `orcid_id`, `language`, `gpc_opt_out`; work details of doctors and researchers: `first_name`, `last_name`, `institutions` (JSON, at most 3), `atlas_node_id`, `professional_updated_at`; verification: `orcid_verified_at`, `verified_name`, `verification_method` (orcid / institutional_email, or orcid_simulated / manual_simulated in local demos), `verified_at`, `verification_reason`, `verification_request` (JSON), `atlas_link_verified`; public card (off by default): `card_id`, `card_visible`, `card_visible_since`, `card_headline`, `card_show_institutions`, `card_show_atlas_entry`, `accepts_patient_messages`; `connect_age_group` (18_plus / 16_17, self-declared), `connect_age_group_at` |
| `consents` | `user_id`, `consent_type` (health_data / contribute / connect), `version`, `granted_at`, `revoked_at` |
| `patient_profiles` | `user_id`, `profile` (JSON matching the `PatientProfile` schema), `updated_at` |
| `chat_sessions` / `chat_messages` | `user_id`, session and message content |
| `chat_runs` | `id`, `user_id`, `session_id` (unique: one running turn per session), `user_message_id`, `worker`, latest LangGraph checkpoint; exists only while the turn runs |
| `documents` | `id`, `user_id`, `status`, `doc_type`, `created_at`, `raw_deleted_at` |
| `findings` | `id`, `document_id`, `user_id`, `type`, `value`, `normalized_id`, `page`, `snippet`, `confirmed` |
| `contributions` | `id`, `user_id`, `kind`, `payload`, `status`, `consent_id` |
| `edge_flags` | `edge_id`, `user_id`, `reason`, `status` |
| `jobs` | `id`, `user_id`, `kind`, `status`, `progress`, `result` |
| `threads` | `id`, `opener_id` (the patient), `recipient_id` (the professional), `origin` (card / signup), `call_id`, `signup_id`, `recipient_card_id`, name snapshots, `status` (requested / open / declined / closed / blocked), times; readable by both participants |
| `thread_reads` | `thread_id`, `user_id`, `last_read_at`, `hidden_at`, `guardian_agreed_at`, `guardian_text_version` (own rows) |
| `messages` | `id`, `thread_id`, `sender_id`, `body_enc` (Fernet, `MESSAGE_ENCRYPTION_KEY`), `created_at`; readable by both participants, deletable by the sender |
| `blocks` / `reports` | the blocker's / reporter's own rows; a report authorizes a logged operator read of that conversation (`admin_access_log`, no API access) |

**Rules**

- **Messaging tables** use participant policies instead (`opener_id = me OR recipient_id = me`); a card conversation is created only by the `SECURITY DEFINER` function `open_card_thread(card_id, …)`, which resolves the card to the professional without returning a user ID, and the trigger `threads_guard` allows only the planned status changes.
- **Row-level security** on every user table, with `FORCE ROW LEVEL SECURITY` and the policy `user_id = current_setting('app.user_id', true)::uuid` (on `users`: `id = …`). FastAPI runs `SELECT set_config('app.user_id', :user_id, true)` at the start of every request transaction, so the setting is scoped to that transaction. A bug in the API still cannot leak one user's rows to another; a request without a user sees no user rows at all.
- **Database roles:**
  - `atlas_owner` owns the schema and runs Alembic migrations.
  - `atlas_app` is what FastAPI connects as: not the table owner, no `BYPASSRLS`, read-only on graph tables, read/write on user tables (subject to RLS).
  - `atlas_pipeline` writes the staging schema and graph tables, and has no access to user tables.
- **Public cards:** other users see a doctor's or researcher's card only through the `SECURITY DEFINER` function `professional_cards()`, which returns the chosen card fields (never `user_id`) for rows with `role_verified AND card_visible`; `atlas_definer` reads only the profile columns its functions need. `pending_verification_requests()` is executable by `atlas_owner` only, for the operator CLI (`backend verification-requests`, `backend verify-professional`).
- **Auth bridge exception:** sign-in must look up a user by `(auth_provider, auth_subject)` before `app.user_id` is known. This one query runs through a narrow `SECURITY DEFINER` function (`auth_find_or_create_user(provider, sub, email, name)`; the three-argument form means `openai`) instead of bypassing RLS for the whole connection. Accounts are never matched or merged by e-mail.
- `ON DELETE CASCADE` from `users`, so account deletion removes everything.
- Access from FastAPI via `asyncpg` through SQLAlchemy 2.0 async; migrations are managed with Alembic in `apps/backend/migrations` (autogenerate from the SQLAlchemy models; extensions, roles, RLS policies and other raw SQL go in via `op.execute`).
- At startup the API loads `nodes`, `edges` and `hpo_terms` into memory; Postgres serves search, evidence lookups and all writes. A new load is picked up only when the API restarts.

## Sign-in

**Continue with ChatGPT is the default sign-in method; Continue with Google is optional.** Everyone else uses the app as a guest.

Google is offered only when `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set **and** either a server `OPENAI_API_KEY` is set or `GOOGLE_LOGIN_ENABLED=true` (default false). Otherwise `/auth/google/*` answer 404 and nothing changes. The frontend learns the methods from `sign_in_methods` in `GET /auth/session`. A Google account and a ChatGPT account with the same e-mail are two accounts.

Model access is chosen in the gateway (`llm_for_user`): ChatGPT accounts always use their own plan (a lost sign-in asks them to sign in again, never falls back to the server key); other accounts use `OPENAI_API_KEY` with `OPENAI_API_MODEL_MAIN` / `OPENAI_API_MODEL_SMALL` (defaults `gpt-5`, `gpt-5-mini`), billed to the operator; without a key every model feature answers 503 `assistant_unavailable` ("Dr. Wu is not available for this sign-in.") and the rest of the app works.

| | Guest | Signed in with ChatGPT |
| --- | --- | --- |
| Search, graph views, paths, evidence, clusters, graph export | Yes | Yes |
| Cached (precomputed) explanations | Yes | Yes |
| Chat orchestrator, uncached explanations, gap search, document upload, profile, contributions, flags, proposals | No — prompts sign-in | Yes |
| LLM calls | None | Billed to the user's own ChatGPT plan (Google accounts: the server key, if configured) |
| Stored data | None (stateless, no user rows) | User tables under RLS |

Guests never trigger an LLM call, so there is no team key for guests; apart from the optional server key for Google accounts, the team's own OpenAI key is used only by the offline pipeline (extraction, linking, precomputed explanations). For guests, the landing-page input box works as the global search; typing free text there offers sign-in to use the agent.

### Flow

1. A guest uses search and the graph, then clicks something that needs the agent ("Ask Dr. Wu", "Upload a report", …).
2. An inline dialog offers **Continue with ChatGPT** with OpenAI's approved branding ([OpenAI quickstart](https://developers.openai.com/siwc/quickstart)). No passwords to manage.
3. **Continue with ChatGPT** runs OpenID Connect with PKCE:
   1. `GET /auth/chatgpt/start` creates `state`, `nonce` and a PKCE verifier, stores them in a short-lived signed cookie, and redirects to OpenAI. It requests the identity scopes (`openid profile email`) plus whatever OpenAI requires for API usage on the user's plan (to be confirmed against OpenAI's docs).
   2. `GET /auth/chatgpt/callback` validates `state`, exchanges the code, and verifies the ID token: signature against OpenAI's published keys, `iss`, `aud`, `exp`, `nonce`.
   3. The backend calls `auth_find_or_create_user` with `sub`, `email`, `name`: a known `chatgpt_sub` signs into the existing user, a new one creates a user. The OpenAI tokens are stored encrypted in `openai_tokens`.
   4. The backend sets the session cookie (below) and redirects back to where the user was.

   **Continue with Google** (when enabled) is the same pattern: `GET /auth/google/start` (state, nonce, PKCE S256 in a sealed cookie on `/auth/google`, scopes `openid email profile` only) and `GET /auth/google/callback` (redirect URI `GOOGLE_REDIRECT_URI`, default `<API_URL>/auth/google/callback`), which checks `state` (single use), exchanges the code with the verifier and verifies the ID token: RS256 signature against Google's published keys, `iss`, `aud`, `exp`, `nonce`, `azp`, and `email_verified`. Then `auth_find_or_create_user('google', sub, email, name)` and the same session cookie. Google's access and refresh tokens are discarded, never stored.
4. First sign-in: the user picks a role (patient, doctor, researcher). Doctors and researchers then see an optional, skippable step for their work details: first and last name (prefilled from the sign-in account, nothing saved until they save), up to three institutions (atlas institutions or free text), an ORCID iD, and a private link to their own researcher or doctor entry, picked from up to five candidates matched by exact ORCID iD or by name, shared institutions first. The details are self-declared and private: never shown to others, never sent to a model, and saving them verifies nothing. Separately, a doctor or researcher can confirm their identity (ORCID sign-in, or a manual review of an institutional e-mail and a public profile page) and then switch on a public card, off by default, that signed-in users can open; it shows only what the person chose, labels the role as self-declared and says what was checked. While the role is doctor or researcher, the confirmed name is the display name. Switching the role to patient deletes them today (whether to delete or keep them hidden is not finally decided). Before the first chat message, profile save or upload, whichever comes first, one consent screen covers all processing of the user's own health and genetic data (`health_data`). It explains what is processed, that personal data is redacted, that raw files are deleted after extraction, and that nothing is shared without the separate `contribute` opt-in. The consent is stored with timestamp and text version (GDPR Article 9).
5. The requested feature proceeds.

### Sessions

- FastAPI issues its own session: a signed, `HttpOnly`, `Secure`, `SameSite=Lax` cookie holding a short-lived JWT (`sub` = user id), signed with a server secret (`SESSION_SECRET`), refreshed on activity. Logout clears it.
- The Next.js frontend never handles tokens; it calls the API with the cookie (same site, behind the same domain or with credentials enabled).
- OpenAI access tokens are refreshed server-side with the stored refresh token; if refresh fails, the user is asked to sign in again.

**Availability caveat:** Sign in with ChatGPT for websites is currently a limited trial for selected partners and needs a requested client ID. Request it immediately; if approval is late, the demo runs in guest mode or with the optional Google sign-in and a server key. Billing API usage to the user's ChatGPT plan is in scope and the main reason for this sign-in method.

### FastAPI dependencies

- `get_optional_user`: verifies the session cookie; returns the user (`user_id`, `role`, `role_verified`) or `None` for guests, and sets `app.user_id` on the request's database transaction.
- `require_user`: `401` with code `sign_in_required` for guests.
- `require_consent(type)`: `403` with code `consent_required` if no active consent of that type. There are two types: `health_data` (one general consent for chat, profile and uploads) and `contribute` (sharing into the shared graph).

### Role lenses

The role travels with every request and selects a lens: starting view, label style, explanation template and reading-level target. A lens never hides a node, edge or source.

The lens is the role in the user's settings (picked at first sign-in, changed on the profile page), never a separate choice; there is no "view as" switcher. Guests always get the guest lens.

## Backend services

Ten services, each a module under `/api/services`; the `PatientProfile` schema is the shared contract between chat, documents and graph search.

### Search

- Combines trigram matches on `node_synonyms`, vector matches on `nodes.embedding`, and a ranking boost by node type and centrality.
- Returns typed results (disease, gene, symptom, group, mechanism) with the synonym that matched, so the UI can show "Ohtahara syndrome → STXBP1 encephalopathy."
- Ids match directly: `MONDO:` and `HP:` ids (also without zero padding), and `ORPHA:` and `OMIM:` ids through the disease's `orpha_ids` / `omim_ids`.
- Search covers both tiers, so it also returns nodes that are not on the Atlas map.

### Graph

- Loads nodes and edges into memory at startup (NetworkX for queries, positions precomputed).
- `neighborhood(node, role)` returns the same neighborhood for every role; the role only adds presentation hints (starting layout, label style, which edge family is highlighted first). Hub nodes are capped at 300 neighbours (cluster members first, then by the best direct edge: active first, higher confidence); a cut response carries the headers `X-Neighborhood-Total` (the full count) and `X-Neighborhood-Truncated: true`, and the node page says so.
- `clusters()` serves cluster metadata.
- **Atlas tree** (`GET /atlas/tree.json`, `api/services/atlas_tree.py`): one tree per category. Only focus-tier diseases, genes, phenotypes and pathways are placed (other node types are always focus), clusters only when they have a focus member, and `edges` only between placed nodes. The Diseases trunk hangs the clusters under HPO groups from the clusters' `lineage`; the Symptoms trunk follows `hpo_lineage`; genes are grouped by chromosome. Built from the in-memory graph at startup and cached, with its layout, until the graph changes (shared contributions or flags are reloaded). Each category gets its own angular sector and its tree grows outward without overlaps; the layout is deterministic. The payload carries every tree node with its position, the category sectors and label positions, and all real edges, which the frontend draws only for a clicked node. Its ETag is keyed on the data version and `LAYOUT_VERSION` (bumped on every layout change). The old whole-graph layout (`GET /atlas.json`, pipeline positions) is still served, built on first request only, and no longer used by the frontend.
- **Atlas summary** (`GET /atlas/summary/{id}`): what a node is connected to, deterministic and without a model, read from the in-memory graph on every click. Direct links plus fixed chains of up to three hops per node type (for example a disease's researchers via its papers). Items are grouped into sections by type and ranked by the number of chains that reach them, then by the weakest link of the best chain; each section keeps its top 10. Each item carries the edge IDs of its best chain and a short "via …" label; membership of a computed cluster is marked as grouped by the atlas, not a direct link. The response also lists up to 20 edge IDs for "Write a summary". A node that is not on the map is summarised the same way, with an empty place in the tree. `coverage` is `focus` or `core`, and `focus_disease_count` gives the number of focus diseases for the panel's coverage line. An item reached by a single computed edge carries that edge's `explanation`.
- **Stats** (`GET /stats`): headline counts of the loaded graph (diseases, genes, symptoms, cited and computed links) with the `data_version`, computed once per data version, ETag on it. Docs and pages that show counts read them here instead of fixing numbers.

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

- Each turn runs on the server as a LangGraph graph, detached from the request: clients attach to it by run id and replay its numbered events, so a reload or a switch between the Atlas dock and `/chat` keeps the turn (details in [`agent.md`](agent.md)).
- SSE chat with tools: `extract_entities`, `resolve_to_ids`, `search_graph`, `get_neighborhood`, `find_path`, `match_phenotypes`, `ask_followup`.
- `match_phenotypes(present, absent)` ranks the atlas's diseases (both tiers) by how well their recorded symptoms overlap the user's, with the same similarity code as the pipeline; symptoms-only messages run it in code before the first round. Results are an overlap ranking with cited `has_phenotype` edges, never a probability or a diagnosis (details in [`agent.md`](agent.md)).
- Live entity extraction for chips: diseases → MONDO, genes → HGNC, variants (HGVS) → ClinVar, symptoms → HPO, with negation ("no feeding problems" = excluded), age, onset and country.
- Maintains the `PatientProfile`; chips are confirmed, corrected or removed by the user before they count.
- `ask_followup` asks at most one question at a time, chosen by which answer best separates the remaining candidate clusters, with quick-reply options, always skippable.
- Replies include tool results the frontend renders as cards (mini graph, patient group, evidence chips, "Open in Atlas"). Links from a reply to the Atlas go to plain `/atlas` and hand the found node and edge IDs over in memory, never in the URL.
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

### Calls

- Verified doctors and researchers with a visible card write surveys, studies and trials looking for participants (`calls`); a study or trial needs an ethics reference, a trial a registry ID (NCT, EU CT / EudraCT, DRKS); atlas IDs must exist.
- Default (`CALLS_REVIEW_REQUIRED=false`): draft -> submit (wording check: no offer, promise or price of a treatment) -> published at once through the definer function `publish_own_call()`, which takes only the caller's own draft or pending call live, re-checks the visible verified card, sets `calls.self_published` and logs a `self_published` row in `call_reviews`. Such a call shows "Published by the expert. Not reviewed by the Amber team."; `GET /me/calls` returns `review_required` so the form labels its button.
- With `CALLS_REVIEW_REQUIRED=true`: draft -> submit (same wording check) -> the operator approves or rejects with `backend.cli calls ...` through the definer functions `pending_calls()` and `review_call()`, every action logged in `call_reviews`.
- The trigger `calls_guard` stops the API role from publishing any other way, from changing review fields, `demo` or `self_published`, and from editing a published call. Published calls are listed to every signed-in user while the publisher's card stays visible (`call_publisher_cards()` joined with `professional_cards()`); nothing about readers is stored. `backend.cli demo-calls` seeds labelled demo calls locally.

### Proposal export and data rights

- Generates a one-page sourced proposal from a path, its assets and contacts (HTML for print-to-PDF).
- `GET /me/export` returns all user data as JSON; `DELETE /me` deletes the account with cascade.

## API

| Method | Path | Access | Returns |
| --- | --- | --- | --- |
| GET | `/auth/chatgpt/start` | Anyone | Redirect to OpenAI (OIDC + PKCE) |
| GET | `/auth/chatgpt/callback` | Anyone | Session cookie, redirect back |
| GET | `/auth/google/start` · `/auth/google/callback` | Anyone, only when Google sign-in is enabled (else 404) | Redirect to Google (OIDC + PKCE) · session cookie, redirect back |
| POST | `/auth/logout` | Signed in | Session cleared |
| GET | `/search?q=` | Anyone | Typed matches with matched synonym |
| GET | `/node/{id}` | Anyone | Node details + summary for the side panel |
| GET | `/neighborhood/{id}` | Anyone | Neighborhood with positions + role presentation hints; at most 300 neighbours, a cut is reported in `X-Neighborhood-Total` / `X-Neighborhood-Truncated` |
| GET | `/clusters` | Anyone | Cluster IDs, labels, sizes |
| GET | `/atlas/tree.json` | Anyone | Atlas hub and category trees (focus tier) with positions, the edges between them, clusters (ETag) |
| GET | `/atlas/summary/{id}?role=` | Anyone | A node's place in the tree, headline, ranked connections by section, edge IDs for a written summary, `coverage` and `focus_disease_count` |
| GET | `/stats` | Anyone | Counts of diseases, genes, symptoms, cited and computed links, with the data version (ETag) |
| GET | `/path?from=&to=&family=` | Anyone | Ordered path steps, or `no_supported_route` + coverage report |
| GET | `/edge/{id}/evidence` | Anyone | Sources, quotes, tiers, contradictions |
| POST | `/explain` (SSE) | Anyone for cached explanations; signed in to generate new ones | Streamed role-specific explanation of a path with citation IDs; with `subject_node_id`, a summary of that node's connections |
| POST | `/chat` (SSE) | Signed in + health-data consent | Starts the turn's run; streamed reply, chips, cards, follow-up question |
| GET | `/chat/runs` | Owner | The user's running turns |
| GET | `/chat/runs/{id}/events?after=` (SSE) | Owner | Replay a run's events after a sequence number, then follow it |
| DELETE | `/chat/runs/{id}` | Owner | Stop a running turn (stored as interrupted) |
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
| GET / PUT | `/me/professional` | Signed in, doctor or researcher | Private work details, a name suggestion from the ChatGPT account (not stored) and the linked atlas entry · replace them |
| DELETE | `/me/professional` | Signed in (any role) | Work details deleted |
| POST | `/me/professional/matches` | Signed in, doctor or researcher, rate-limited | Up to five atlas entries that may be the user; stores nothing |
| GET / PUT | `/me/professional/card` | Signed in (PUT on: verified doctor or researcher, rate-limited) | Own verification state, card settings and a preview · replace the settings (off always works) |
| POST | `/me/professional/orcid/start` · GET `/me/professional/orcid/callback` | Signed in, doctor or researcher, rate-limited | ORCID sign-in URL (or the local simulated one) · redirect back with `?orcid=confirmed\|denied\|failed\|already_linked` |
| POST / DELETE | `/me/professional/verification-request` | Signed in, doctor or researcher, 3 a day | Manual review request (approved at once in local demos) · withdraw it |
| GET | `/people?disease=` · `/people/{card_id}` | Signed in, rate-limited | Visible verified cards linked to a disease through their verified atlas entry · one card |
| GET · PUT | `/me/connect` · `/me/connect/age-group` | Signed in (PUT: + connect consent) | Connect consent state, age group, checkbox texts · state or correct the age group |
| GET · POST | `/me/threads` | Signed in (POST: + connect consent, patients only, 5 per day) | My conversations with unread counts · a message request to a professional's card |
| GET | `/me/threads/unread-count` · `/me/threads/{id}` | Signed in, participant | Unread messages and waiting requests · a conversation (marks it read) |
| POST | `/me/threads/{id}/accept` · `/decline` · `/messages` | Participant + connect consent | Accept or decline a request (recipient only) · send a plain-text message |
| DELETE · POST | `/me/threads/{id}/messages/{mid}` · `/hide` · `/block` · `/report` | Participant | Delete my message for both · hide · block the other person · report (authorizes a logged review) |
| GET · DELETE | `/me/blocks` · `/me/blocks/{id}` | Signed in | My blocks · unblock |
| GET | `/calls?kind=` · `/calls/{id}` | Signed in (16+), rate-limited | Every published, still open call with its publisher's card, the review badge and the "ask your doctor" notice · one call |
| GET | `/me/calls` · `/me/calls/{id}` | Signed in | Own calls in every status with review note and wording-check result · one |
| POST · PUT | `/me/calls` · `/me/calls/{id}` | Verified doctor or researcher with a visible card, rate-limited | New draft (at most 10 open calls) · replace a draft, rejected or pending call (back to draft) |
| POST | `/me/calls/{id}/submit` · `/close` · DELETE `/me/calls/{id}` | Submit: as above, 10 a day; close and delete: owner | Publish at once after the wording check (to review instead when `CALLS_REVIEW_REQUIRED` is on) · close a published call or withdraw an unpublished one · delete |
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
- Automatic reach-out from patients to other patients. (Patients writing to verified doctors and researchers themselves is built: messaging under the `connect` consent.)
- Automatic warm introductions between research groups.
- Automatically connecting patients to studies and trials.

## Project names

- **Amber — Rare Disease Atlas.** Logo: amber with a DNA sequence inside.
- **Dr. Wu** for the AI assistant (Jurassic Park reference; check trademark risk before submission).
