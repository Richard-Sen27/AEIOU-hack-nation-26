"""Operator review of calls, and the local demo calls (wired into `backend.cli`).

    uv run python -m backend.cli calls pending --operator NAME
    uv run python -m backend.cli calls approve <call id> --operator NAME [--note "..."]
    uv run python -m backend.cli calls reject <call id> --operator NAME --note "..."
    uv run python -m backend.cli demo-calls [--clear]

The review commands connect as atlas_owner (MIGRATION_DATABASE_URL) and go only through the
SECURITY DEFINER functions pending_calls() and review_call(), which the API role cannot call;
each logs its action (viewed, approved, rejected) with the operator's name in call_reviews.
Approving re-runs the wording check first and refuses while it finds anything.

demo-calls (DEMO DATA, local development only) creates a demo publisher account (a researcher
with a simulated verification and a visible card, labelled as demo) and a few demo calls for
diseases of the atlas (Dravet syndrome, the STXBP1 family), published through review_call()
with the operator name `demo-seed`. Every demo call has `demo = true` and a title starting with
"Demo:". `--clear` deletes the demo publisher, which deletes the demo calls. Refuses to run
unless API_URL, FRONTEND_URL and the database are loopback addresses.
"""

import argparse
import json
import sys
import uuid
from typing import Any

DEMO_SUB = "demo-call-publisher"
DEMO_OPERATOR = "demo-seed"
DEMO_CARD_NAME = "Demo researcher (Amber demo data)"


def _psycopg_url(url: str) -> str:
    for prefix in ("postgresql+psycopg://", "postgresql+asyncpg://"):
        url = url.replace(prefix, "postgresql://")
    return url


def _owner_connect():
    import psycopg
    from psycopg.rows import dict_row

    from backend.config import get_settings

    return psycopg.connect(
        _psycopg_url(get_settings().migration_database_url), row_factory=dict_row
    )


def _app_connect():
    import psycopg
    from psycopg.rows import dict_row

    from backend.config import get_settings

    return psycopg.connect(_psycopg_url(get_settings().database_url), row_factory=dict_row)


def _operator(name: str | None) -> str:
    name = " ".join((name or "").split())
    if not name or len(name) > 100:
        raise SystemExit("--operator (your name, 1-100 characters) is required")
    return name


def _call_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise SystemExit("not a call id") from None


def _db_error(exc: Exception) -> SystemExit:
    diag = getattr(exc, "diag", None)
    return SystemExit(f"refused: {getattr(diag, 'message_primary', None) or exc}")


# ---- operator review ----------------------------------------------------------------------


def pending(operator: str, out=sys.stdout) -> list[dict]:
    """Print every call waiting for review (each view is logged)."""
    from backend.api.services.calls import wording_issues

    operator = _operator(operator)
    with _owner_connect() as conn:
        rows = conn.execute("SELECT * FROM pending_calls(%s)", (operator,)).fetchall()
    print(f"calls waiting for review: {len(rows)} (viewed by {operator}, logged)", file=out)
    for r in rows:
        call, pub = r["call"], r["publisher"]
        inst = "; ".join(i.get("label", "") for i in (pub.get("institutions") or []))
        issues = wording_issues(call)
        print(f"\n  {r['call_id']}  {call['kind']}  submitted {call.get('submitted_at')}", file=out)
        print(f"    title: {call['title']}", file=out)
        print(
            f"    publisher: {pub.get('name')} ({pub.get('role')}, {inst or 'no institution'};"
            f" verified by {pub.get('verification_method')}, card visible"
            f" {pub.get('card_visible')})",
            file=out,
        )
        print(
            f"    diseases: {', '.join(call['disease_ids'])}  registry: "
            f"{call.get('registry_id') or '-'}  ethics: {call.get('ethics_body') or '-'} "
            f"{call.get('ethics_reference') or '-'}  link: {call.get('external_url') or '-'}",
            file=out,
        )
        for key in ("summary", "participation", "eligibility_text"):
            if call.get(key):
                print(f"    {key}: {call[key]}", file=out)
        print(
            "    wording check: "
            + (", ".join(f"{i.field} ('{i.term}')" for i in issues) if issues else "clean"),
            file=out,
        )
    return rows


def review(
    call_id: str, decision: str, operator: str, note: str | None = None, out=sys.stdout
) -> str:
    """Approve or reject a call waiting for review; returns the new status."""
    import psycopg

    from backend.api.services.calls import wording_issues

    operator = _operator(operator)
    call_id = _call_id(call_id)
    note = " ".join(note.split()) if note else None
    if note and len(note) > 1000:
        raise SystemExit("the note has at most 1000 characters")
    if decision == "reject" and not note:
        raise SystemExit("a rejection needs --note (it is shown to the publisher)")
    with _owner_connect() as conn:
        if decision == "approve":
            rows = conn.execute("SELECT * FROM pending_calls(%s)", (operator,)).fetchall()
            match = next((r for r in rows if str(r["call_id"]) == call_id), None)
            if match is None:
                raise SystemExit("no call with this id is waiting for review")
            issues = wording_issues(match["call"])
            if issues:
                found = ", ".join(f"{i.field} ('{i.term}')" for i in issues)
                raise SystemExit(f"refused: the wording check finds {found}; reject it instead")
        try:
            status = conn.execute(
                "SELECT review_call(%s, %s, %s, %s) AS status", (call_id, decision, note, operator)
            ).fetchone()["status"]
        except psycopg.Error as exc:
            raise _db_error(exc) from None
    print(f"call {call_id}: {status} by {operator} (logged)", file=out)
    if note:
        print(f"  note: {note}", file=out)
    return status


# ---- demo calls ---------------------------------------------------------------------------


def _require_local() -> None:
    from urllib.parse import urlsplit

    from backend.config import get_settings, is_loopback_url

    s = get_settings()
    if not (is_loopback_url(s.api_url) and is_loopback_url(s.frontend_url)):
        raise SystemExit("refusing: API_URL or FRONTEND_URL is not a loopback address (demo data)")
    for url in (s.database_url, s.migration_database_url):
        host = urlsplit(_psycopg_url(url)).hostname or ""
        if not host or not is_loopback_url(f"http://{host}"):
            raise SystemExit("refusing: the database is not on a loopback address (demo data)")


def _demo_calls(conn) -> list[dict[str, Any]]:
    """The demo calls, with disease ids taken from the loaded atlas."""

    def diseases(label_like: str, gene: str | None = None) -> list[str]:
        rows = conn.execute(
            "SELECT id FROM nodes WHERE type = 'disease' AND label ILIKE %s ORDER BY id LIMIT 5",
            (label_like,),
        ).fetchall()
        ids = [r["id"] for r in rows]
        if not ids and gene:
            rows = conn.execute(
                "SELECT DISTINCT n.id FROM edges e JOIN nodes n"
                " ON n.id IN (e.source_id, e.target_id) AND n.type = 'disease'"
                " WHERE %s IN (e.source_id, e.target_id) ORDER BY n.id LIMIT 5",
                (gene,),
            ).fetchall()
            ids = [r["id"] for r in rows]
        return [i for i in ids if i.startswith("MONDO:")]

    def existing(ids: list[str], node_type: str) -> list[str]:
        rows = conn.execute(
            "SELECT id FROM nodes WHERE id = ANY(%s) AND type = %s", (ids, node_type)
        ).fetchall()
        found = {r["id"] for r in rows}
        return [i for i in ids if i in found]

    dravet = diseases("Dravet syndrome%") or diseases("%Dravet%")
    stxbp1 = diseases("%STXBP1%", gene="HGNC:11444")
    calls = []
    if dravet:
        calls.append(
            {
                "kind": "survey",
                "title": "Demo: Survey on sleep and daily routines in Dravet syndrome",
                "summary": "Demo data, not a real study. A short online survey for parents and "
                "caregivers about sleep, night-time seizures and daily routines.",
                "participation": "About 20 minutes online, once. No visits.",
                "eligibility_text": "Parents or caregivers of a person with Dravet syndrome.",
                "disease_ids": dravet[:1],
                "gene_ids": existing(["HGNC:10585"], "gene"),
                "phenotype_ids": existing(["HP:0002133", "HP:0001250"], "phenotype"),
                "children_ok": True,
                "remote": True,
                "countries": [],
                "run_by_label": "Amber demo team",
                "requested_fields": ["diagnosis", "age_range", "country"],
            }
        )
        calls.append(
            {
                "kind": "trial",
                "title": "Demo: Observational trial listing for SCN1A-related epilepsy",
                "summary": "Demo data, not a real trial. Shows how a recruiting trial with a "
                "registry number and an ethics approval appears in Amber.",
                "participation": "Two clinic visits over 12 months; travel costs reimbursed.",
                "eligibility_text": "Children and adults with a confirmed SCN1A variant.",
                "disease_ids": dravet[:1],
                "gene_ids": existing(["HGNC:10585"], "gene"),
                "phenotype_ids": [],
                "min_age": 2,
                "children_ok": True,
                "remote": False,
                "countries": ["DE", "AT"],
                "run_by_label": "Amber demo team",
                "ethics_body": "Demo ethics committee",
                "ethics_reference": "DEMO-EC-2026-001",
                "registry_id": "NCT00000000",
                "requested_fields": ["diagnosis", "genetic_findings"],
            }
        )
    if stxbp1:
        calls.append(
            {
                "kind": "study",
                "title": "Demo: Natural history study of the STXBP1 family of disorders",
                "summary": "Demo data, not a real study. A natural history study collecting how "
                "STXBP1-related disorders develop over time.",
                "participation": "Yearly online questionnaire and one optional video call.",
                "eligibility_text": "People of any age with an STXBP1-related disorder.",
                "disease_ids": stxbp1[:3],
                "gene_ids": existing(["HGNC:11444"], "gene"),
                "phenotype_ids": existing(["HP:0001263"], "phenotype"),
                "children_ok": True,
                "remote": True,
                "countries": [],
                "run_by_label": "Amber demo team",
                "ethics_body": "Demo ethics committee",
                "ethics_reference": "DEMO-EC-2026-002",
                "requested_fields": ["diagnosis", "genetic_findings", "symptoms", "age_range"],
            }
        )
    return calls


def demo_calls(*, clear: bool = False, out=sys.stdout) -> list[str]:
    """Seed (or with clear=True delete) the labelled demo calls; returns the new call ids."""
    _require_local()
    with _app_connect() as conn:
        uid = conn.execute(
            "SELECT auth_find_or_create_user(%s, %s, %s) AS id",
            (DEMO_SUB, "demo-publisher@example.invalid", DEMO_CARD_NAME),
        ).fetchone()["id"]
        conn.execute("SELECT set_config('app.user_id', %s, false)", (str(uid),))
        if clear:
            conn.execute("DELETE FROM users WHERE id = %s", (uid,))
            print("demo publisher and demo calls deleted", file=out)
            return []
        conn.execute(
            "UPDATE profiles SET role = 'researcher', age_confirmed_at = COALESCE("
            "age_confirmed_at, now()), role_verified = true, verification_method ="
            " 'orcid_simulated', verified_at = now(), verified_name = %s,"
            " card_id = COALESCE(card_id, gen_random_uuid()), card_visible = true,"
            " card_visible_since = COALESCE(card_visible_since, now()), card_headline = %s,"
            " institutions = %s::jsonb, updated_at = now() WHERE user_id = %s",
            (
                DEMO_CARD_NAME,
                "Demo account: verification simulated, not a real person",
                json.dumps([{"node_id": None, "label": "Amber demo institute"}]),
                uid,
            ),
        )
        conn.execute("DELETE FROM calls WHERE publisher_id = %s AND demo", (uid,))
        ids = []
        for call in _demo_calls(conn):
            cols = list(call)
            ids.append(
                str(
                    conn.execute(
                        f"INSERT INTO calls (publisher_id, demo, status, submitted_at,"
                        f" {', '.join(cols)}) VALUES (%s, true, 'pending_review', now(),"
                        f" {', '.join(['%s'] * len(cols))}) RETURNING id",
                        (uid, *call.values()),
                    ).fetchone()["id"]
                )
            )
        conn.commit()
    with _owner_connect() as conn:
        for call_id in ids:
            conn.execute(
                "SELECT review_call(%s, 'approve', %s, %s)",
                (call_id, "Demo data seeded locally, not a real study", DEMO_OPERATOR),
            )
    if not ids:
        raise SystemExit("no demo diseases (Dravet syndrome, STXBP1) in this atlas")
    print(f"DEMO DATA: {len(ids)} demo calls published by '{DEMO_CARD_NAME}'", file=out)
    for call_id in ids:
        print(f"  {call_id}", file=out)
    return ids


# ---- argparse wiring ----------------------------------------------------------------------


def add_parsers(sub) -> None:
    calls = sub.add_parser("calls", help="Operator: review calls waiting for review (logged)")
    calls_sub = calls.add_subparsers(dest="calls_command", required=True)
    pend = calls_sub.add_parser("pending", help="List calls waiting for review (logged)")
    pend.add_argument("--operator", required=True, help="Your name (logged)")
    ok = calls_sub.add_parser("approve", help="Publish a call waiting for review (logged)")
    ok.add_argument("call_id")
    ok.add_argument("--operator", required=True, help="Your name (logged)")
    ok.add_argument("--note", help="Optional note to the publisher")
    no = calls_sub.add_parser("reject", help="Reject a call waiting for review (logged)")
    no.add_argument("call_id")
    no.add_argument("--operator", required=True, help="Your name (logged)")
    no.add_argument("--note", required=True, help="Why (shown to the publisher)")

    demo = sub.add_parser(
        "demo-calls",
        help="DEMO DATA, local only: seed labelled demo calls by a demo publisher",
        description="DEMO DATA for local development: creates a demo publisher (simulated "
        "verification, labelled) and a few demo calls for Dravet syndrome and the STXBP1 "
        "family, published through the logged review function. Refuses to run unless API_URL, "
        "FRONTEND_URL and the database are loopback addresses.",
    )
    demo.add_argument("--clear", action="store_true", help="Delete the demo publisher and calls")


def run(args: argparse.Namespace) -> int | None:
    """Handle the commands added above; None for any other command."""
    if args.command == "demo-calls":
        demo_calls(clear=args.clear)
        return 0
    if args.command != "calls":
        return None
    if args.calls_command == "pending":
        pending(args.operator)
    else:
        review(args.call_id, args.calls_command, args.operator, args.note)
    return 0
