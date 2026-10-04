# Homework

Work deliberately left for later. Add an item when you leave something for later; check the area's section before starting work there; remove an item when it is done. One line per item: where, what, and, when known, why it was left and what the fix would be.

## Landing page

- **Networking cards** (`apps/frontend/src/components/landing/landing-config.ts`, `CONNECT_STATUS`): follow, calls and choose are "coming"; switch each to "live" (with its `CONNECT_HREF`) as its networking stage lands, so the card links there and drops "Coming soon".

## Atlas view

- **Category labels on phones** (`apps/backend/src/backend/api/services/atlas_tree.py`, `LABEL_CHAR_WIDTH = 0.006`): at 390 px the labels are 4.6–7.9 px, because the boxes the backend reserves for them scale with the map. Fix: let labels outgrow their box on phones, or raise `LABEL_CHAR_WIDTH` to about 0.0105 (a layout change).
- **Label under the search bar:** at 1024 px in the doctor lens, the "Clinical features" label sits partly under the map search bar.
- **Group names at 390 px:** some are drawn under the logo or cut off at the canvas edge.
- **Portrait phones:** the landscape-shaped map leaves empty space above and below.
- **Busy trunks:** Genes is the busiest, with long chromosome branches and some crossing lines; Literature has long spokes.
- **Selecting the busiest node** costs one frame of 100–150 ms in dev mode, mostly the panel mounting.
- **"Other organisations"** still holds 29 institutions after the name keyword rule (`institution_kind` in `atlas_tree.py`).
- **`GET /atlas.json`** (`api/routes/graph.py`, `graph.atlas_payload`) is no longer used by the frontend and can be removed, together with its mock in `apps/frontend/e2e/graph/fixtures.ts`.
- **Symptom panel sections from the data rework plan:** a phenotype's summary has no "Shared genes" section (genes linked to two or more of its diseases), no "Hypotheses" section (from `candidate_phenotype`) and no frequency per disease; `SummarySectionKey` has none of these keys.
- **"Possibly relevant" researchers and trials** of a neighbouring focus disease are not shown in a core disease's panel (wide-scope plan, Stage C).
- **Wide map (wide-scope plan, Stage B)** is not built and awaits the user's go-ahead: the core tier on the map, edges on demand (`GET /atlas/edges/{id}`, `POST /atlas/edges`), a disease supergroup level and genes by cytoband.

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
- **Dock history:** the Atlas dock shows only this tab's current conversation (kept in memory across views) or a turn still running on the server; it never lists stored sessions, so an older failed turn shows on `/chat` only.
- **Retry of an older failed turn** returns 409 when a later message exists in the session; the UI still offers "Try again" on such turns in a reloaded session.
- **Real model untested:** answer quality, document extraction, the gap-search agent, written explanations and summaries were covered only by the mock.
- **No ranking card for `match_phenotypes`:** the frontend has no Dr. Wu card for the symptom-overlap ranking; it shows only through the normal reply and `graph_focus`.
- **No eval for symptom matching:** `evals/golden.yaml` has no chronic-cough case expecting primary ciliary dyskinesia 25 (`MONDO:0014203`) in `graph_focus`.

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
- **Model-inferred abstract relations (open decision):** the model marked 697 of 1,877 relations from PubMed abstracts as inferred (implied by the quote, not stated in it). Since commit 66aae75 they are not written to the graph. Open question: show them as dashed hypotheses with the quote as explanation, or leave them out. The model's answers, these relations included, are in `apps/pipeline/data/cache/llm`, with a copy in `apps/pipeline/data/backups/llm-cache-2026-10-04/`. Bringing them back means: write them again in `extract/abstracts.py` with an explanation, method and confidence basis; relax the validation rule that inferred edges carry only `computed` hypothesis evidence; then rerun extract, build, analytics and validate (abstracts come from the cache; the cluster labels are about 150 calls, also cached).
- **Docker run:** a full pipeline run inside Docker is unverified.
- **Stale graph after a load:** the API keeps serving the old graph until it is restarted. Fix: a reload hook.
- **Candidate links not produced:** `candidate_phenotype` and `suggested_by_neighbour` have caps (`build.INFERRED_CONFIDENCE_CAPS`), validation and enums, but `analytics.py` writes none. They need a studiedness measure first (PubMed counts for every core disease, number of HPO terms and P/LP variants, ClinGen validity, prevalence → `little_studied`), from the data rework plan, Stage 2 / wide-scope Stage C.
- **Cough / primary ciliary dyskinesia focus region:** the planned seed genes (DNAAF4, DNAH5, CCDC39, …) and a `phenotype_seeds` rule in `scope.py` are not in `seeds.yaml`; PCD 25 is core only.
- **Linking outside the model budget** (`linking.py`, `_get_llm`): linking decisions call the model directly, without the `data/cache/llm` disk cache and without `PIPELINE_LLM_MAX_CALLS`; extraction and cluster labels use both.

## Privacy and compliance

- **Missing documents:** `docs/incident.md`, `docs/dpia.md`, `docs/ropa.md`; `ropa.md` must include the work details of doctors and researchers as a purpose (contract, Art. 6(1)(b)).
- **`/privacy` placeholders** (`apps/frontend/src/app/privacy/page.tsx`, `ToBeCompleted`): controller name and address, `NEXT_PUBLIC_PRIVACY_EMAIL`, hosting provider and region, supervisory authority.
- **HPO release date hard-coded** (`apps/frontend/src/app/about-data/page.tsx`, "Data version"): "2 September 2026" goes stale at the next fetch; it should come from `ingestion_runs.source_versions` via `GET /stats`.
- **Privacy notices** are English only.
- **Redaction** misses a bare first name in unlabelled prose (worse in German).
- **Test addresses** (`apps/backend/tests/platform/test_redaction.py`): two invented addresses at real mail domains (gmail.com, outlook.com); switch to example domains.
- **Graph backup** `apps/pipeline/data/backups/atlas-graph-2026-10-04.9.dump` falls under the 30-day backup rule in [`retention.md`](retention.md) and must be deleted by 2026-11-03.
- **Second read** for texts shortened next to compliance wording: the contribute-consent note on suggested links, the age line, the export text, the delete text.
- **Work details: legal basis** (`api/services/professional.py`): counsel should confirm contract (Art. 6(1)(b)) as the basis for the optional work details of doctors and researchers.
- **Work details: name prefill** (`auth.stored_name_claims`, `professional.suggested_name`): reading `given_name` / `family_name` from the real OpenAI ID token is unverified; the mock is the only source tested, and without the claims the code splits the account name (last word = last name).
- **Work details: role switch** (`on_role_change` in `api/services/account.py`): switching to patient deletes them today; the user has not decided between deleting and keeping them hidden. Keeping them means dropping the clear there.
- **Professionals for others:** contacting doctors and researchers and credit on contributions are still deferred (messaging is stage 5); verified, opt-in public cards exist (`api/services/people.py`).
- **Real ORCID credentials** (`config.py`, `ORCID_*`): ORCID sign-in is built but untested against ORCID; it needs a registered client (`ORCID_CLIENT_ID`, `ORCID_CLIENT_SECRET`, `ORCID_BASE_URL` sandbox then production, the exact `ORCID_REDIRECT_URI`). Demos use `ORCID_MOCK=true`.
- **Institutional verification is manual** (`backend verify-professional`): no automatic e-mail check, no notice to the operator when a request arrives, no moderation UI; the user sees only "pending" until the operator runs the CLI.
- **Demo verifications can name real people** (`ORCID_MOCK`, local only): the simulated sign-in accepts any ORCID iD, so a local demo card can carry a real researcher's iD and atlas entry, labelled "demo, verification simulated". Do not demo with real names you do not own.
- **Card cache across workers** (`people.CACHE_MAX_AGE_S`): a card switched off disappears at once in the process that handled the change, elsewhere (another worker, after an operator `--revoke`) within 60 s; `GET /people/{card_id}` is always fresh.
- **Cards per disease** (`people._person_diseases`): a card is listed for a disease only through its verified atlas entry (papers, grants, trials); cards without one are reachable by card link only. No work topics, by decision.
- **Card frontend:** the endpoints and SDK exist; the profile panel, the Atlas chip ("In Amber · ORCID iD confirmed") and the card page are not built.
- **ORCID state replay** (`orcid._used_nonces`): used states are remembered per process for 10 minutes; with several workers a replay inside that window is stopped only by ORCID's single-use code.

## Messaging (connect)

- **Before real patients use messaging:** `docs/dpia.md`, `docs/ropa.md` (messaging and the `connect` consent as a purpose) and `docs/incident.md` must exist; counsel must review the `connect` consent text and the banners.
- **Minors:** messaging and sign-ups are open from 16 with a self-declared age group and a self-declared guardian agreement (`thread_reads.guardian_*`). A legal check is needed on contacting 16- and 17-year-olds and on whether a self-declared guardian agreement is enough. The professional is not told the writer is 16 or 17 today.
- **Moderation:** reports are read only through `backend.cli read-reported-thread` (logged). There is no moderation UI, no service level, no process for acting on a report (warning, suspending a card) and no evidence copy: a reported message the sender deletes is gone.
- **E-mail notifications:** none; new messages show only through `GET /me/threads/unread-count`. Messages are not written into the stage 1 `notifications` table (its kinds and bell are graph-shaped and its rows are filled lazily from public data; an unread count is what a stored row would add). Any future e-mail must never contain message text or health data.
- **Daily clean-up:** `backend.cli purge-messages` (12-month inactive threads, orphaned threads, reports after 12 months, access log after 24 months) needs a scheduler on the deployment; today only the user's own threads are purged when they read their list.
- **Development key:** without `MESSAGE_ENCRYPTION_KEY` the API derives a key from `SESSION_SECRET` while API and frontend are loopback; messages stored that way cannot be read after `SESSION_SECRET` or the key changes unless the derived key is listed in `MESSAGE_ENCRYPTION_KEY` and rotated.
- **Operator role:** the CLI uses `atlas_owner`, which has policies on `threads`, `messages` and `reports`; a separate least-privilege operator role would be better.
- **Sign-up threads (stage 4):** `messaging.open_signup_thread` exists; stage 4 must add foreign keys from `threads.call_id` / `signup_id` and tighten the `threads_signup_insert` policy to the sign-up's own patient.
- **Messaging tables outside `USER_TABLES`:** `threads`, `messages`, `thread_reads`, `blocks` and `reports` are in `MESSAGING_TABLES` (`db/models.py`), because the generic owner-column tests in `tests/test_rls.py` and `test_data_rights.py` cannot seed shared rows; their RLS is proven in `tests/account/test_messaging.py`.
- **Banners** ("You are writing to a person, not Dr. Wu", "not a medical consultation; in an emergency call 112/911", "do not give individual medical advice or prescribe through Amber") and the just-in-time `connect` dialog are frontend work still to do.

## Documents

- **OCR** is basic (clean scans, English); HEIC decoding is untested.
- **Drop zone** has empty space because the panel next to it sets its height.

## Landing page

- **Sign-in dialog** opened from the landing input (`components/landing/hero-input.tsx`) starts with a sentence that repeats the landing copy.
- **Hero input** has empty space under its placeholder on desktop (its `min-h`).

## Calls

- **Moderation UI:** calls are reviewed only through `backend.cli calls pending|approve|reject`; an operator screen is missing.
- **No auto-publish in local demos:** the planned shortcut that publishes a submitted call at once in local settings (labelled "demo, not reviewed") was not built (a definer function the API role may call was refused as weakening the review guarantee); demos use `backend.cli demo-calls` or the operator command.
- **Operator log noise:** `calls approve` lists the pending calls first for the wording check, which logs a "viewed" row for every pending call, not only the approved one.
- **Expired calls** stay `published` after `closes_at` (only hidden from the list); no job closes them.
- **Wording check** (`WORDING_RULES` in `api/services/calls.py`) is a coarse English/German blocklist; counsel should review the drug-advertising wording before real use.
- **Call frontend:** browsing, the publisher form and the "for adults" label for 16-17 users are not built yet (frontend task).

## Tests and tooling

- **Flaky spec:** `apps/frontend/e2e/account/documents.spec.ts` "pending uploads from the landing page are picked up" fails intermittently.
- **Dev-only error** "Router action dispatched before initialization" has made specs fail and pass on rerun.
- **GPU:** the Atlas needs a real GPU; software rendering is too slow for e2e.
- **Auto-reload** (`make backend`, `--reload`): the dev API restarts on every saved backend file and cuts open chat streams.

## Agent architecture

Decided and built (Oct 4): a Dr. Wu turn is a LangGraph graph (`api/services/chat/agent.py`: safety → emergency | entities → agent → partial → postcheck → persist) run on the server, detached from the request (`runs.py`); clients attach by run id and replay numbered events; state is checkpointed per node by a custom saver into the run's own `chat_runs` row (RLS, redacted only, deleted when the turn ends). Gap search still runs on the OpenAI Agents SDK (`api/services/gap_search/`), a second orchestration approach.

- **One API process:** runs and their event buffers live in that process's memory. Several instances need a shared event log (or sticky routing by run id) and a lease with heartbeat instead of the boot id in `chat_runs.worker`, which today marks every other worker's run as orphaned.
- **No resume after a restart:** a run whose process died is stored as an interrupted failed turn ("Try again" reruns it), lazily when its owner next lists runs, opens the session or sends; not resumed, because the tool cache (`TurnState`, needed by the post-check's citation rules) and the turn deadline are per process and a resume would make model calls on the user's plan without them present. Resuming needs the tool results in the checkpoint (graph data plus the redacted message only) and a user-present trigger.
- **Orphans of users who never return** stay in `chat_runs` (redacted content, same class as `chat_messages`) until they do or delete the session, consent or account; a sweep would need a `SECURITY DEFINER` function, since RLS hides other users' rows.
- **Tool rounds are one node:** the rounds and the final answer run inside the gateway's `run_tools` (budgets, tool-mode fallbacks); splitting each round into its own node means moving that loop out of `llm/client.py`.
- **Next agent features** (not built): pauses for the user's confirmation (`interrupt` between `agent` and `postcheck`, a `resume` route), long multi-step tasks (a planner node and a loop over `agent`), live streaming of the final answer's text (the summary is chunked after the post-check today).
- **Gap search** could move onto the same run machinery and the Agents SDK be retired.
