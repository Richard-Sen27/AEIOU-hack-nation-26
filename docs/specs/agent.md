# Amber Agent Spec — "Dr. Henry Wu"

Detailed design of the chat orchestrator. [`system.md`](system.md) is the source of truth for everything else (frontend, pipeline, database, auth, API); where this document and `system.md` differ, `system.md` wins. Privacy rules are in [`../compliance.md`](../compliance.md).

## Overview

Dr. Henry Wu is the conversational agent of the Amber Platform: it turns a patient's words, documents and questions into cited paths through the rare-disease knowledge graph, and ends every session with a concrete shared action. It never answers from model memory alone. Every claim it shows is backed by a graph edge with a source, a date and a confidence level.

**In scope for the 24h build**

- Chat intake of a disease, gene, variant, symptom or patient group, resolved to stable IDs (MONDO, HGNC, HPO, ClinVar) and shown as chips the user confirms
- Using user-confirmed findings from the document service (the agent never reads raw uploads)
- Graph exploration: neighbourhoods, mechanism and phenotype clusters, most-trustworthy cited paths
- Action layer: shared assets, overlapping researchers or funders, trials, a proposed next step
- Trust layer on every answer: observed vs. inferred, contradictions, and named missing evidence

**Out of scope**

- Diagnosis, treatment advice, prognosis or variant reclassification
- Writing to the shared graph; agent output never becomes trusted evidence (gap-search results stay `pending_review`)
- Contacting researchers, groups or funders on the user's behalf. Users write to verified professionals themselves (messaging, `connect` consent); Dr. Wu never reads, sends, summarizes or drafts those messages and has no tool that reaches them

**Success criteria (mapped to judging)**

| Criterion | What the agent must show |
| --- | --- |
| Graph quality | Answers navigate typed nodes and edges; clusters come with their shared mechanism and a counterexample |
| Evidence integrity | 100% of displayed claims carry a source link; inferred links are labelled as hypotheses |
| Patient progress | One full journey: diagnosis → related cluster → reusable asset → next milestone |
| 10× impact | The action plan states today's timeline, the proposed route, and its assumptions |
| Product craft | Plain-language summary first, detail on click; reading level checked with textstat |

## Personas and lenses

The agent is available only to users signed in with ChatGPT; its LLM calls are billed to the user's own ChatGPT plan. Guests can explore the graph but get no agent features (see Sign-in in `system.md`). The agent adapts starting point, depth and vocabulary to the role lens (patient, doctor, researcher), but the underlying tools, graph and evidence are identical for everyone. A lens never hides a node, edge or source.

| Persona | Role lens | Job to be done | What the agent returns |
| --- | --- | --- | --- |
| Maria, patient-group leader (main) | patient | Who shares our disease characteristics? What already exists? What should we do together next? | Related clusters with the shared mechanism, reusable assets, partner groups and one next experiment |
| Devon, newly diagnosed caregiver | patient (explores as a guest first) | Find our exact community, or the closest ones, in plain language | Matching patient groups ranked by mechanism and phenotype overlap, at a grade-8 reading level |
| Priya, biotech scout | researcher (expert mode) | Rank disease clusters my therapeutic mechanism could treat | Ranked cluster list with patient counts, trial activity and evidence strength per cluster |
| Dr. Osei, academic researcher | researcher / doctor | Find people working on the same mechanism under other gene names | Researchers, papers and grants linked via shared pathway nodes, with the connecting edges shown |

Starting points per lens (from `system.md`): patients start at their disease; doctors at the symptom profile; researchers at mechanism clusters. Expert mode is open to everyone and the default for researchers; it accepts mechanism queries ("AAV gene replacement for loss-of-function") and returns ranked clusters.

**Three questions the agent must always be able to answer for a patient leader**

1. Who shares our disease characteristics?
2. What useful work already exists (registries, models, studies)?
3. What should we do together next?

## Architecture

One orchestrating agent with typed tools beats a multi-agent swarm for a 24h build: fewer moving parts, one trace per turn, and every answer passes the same two gates.

```
User message ─▶ Presidio redaction ─▶ Chat orchestrator (POST /chat, SSE)
                                          │  tools (in-process calls to backend services)
                                          ▼
                       search · graph (in-memory NetworkX) · path · explanation
                                          │
                                          ▼
                              Citation post-check + safety post-check ─▶ streamed reply

no_supported_route ─▶ Gap-search agent (POST /gap-search, separate) ─▶ candidate edges, pending_review
Offline ingestion pipeline ─▶ the only writer of trusted graph edges
```

User input is redacted before the model sees it; the model only reaches data through tools; the citation and safety checks run on every reply before it is streamed.

**A turn is a LangGraph graph run on the server** (`api/services/chat/agent.py`, `runs.py`). Nodes: `safety` (boundary categories; emergency → `emergency`, a fixed reply without a model call) → `entities` (extract_entities, resolve_to_ids, match_phenotypes) → `agent` (the tool rounds and the final answer inside the gateway's `run_tools`, same budgets) → `partial` (only when the deadline or bad output cut the turn) → `postcheck` → `persist` (the reply and the end of the run in one transaction). Redaction and emergency detection run before the graph, so raw text never enters it. The run keeps going when the client goes away: its events carry sequence numbers, any client of the same user can attach (`GET /chat/runs/{id}/events?after=N`), and the dock and `/chat` show the same turn. A session has at most one running turn (409 otherwise). Stop cancels the run (`DELETE /chat/runs/{id}`); it is stored as an interrupted turn. State is checkpointed after each node into the run's own `chat_runs` row (redacted content only, deleted when the turn ends). A run whose API process died is not resumed: it is stored as an interrupted turn, and "Try again" reruns it. The graph is precomputed offline (clusters, layouts, similarity and mechanism edges, demo-path explanations), so a chat turn only reads. Langfuse traces each turn end to end.

## Tools

The orchestrator has the seven tools defined in `system.md`. They wrap the backend services, so the agent sees exactly what the API serves. Tool inputs and outputs are Pydantic models that double as the OpenAI JSON schemas.

| Tool | Input | Output | Service |
| --- | --- | --- | --- |
| `extract_entities` | redacted user text | candidate chips: diseases, genes, variants (HGVS), symptoms, with negation ("no feeding problems" = excluded), age, onset, country | LLM (Structured Outputs); run by the orchestrator before the first round, not offered to the model |
| `resolve_to_ids` | extracted mentions | stable IDs with score: diseases → MONDO, genes → HGNC, variants → ClinVar, symptoms → HPO | Search |
| `search_graph` | query, node types, limit | typed matches with the matched synonym ("Ohtahara syndrome → STXBP1 encephalopathy"); in expert mode, mechanism queries return ranked clusters | Search (trigram + pgvector + type/centrality boost) |
| `get_neighborhood` | node id, role | full neighbourhood with positions, edges with evidence summaries, cluster membership, role presentation hints | Graph |
| `find_path` | from id, to id, edge family (dna / symptoms / research / all) | top-k paths by edge cost `−log(confidence)`, or `no_supported_route` with a coverage report (sources queried, closest partial path, missing link, suggested next question) | Path |
| `match_phenotypes` | `present` and `absent` symptom mentions (at most 20 each) | the top 10 diseases by symptom overlap, each with `overlap` (how many of the user's symptoms are recorded for it) of `of`, a similarity `score`, the shared terms (user's symptom, recorded term, match `same` / `more_specific` / `broader`, frequency when recorded, and the `has_phenotype` `edge_id`), recorded symptoms the user said are absent, and unresolved mentions | Phenotype matching over the in-memory `hpo_terms` table and the graph; run in code before the first round for symptoms-only messages, offered to the model for symptoms that run lacked |
| `ask_followup` | remaining candidate clusters | at most one question, chosen by which answer best separates the candidates, with quick-reply options; always skippable | Orchestrator |

How the action layer maps onto the graph (all precomputed edges, read via `get_neighborhood` and `find_path`):

- **Who shares characteristics:** `same_gene_same_mechanism`, `shared_gene`, `shared_pathway`, `similar_symptoms` edges and the node's cluster; `near_on_chromosome` between their genes is weak evidence only. All of these are computed hypotheses (`origin = inferred`) with a one-line `explanation`.
- **Counterexample:** `same_gene_different_mechanism` edges (e.g. SCN2A gain- vs. loss-of-function).
- **Reusable assets:** `serves` and `runs` edges (organization → registry or study).
- **Common people and funders:** `shared_researcher`, `authored`, `pi_of`, `funds_research_on`, `investigator_of`.
- **Trials:** `studies` edges (trial → disease), ingested from ClinicalTrials.gov.

**`match_phenotypes` in detail.** Mentions resolve against the HPO term table (an HP id, an exact label, a synonym, a singular form, then a fuzzy match), so terms that are not graph nodes still resolve. Every disease with recorded symptoms is ranked, core and focus tier alike, so diseases that are not on the Atlas map can be returned. The score is the shared `phenotype_similarity` function the pipeline uses for `similar_symptoms` (information content over the whole HPO annotation corpus, the disease's recorded frequencies, the user's symptoms at weight 1), reduced by the share of the user's symptoms that contradict the record: symptoms the user said are absent but the disease records, and present symptoms the disease records as excluded. Only diseases with at least one shared term are returned. It adds no model round-trip.

What the agent may claim from it: these are "conditions in the atlas whose recorded symptoms overlap", with the overlap count ("3 of your 4 symptoms are recorded for it"), each shared symptom citing its `has_phenotype` edge. The score is a similarity, not a probability: never a probability, likelihood or percentage, never "you have" or "this is", never a diagnosis; the conditions are to discuss with a clinical geneticist. The tool result carries this rule as a note, and the system prompt repeats it.

The reply carries the ranking as `symptom_match`, built by the post-check from the tool result, never from the model's text: the top 5 conditions with `overlap` of `of`, whether each is on the Atlas map, and each shared or contradicting symptom with its `has_phenotype` edge (a term whose edge the turn did not return is dropped, and so is a condition left without one); no score. The chat page and the Atlas dock show it as a card ("Symptom overlap in the atlas data, not a diagnosis."); conditions on the map open in the Atlas, the others their node page. The post-check also removes summary sentences and claims that give the overlap as a probability, likelihood or percentage. The eval's `symptoms` check (chronic cough) asserts the ranking, a cited `has_phenotype` edge and no such wording.

## Graph and evidence model

Defined in `system.md` (Graph data model, Database). What the agent relies on:

```json
{
  "id": "e_123",
  "source_id": "MONDO:0010679",
  "target_id": "HGNC:2928",
  "relation": "caused_by_variant_in",
  "family": "dna",
  "confidence": 0.92,
  "origin": "observed",
  "status": "active",
  "features": null,
  "data_version": "2026-10-03.1",
  "evidence": [
    {"tier": "curated_db", "source_type": "ClinVar", "source_id": "VCV000012345",
     "url": "…", "quote": "…", "retrieved_at": "2026-10-03", "polarity": "supports"}
  ]
}
```

- `origin` is `observed`, `inferred`, `patient_reported` or `user_contributed`. Only `observed` is rendered as data; `inferred` is rendered as a hypothesis; `patient_reported` and `user_contributed` carry their own labels.
- `status` other than `active` (`pending_review`, `under_review`) is shown with a visible flag and never used as support for an action.
- `confidence` comes from the Stage 4 formula (tier weights, minus a penalty of 0.1 per contradicting evidence item) and is shown as High / Medium / Low with the breakdown on click. Computed links have tier `computed`, are capped per relation (at most 0.79, chromosome proximity 0.45), so they never show as High, and carry `explanation`, a one-line reason the link exists, which the tools pass to the model with the edge.
- Evidence with `polarity: contradicts` must be surfaced next to the claim.
- VUS variants are stored with classification `uncertain_significance` and are excluded from path-finding unless the user asks.

## Workflows

W1 → W3 → W4 together are the one complete journey the 24h goal asks for.

**W1 — Chat intake**

1. User types a disease, gene, variant or symptoms ("My daughter is 2, diagnosed with STXBP1 last month. Lots of seizures, not walking yet, no problems with eating.").
2. Redact, then `extract_entities` → `resolve_to_ids`, both in code before the first model round, so the model starts from the resolved IDs. A message with symptoms but no disease, gene or variant also runs `match_phenotypes` in code, and the model starts from its ranking. The resolved items appear as chips the user confirms, corrects or removes; only confirmed chips enter the `PatientProfile`.
3. If resolution is ambiguous or several clusters remain, `ask_followup` asks one skippable question with quick replies.
4. Open the resolved node in the graph view at the lens's starting point (one global search principle).
5. Reply: two-sentence plain summary, then cards (mini graph, patient group, evidence chips, "Open in Atlas").

**In the Atlas: the Dr. Wu dock.** The same chat runs in a dock in the bottom-left corner of the Atlas, under the same sign-in and `health_data` consent. Free text typed into the Atlas search bar is offered to the dock instead of the search. On each final reply, the node IDs from `graph_focus.node_ids`, the cards and the unnegated chips that exist in the Atlas are highlighted and framed on the map, `graph_focus.highlight_path` is drawn, and the nodes are listed as "Dr. Wu found N". The question and these found node IDs are health data: they stay in memory only, never in the URL (no `?focus=`, no links that carry them) and never in browser storage.

**From the chat to the Atlas.** "Show in graph" and the "Open in Atlas" links of a reply on `/chat` point to plain `/atlas` with no query string. Activating one hands the reply's node IDs and `graph_focus.highlight_path` to the Atlas in memory (`components/atlas/atlas-handoff.ts`) and navigates client-side; the Atlas takes the handoff once on load and shows it exactly like the dock's finds. A new tab or a full page load starts without highlights.

**W2 — Documents** (handled by the document service, not by the agent)

1. Upload requires sign-in and an active `health_data` consent (`POST /documents`); guests see the inline sign-in dialog first.
2. The service extracts text locally, redacts with Presidio, classifies, runs structured extraction and stores findings with page and snippet; raw bytes are deleted on completion.
3. The user confirms or rejects each finding on the review screen (`POST /findings/{id}/confirm` · `/reject`).
4. Confirmed findings update the `PatientProfile`; the agent then re-runs W3 with the enriched profile. VUS findings carry the standard uncertainty sentence.

**W3 — Cluster discovery**

1. `get_neighborhood` on the profile's disease: cluster membership plus mechanism and symptom edges.
2. For each relevant cluster member, `find_path` back to the user's disease; keep paths whose edges all pass the confidence threshold (default 0.6).
3. Present: who shares the mechanism, who shares the phenotype ("similar experience, possibly different cause"), and one counterexample.

**W4 — Action plan**

1. From the user's disease and the top 2–3 cluster members, collect shared assets, common researchers and funders, and trials (see the action-layer mapping above).
2. Sort leads into *viable* (all supporting edges observed and active) and *unsupported* (any inferred edge, non-active status or open contradiction).
3. Propose one next step (e.g. reuse the registry of a related community instead of building one), with today's timeline vs. the proposed route and the assumptions behind it.
4. Output as an action card; signed-in users can export it as a one-page sourced proposal (`POST /proposal`).

**W5 — Gap search** (stretch, separate agent)

1. Triggered when `find_path` returns `no_supported_route`; the user starts it from the coverage report.
2. `POST /gap-search` runs the OpenAI Agents SDK agent with `pubmed_search`, `clinicaltrials_search`, `web_search` (Bright Data) and `fetch_page`, under hard budgets (max steps, max tokens, 90 s).
3. Queries are built from graph IDs and public terms only, never from profile text or chat messages.
4. Results are candidate edges with quotes and sources, always `pending_review`, never promoted automatically.

Ingestion is the offline pipeline described in `system.md`; it is not part of the agent.

## Trust, safety and privacy

The agent is a navigator, not a clinician: it may say what the evidence connects, never what a patient should do medically.

**Evidence rules (enforced in code, not only in the prompt)**

- A post-processor checks every claim in the reply against the edge IDs returned by tools in this turn; a claim citing anything else is removed or the reply is regenerated.
- Observed and inferred links are styled differently in text and graph (solid vs. dashed) and labelled "data" vs. "hypothesis".
- Contradicting evidence is always shown next to the claim it contradicts.
- No supported route → the agent says so, names the missing evidence ("No source links gene X to pathway Y; a functional study would close this gap"), and offers gap search.

**Uncertainty**

- VUS findings show: "This result is uncertain. Discuss it with a genetic counselor before acting on it."
- Low-confidence answers (all paths below the threshold) open with a one-line uncertainty statement before any content.

**Medical boundary** (system prompt + post-check)

- Emergency detection runs first: acute symptoms or crisis language → short message to call emergency services, no graph answer.
- No diagnosis: symptoms-only input maps to clusters "to discuss with a clinical geneticist".
- No treatment choice, dosing or variant reclassification; redirect to a clinician or genetic counselor while still offering the graph context.
- No prognosis or mortality figures unless the user asks.

**Privacy**

- Presidio redaction runs before every LLM call on user content, including chat messages, not only uploads.
- The agent never sees raw uploads; only confirmed findings reach the profile.
- Chat, the profile and uploads run under one `health_data` consent, asked once before the first chat message, profile save or upload; without it the agent does not process the user's messages.
- Profiles are private to the user; contributions to the shared graph need an active `contribute` consent and are stored as `patient_reported`.
- Gap search and web search never receive user data.
- Messages between users (`connect` consent) never reach the agent or any model: no tool reads them, nothing is redacted or rewritten.
- All agent LLM calls run on the signed-in user's own ChatGPT plan; guests never reach the agent.

## Output contract, prompt and runtime

Every agent turn returns one structured object (OpenAI Structured Outputs); the frontend renders it, so the model never emits free-form markup.

```json
{
  "summary": "Plain-language answer, max 3 sentences, at the lens's reading level",
  "uncertainty": "null or one sentence",
  "chips": [{"type": "disease|gene|variant|symptom", "id": "…", "label": "…", "negated": false, "confirmed": false}],
  "claims": [
    {"text": "…", "edge_ids": ["e_123"], "origin": "observed|inferred|patient_reported|user_contributed", "confidence": "high|medium|low"}
  ],
  "contradictions": [{"claim_index": 0, "edge_ids": ["e_456"], "note": "…"}],
  "missing_evidence": ["…"],
  "cards": [{"type": "mini_graph|patient_group|evidence|open_in_atlas", "node_ids": ["…"], "edge_ids": ["…"]}],
  "graph_focus": {"node_ids": ["…"], "highlight_path": ["e_123", "e_789"]},
  "actions": [
    {"title": "…", "type": "reuse_asset|contact|join_trial|fund", "viable": true, "edge_ids": ["…"],
     "timeline_today": "…", "timeline_proposed": "…", "assumptions": ["…"]}
  ],
  "follow_up": {"question": "…", "quick_replies": ["…"], "skippable": true},
  "symptom_match": {"items": [{"id": "…", "label": "…", "overlap": 2, "of": 3, "on_map": false,
    "shared": [{"user_symptom": "…", "recorded_as": "…", "match": "same|more_specific|broader", "edge_id": "e_123"}],
    "absent": []}]}
}
```

**System prompt (core)**

```text
You are Dr. Henry Wu, the guide of the Amber rare-disease atlas.
You help patients, caregivers, researchers and biotech scouts find
what connects rare diseases: shared mechanisms, symptoms, people,
assets and trials.

Rules:
1. Answer only from tool results. Every claim cites edge_ids.
2. Label each claim by origin. Never present inference as fact.
3. Always surface contradicting evidence.
4. If no supported path exists, say so and name what evidence is missing.
5. Summary first, in plain language for the user's role; detail goes in claims.
6. Never diagnose, recommend treatment, give prognosis unless asked, or reclassify variants.
   For VUS results, use the standard uncertainty sentence.
   Emergency language: tell the user to call emergency services and stop.
7. End with one concrete, viable next action when the evidence allows it.
8. Ask at most one follow-up question, only when it separates candidate clusters.
9. Reply in the user's language.

User role: {role}. Expert mode: {expert_mode}. Profile: {confirmed_profile_json}.
```

**Runtime**

- OpenAI Responses API with function calling. Budget per turn, enforced in code: after the extraction and resolution, at most 3 tool rounds and 15 s of tool work (and 8 tool calls); then the final answer is written with tools disabled and names in `missing_evidence` what it could not check. A 90 s deadline is the backstop: when it fires, the turn answers in code from the edges its tools returned (one cited edge per claim, post-checked as usual), or ends with an error if it gathered nothing. The post-check's own model calls stop at the deadline.
- A turn that ends in an error (deadline, model error, sign-in expired, stopped, API restart) is stored as an assistant message holding only the error code, message and status steps the stream showed; the session view shows it with "Try again", and a retry (`retry_message_id`) replaces it without storing the user's message again.
- Billing: every agent call runs on the signed-in user's ChatGPT plan usage, using their stored OpenAI token. The team key is used only by the offline pipeline.
- The gap-search agent uses the OpenAI Agents SDK with its own budgets.
- Planner/answer model: the strongest OpenAI model on the team's credits; extraction and classification on a smaller, cheaper model; embeddings via OpenAI embeddings into pgvector. On a ChatGPT plan whose model list offers no smaller model, the small calls use the main model. Tool-selection rounds and the extraction ask for low reasoning effort only when the model list advertises it; the final answer keeps the default.
- Streaming over SSE (`POST /chat`, or attached later with `GET /chat/runs/{id}/events`): status steps, then `summary`, then chips, claims, cards and actions; each frame's SSE `id` is its sequence number in the run.
- Path explanations go through the Explanation service (`POST /explain`), which is cached per `(path_id, role, language, data_version)` and gated by textstat per role. With `subject_node_id` the same service writes a summary of one node's connections (the Atlas panel's "Write a summary"), citing only the edges listed for that node.

**Endpoints the agent uses or produces** (full API in `system.md`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/chat` (SSE) | Send a message, start the turn's run and stream it |
| GET | `/chat/runs`, `/chat/runs/{id}/events` (SSE) | Running turns; attach to one (replay after `after`, then live) |
| DELETE | `/chat/runs/{id}` | Stop a running turn |
| GET / PUT | `/profile` | Read or update the `PatientProfile` (confirmed chips and findings) |
| POST | `/explain` (SSE) | Role-specific explanation of a path with citation IDs, or with `subject_node_id` a summary of one node's connections |
| GET | `/edge/{id}/evidence` | Full evidence for the trust panel |
| POST | `/gap-search` (SSE) | Gap-search agent progress and candidate edges |
| POST | `/proposal` | Export an action plan as a one-page sourced proposal |

## Evaluation, build plan and open questions

**Evaluation (run before the demo)**

- 20 golden questions, five per persona, each with expected node IDs; pass = expected IDs appear in `graph_focus` or `claims`.
- Citation check: 100% of claims have valid edge IDs (automated).
- Inference labelling: seeded inferred edges must never appear as `observed`.
- Redaction test: 10 synthetic reports with fake names and IDs; zero PII in Langfuse traces.
- Readability: textstat Flesch-Kincaid grade ≤ 8 on `summary` in patient mode.
- Refusal test: 5 diagnosis or treatment prompts must be declined with graph context still offered.
- Graph validation (Stage 6 in `system.md`) must pass: SCN1A → Dravet syndrome is found; SCN2A gain- and loss-of-function diseases do not share a mechanism cluster.

**Observability**

Langfuse traces every turn: tool calls, latency, token cost, cited edge IDs, and post-processor removals. Traces store redacted text only.

**Build order**

The agent follows the system build order in `system.md`: it needs the graph and the search, graph and path services (steps 2–4) first. Its own parts are the explanation service (step 7), the chat orchestrator with chips, profile and follow-ups (step 9), and the gap-search agent and proposal export (step 11). The golden-question eval runs before recording the 1-minute family walkthrough.

**Open questions**

- [ ] Which disease cluster is the demo journey (needs good ClinVar, trial and patient-group coverage)? The examples point to STXBP1 and the SCN1A/SCN2A channelopathies.
- [ ] Final assistant name: "Dr. Henry Wu" is a Jurassic Park character; a trademark-safe original name may be safer for the submission.
- [ ] OMIM is optional and needs a registered key; request it now or rely on MONDO cross-references.
- [x] The confidence threshold for "supported" paths is 0.6 and the contradiction penalty `p` is 0.1.
