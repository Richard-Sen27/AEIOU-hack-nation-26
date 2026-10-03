"""Deterministic responses for the mock /v1/responses endpoint."""

import json
import re
from dataclasses import dataclass, field
from typing import Any

EDGE_ID_RE = re.compile(r"\be_[0-9a-f]{12}\b")
CURIE_RE = re.compile(r"\b(?:MONDO|HGNC|HP|ORPHA|OMIM|CHEBI|GO|R-HSA)[:_]\d+\b|\bNCT\d{8}\b")
SCHEMA_TAG_RE = re.compile(r"<json_schema>(\{.*?\})</json_schema>", re.DOTALL)
TOOLS_TAG_RE = re.compile(r"<tools>(\[.*?\])</tools>", re.DOTALL)

QUERY_NAMES = {"query", "q", "text", "message", "user_text", "question", "term", "mention", "input"}
MAX_AUTO_TOOL_CALLS = 3


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


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(c.get("text", "")) for c in content if isinstance(c, dict) and "text" in c
        )
    return ""


def build_context(body: dict[str, Any]) -> Context:
    user_texts, tool_outputs, called = [], [], []
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
            else:
                user_texts.append(text)
        elif itype == "function_call":
            called.append(item.get("name", ""))
        elif itype == "function_call_output":
            tool_outputs.append(str(item.get("output", "")))
    instructions = body.get("instructions") or ""
    all_text = "\n".join([*user_texts, *tool_outputs])
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


class Generator:
    def __init__(self, ctx: Context, root: dict[str, Any]):
        self.ctx = ctx
        self.root = root

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

    def value(self, schema: dict[str, Any], name: str = "", depth: int = 0) -> Any:
        schema = self._resolve(schema or {})
        if depth > 8:
            return None
        if "const" in schema:
            return schema["const"]
        if schema.get("enum"):
            return schema["enum"][0]
        for key in ("anyOf", "oneOf"):
            if key in schema:
                options = [self._resolve(o) for o in schema[key]]
                non_null = [o for o in options if o.get("type") != "null"] or options
                return self.value(non_null[0], name, depth + 1)
        if "allOf" in schema and schema["allOf"]:
            return self.value(schema["allOf"][0], name, depth + 1)
        stype = schema.get("type")
        if isinstance(stype, list):
            stype = next((t for t in stype if t != "null"), "null")
        if stype is None:
            stype = "object" if "properties" in schema else "string"
        lname = name.lower()
        if stype == "object":
            props = schema.get("properties") or {}
            return {k: self.value(v, k, depth + 1) for k, v in props.items()}
        if stype == "array":
            return self._array(schema, lname, depth)
        if stype == "string":
            return self._string(schema, lname)
        if stype == "integer":
            return int(schema.get("minimum", 1) if schema.get("minimum", 1) > 0 else 1)
        if stype == "number":
            lo, hi = schema.get("minimum", 0.0), schema.get("maximum", 1.0)
            return round(lo + (hi - lo) * 0.75, 3)
        if stype == "boolean":
            return False
        return None

    def _array(self, schema: dict[str, Any], lname: str, depth: int) -> list[Any]:
        items = self._resolve(schema.get("items") or {})
        item_type = items.get("type")
        min_items = schema.get("minItems", 0)
        max_items = schema.get("maxItems", 3)
        values: list[Any] = []
        if item_type == "string" and not items.get("enum"):
            if "edge" in lname:
                values = self.ctx.edge_ids[:3]
            elif "node" in lname or lname.endswith("ids") or "curie" in lname:
                values = self.ctx.curies[:3]
            elif "quote" in lname or "snippet" in lname:
                values = self.ctx.sentences[:1]
            elif lname in ("mentions", "terms", "queries", "keywords"):
                values = [self.ctx.last_user[:80]] if self.ctx.last_user else []
            else:
                values = [self._string(items, lname.rstrip("s"))] if min_items else []
        else:
            count = max(min_items, 1 if depth < 3 else 0)
            values = [self.value(items, lname.rstrip("s"), depth + 1) for _ in range(count)]
        while len(values) < min_items:
            values.append(self.value(items, lname.rstrip("s"), depth + 1))
        return values[:max_items] if max_items else values

    def _string(self, schema: dict[str, Any], lname: str) -> str:
        if schema.get("format") == "date" or lname.endswith("date"):
            return "2026-01-01"
        if lname in QUERY_NAMES or lname.endswith("query"):
            return self.ctx.last_user[:200] or "mock query"
        if "quote" in lname or "snippet" in lname:
            return (self.ctx.sentences or ["mock quote"])[0]
        if "edge" in lname and "id" in lname:
            return (self.ctx.edge_ids or ["e_000000000000"])[0]
        if lname.endswith("id") or lname.endswith("_id") or lname in ("from", "to", "node"):
            return (self.ctx.curies or ["MONDO:0000001"])[0]
        if lname in ("summary", "answer", "explanation", "text", "reply", "message", "note"):
            return final_text(self.ctx)
        if lname in ("language", "lang"):
            return "en"
        return "mock"


def final_text(ctx: Context) -> str:
    text = "This is a mock answer from the local development stand-in."
    if ctx.tool_outputs:
        text += f" It used {len(ctx.tool_outputs)} tool result(s)."
    if ctx.edge_ids:
        text += " Supporting edges: " + ", ".join(f"[{e}]" for e in ctx.edge_ids[:5]) + "."
    return text


def _text_format_schema(body: dict[str, Any]) -> dict[str, Any] | None:
    fmt = ((body.get("text") or {}).get("format")) or {}
    if fmt.get("type") == "json_schema":
        return fmt.get("schema") or {}
    return None


def plan_response(body: dict[str, Any]) -> Plan:
    ctx = build_context(body)
    instructions = ctx.instructions

    tools_tag = TOOLS_TAG_RE.search(instructions)
    schema_tag = SCHEMA_TAG_RE.search(instructions)
    if tools_tag:
        tools = json.loads(tools_tag.group(1))
        pending = [t for t in tools if not t["name"].startswith("ask_")]
        if ctx.json_results < min(len(pending), MAX_AUTO_TOOL_CALLS):
            tool = pending[ctx.json_results]
            args = Generator(ctx, tool.get("parameters") or {}).value(tool.get("parameters") or {})
            return Plan(text=json.dumps({"tool": tool["name"], "arguments": args or {}}))
        if schema_tag:
            schema = json.loads(schema_tag.group(1))
            return Plan(text=json.dumps({"final": Generator(ctx, schema).value(schema)}))
        return Plan(text=json.dumps({"final": final_text(ctx)}))

    tools = [] if body.get("tool_choice") == "none" else offered_tools(body)
    pending = [t for t in tools if not t[0].startswith("ask_") and t[0] not in ctx.called]
    if pending and len(ctx.called) < MAX_AUTO_TOOL_CALLS:
        name, params, namespace = pending[0]
        args = Generator(ctx, params).value(params) or {}
        return Plan(calls=[(name, args, namespace)])

    schema = _text_format_schema(body)
    if schema is None and schema_tag:
        schema = json.loads(schema_tag.group(1))
    if schema is not None:
        return Plan(text=json.dumps(Generator(ctx, schema).value(schema)))
    return Plan(text=final_text(ctx))
