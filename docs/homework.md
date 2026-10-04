# Homework

Work deliberately left for later. Add an item when you leave something for later; check the area's section before starting work there; remove an item when it is done. One line per item: where, what, and, when known, why it was left and what the fix would be.

## Atlas view

- **Category labels on phones** (`apps/backend/src/backend/api/services/atlas_tree.py`, `LABEL_CHAR_WIDTH = 0.006`): at 390 px the labels are 4.6–7.9 px, because the boxes the backend reserves for them scale with the map. Fix: let labels outgrow their box on phones, or raise `LABEL_CHAR_WIDTH` to about 0.0105 (a layout change).
- **Label under the search bar:** at 1024 px in the doctor lens, the "Clinical features" label sits partly under the map search bar.
- **Group names at 390 px:** some are drawn under the logo or cut off at the canvas edge.
- **Portrait phones:** the landscape-shaped map leaves empty space above and below.
- **Busy trunks:** Genes is the busiest, with long chromosome branches and some crossing lines; Literature has long spokes.
- **Selecting the busiest node** costs one frame of 100–150 ms in dev mode, mostly the panel mounting.
- **"Other organisations"** still holds 29 institutions after the name keyword rule (`institution_kind` in `atlas_tree.py`).
- **`GET /atlas.json`** (`api/routes/graph.py`, `graph.atlas_payload`) is no longer used by the frontend and can be removed, together with its mock in `apps/frontend/e2e/graph/fixtures.ts`.

## Node, path and panels

- **Nested edge features** (`apps/frontend/src/components/node/edge-panel.tsx`, `FeatureValue`): objects such as `basis` and `mechanisms` fall through to `String(value)` and print "[object Object]".
- **Path flow labels** (`components/path/path-flow.tsx`): the compact edge labels do not show a computed link's explanation; the steps list and the evidence sheet do.
- **"Write a summary" template** (`api/services/explanation/templates.py`): the template text does not quote a computed link's explanation.
- **Trailing periods** (`relation_sentence` in `templates.py`): paper titles that end in a period produce "…syndrome. is about". Fix: strip a trailing period from labels before formatting.
- **Sign-in from `/path?from=…&to=…`** drops the pair: `signIn` in `components/providers/session-provider.tsx` keeps only the path, because query strings could carry user input.
- **Profile variants** (`components/account/profile-editor.tsx`): a variant whose gene is not in the gene list shows its raw HGNC id in the gene select.

## Chat (Dr. Wu)

- **No log handlers:** the backend configures none, so INFO lines from `backend.*` (for example "chat turn failed") never reach the server log; only the chat timing logger has its own handler.
- **Ids in chat links:** links from a chat answer to a node page (`/node/<id>`, `components/chat/cards.tsx`, `mini-graph.tsx`) and to `/path?from=…&to=…` (`assistant-turn.tsx`) still carry an id in the URL; the Atlas links were moved to an in-memory handoff. A decision on these is open.
- **Reasoning effort unverified** (`llm/client.py`, `reasoning`): tool rounds, the extraction and the reading-gate rewrite ask for `low` effort only when the model list advertises `supported_reasoning_levels`; whether the ChatGPT-plan gateway lists or accepts it is unknown until a real turn (the timing log shows the effect; a 400 on `reasoning` switches it off).
- **No smaller model on the plan:** the user's model list resolves `small` to the main model (`gpt-6-astra`), so the extraction costs a full model call (about 5 s). `OPENAI_MODEL_SMALL` can pin a faster model if the plan offers one.
- **Reading gate time** (`api/services/chat/postcheck.py`): for patient and guest lenses, a summary above grade 8 costs one or two more small-model calls (about 4 s each), bounded by the turn deadline.
- **Cold model list:** the first turn per account every 6 h waits for the model listing (about 2 s, partly hidden behind redaction).
- **Dock has no history:** the Atlas dock starts empty and never loads stored sessions, so a stored failed turn shows on `/chat` only; the dock's live retry does not store the message twice.
- **Retry of an older failed turn** returns 409 when a later message exists in the session; the UI still offers "Try again" on such turns in a reloaded session.
- **Real model untested:** answer quality, document extraction, the gap-search agent, written explanations and summaries were covered only by the mock.

## Data and pipeline

- **"UCB Cares"** (`DOC:2b11f0e39516`), a sponsor contact, is stored as a doctor and ranks first among Dravet syndrome's doctors.
- **Paper ranking:** every paper `about` edge has confidence 0.70, so paper lists cannot be ranked; several papers are titled just "[Dravet syndrome]."
- **Dravet syndrome** (`MONDO:0100135`) has no ORPHA or OMIM id: Orphanet maps ORPHA:33069 to `MONDO:0011794`, which is not in scope.
- **Multi-gene copy-number variants:** the cached ClinVar file holds single-gene rows only, so they are missing and the copy-number boost for `near_on_chromosome` fires for 2 pairs only. Fix: a coordinate-based re-filter of ClinVar.
- **`shared_gene` density:** links are dense per gene (SCN1A links 64 disease pairs); a per-disease cap may be worth adding.
- **MT-TL2 coordinates:** MANE has no mitochondrial genes (`sources/mane.py`), so MT-TL2 has none.
- **Onset** is recorded on only 48 `has_phenotype` edges.
- **Scope selection** (`scope.py` via `hpo_sim.ic`, `IC_KIND = "omim"`) still uses pyhpo's OMIM-only information content, not the corpus-wide one.
- **Unused constant:** `PHENOTYPES_PER_DISEASE = 40` in `bio.py`; the real cap is `phenotypes_per_disease` in `seeds.yaml`.
- **Model steps never run:** abstract extraction, cluster labels and model-written explanations need `make pipeline-login` and a run with `PIPELINE_LLM_MAX_CALLS`.
- **Docker run:** a full pipeline run inside Docker is unverified.
- **Stale graph after a load:** the API keeps serving the old graph until it is restarted. Fix: a reload hook.

## Privacy and compliance

- **Missing documents:** `docs/incident.md`, `docs/dpia.md`, `docs/ropa.md`.
- **`/privacy` placeholders** (`apps/frontend/src/app/privacy/page.tsx`, `ToBeCompleted`): controller name and address, `NEXT_PUBLIC_PRIVACY_EMAIL`, hosting provider and region, supervisory authority.
- **Privacy notices** are English only.
- **Redaction** misses a bare first name in unlabelled prose (worse in German).
- **Test addresses** (`apps/backend/tests/platform/test_redaction.py`): two invented addresses at real mail domains (gmail.com, outlook.com); switch to example domains.
- **Graph backup** `apps/pipeline/data/backups/atlas-graph-2026-10-04.9.dump` falls under the 30-day backup rule in [`retention.md`](retention.md) and must be deleted by 2026-11-03.
- **Second read** for texts shortened next to compliance wording: the contribute-consent note on suggested links, the age line, the export text, the delete text.

## Documents

- **OCR** is basic (clean scans, English); HEIC decoding is untested.
- **Drop zone** has empty space because the panel next to it sets its height.

## Landing page

- **Sign-in dialog** opened from the landing input (`components/landing/hero-input.tsx`) starts with a sentence that repeats the landing copy.
- **Hero input** has empty space under its placeholder on desktop (its `min-h`).

## Tests and tooling

- **Flaky spec:** `apps/frontend/e2e/account/documents.spec.ts` "pending uploads from the landing page are picked up" fails intermittently.
- **Dev-only error** "Router action dispatched before initialization" has made specs fail and pass on rerun.
- **GPU:** the Atlas needs a real GPU; software rendering is too slow for e2e.
- **Auto-reload** (`make backend`, `--reload`): the dev API restarts on every saved backend file and cuts open chat streams.

## Agent architecture

Decided: not now, evaluate later. The question: should a Dr. Wu turn run on LangGraph, or on what the app already has, so that it can work like an actual agent with durable, resumable, multi-step runs?

- **Today:** chat is a custom tool loop (`api/services/chat/`) over the model gateway (`llm/client.py`) on the user's own ChatGPT plan, one `POST /chat` request per turn with a streamed reply. Gap search runs on the OpenAI Agents SDK (`api/services/gap_search/`, `llm/agents_sdk.py`). Documents and gap search already run as jobs (`jobs` table, `GET /jobs/{job_id}` stream). A turn's working state (steps, tool results) lives in memory only; `chat_sessions` and `chat_messages` keep the user's redacted message and the finished reply.
- **What LangGraph would give:** state saved after every step (Postgres checkpointer), resume after a failure, pauses for the user's confirmation, long-running background runs, streaming of intermediate state.
- **What it would not give:** faster model calls. Turns failed because of up to seven sequential model round-trips of 3.5–10 s each against the 45 s deadline; that is being fixed in the existing loop.
- **What it would cost here:** its checkpoint tables would hold health conversations outside the per-user row-level security, export, deletion and retention the chat tables have ([`compliance.md`](compliance.md), [`retention.md`](retention.md)), so all of that would have to be built around it. The post-check and citation rules of [`specs/agent.md`](specs/agent.md) would have to be ported. And it would be a third orchestration approach next to the custom loop and the Agents SDK, unless one of them is retired.
- **Compare it with:** running a chat turn as a job on the existing `jobs` table and stream, persisting each step, with the current loop or the Agents SDK.
- **The evaluation should produce:** a recommendation, the migration steps, and the data-protection design for stored agent state.
