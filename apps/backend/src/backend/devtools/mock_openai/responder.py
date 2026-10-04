"""Deterministic responses for the mock /v1/responses endpoint.

Generic by design: driven by tool names, JSON schemas and what appears in the conversation
(user text, tool outputs), never by importing application code.

Tool-enabled requests call tools in a sensible order, one per round: `*extract*` with the user
text, `*resolve*` / `*search*` with the gene- and disease-like terms found in it, `*neighbo*` on
the best id returned, `*path*` between the two best disease ids; other tools (not `ask_*`) once
with schema-derived arguments. The final answer is built from the tool outputs: labels in the
summary, claims citing real `e_…` edges, cards and focus on the nodes found.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

EDGE_ID_RE = re.compile(r"\be_[0-9a-f]{12}\b")
CURIE_RE = re.compile(r"\b(?:MONDO|HGNC|HP|ORPHA|OMIM|CHEBI|GO|R-HSA)[:_]\d+\b|\bNCT\d{8}\b")
DISEASE_ID_RE = re.compile(r"^(?:MONDO|ORPHA|OMIM)[:_]\d+$")
SCHEMA_TAG_RE = re.compile(r"<json_schema>(\{.*?\})</json_schema>", re.DOTALL)
TOOLS_TAG_RE = re.compile(r"<tools>(\[.*?\])</tools>", re.DOTALL)
GENE_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\d[A-Z0-9]{0,3}\b|\b(?:ARX|DMD|CFTR|PTEN|MECP2)\b")
HGVS_RE = re.compile(r"\b(?:NM_\d+(?:\.\d+)?:)?[cgp]\.\(?[A-Za-z*]*-?\d+[^\s,;)]*\)?")
DISEASE_RE = re.compile(
    r"\b(?:[A-Z][\w'-]+[ -])?(?:[A-Z0-9][\w-]*[ -])?"
    r"(?:syndrome|encephalopathy|epilepsy|disease|disorder|dystrophy|ataxia|spasms)\b",
)
SYMPTOMS = {
    "seizure": "Seizure",
    "seizures": "Seizure",
    "spasms": "Infantile spasms",
    "hypotonia": "Hypotonia",
    "walking": "Delayed ability to walk",
    "delay": "Global developmental delay",
    "eating": "Feeding difficulties",
    "feeding": "Feeding difficulties",
    "fever": "Fever",
    "anfälle": "Seizure",
    "krampfanfälle": "Seizure",
}
NEGATION_RE = re.compile(r"\b(?:no|not|without|never|keine?|nicht|ohne)\b[^.,;]{0,40}$", re.I)
FEEDBACK_PREFIXES = ("Your previous reply was invalid", "Invalid reply", "<tool_result")

QUERY_NAMES = {"query", "q", "text", "message", "user_text", "question", "term", "mention", "input"}
MAX_AUTO_TOOL_CALLS = 5
PREFER_NULL = ("uncertainty", "follow_up", "followup", "onset", "country", "error", "note")


@dataclass
class Plan:
    """What to stream: function calls (name, arguments, namespace) or one text message."""

    calls: list[tuple[str, dict[str, Any], str | None]] = field(default_factory=list)
    text: str | None = None


@dataclass
class Context:
    instructions: str
    user_texts: list[str]
    tool_outputs: list[str]
    called: list[str]
    json_results: int
    all_text: str
    _parsed: list[Any] | None = None

    @property
    def last_user(self) -> str:
        return self.user_texts[-1] if self.user_texts else ""

    @property
    def edge_ids(self) -> list[str]:
        return list(dict.fromkeys(EDGE_ID_RE.findall(self.all_text)))

    @property
    def curies(self) -> list[str]:
        return list(dict.fromkeys(CURIE_RE.findall(self.all_text)))

    @property
    def sentences(self) -> list[str]:
        source = " ".join(self.user_texts) or self.all_text
        parts = re.split(r"(?<=[.!?])\s+|\n+", source)
        return [p.strip() for p in parts if 15 <= len(p.strip()) <= 300]

    # ---- what the user wrote ----------------------------------------------------------

    @property
    def genes(self) -> list[str]:
        text = self.last_user
        hgvs = {m.group(0) for m in HGVS_RE.finditer(text)}
        found = [g for g in GENE_RE.findall(text) if not any(g in h for h in hgvs)]
        return list(dict.fromkeys(found))

    @property
    def diseases(self) -> list[str]:
        return list(dict.fromkeys(m.group(0).strip() for m in DISEASE_RE.finditer(self.last_user)))

    @property
    def variants(self) -> list[str]:
        return list(dict.fromkeys(m.group(0) for m in HGVS_RE.finditer(self.last_user)))

    def symptoms(self) -> list[tuple[str, str, bool]]:
        """(as written, English term, negated)."""
        out, seen = [], set()
        for m in re.finditer(r"[\wäöüß]+", self.last_user):
            term = SYMPTOMS.get(m.group(0).lower())
            if term and term not in seen:
                seen.add(term)
                negated = bool(NEGATION_RE.search(self.last_user[: m.start()].split(".")[-1]))
                out.append((m.group(0), term, negated))
        return out

    @property
    def search_terms(self) -> list[str]:
        return self.genes + self.diseases

    # ---- what the tools returned --------------------------------------------------------

    @property
    def outputs(self) -> list[Any]:
        if self._parsed is None:
            parsed = []
            for raw in self.tool_outputs:
                text = re.sub(r"^<tool_result[^>]*>|</tool_result>$", "", raw.strip())
                try:
                    parsed.append(json.loads(text))
                except ValueError:
                    continue
            self._parsed = parsed
        return self._parsed

    def _walk(self) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                found.append(value)
                for v in value.values():
                    visit(v)
            elif isinstance(value, list):
                for v in value:
                    visit(v)

        for out in self.outputs:
            visit(out)
        return found

    @property
    def nodes(self) -> list[dict[str, Any]]:
        """{id, label, type?} for every node-like object in the tool outputs, first seen first."""
        nodes: dict[str, dict[str, Any]] = {}
        for d in self._walk():
            nid = d.get("id")
            if isinstance(nid, str) and CURIE_RE.fullmatch(nid) and d.get("label"):
                nodes.setdefault(nid, {"id": nid, "label": str(d["label"]), "type": d.get("type")})
        return list(nodes.values())

    @property
    def edges(self) -> list[dict[str, Any]]:
        """Edge-like objects: id/edge_id e_…, with source/target or from/to when present."""
        edges: dict[str, dict[str, Any]] = {}
        labels = {n["id"]: n["label"] for n in self.nodes}
        for d in self._walk():
            eid = d.get("id") if EDGE_ID_RE.fullmatch(str(d.get("id", ""))) else d.get("edge_id")
            if not (isinstance(eid, str) and EDGE_ID_RE.fullmatch(eid)) or eid in edges:
                continue
            src, tgt = d.get("source") or d.get("source_id"), d.get("target") or d.get("target_id")
            edges[eid] = {
                "id": eid,
                "source": src,
                "target": tgt,
                "from": d.get("from") or labels.get(src) or src,
                "to": d.get("to") or labels.get(tgt) or tgt,
                "relation": str(d.get("relation") or "is linked to").replace("_", " "),
                "origin": d.get("origin"),
                "confidence": d.get("confidence"),
            }
        for eid in self.edge_ids:
            edges.setdefault(eid, {"id": eid, "relation": "is linked to"})
        return list(edges.values())

    @property
    def path_edge_ids(self) -> list[str]:
        for d in self._walk():
            ids = d.get("edge_ids")
            if isinstance(ids, list) and ids and all(EDGE_ID_RE.fullmatch(str(i)) for i in ids):
                return [str(i) for i in ids]
        return []

    def best_ids(self) -> list[str]:
        ids = [n["id"] for n in self.nodes]
        return ids or self.curies


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(c.get("text", "")) for c in content if isinstance(c, dict) and "text" in c
        )
    return ""


def build_context(body: dict[str, Any]) -> Context:
    user_texts, tool_outputs, called, other = [], [], [], []
    json_results = 0
    for item in body.get("input") or []:
        if not isinstance(item, dict):
            continue
        itype = item.get("type", "message")
        if itype == "message" and item.get("role") in ("user", "developer"):
            text = _content_text(item.get("content"))
            if text.startswith("<tool_result"):
                json_results += 1
                tool_outputs.append(text)
            elif item.get("role") == "user" and not text.startswith(FEEDBACK_PREFIXES):
                user_texts.append(text)
            else:
                other.append(text)
        elif itype == "function_call":
            called.append(item.get("name", ""))
        elif itype == "function_call_output":
            tool_outputs.append(str(item.get("output", "")))
    instructions = body.get("instructions") or ""
    all_text = "\n".join([*user_texts, *tool_outputs, *other])
    return Context(instructions, user_texts, tool_outputs, called, json_results, all_text)


def offered_tools(body: dict[str, Any]) -> list[tuple[str, dict[str, Any], str | None]]:
    """(name, parameters schema, namespace) for every function tool offered."""
    found: list[tuple[str, dict[str, Any], str | None]] = []

    def collect(tools: list[Any]) -> None:
        for tool in tools or []:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") == "function":
                found.append((tool["name"], tool.get("parameters") or {}, None))
            elif tool.get("type") == "namespace":
                for sub in tool.get("tools") or []:
                    if sub.get("type") == "function":
                        found.append((sub["name"], sub.get("parameters") or {}, tool["name"]))

    collect(body.get("tools") or [])
    for item in body.get("input") or []:
        if isinstance(item, dict) and item.get("type") == "additional_tools":
            collect(item.get("tools") or [])
    return found


# ---- schema-driven value generation ---------------------------------------------------------


def _confidence_level(value: Any, options: list[Any]) -> Any:
    if not isinstance(value, int | float):
        return None
    level = "high" if value >= 0.8 else "medium" if value >= 0.5 else "low"
    return level if level in options else None


class Generator:
    def __init__(self, ctx: Context, root: dict[str, Any], overrides: dict[str, Any] | None = None):
        self.ctx = ctx
        self.root = root
        self.overrides = overrides or {}

    def _resolve(self, schema: dict[str, Any]) -> dict[str, Any]:
        seen = 0
        while "$ref" in schema and seen < 20:
            ref = schema["$ref"]
            node: Any = self.root
            for part in ref.lstrip("#/").split("/"):
                node = node.get(part, {}) if isinstance(node, dict) else {}
            schema = {**node, **{k: v for k, v in schema.items() if k != "$ref"}}
            seen += 1
        return schema

    def value(
        self, schema: dict[str, Any], name: str = "", depth: int = 0, item: dict | None = None
    ) -> Any:
        schema = self._resolve(schema or {})
        lname = name.lower()
        if depth > 8:
            return None
        if depth == 1 and lname in self.overrides:
            return self.overrides[lname]
        if "const" in schema:
            return schema["const"]
        if schema.get("enum"):
            return self._enum(schema["enum"], lname, item)
        for key in ("anyOf", "oneOf"):
            if key in schema:
                options = [self._resolve(o) for o in schema[key]]
                non_null = [o for o in options if o.get("type") != "null"] or options
                nullable = len(non_null) < len(options)
                if nullable and self._prefer_null(lname, non_null[0], item):
                    return None
                return self.value(non_null[0], name, depth, item)
        if "allOf" in schema and schema["allOf"]:
            return self.value(schema["allOf"][0], name, depth, item)
        stype = schema.get("type")
        if isinstance(stype, list):
            non_null = [t for t in stype if t != "null"]
            nullable = len(non_null) < len(stype)
            if nullable and self._prefer_null(lname, {"type": non_null[0]}, item):
                return None
            stype = non_null[0] if non_null else "null"
        if stype is None:
            stype = "object" if "properties" in schema else "string"
        if stype == "object":
            props = schema.get("properties") or {}
            return {k: self.value(v, k, depth + 1, item) for k, v in props.items()}
        if stype == "array":
            return self._array(schema, lname, depth, item)
        if stype == "string":
            return self._string(schema, lname, item)
        if stype == "integer":
            if lname in ("age_years", "age"):
                m = re.search(r"\b(?:is|ist|age|aged)\s+(\d{1,2})\b", self.ctx.last_user, re.I)
                return int(m.group(1)) if m else None
            return int(schema.get("minimum", 1) if schema.get("minimum", 1) > 0 else 1)
        if stype == "number":
            lo, hi = schema.get("minimum", 0.0), schema.get("maximum", 1.0)
            return round(lo + (hi - lo) * 0.75, 3)
        if stype == "boolean":
            return bool(item.get("negated")) if item and lname == "negated" else False
        return None

    def _prefer_null(self, lname: str, schema: dict[str, Any], item: dict | None = None) -> bool:
        if item and item.get(lname) is not None:
            return False
        if "focus" in lname:
            return not (self.ctx.nodes or self.ctx.edge_ids)
        if lname in ("age_years", "age"):
            return False
        return lname in PREFER_NULL or schema.get("type") in ("integer", "number", "string")

    def _enum(self, options: list[Any], lname: str, item: dict | None) -> Any:
        if item:
            if lname == "origin" and item.get("origin") in options:
                return item["origin"]
            if lname == "confidence":
                level = _confidence_level(item.get("confidence"), options)
                if level:
                    return level
            if lname == "type" and item.get("kind") in options:
                return item["kind"]
        return options[0]

    def _array(self, schema: dict[str, Any], lname: str, depth: int, item: dict | None) -> list:
        items = self._resolve(schema.get("items") or {})
        item_type = items.get("type")
        min_items = schema.get("minItems", 0)
        max_items = schema.get("maxItems", 5)
        values: list[Any]
        if item_type == "string" and not items.get("enum"):
            values = self._string_list(lname, item, min_items)
        elif item_type == "object" or "properties" in items:
            values = [
                self.value(items, lname.rstrip("s"), depth + 1, it)
                for it in self._object_items(lname, items, depth)
            ]
        else:
            count = max(min_items, 1 if depth < 3 else 0)
            values = [self.value(items, lname.rstrip("s"), depth + 1) for _ in range(count)]
        while len(values) < min_items:
            values.append(self.value(items, lname.rstrip("s"), depth + 1))
        return values[:max_items] if max_items else values

    def _string_list(self, lname: str, item: dict | None, min_items: int) -> list[str]:
        ctx = self.ctx
        if "edge" in lname or lname == "highlight_path":
            if item and item.get("id") and EDGE_ID_RE.fullmatch(str(item["id"])):
                return [item["id"]]
            if lname == "highlight_path":
                return ctx.path_edge_ids or [e["id"] for e in ctx.edges[:2]]
            return [e["id"] for e in ctx.edges[:3]]
        if "node" in lname or lname.endswith("ids") or "curie" in lname:
            if item and item.get("node_ids"):
                return item["node_ids"]
            return [n["id"] for n in ctx.nodes[:5]] or ctx.curies[:3]
        if "quote" in lname or "snippet" in lname:
            return ctx.sentences[:1]
        if lname in ("mentions", "terms", "queries", "keywords"):
            return ctx.search_terms[:3] or ([ctx.last_user[:80]] if ctx.last_user else [])
        if lname in ("missing_evidence", "assumptions", "warnings", "errors"):
            return []
        return [self._string({}, lname.rstrip("s"), item)] if min_items else []

    def _object_items(self, lname: str, items: dict[str, Any], depth: int) -> list[dict]:
        """One context dict per array element, chosen by the array's name."""
        ctx = self.ctx
        props = set((items.get("properties") or {}).keys())
        if lname in ("genes", "diseases", "variants", "symptoms") and "text" in props:
            if lname == "symptoms":
                return [{"text": t, "english": e, "negated": n} for t, e, n in ctx.symptoms()]
            terms = {"genes": ctx.genes, "diseases": ctx.diseases, "variants": ctx.variants}
            return [{"text": t, "english": t, "negated": False} for t in terms[lname]]
        if lname == "mentions" and "text" in props:
            mentions = [{"text": g, "kind": "gene"} for g in ctx.genes]
            mentions += [{"text": d, "kind": "disease"} for d in ctx.diseases]
            mentions += [{"text": v, "kind": "variant"} for v in ctx.variants]
            mentions += [{"text": e, "kind": "symptom", "negated": n} for _, e, n in ctx.symptoms()]
            return mentions[:6]
        if "claim" in lname:
            # Only observed (or unlabelled) edges: the mock never presents a hypothesis.
            return [
                e
                for e in ctx.edges
                if (e.get("source") or e.get("from")) and e.get("origin") in (None, "observed")
            ][:3]
        if "card" in lname:
            nodes = ctx.nodes[:4]
            return [{"node_ids": [n["id"] for n in nodes]}] if nodes else []
        if lname in ("contradictions", "actions", "findings", "candidates", "errors"):
            return []
        return [{}] if depth < 3 else []

    def _string(self, schema: dict[str, Any], lname: str, item: dict | None = None) -> str:
        ctx = self.ctx
        if item:
            if lname == "text" and item.get("relation") and (item.get("from") or item.get("to")):
                return f"{item.get('from')} {item['relation']} {item.get('to')}."
            if lname in ("text", "english") and item.get("text"):
                return str(item["english" if lname == "english" else "text"] or item["text"])
        if schema.get("format") == "date" or lname.endswith("date"):
            return "2026-01-01"
        if lname in QUERY_NAMES or lname.endswith("query"):
            return (ctx.search_terms or [ctx.last_user[:200] or "mock query"])[0]
        if "quote" in lname or "snippet" in lname:
            return (ctx.sentences or ["mock quote"])[0]
        if "edge" in lname and "id" in lname:
            return (ctx.edge_ids or ["e_000000000000"])[0]
        if lname.endswith("id") or lname.endswith("_id") or lname in ("from", "to", "node"):
            return (ctx.best_ids() or ["MONDO:0000001"])[0]
        if lname == "summary":
            return final_text(ctx, cite=False)
        if lname in ("answer", "explanation", "text", "reply", "message", "note"):
            return final_text(ctx)
        if lname in ("language", "lang"):
            return "en"
        if lname == "title":
            return "Mock title"
        return "mock"


def final_text(ctx: Context, *, cite: bool = True) -> str:
    """Short, plain sentences (patient lenses gate on reading level)."""
    labels = [n["label"] for n in ctx.nodes[:3]]
    if labels:
        text = " ".join(f"I found {label}." for label in labels)
    else:
        text = "This is a mock answer from the local test server."
    if ctx.tool_outputs and not labels:
        text += f" It used {len(ctx.tool_outputs)} tool results."
    if cite and ctx.edge_ids:
        text += " See " + ", ".join(f"[{e}]" for e in ctx.edge_ids[:5]) + "."
    return text


def _text_format_schema(body: dict[str, Any]) -> dict[str, Any] | None:
    fmt = ((body.get("text") or {}).get("format")) or {}
    if fmt.get("type") == "json_schema":
        return fmt.get("schema") or {}
    return None


# ---- tool planning ------------------------------------------------------------------------


def _tool_args(ctx: Context, name: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """Arguments for a tool by its name; None when its preconditions are not met yet."""
    lname = name.lower()
    gen = Generator(ctx, params)
    props = params.get("properties") or {}
    if "path" in lname:
        diseases = [i for i in ctx.best_ids() if DISEASE_ID_RE.match(i)]
        if len(diseases) < 2:
            return None
        args = gen.value(params) or {}
        keys = [k for k in props if k.lower() in ("from_id", "from", "source", "source_id")]
        keys += [k for k in props if k.lower() in ("to_id", "to", "target", "target_id")]
        if len(keys) >= 2:
            args[keys[0]], args[keys[1]] = diseases[0], diseases[1]
        return args
    if "neighbo" in lname:
        ids = ctx.best_ids()
        if not ids:
            return None
        args = gen.value(params) or {}
        for k in props:
            if k.lower().endswith("id") or k.lower() == "node":
                args[k] = ids[0]
        return args
    if ("resolve" in lname or "search" in lname) and not ctx.search_terms:
        return None if ctx.called else gen.value(params) or {}
    args = gen.value(params) or {}
    if "extract" in lname:
        for k in props:
            if k.lower() in QUERY_NAMES:
                args[k] = ctx.last_user
    return args


def _tool_rank(name: str) -> int:
    lname = name.lower()
    for rank, key in enumerate(("extract", "resolve", "search", "neighbo", "path")):
        if key in lname:
            return rank
    return 5


def next_tool_call(
    ctx: Context, tools: list[tuple[str, dict[str, Any], str | None]]
) -> tuple[str, dict[str, Any], str | None] | None:
    if len(ctx.called) >= MAX_AUTO_TOOL_CALLS:
        return None
    pending = [t for t in tools if not t[0].startswith("ask_") and t[0] not in ctx.called]
    for name, params, namespace in sorted(pending, key=lambda t: _tool_rank(t[0])):
        args = _tool_args(ctx, name, params)
        if args is not None:
            return name, args, namespace
    return None


def _final_object(ctx: Context, schema: dict[str, Any]) -> Any:
    return Generator(ctx, schema).value(schema)


def plan_response(body: dict[str, Any]) -> Plan:
    ctx = build_context(body)
    instructions = ctx.instructions

    tools_tag = TOOLS_TAG_RE.search(instructions)
    schema_tag = SCHEMA_TAG_RE.search(instructions)
    if tools_tag:
        tools = [
            (t["name"], t.get("parameters") or {}, None) for t in json.loads(tools_tag.group(1))
        ]
        ctx.called = [m for m in re.findall(r'<tool_result name="([^"]+)"', ctx.all_text)]
        call = next_tool_call(ctx, tools)
        if call is not None:
            return Plan(text=json.dumps({"tool": call[0], "arguments": call[1]}))
        if schema_tag:
            schema = json.loads(schema_tag.group(1))
            return Plan(text=json.dumps({"final": _final_object(ctx, schema)}))
        return Plan(text=json.dumps({"final": final_text(ctx)}))

    tools = [] if body.get("tool_choice") == "none" else offered_tools(body)
    call = next_tool_call(ctx, tools) if tools else None
    if call is not None:
        return Plan(calls=[call])

    schema = _text_format_schema(body)
    if schema is None and schema_tag:
        schema = json.loads(schema_tag.group(1))
    if schema is not None:
        return Plan(text=json.dumps(_final_object(ctx, schema)))
    return Plan(text=final_text(ctx))
