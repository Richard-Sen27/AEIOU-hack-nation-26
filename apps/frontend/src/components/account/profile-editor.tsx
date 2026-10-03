"use client";

import { Loader2, Plus, Save, Trash2, Undo2 } from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { toast } from "sonner";

import { NodeChip, VusNotice } from "@/components/graph-ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { announce } from "@/lib/a11y";
import { apiFetch } from "@/lib/api/fetch";
import type {
  AgeRange,
  PatientProfile,
  ProfileDisease,
  ProfileGene,
  ProfilePhenotype,
  ProfileSource,
  ProfileVariant,
  VariantClassification,
  Zygosity,
} from "@/lib/api/generated/types.gen";
import { cn } from "@/lib/utils";

import { routeGlobalError } from "./api-errors";
import { EntityPicker } from "./entity-picker";
import {
  AGE_RANGE_LABEL,
  AGE_RANGES,
  CLASSIFICATION_LABEL,
  COUNTRY_CODES,
  ONSETS,
  SOURCE_LABEL,
  ZYGOSITY_LABEL,
  countryName,
} from "./labels";
import { NativeSelect } from "./native-select";

const PRESSED = "aria-pressed:border-primary aria-pressed:bg-primary/15 aria-pressed:text-foreground";

type LoadState = { kind: "loading" } | { kind: "ready" } | { kind: "error"; message: string };

const EMPTY: PatientProfile = { diseases: [], genes: [], variants: [], phenotypes: [] };

function normalise(p: PatientProfile | null | undefined): PatientProfile {
  return {
    ...EMPTY,
    ...(p ?? {}),
    diseases: p?.diseases ?? [],
    genes: p?.genes ?? [],
    variants: p?.variants ?? [],
    phenotypes: p?.phenotypes ?? [],
  };
}

function SourceBadge({ source }: { source: ProfileSource }) {
  return (
    <Badge variant="outline" className="font-normal text-muted-foreground" data-testid="source-badge" data-source={source}>
      {SOURCE_LABEL[source] ?? source}
    </Badge>
  );
}

function RemoveButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <Button variant="ghost" size="icon-sm" onClick={onClick} aria-label={`Remove ${label}`} title="Remove">
      <Trash2 aria-hidden />
    </Button>
  );
}

function Group({
  title,
  description,
  count,
  children,
}: {
  title: string;
  description: string;
  count?: number;
  children: React.ReactNode;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="space-y-3 border-t pt-5 first:border-t-0 first:pt-0">
      <div>
        <h3 id={id} className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
          {title}
          {count !== undefined && (
            <span className="font-mono text-[11px] font-normal text-muted-foreground tabular-nums">{count}</span>
          )}
        </h3>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      {children}
    </section>
  );
}

function EmptyLine({ children }: { children: React.ReactNode }) {
  return <p className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">{children}</p>;
}

const now = () => new Date().toISOString();

export function ProfileEditor() {
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });
  const [saved, setSaved] = useState<PatientProfile>(EMPTY);
  const [draft, setDraft] = useState<PatientProfile>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [phenoMode, setPhenoMode] = useState<"present" | "excluded">("present");
  const [ageMode, setAgeMode] = useState<"years" | "range">("years");
  const ids = useId();

  const fetchProfile = useCallback(async () => {
    try {
      const p = normalise(await apiFetch<PatientProfile>("/profile", { quiet: true, cache: "no-store" }));
      setSaved(p);
      setDraft(p);
      setAgeMode(p.age_range && p.age_years == null ? "range" : "years");
      setLoad({ kind: "ready" });
    } catch (e) {
      const err = routeGlobalError(e);
      setLoad({
        kind: "error",
        message:
          err?.code === "not_implemented"
            ? "Your profile is not available yet. This part of Amber is still being built."
            : err?.code === "network_error"
              ? "Amber's server is not reachable, so your profile cannot be shown right now."
              : "Your profile could not be loaded. Please try again.",
      });
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch, state set after await
    void fetchProfile();
  }, [fetchProfile]);

  const dirty = useMemo(() => JSON.stringify(saved) !== JSON.stringify(draft), [saved, draft]);
  const childInvalid = !!draft.about_child && !draft.parental_responsibility_confirmed;

  const update = (patch: Partial<PatientProfile>) => setDraft((d) => ({ ...d, ...patch }));

  async function save() {
    if (childInvalid) {
      announce("Please confirm parental responsibility before saving.", "assertive");
      return;
    }
    setSaving(true);
    // Optimistic locking: send back the updated_at we last read.
    const body: PatientProfile = { ...draft, updated_at: saved.updated_at ?? null };
    if (!body.about_child) body.parental_responsibility_confirmed = false;
    try {
      const p = normalise(await apiFetch<PatientProfile>("/profile", { method: "PUT", json: body, quiet: true }));
      setSaved(p);
      setDraft(p);
      toast("Profile saved");
      announce("Profile saved.");
    } catch (e) {
      const err = routeGlobalError(e);
      if (err?.code === "conflict") {
        await fetchProfile();
        toast("Your profile changed elsewhere", {
          description: "We loaded the latest version. Please make your change again.",
        });
        return;
      }
      toast("Your profile was not saved", {
        description:
          err?.code === "validation_error"
            ? err.message || "Some fields are not valid. Please check them."
            : err?.code === "not_implemented"
              ? "Saving is not available yet."
              : "Please try again in a moment.",
      });
    } finally {
      setSaving(false);
    }
  }

  if (load.kind === "loading") {
    return (
      <div className="space-y-3" aria-busy="true" aria-label="Loading your profile">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }
  if (load.kind === "error") {
    return (
      <div className="space-y-3 rounded-lg border border-dashed p-4 text-sm" role="status">
        <p className="text-muted-foreground">{load.message}</p>
        <Button variant="outline" onClick={() => void fetchProfile()}>
          Try again
        </Button>
      </div>
    );
  }

  const diseases = draft.diseases ?? [];
  const genes = draft.genes ?? [];
  const variants = draft.variants ?? [];
  const phenotypes = draft.phenotypes ?? [];
  const present = phenotypes.filter((p) => !p.excluded);
  const excluded = phenotypes.filter((p) => p.excluded);

  const setVariant = (i: number, patch: Partial<ProfileVariant>) =>
    update({ variants: variants.map((v, j) => (j === i ? { ...v, ...patch } : v)) });
  const setPheno = (id: string, patch: Partial<ProfilePhenotype>) =>
    update({ phenotypes: phenotypes.map((p) => (p.id === id ? { ...p, ...patch } : p)) });

  const phenoRow = (p: ProfilePhenotype) => (
    <li key={p.id} className="flex flex-wrap items-center gap-2 rounded-lg border bg-background px-2.5 py-2" data-testid="profile-phenotype">
      <NodeChip id={p.id} type="phenotype" label={p.label} href={null} size="sm" className={cn(p.excluded && "line-through decoration-muted-foreground")} />
      <SourceBadge source={p.source} />
      <span className="ml-auto flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setPheno(p.id, { excluded: !p.excluded })}
          aria-label={p.excluded ? `Mark ${p.label} as present` : `Mark ${p.label} as not present`}
        >
          {p.excluded ? "Mark present" : "Mark not present"}
        </Button>
        <RemoveButton label={p.label} onClick={() => update({ phenotypes: phenotypes.filter((x) => x.id !== p.id) })} />
      </span>
    </li>
  );

  return (
    <div className="space-y-6" data-testid="profile-editor">
      <Group
        title="Diagnoses"
        description="Diagnoses you confirmed. Amber never makes a diagnosis."
        count={diseases.length}
      >
        {diseases.length ? (
          <ul className="space-y-2">
            {diseases.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center gap-2 rounded-lg border bg-background px-2.5 py-2" data-testid="profile-disease">
                <NodeChip id={d.id} type="disease" label={d.label} size="sm" />
                <SourceBadge source={d.source} />
                <span className="ml-auto">
                  <RemoveButton label={d.label} onClick={() => update({ diseases: diseases.filter((x) => x.id !== d.id) })} />
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyLine>No diagnoses yet.</EmptyLine>
        )}
        <EntityPicker
          types={["disease"]}
          label="Add a diagnosis"
          placeholder="Add a diagnosis, e.g. Dravet syndrome"
          exclude={diseases.map((d) => d.id)}
          testId="picker-disease"
          onSelect={(h) => {
            const item: ProfileDisease = { id: h.id, label: h.label, source: "manual", confirmed_at: now() };
            update({ diseases: [...diseases, item] });
            announce(`${h.label} added. Save to keep it.`);
          }}
        />
      </Group>

      <Group title="Genes" description="Genes named in a report or by your care team." count={genes.length}>
        {genes.length ? (
          <ul className="flex flex-wrap gap-2">
            {genes.map((g) => (
              <li key={g.id} className="flex items-center gap-1.5 rounded-lg border bg-background py-1 pr-1 pl-2" data-testid="profile-gene">
                <NodeChip id={g.id} type="gene" label={g.label} size="sm" />
                <SourceBadge source={g.source} />
                <RemoveButton label={g.label} onClick={() => update({ genes: genes.filter((x) => x.id !== g.id) })} />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyLine>No genes yet.</EmptyLine>
        )}
        <EntityPicker
          types={["gene"]}
          label="Add a gene"
          placeholder="Add a gene, e.g. STXBP1"
          exclude={genes.map((g) => g.id)}
          testId="picker-gene"
          onSelect={(h) => {
            const item: ProfileGene = { id: h.id, label: h.label, source: "manual", confirmed_at: now() };
            update({ genes: [...genes, item] });
            announce(`${h.label} added. Save to keep it.`);
          }}
        />
      </Group>

      <Group
        title="Variants"
        description="As written on the genetic report, in HGVS notation (for example NM_003165.6:c.1631G>A)."
        count={variants.length}
      >
        {variants.length ? (
          <ul className="space-y-3">
            {variants.map((v, i) => (
              <li key={`${v.finding_id ?? "v"}-${i}`} className="space-y-3 rounded-lg border bg-background p-3" data-testid="profile-variant">
                <div className="flex items-center gap-2">
                  <SourceBadge source={v.source} />
                  <span className="ml-auto">
                    <RemoveButton label={`variant ${v.hgvs || i + 1}`} onClick={() => update({ variants: variants.filter((_, j) => j !== i) })} />
                  </span>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="space-y-1 text-sm sm:col-span-2">
                    <span className="font-medium">HGVS</span>
                    <Input
                      value={v.hgvs ?? ""}
                      onChange={(e) => setVariant(i, { hgvs: e.target.value || null })}
                      className="font-mono"
                      spellCheck={false}
                      autoComplete="off"
                    />
                  </label>
                  <label className="space-y-1 text-sm">
                    <span className="font-medium">Gene</span>
                    <NativeSelect value={v.gene_id ?? ""} onChange={(e) => setVariant(i, { gene_id: e.target.value || null })}>
                      <option value="">Not set</option>
                      {genes.map((g) => (
                        <option key={g.id} value={g.id}>
                          {g.label}
                        </option>
                      ))}
                      {v.gene_id && !genes.some((g) => g.id === v.gene_id) && <option value={v.gene_id}>{v.gene_id}</option>}
                    </NativeSelect>
                  </label>
                  <label className="space-y-1 text-sm">
                    <span className="font-medium">Zygosity</span>
                    <NativeSelect value={v.zygosity ?? ""} onChange={(e) => setVariant(i, { zygosity: (e.target.value || null) as Zygosity | null })}>
                      <option value="">Not set</option>
                      {Object.entries(ZYGOSITY_LABEL).map(([k, l]) => (
                        <option key={k} value={k}>
                          {l}
                        </option>
                      ))}
                    </NativeSelect>
                  </label>
                  <label className="space-y-1 text-sm">
                    <span className="font-medium">Classification</span>
                    <NativeSelect
                      value={v.classification ?? ""}
                      onChange={(e) => setVariant(i, { classification: (e.target.value || null) as VariantClassification | null })}
                    >
                      <option value="">Not set</option>
                      {Object.entries(CLASSIFICATION_LABEL).map(([k, l]) => (
                        <option key={k} value={k}>
                          {l}
                        </option>
                      ))}
                    </NativeSelect>
                  </label>
                  <label className="space-y-1 text-sm">
                    <span className="font-medium">Test date</span>
                    <Input type="date" value={v.test_date ?? ""} onChange={(e) => setVariant(i, { test_date: e.target.value || null })} />
                  </label>
                </div>
                {v.classification === "uncertain_significance" && <VusNotice compact />}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyLine>No variants yet. Upload a genetic report, or add one by hand.</EmptyLine>
        )}
        <Button
          variant="outline"
          onClick={() => update({ variants: [...variants, { source: "manual", confirmed_at: now(), hgvs: "" }] })}
        >
          <Plus aria-hidden /> Add a variant
        </Button>
      </Group>

      <Group
        title="Symptoms"
        description="Symptoms present, and ones that are clearly not present (that helps tell similar conditions apart)."
        count={phenotypes.length}
      >
        {present.length ? <ul className="space-y-2" aria-label="Present">{present.map(phenoRow)}</ul> : <EmptyLine>No symptoms yet.</EmptyLine>}
        {excluded.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Not present</p>
            <ul className="space-y-2" aria-label="Not present">{excluded.map(phenoRow)}</ul>
          </div>
        )}
        <div className="space-y-2">
          <ToggleGroup
            value={[phenoMode]}
            onValueChange={(v: unknown[]) => v[0] && setPhenoMode(v[0] as "present" | "excluded")}
            variant="outline"
            size="sm"
            aria-label="Add as"
          >
            <ToggleGroupItem value="present" className={PRESSED}>Add as present</ToggleGroupItem>
            <ToggleGroupItem value="excluded" className={PRESSED}>Add as not present</ToggleGroupItem>
          </ToggleGroup>
          <EntityPicker
            types={["phenotype"]}
            label="Add a symptom"
            placeholder="Add a symptom, e.g. seizures"
            exclude={phenotypes.map((p) => p.id)}
            testId="picker-phenotype"
            onSelect={(h) => {
              const item: ProfilePhenotype = {
                id: h.id,
                label: h.label,
                source: "manual",
                confirmed_at: now(),
                excluded: phenoMode === "excluded",
              };
              update({ phenotypes: [...phenotypes, item] });
              announce(`${h.label} added. Save to keep it.`);
            }}
          />
        </div>
      </Group>

      <Group title="About" description="Only what helps find connections. Amber never asks for names, birth dates, addresses or patient numbers.">
        <div className="grid gap-4 sm:grid-cols-2">
          <fieldset className="space-y-2 text-sm sm:col-span-2">
            <legend className="mb-1 font-medium">Age</legend>
            <div className="flex flex-wrap items-center gap-3">
              <ToggleGroup
                value={[ageMode]}
                onValueChange={(v: unknown[]) => {
                  const m = v[0] as "years" | "range" | undefined;
                  if (!m) return;
                  setAgeMode(m);
                  update(m === "years" ? { age_range: null } : { age_years: null });
                }}
                variant="outline"
                size="sm"
                aria-label="Age as"
              >
                <ToggleGroupItem value="years" className={PRESSED}>In years</ToggleGroupItem>
                <ToggleGroupItem value="range" className={PRESSED}>As a range</ToggleGroupItem>
              </ToggleGroup>
              {ageMode === "years" ? (
                <Input
                  type="number"
                  min={0}
                  max={120}
                  inputMode="numeric"
                  aria-label="Age in years"
                  value={draft.age_years ?? ""}
                  onChange={(e) => update({ age_years: e.target.value === "" ? null : Math.max(0, Math.min(120, Number(e.target.value))) })}
                  className="w-28"
                />
              ) : (
                <NativeSelect
                  aria-label="Age range"
                  value={draft.age_range ?? ""}
                  onChange={(e) => update({ age_range: (e.target.value || null) as AgeRange | null })}
                  className="w-48"
                >
                  <option value="">Not set</option>
                  {AGE_RANGES.map((r) => (
                    <option key={r} value={r}>
                      {AGE_RANGE_LABEL[r]}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </div>
          </fieldset>
          <label className="space-y-1 text-sm">
            <span className="font-medium">When symptoms started</span>
            <NativeSelect value={draft.onset ?? ""} onChange={(e) => update({ onset: e.target.value || null })}>
              <option value="">Not set</option>
              {ONSETS.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
              {draft.onset && !ONSETS.some((o) => o.id === draft.onset) && <option value={draft.onset}>{draft.onset}</option>}
            </NativeSelect>
          </label>
          <label className="space-y-1 text-sm">
            <span className="font-medium">Country (optional)</span>
            <NativeSelect value={draft.country ?? ""} onChange={(e) => update({ country: e.target.value || null })}>
              <option value="">Not set</option>
              {COUNTRY_CODES.map((c) => (
                <option key={c} value={c}>
                  {countryName(c)}
                </option>
              ))}
            </NativeSelect>
            <span className="block text-xs text-muted-foreground">Only used to find patient groups near you.</span>
          </label>
        </div>
        <div className="space-y-2 rounded-lg border bg-muted/40 p-3 text-sm">
          <label htmlFor={`${ids}-child`} className="flex items-start gap-2.5">
            <Checkbox
              id={`${ids}-child`}
              checked={!!draft.about_child}
              onCheckedChange={(v) => update({ about_child: v === true, ...(v === true ? {} : { parental_responsibility_confirmed: false }) })}
              className="mt-0.5"
            />
            <span>This profile describes a child I care for.</span>
          </label>
          {draft.about_child && (
            <label htmlFor={`${ids}-parental`} className="flex items-start gap-2.5">
              <Checkbox
                id={`${ids}-parental`}
                checked={!!draft.parental_responsibility_confirmed}
                onCheckedChange={(v) => update({ parental_responsibility_confirmed: v === true })}
                aria-invalid={childInvalid}
                className="mt-0.5"
              />
              <span>
                I confirm that I hold parental responsibility (I am the parent or legal guardian) for this child.
                {childInvalid && <span className="mt-1 block text-destructive">Needed before you can save.</span>}
              </span>
            </label>
          )}
        </div>
      </Group>

      <div
        className={cn(
          "sticky bottom-3 z-10 flex flex-wrap items-center gap-3 rounded-xl border bg-card/95 p-3 shadow-lg backdrop-blur",
          !dirty && "hidden",
        )}
      >
        <p className="text-sm text-muted-foreground">You have unsaved changes.</p>
        <span className="ml-auto flex gap-2">
          <Button variant="ghost" onClick={() => setDraft(saved)} disabled={saving}>
            <Undo2 aria-hidden /> Discard
          </Button>
          <Button onClick={() => void save()} disabled={saving || childInvalid}>
            {saving ? <Loader2 className="animate-spin" aria-hidden /> : <Save aria-hidden />}
            Save changes
          </Button>
        </span>
      </div>
      {draft.updated_at && !dirty && (
        <p className="text-xs text-muted-foreground">Last saved {new Date(draft.updated_at).toLocaleString("en-GB")}</p>
      )}
    </div>
  );
}

export { normalise as normaliseProfile };
