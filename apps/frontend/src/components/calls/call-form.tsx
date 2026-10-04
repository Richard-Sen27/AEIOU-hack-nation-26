"use client";

import { ArrowLeft, Loader2, Save, Send, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { toast } from "sonner";

import { routeGlobalError } from "@/components/account/api-errors";
import { EntityPicker } from "@/components/account/entity-picker";
import { SessionLoading, SignInPrompt } from "@/components/account/sign-in-prompt";
import { useSession } from "@/components/providers/session-provider";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { createCall, getMyCall, listMyCalls, submitCall, updateCall } from "@/lib/api";
import { announce } from "@/lib/a11y";
import type { ApiError } from "@/lib/api/errors";
import type { NodeType } from "@/lib/api/generated/types.gen";
import { nodeTypeMeta } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

import {
  CALL_KINDS,
  callErrorText,
  countryName,
  fieldLabel,
  invalidFields,
  KIND_META,
  REQUESTED_FIELD_LABELS,
  reviewRequired,
  type CallInput,
  type CallKind,
  type OwnCall,
  type RequestedField,
} from "./call-meta";
import { CannotPublishNote, NotPublisherNote } from "./my-calls";
import { invalidatePublishedCalls } from "./use-published-calls";

/** The backend's limits (schemas/calls.py), mirrored so the form says so first. */
const LIMITS = { title: 140, summary: 1000, participation: 1000, eligibility_text: 1500, label: 200, ethics_reference: 100, url: 500 };
const MAX = { diseases: 10, genes: 20, phenotypes: 30, countries: 60 };
const REGISTRY_RE = /^(NCT\d{8}|DRKS\d{8}|\d{4}-\d{6}-\d{2}(-\d{2})?)$/;
const HTTPS_RE = /^https:\/\/[^/\s?#]+\.[^/\s?#]+\S*$/i;
const REQUESTED: RequestedField[] = ["diagnosis", "genetic_findings", "symptoms", "age_range", "country"];

type Ref = { id: string; label: string };
type Draft = {
  kind: CallKind;
  title: string;
  summary: string;
  participation: string;
  eligibility_text: string;
  diseases: Ref[];
  genes: Ref[];
  phenotypes: Ref[];
  min_age: string;
  max_age: string;
  children_ok: boolean;
  countries: string;
  remote: boolean;
  run_by: (Ref & { node: boolean }) | null;
  ethics_body: string;
  ethics_reference: string;
  registry_id: string;
  external_url: string;
  opens_at: string;
  closes_at: string;
  max_signups: string;
  requested_fields: RequestedField[];
};

const EMPTY: Draft = {
  kind: "survey",
  title: "",
  summary: "",
  participation: "",
  eligibility_text: "",
  diseases: [],
  genes: [],
  phenotypes: [],
  min_age: "",
  max_age: "",
  children_ok: false,
  countries: "",
  remote: false,
  run_by: null,
  ethics_body: "",
  ethics_reference: "",
  registry_id: "",
  external_url: "",
  opens_at: "",
  closes_at: "",
  max_signups: "",
  requested_fields: ["diagnosis"],
};

const refs = (list: Array<{ id: string; label: string | null }>): Ref[] => list.map((r) => ({ id: r.id, label: r.label ?? r.id }));

function draftFrom(c: OwnCall): Draft {
  return {
    kind: c.kind,
    title: c.title,
    summary: c.summary,
    participation: c.participation,
    eligibility_text: c.eligibility_text ?? "",
    diseases: refs(c.diseases),
    genes: refs(c.genes),
    phenotypes: refs(c.phenotypes),
    min_age: c.min_age?.toString() ?? "",
    max_age: c.max_age?.toString() ?? "",
    children_ok: c.children_ok,
    countries: c.countries.join(", "),
    remote: c.remote,
    run_by: c.run_by_node
      ? { id: c.run_by_node.id, label: c.run_by_node.label ?? c.run_by_node.id, node: true }
      : c.run_by_label
        ? { id: "", label: c.run_by_label, node: false }
        : null,
    ethics_body: c.ethics_body ?? "",
    ethics_reference: c.ethics_reference ?? "",
    registry_id: c.registry_id ?? "",
    external_url: c.external_url ?? "",
    opens_at: c.opens_at ?? "",
    closes_at: c.closes_at ?? "",
    max_signups: c.max_signups?.toString() ?? "",
    requested_fields: c.requested_fields.length ? c.requested_fields : ["diagnosis"],
  };
}

const parseCountries = (s: string) => [...new Set(s.split(/[\s,;]+/).filter(Boolean).map((c) => c.toUpperCase()))];
const intOrNull = (s: string) => (s.trim() === "" ? null : Number(s));
const textOrNull = (s: string) => (s.trim() === "" ? null : s.trim());

function toInput(d: Draft): CallInput {
  return {
    kind: d.kind,
    title: d.title.trim(),
    summary: d.summary.trim(),
    participation: d.participation.trim(),
    eligibility_text: textOrNull(d.eligibility_text),
    disease_ids: d.diseases.map((r) => r.id),
    gene_ids: d.genes.map((r) => r.id),
    phenotype_ids: d.phenotypes.map((r) => r.id),
    min_age: intOrNull(d.min_age),
    max_age: intOrNull(d.max_age),
    children_ok: d.children_ok,
    countries: parseCountries(d.countries),
    remote: d.remote,
    run_by_label: d.run_by && !d.run_by.node ? d.run_by.label : null,
    run_by_node_id: d.run_by?.node ? d.run_by.id : null,
    ethics_body: textOrNull(d.ethics_body),
    ethics_reference: textOrNull(d.ethics_reference),
    registry_id: textOrNull(d.registry_id)?.toUpperCase() ?? null,
    external_url: textOrNull(d.external_url),
    opens_at: d.opens_at || null,
    closes_at: d.closes_at || null,
    max_signups: intOrNull(d.max_signups),
    requested_fields: d.requested_fields,
  };
}

const isInt = (s: string, min: number, max: number) => /^\d+$/.test(s.trim()) && Number(s) >= min && Number(s) <= max;
const today = () => new Date().toISOString().slice(0, 10);

/** The same rules the API checks, so most mistakes are named before saving. */
function validate(d: Draft, submitting: boolean): Record<string, string> {
  const e: Record<string, string> = {};
  const len = (k: keyof typeof LIMITS, v: string, field = k as string) => {
    if (v.trim().length > LIMITS[k]) e[field] = `At most ${LIMITS[k]} characters.`;
  };
  if (!d.title.trim()) e.title = "Required.";
  else len("title", d.title);
  if (!d.summary.trim()) e.summary = "Required.";
  else len("summary", d.summary);
  if (!d.participation.trim()) e.participation = "Required.";
  else len("participation", d.participation);
  len("eligibility_text", d.eligibility_text);
  if (d.diseases.length === 0) e.disease_ids = "Add at least one disease.";
  if (d.min_age.trim() && !isInt(d.min_age, 0, 120)) e.min_age = "A whole number from 0 to 120.";
  if (d.max_age.trim() && !isInt(d.max_age, 0, 120)) e.max_age = "A whole number from 0 to 120.";
  if (!e.min_age && !e.max_age && d.min_age.trim() && d.max_age.trim() && Number(d.min_age) > Number(d.max_age)) e.max_age = "Must not be below the minimum age.";
  const countries = parseCountries(d.countries);
  const bad = countries.filter((c) => !/^[A-Z]{2}$/.test(c));
  if (bad.length) e.countries = `Two-letter codes, like DE or US. Not: ${bad.join(", ")}.`;
  else if (countries.length > MAX.countries) e.countries = `At most ${MAX.countries}.`;
  if (d.run_by && !d.run_by.node && d.run_by.label.length > LIMITS.label) e.run_by_label = `At most ${LIMITS.label} characters.`;
  len("label", d.ethics_body, "ethics_body");
  if ((d.kind === "study" || d.kind === "trial") && !d.ethics_reference.trim()) e.ethics_reference = `Required for a ${d.kind}.`;
  else len("ethics_reference", d.ethics_reference);
  const reg = d.registry_id.trim().toUpperCase();
  if (d.kind === "trial" && !reg) e.registry_id = "Required for a trial.";
  else if (reg && !REGISTRY_RE.test(reg)) e.registry_id = "An NCT, EU CT, EudraCT or DRKS number.";
  const url = d.external_url.trim();
  if (url && (!HTTPS_RE.test(url) || url.length > LIMITS.url)) e.external_url = "An https:// link.";
  if (d.opens_at && d.closes_at && d.opens_at > d.closes_at) e.closes_at = "Must not be before the opening date.";
  else if (submitting && d.closes_at && d.closes_at < today()) e.closes_at = "Must not be in the past.";
  if (d.max_signups.trim() && !isInt(d.max_signups, 1, 10000)) e.max_signups = "A whole number from 1 to 10,000.";
  return e;
}

function Field({
  id,
  label,
  hint,
  error,
  optional,
  count,
  children,
  className,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  optional?: boolean;
  count?: { value: number; max: number };
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1.5", className)} data-testid={`field-${id.split("-").pop()}`}>
      <div className="flex items-baseline gap-2">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
          {optional && <span className="font-normal text-muted-foreground"> (optional)</span>}
        </label>
        {count && count.value > count.max * 0.8 && (
          <span className={cn("ml-auto font-mono text-[11px] tabular-nums", count.value > count.max ? "text-destructive" : "text-muted-foreground")}>
            {count.value}/{count.max}
          </span>
        )}
      </div>
      {children}
      {hint && !error && <p className="text-xs text-muted-foreground">{hint}</p>}
      {error && (
        <p id={`${id}-err`} className="text-xs text-destructive" data-testid="field-error">
          {error}
        </p>
      )}
    </div>
  );
}

function RefChips({ items, type, onRemove }: { items: Ref[]; type: NodeType; onRemove: (id: string) => void }) {
  const meta = nodeTypeMeta(type);
  if (!items.length) return null;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((r) => (
        <li key={r.id} className="flex max-w-full items-center gap-1.5 rounded-lg border bg-background py-0.5 pr-0.5 pl-2 text-sm" data-testid={`chip-${type}`}>
          <meta.icon className="size-3.5 shrink-0" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
          <span className="truncate">{r.label}</span>
          <Button variant="ghost" size="icon-xs" onClick={() => onRemove(r.id)} aria-label={`Remove ${r.label}`}>
            <X aria-hidden />
          </Button>
        </li>
      ))}
    </ul>
  );
}

function RefPicker({
  id,
  label,
  type,
  items,
  max,
  error,
  optional,
  onChange,
}: {
  id: string;
  label: string;
  type: NodeType;
  items: Ref[];
  max: number;
  error?: string;
  optional?: boolean;
  onChange: (next: Ref[]) => void;
}) {
  return (
    <Field id={id} label={label} error={error} optional={optional} hint={items.length >= max ? `At most ${max}.` : undefined}>
      <RefChips items={items} type={type} onRemove={(rid) => onChange(items.filter((r) => r.id !== rid))} />
      {items.length < max && (
        <EntityPicker
          types={[type]}
          label={label}
          placeholder={`Add ${label.toLowerCase()}`}
          idleHint="Type a name from the atlas."
          exclude={items.map((r) => r.id)}
          testId={`picker-${type}`}
          onSelect={(h) => {
            onChange([...items, { id: h.id, label: h.label }]);
            announce(`${h.label} added.`);
          }}
        />
      )}
    </Field>
  );
}

type Load =
  | { kind: "loading" }
  | { kind: "ready"; call: OwnCall | null; canPublish: boolean; review: boolean }
  | { kind: "error"; error: ApiError | null };

/** Create (`callId` null) or edit one of the publisher's own calls. */
export function CallForm({ callId }: { callId: string | null }) {
  const { user, status } = useSession();
  const professional = user?.role === "doctor" || user?.role === "researcher";
  const [load, setLoad] = useState<Load>({ kind: "loading" });

  const fetchAll = useCallback(async () => {
    const [list, own] = await Promise.all([
      listMyCalls({ meta: { quiet: true }, cache: "no-store" }),
      callId ? getMyCall({ path: { call_id: callId }, meta: { quiet: true }, cache: "no-store" }) : Promise.resolve(null),
    ]);
    if (!list.data) return setLoad({ kind: "error", error: routeGlobalError(list.error) });
    if (own && !own.data) return setLoad({ kind: "error", error: routeGlobalError(own.error) });
    setLoad({ kind: "ready", call: own?.data ?? null, canPublish: list.data.can_publish, review: reviewRequired(list.data) });
  }, [callId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch, state set after await
    if (professional) void fetchAll();
  }, [professional, fetchAll]);

  const back = (
    <Link href="/calls/mine" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="size-4" aria-hidden /> My calls
    </Link>
  );

  if (status === "loading") return <SessionLoading />;
  if (!user) return <SignInPrompt title="Sign in to write a call" description="Doctors and researchers publish surveys, studies and trials here." returnTo="/calls/mine" />;
  if (!professional) return <NotPublisherNote />;
  if (load.kind === "loading") {
    return (
      <div className="space-y-3" aria-busy="true" aria-label="Loading">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (load.kind === "error") {
    return (
      <div className="space-y-4" data-testid="call-form-error">
        {back}
        <p className="text-sm text-muted-foreground">{callErrorText(load.error)}</p>
      </div>
    );
  }
  if (load.call && !load.call.editable) {
    return (
      <div className="space-y-4" data-testid="call-not-editable">
        {back}
        <p className="text-sm text-muted-foreground">Published, closed and withdrawn calls cannot be edited. Close it and write a new one.</p>
      </div>
    );
  }
  if (!load.canPublish) {
    return (
      <div className="space-y-4">
        {back}
        <CannotPublishNote />
      </div>
    );
  }
  return (
    <div className="space-y-6">
      {back}
      <CallFormBody key={load.call?.id ?? "new"} initial={load.call} review={load.review} />
    </div>
  );
}

function CallFormBody({ initial, review }: { initial: OwnCall | null; review: boolean }) {
  const router = useRouter();
  const ids = useId();
  const id = (name: string) => `${ids}-${name}`;
  const start = useMemo(() => (initial ? draftFrom(initial) : EMPTY), [initial]);
  const [d, setD] = useState<Draft>(start);
  const [saved, setSaved] = useState<OwnCall | null>(initial);
  const [shown, setShown] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<{ text: string; fields: string[] } | null>(null);
  const [busy, setBusy] = useState<"save" | "submit" | null>(null);
  const update = (patch: Partial<Draft>) => setD((x) => ({ ...x, ...patch }));
  const dirty = JSON.stringify(d) !== JSON.stringify(saved ? draftFrom(saved) : EMPTY);

  const errors = { ...shown };
  for (const f of serverError?.fields ?? []) errors[f] ??= serverError?.text.startsWith("Calls look") ? "Rephrase this." : "Check this.";
  const err = (name: string) => errors[name];
  const aria = (name: string) => ({ "aria-invalid": !!err(name) || undefined, "aria-describedby": err(name) ? `${id(name)}-err` : undefined });

  async function save(): Promise<OwnCall | null> {
    const body = toInput(d);
    const { data, error } = saved
      ? await updateCall({ path: { call_id: saved.id }, body, meta: { quiet: true } })
      : await createCall({ body, meta: { quiet: true } });
    if (!data) {
      const e = routeGlobalError(error);
      setServerError({ text: callErrorText(e), fields: e?.code === "validation_error" ? invalidFields(e.message) : [] });
      announce("Not saved. Check the form.", "assertive");
      return null;
    }
    setSaved(data);
    if (!saved) router.replace(`/calls/mine/${encodeURIComponent(data.id)}`, { scroll: false });
    return data;
  }

  async function onSave(submit: boolean) {
    setServerError(null);
    const found = validate(d, submit);
    setShown(found);
    if (Object.keys(found).length) {
      announce(`Check: ${[...new Set(Object.keys(found).map(fieldLabel))].join(", ")}.`, "assertive");
      document.getElementById(id(Object.keys(found)[0]))?.focus();
      return;
    }
    setBusy(submit ? "submit" : "save");
    try {
      const call = dirty || !saved ? await save() : saved;
      if (!call) return;
      if (!submit) {
        toast("Draft saved");
        announce("Draft saved.");
        return;
      }
      const { data, error } = await submitCall({ path: { call_id: call.id }, meta: { quiet: true } });
      if (!data) {
        const e = routeGlobalError(error);
        setServerError({ text: callErrorText(e), fields: e?.code === "validation_error" ? invalidFields(e.message) : [] });
        announce("Not sent. Check the form.", "assertive");
        return;
      }
      invalidatePublishedCalls();
      if (data.status === "published") {
        toast("Published", { description: "It is listed now." });
        announce("Published.");
      } else {
        toast("Sent for review", { description: "The Amber team reviews it before it is listed." });
        announce("Sent for review.");
      }
      router.push("/calls/mine");
    } finally {
      setBusy(null);
    }
  }

  const needsEthics = d.kind === "study" || d.kind === "trial";
  const countryNames = parseCountries(d.countries)
    .filter((c) => /^[A-Z]{2}$/.test(c))
    .map(countryName)
    .join(", ");

  return (
    <form
      className="space-y-8"
      onSubmit={(e) => {
        e.preventDefault();
        void onSave(false);
      }}
      noValidate
      data-testid="call-form"
    >
      <section className="space-y-5">
        <fieldset className="space-y-2" data-testid="field-kind">
          <legend className="text-sm font-medium">Kind</legend>
          <RadioGroup value={d.kind} onValueChange={(v) => update({ kind: v as CallKind })} className="flex flex-wrap gap-2">
            {CALL_KINDS.map((k) => {
              const meta = KIND_META[k];
              return (
                <label
                  key={k}
                  className="flex cursor-pointer items-center gap-2 rounded-lg border bg-background px-3 py-2 text-sm has-data-checked:border-primary has-data-checked:bg-primary/10 has-focus-visible:ring-3 has-focus-visible:ring-ring/50"
                >
                  <RadioGroupItem value={k} aria-label={meta.label} />
                  <meta.icon className="size-4 text-muted-foreground" aria-hidden />
                  {meta.label}
                </label>
              );
            })}
          </RadioGroup>
        </fieldset>

        <Field id={id("title")} label="Title" error={err("title")} count={{ value: d.title.length, max: LIMITS.title }}>
          <Input id={id("title")} value={d.title} onChange={(e) => update({ title: e.target.value })} {...aria("title")} />
        </Field>
        <Field id={id("summary")} label="What it is about" hint="What the research wants to find out." error={err("summary")} count={{ value: d.summary.length, max: LIMITS.summary }}>
          <Textarea id={id("summary")} value={d.summary} onChange={(e) => update({ summary: e.target.value })} rows={4} {...aria("summary")} />
        </Field>
        <Field
          id={id("participation")}
          label="What taking part involves"
          hint="Time, visits, online or not, travel costs covered."
          error={err("participation")}
          count={{ value: d.participation.length, max: LIMITS.participation }}
        >
          <Textarea id={id("participation")} value={d.participation} onChange={(e) => update({ participation: e.target.value })} rows={3} {...aria("participation")} />
        </Field>
        <Field id={id("eligibility_text")} label="Who can take part" optional error={err("eligibility_text")} count={{ value: d.eligibility_text.length, max: LIMITS.eligibility_text }}>
          <Textarea id={id("eligibility_text")} value={d.eligibility_text} onChange={(e) => update({ eligibility_text: e.target.value })} rows={3} {...aria("eligibility_text")} />
        </Field>
      </section>

      <section className="space-y-5 border-t pt-6">
        <RefPicker id={id("disease_ids")} label="Diseases" type="disease" items={d.diseases} max={MAX.diseases} error={err("disease_ids")} onChange={(diseases) => update({ diseases })} />
        <RefPicker id={id("gene_ids")} label="Genes" type="gene" items={d.genes} max={MAX.genes} optional error={err("gene_ids")} onChange={(genes) => update({ genes })} />
        <RefPicker id={id("phenotype_ids")} label="Symptoms" type="phenotype" items={d.phenotypes} max={MAX.phenotypes} optional error={err("phenotype_ids")} onChange={(phenotypes) => update({ phenotypes })} />
      </section>

      <section className="space-y-5 border-t pt-6">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field id={id("min_age")} label="Minimum age" optional error={err("min_age")}>
            <Input id={id("min_age")} inputMode="numeric" value={d.min_age} onChange={(e) => update({ min_age: e.target.value })} {...aria("min_age")} />
          </Field>
          <Field id={id("max_age")} label="Maximum age" optional error={err("max_age")}>
            <Input id={id("max_age")} inputMode="numeric" value={d.max_age} onChange={(e) => update({ max_age: e.target.value })} {...aria("max_age")} />
          </Field>
          <Field id={id("max_signups")} label="Most sign-ups" optional error={err("max_signups")}>
            <Input id={id("max_signups")} inputMode="numeric" value={d.max_signups} onChange={(e) => update({ max_signups: e.target.value })} {...aria("max_signups")} />
          </Field>
        </div>
        <div className="flex flex-wrap gap-x-6 gap-y-3">
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={d.children_ok} onCheckedChange={(v) => update({ children_ok: v === true })} />
            Children can take part
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={d.remote} onCheckedChange={(v) => update({ remote: v === true })} />
            Remote, no visits needed
          </label>
        </div>
        <Field id={id("countries")} label="Countries" optional hint={countryNames || "Two-letter codes, like DE, AT, US."} error={err("countries")}>
          <Input id={id("countries")} value={d.countries} onChange={(e) => update({ countries: e.target.value })} placeholder="DE, AT" autoComplete="off" spellCheck={false} {...aria("countries")} />
        </Field>
        <Field id={id("run_by_label")} label="Run by" optional hint="Institution or patient organisation." error={err("run_by_label") ?? err("run_by_node_id")}>
          {d.run_by ? (
            <div className="flex max-w-full items-center gap-1.5 self-start rounded-lg border bg-background py-0.5 pr-0.5 pl-2 text-sm" data-testid="chip-run-by">
              <span className="truncate">{d.run_by.label}</span>
              <Button variant="ghost" size="icon-xs" onClick={() => update({ run_by: null })} aria-label={`Remove ${d.run_by.label}`}>
                <X aria-hidden />
              </Button>
            </div>
          ) : (
            <EntityPicker
              types={["institution", "patient_org"]}
              label="Run by"
              placeholder="Add an institution"
              idleHint="Type the name of a hospital, university or patient group."
              freeTextMax={LIMITS.label}
              testId="picker-run-by"
              onSelect={(h) => update({ run_by: { id: h.id, label: h.label, node: true } })}
              onFreeText={(text) => update({ run_by: { id: "", label: text, node: false } })}
            />
          )}
        </Field>
      </section>

      <section className="space-y-5 border-t pt-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id={id("ethics_body")} label="Ethics committee" optional={!needsEthics} error={err("ethics_body")}>
            <Input id={id("ethics_body")} value={d.ethics_body} onChange={(e) => update({ ethics_body: e.target.value })} {...aria("ethics_body")} />
          </Field>
          <Field id={id("ethics_reference")} label="Ethics approval reference" optional={!needsEthics} error={err("ethics_reference")}>
            <Input id={id("ethics_reference")} value={d.ethics_reference} onChange={(e) => update({ ethics_reference: e.target.value })} {...aria("ethics_reference")} />
          </Field>
          <Field id={id("registry_id")} label="Registry number" optional={d.kind !== "trial"} hint="NCT, EU CT, EudraCT or DRKS." error={err("registry_id")}>
            <Input
              id={id("registry_id")}
              value={d.registry_id}
              onChange={(e) => update({ registry_id: e.target.value })}
              placeholder="NCT01234567"
              className="font-mono"
              autoComplete="off"
              spellCheck={false}
              {...aria("registry_id")}
            />
          </Field>
          <Field id={id("external_url")} label="Link to the study's page" optional error={err("external_url")}>
            <Input id={id("external_url")} type="url" value={d.external_url} onChange={(e) => update({ external_url: e.target.value })} placeholder="https://" autoComplete="off" {...aria("external_url")} />
          </Field>
          <Field id={id("opens_at")} label="Opens" optional error={err("opens_at")}>
            <Input id={id("opens_at")} type="date" value={d.opens_at} onChange={(e) => update({ opens_at: e.target.value })} {...aria("opens_at")} />
          </Field>
          <Field id={id("closes_at")} label="Closes" optional error={err("closes_at")}>
            <Input id={id("closes_at")} type="date" value={d.closes_at} onChange={(e) => update({ closes_at: e.target.value })} {...aria("closes_at")} />
          </Field>
        </div>
        <fieldset className="space-y-2" data-testid="field-requested_fields">
          <legend className="text-sm font-medium">People can share when they sign up</legend>
          <div className="flex flex-wrap gap-x-5 gap-y-2">
            {REQUESTED.map((f) => (
              <label key={f} className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={d.requested_fields.includes(f)}
                  onCheckedChange={(v) =>
                    update({ requested_fields: v === true ? REQUESTED.filter((x) => x === f || d.requested_fields.includes(x)) : d.requested_fields.filter((x) => x !== f) })
                  }
                />
                {REQUESTED_FIELD_LABELS[f]}
              </label>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">Each person chooses what to send. Nothing is shared before that.</p>
        </fieldset>
      </section>

      <div className="space-y-3 border-t pt-6">
        {serverError && (
          <p role="alert" className="text-sm text-destructive" data-testid="call-form-server-error">
            {serverError.text}
          </p>
        )}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center">
          <Button type="submit" variant="outline" disabled={busy !== null} data-testid="call-save">
            {busy === "save" ? <Loader2 className="animate-spin" data-icon="inline-start" aria-hidden /> : <Save data-icon="inline-start" aria-hidden />}
            Save draft
          </Button>
          <Button type="button" className="sm:ml-auto" onClick={() => void onSave(true)} disabled={busy !== null} data-testid="call-submit">
            {busy === "submit" ? <Loader2 className="animate-spin" data-icon="inline-start" aria-hidden /> : <Send data-icon="inline-start" aria-hidden />}
            {review ? "Submit for review" : "Publish"}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground sm:text-right">
          {review ? "The Amber team checks wording, ethics and registry number before it is listed." : "Publishing lists it for every signed-in user at once."}
        </p>
      </div>
    </form>
  );
}
