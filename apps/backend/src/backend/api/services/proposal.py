"""Proposal export: one-page sourced proposal as printable HTML.

Deterministic from graph data and the request (no LLM call, no timestamp): who is connected and
why (each statement with source and confidence, hypotheses labelled), reusable assets, the
proposed next step (viability recomputed from the edges), public professional contacts, a
"not medical advice" line and the data version. Everything is HTML-escaped."""

from html import escape
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import not_found
from backend.api.services import graph as graph_service
from backend.api.services.explanation.common import base_language
from backend.api.services.explanation.pathdata import (
    PathData,
    has_contradiction,
    is_supportive,
    load_path_data,
)
from backend.api.services.explanation.templates import TIER_WORDS, relation_sentence
from backend.schemas.account import CurrentUser
from backend.schemas.chat import Action
from backend.schemas.common import Lens
from backend.schemas.enums import EdgeStatus, NodeType, Origin, Relation, confidence_level
from backend.schemas.graph import Edge, Node
from backend.schemas.proposal import ProposalRequest

MAX_ITEMS = 8

L10N = {
    "en": {
        "title": "Collaboration proposal",
        "connected": "Who is connected and why",
        "assets": "Reusable assets",
        "next": "Proposed next step",
        "contacts": "Public professional contacts",
        "none_assets": "No registry, study or trial is linked to these diseases in the atlas yet.",
        "none_next": "No next step was selected.",
        "none_contacts": "No public contacts are linked in the atlas yet.",
        "today": "Today",
        "proposed": "Proposed route",
        "assumptions": "Assumptions",
        "viable": "Viable lead: every supporting link is observed, active and uncontradicted.",
        "unsupported": "Unsupported lead: at least one supporting link is a hypothesis, under "
        "review or contradicted.",
        "data": "Data",
        "hypothesis": "Hypothesis",
        "reported": "Reported, not verified",
        "under_review": "Under review",
        "contradicted": "Contradicting evidence",
        "confidence": "confidence",
        "sources": "Sources",
        "no_sources": "no evidence rows",
        "ai_actions": "Next-step wording was drafted by Dr. Wu, an AI system; verify before use.",
        "disclaimer": "Not medical advice. This page summarises public sources in the Amber "
        "rare-disease atlas; it is not a diagnosis or a treatment recommendation.",
        "version": "Data version",
        "edges": "Links",
    },
    "de": {
        "title": "Kooperationsvorschlag",
        "connected": "Wer verbunden ist und warum",
        "assets": "Wiederverwendbare Ressourcen",
        "next": "Vorgeschlagener nächster Schritt",
        "contacts": "Öffentliche berufliche Kontakte",
        "none_assets": "Im Atlas ist noch kein Register, keine Studie und keine klinische Prüfung "
        "mit diesen Erkrankungen verknüpft.",
        "none_next": "Kein nächster Schritt ausgewählt.",
        "none_contacts": "Im Atlas sind noch keine öffentlichen Kontakte verknüpft.",
        "today": "Heute",
        "proposed": "Vorgeschlagener Weg",
        "assumptions": "Annahmen",
        "viable": "Tragfähig: alle stützenden Verbindungen sind beobachtet, aktiv und "
        "unwidersprochen.",
        "unsupported": "Nicht gestützt: mindestens eine Verbindung ist eine Hypothese, in "
        "Überprüfung oder widersprochen.",
        "data": "Daten",
        "hypothesis": "Hypothese",
        "reported": "Gemeldet, nicht geprüft",
        "under_review": "In Überprüfung",
        "contradicted": "Widersprechende Belege",
        "confidence": "Konfidenz",
        "sources": "Quellen",
        "no_sources": "keine Belege",
        "ai_actions": "Der Text des nächsten Schritts wurde von Dr. Wu, einem KI-System, "
        "entworfen; bitte vor Verwendung prüfen.",
        "disclaimer": "Keine medizinische Beratung. Diese Seite fasst öffentliche Quellen im "
        "Amber-Atlas für seltene Erkrankungen zusammen; sie ist keine Diagnose und keine "
        "Behandlungsempfehlung.",
        "version": "Datenversion",
        "edges": "Verbindungen",
    },
}

CSS = """
@page { size: A4; margin: 14mm; }
* { box-sizing: border-box; }
body { font: 10pt/1.4 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; color: #1c1917;
  margin: 0 auto; max-width: 182mm; padding: 8mm 0; background: #fff; }
h1 { font-size: 16pt; margin: 0 0 2mm; color: #92400e; }
h2 { font-size: 11pt; margin: 5mm 0 1.5mm; border-bottom: 1px solid #e7e5e4; padding-bottom: 1mm; }
p, li { margin: 0 0 1.2mm; }
ul { padding-left: 5mm; margin: 0; }
.meta { color: #57534e; font-size: 8.5pt; }
.tag { display: inline-block; font-size: 7.5pt; padding: 0 1.5mm; border-radius: 2mm;
  border: 1px solid #a8a29e; margin-right: 1mm; }
.tag.hyp { border-style: dashed; }
.tag.warn { border-color: #b45309; color: #b45309; }
.src { color: #57534e; font-size: 8pt; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 3mm; }
.box { border: 1px solid #e7e5e4; border-radius: 2mm; padding: 2mm 3mm; }
a { color: #92400e; }
footer { margin-top: 5mm; border-top: 1px solid #e7e5e4; padding-top: 2mm; font-size: 8pt;
  color: #57534e; }
@media print { body { padding: 0; } a { text-decoration: none; } }
"""


def _t(lang: str, key: str) -> str:
    return L10N.get(lang, L10N["en"])[key]


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _safe_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    return url if parts.scheme in ("http", "https") and parts.netloc else None


def _link(label: str, url: str | None) -> str:
    safe = _safe_url(url)
    if safe is None:
        return _e(label)
    return f'<a href="{_e(safe)}" rel="noopener noreferrer">{_e(label)}</a>'


def _origin_tag(edge: Edge, lang: str) -> str:
    if edge.origin == Origin.observed:
        return f'<span class="tag">{_e(_t(lang, "data"))}</span>'
    if edge.origin == Origin.inferred:
        return f'<span class="tag hyp">{_e(_t(lang, "hypothesis"))}</span>'
    return f'<span class="tag hyp">{_e(_t(lang, "reported"))}</span>'


def _statement(data: PathData, edge: Edge, lang: str) -> str:
    level = confidence_level(edge.confidence).value
    tags = [_origin_tag(edge, lang)]
    if edge.status != EdgeStatus.active:
        tags.append(f'<span class="tag warn">{_e(_t(lang, "under_review"))}</span>')
    sources = []
    for ev in data.supporting(edge.id)[:3]:
        label = ev.label() or ev.source_type
        tier = TIER_WORDS.get(ev.tier, ev.tier)
        sources.append(f"{_link(label, ev.url)} ({_e(tier)})")
    src = "; ".join(sources) if sources else _e(_t(lang, "no_sources"))
    out = (
        f"<li>{''.join(tags)}{_e(relation_sentence(data, edge, lang))}. "
        f'<span class="src">{_e(_t(lang, "confidence"))} {edge.confidence:.2f} ({_e(level)}) · '
        f"{_e(_t(lang, 'sources'))}: {src} · {_e(edge.id)}</span>"
    )
    if has_contradiction(edge, data):
        items = data.contradicting(edge.id)[:2]
        detail = "; ".join(
            _link(ev.label() or ev.source_type, ev.url)
            + (f": “{_e((ev.quote or '')[:160])}”" if ev.quote else "")
            for ev in items
        ) or _e(str(edge.contradiction_count))
        out += (
            f'<br><span class="tag warn">{_e(_t(lang, "contradicted"))}</span>'
            f'<span class="src">{detail}</span>'
        )
    return out + "</li>"


def _neighbors(node_id: str) -> list[tuple[Edge, str]]:
    store = graph_service.get_graph()
    out = []
    for eid in store.incident.get(node_id, ()):
        edge = graph_service.get_edge(eid)
        if edge is None:
            continue
        other = edge.target_id if edge.source_id == node_id else edge.source_id
        out.append((edge, other))
    return sorted(out, key=lambda x: (-x[0].confidence, x[0].id))


def _assets_and_contacts(data: PathData) -> tuple[list[Node], list[tuple[Node, list[str]]]]:
    path_nodes = list(
        dict.fromkeys(n for e in data.ordered_edges() for n in (e.source_id, e.target_id))
    )
    diseases = [
        n
        for n in path_nodes
        if (node := graph_service.get_node(n)) and node.type == NodeType.disease
    ]
    assets: dict[str, Node] = {}
    orgs: dict[str, Node] = {}
    people: dict[str, Node] = {}

    def add(target: dict[str, Node], node_id: str) -> None:
        node = graph_service.get_node(node_id)
        if node is not None:
            target.setdefault(node.id, node)

    for nid in path_nodes:
        node = graph_service.get_node(nid)
        if node is None:
            continue
        if node.type in (NodeType.registry, NodeType.trial):
            assets.setdefault(nid, node)
        elif node.type in (NodeType.patient_org, NodeType.institution, NodeType.network):
            orgs.setdefault(nid, node)
        elif node.type in (NodeType.researcher, NodeType.doctor):
            people.setdefault(nid, node)
    for disease in diseases:
        for edge, other in _neighbors(disease):
            if edge.relation == Relation.studies:
                add(assets, other)
                for e2, o2 in _neighbors(other):
                    if e2.relation == Relation.investigator_of:
                        add(people, o2)
            elif edge.relation == Relation.serves:
                add(orgs, other)
                for e2, o2 in _neighbors(other):
                    if e2.relation == Relation.runs and e2.source_id == other:
                        add(assets, o2)
            elif edge.relation == Relation.funds_research_on:
                for e2, o2 in _neighbors(other):
                    if e2.relation == Relation.pi_of:
                        add(people, o2)
    for org_id in list(orgs):
        for e2, o2 in _neighbors(org_id):
            if e2.relation == Relation.runs and e2.source_id == org_id:
                add(assets, o2)
    contacts: list[tuple[Node, list[str]]] = [(o, []) for o in orgs.values()]
    for person in people.values():
        institutions = [
            graph_service.get_node(o2).label
            for e2, o2 in _neighbors(person.id)
            if e2.relation == Relation.affiliated_with and graph_service.get_node(o2)
        ]
        contacts.append((person, institutions))
    return list(assets.values())[:MAX_ITEMS], contacts[:MAX_ITEMS]


def _asset_item(node: Node) -> str:
    kind = node.attrs.get("kind") or node.type.value
    extra = []
    for key in ("status", "phase"):
        if node.attrs.get(key):
            extra.append(f"{key} {node.attrs[key]}")
    meta = f' <span class="src">({_e(", ".join([str(kind), *extra]))} · {_e(node.id)})</span>'
    return f"<li>{_link(node.label, node.url)}{meta}</li>"


def _contact_item(node: Node, institutions: list[str]) -> str:
    parts = [node.type.value.replace("_", " ")]
    if institutions:
        parts.append(", ".join(institutions[:2]))
    if node.attrs.get("country"):
        parts.append(str(node.attrs["country"]))
    return (
        f'<li>{_link(node.label, node.url)} <span class="src">({_e(" · ".join(parts))})</span></li>'
    )


def _action_block(action: Action, data: PathData, edges: dict[str, Edge], lang: str) -> str:
    cited = [edges[e] for e in action.edge_ids if e in edges]
    viable = (
        bool(cited)
        and len(cited) == len(set(action.edge_ids))
        and all(is_supportive(e, data) for e in cited)
    )
    verdict = _t(lang, "viable") if viable else _t(lang, "unsupported")
    tag = "tag" if viable else "tag warn"
    rows = [
        f"<p><strong>{_e(action.title)}</strong> "
        f'<span class="{tag}">{_e(action.type.value.replace("_", " "))}</span></p>',
        f'<p class="src">{_e(verdict)} {_e(_t(lang, "edges"))}: '
        f"{_e(', '.join(action.edge_ids) or '-')}</p>",
        '<div class="grid">',
        f'<div class="box"><strong>{_e(_t(lang, "today"))}</strong><br>'
        f"{_e(action.timeline_today or '-')}</div>",
        f'<div class="box"><strong>{_e(_t(lang, "proposed"))}</strong><br>'
        f"{_e(action.timeline_proposed or '-')}</div>",
        "</div>",
    ]
    if action.assumptions:
        items = "".join(f"<li>{_e(a)}</li>" for a in action.assumptions[:6])
        rows.append(f"<p><strong>{_e(_t(lang, 'assumptions'))}</strong></p><ul>{items}</ul>")
    return "".join(rows)


async def render_proposal(
    db: AsyncSession, user: CurrentUser, request: ProposalRequest, lens: Lens
) -> str:
    """Render the proposal (path, assets, contacts, citations) as a standalone HTML page."""
    action_edges = [e for a in request.actions or [] for e in a.edge_ids]
    data = await load_path_data(db, [*request.edge_ids, *action_edges])
    if any(e in data.missing for e in request.edge_ids) or not data.edges:
        raise not_found("Unknown edge IDs.")
    lang = base_language(lens.language) if base_language(lens.language) in L10N else "en"
    path_edges = [data.edges[e] for e in dict.fromkeys(request.edge_ids) if e in data.edges]
    first, last = path_edges[0], path_edges[-1]
    title = request.title or (
        f"{_t(lang, 'title')}: {data.node_label(first.source_id)} – "
        f"{data.node_label(last.target_id)}"
    )
    assets, contacts = _assets_and_contacts(data)
    statements = "".join(_statement(data, e, lang) for e in path_edges)
    asset_html = (
        "<ul>" + "".join(_asset_item(n) for n in assets) + "</ul>"
        if assets
        else f"<p>{_e(_t(lang, 'none_assets'))}</p>"
    )
    contact_html = (
        "<ul>" + "".join(_contact_item(n, inst) for n, inst in contacts) + "</ul>"
        if contacts
        else f"<p>{_e(_t(lang, 'none_contacts'))}</p>"
    )
    if request.actions:
        next_html = (
            "".join(_action_block(a, data, data.edges, lang) for a in request.actions[:2])
            + f'<p class="src">{_e(_t(lang, "ai_actions"))}</p>'
        )
    else:
        next_html = f"<p>{_e(_t(lang, 'none_next'))}</p>"
    version = data.data_version or "unversioned"
    return (
        "<!doctype html>"
        f'<html lang="{_e(lang)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(title)}</title><style>{CSS}</style></head><body>"
        f"<header><h1>{_e(title)}</h1>"
        f'<p class="meta">Amber — Rare Disease Atlas · {_e(_t(lang, "version"))} '
        f"{_e(version)}</p></header>"
        f"<section><h2>{_e(_t(lang, 'connected'))}</h2><ul>{statements}</ul></section>"
        f"<section><h2>{_e(_t(lang, 'assets'))}</h2>{asset_html}</section>"
        f"<section><h2>{_e(_t(lang, 'next'))}</h2>{next_html}</section>"
        f"<section><h2>{_e(_t(lang, 'contacts'))}</h2>{contact_html}</section>"
        f"<footer><p><strong>{_e(_t(lang, 'disclaimer'))}</strong></p>"
        f"<p>{_e(_t(lang, 'version'))}: {_e(version)}</p></footer>"
        "</body></html>"
    )
