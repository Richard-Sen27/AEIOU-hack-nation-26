"use client";

import { Loader2, Plus, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useId, useState } from "react";
import { toast } from "sonner";

import { NodeChip, OriginBadge, StatusFlag } from "@/components/graph-ui";
import { useGate } from "@/components/providers/gate-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { announce } from "@/lib/a11y";
import { ApiError, reportApiError } from "@/lib/api/errors";
import { createContribution, deleteContribution, getProfile, listContributions, unwrap } from "@/lib/api";
import type {
  AgeRange,
  AssetType,
  Contribution,
  ContributionCreate,
  PatientProfile,
} from "@/lib/api/generated/types.gen";
import type { SearchHit } from "@/lib/api/types";

import { routeGlobalError } from "./api-errors";
import { EntityPicker } from "./entity-picker";
import { AGE_RANGE_LABEL, AGE_RANGES, ASSET_TYPE_LABEL, formatDate } from "./labels";
import { NativeSelect } from "./native-select";

const PRESSED = "aria-pressed:border-primary aria-pressed:bg-primary/15 aria-pressed:text-foreground";

type Ref = { id: string; label: string };

function asStrings(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

function RefList({
  items,
  type,
  onRemove,
}: {
  items: Ref[];
  type: string;
  onRemove: (id: string) => void;
}) {
  if (!items.length) return null;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((r) => (
        <li key={r.id} className="flex items-center gap-0.5 rounded-md border bg-background pr-0.5">
          <NodeChip id={r.id} type={type} label={r.label} href={null} size="sm" className="border-0" />
          <Button variant="ghost" size="icon-xs" onClick={() => onRemove(r.id)} aria-label={`Remove ${r.label}`}>
            <X aria-hidden />
          </Button>
        </li>
      ))}
    </ul>
  );
}

function ContributionForm({
  onCreated,
  onClose,
}: {
  onCreated: (c: Contribution) => void;
  onClose: () => void;
}) {
  const ids = useId();
  const [kind, setKind] = useState<"phenotype_profile" | "asset">("phenotype_profile");
  const [disease, setDisease] = useState<Ref | null>(null);
  const [present, setPresent] = useState<Ref[]>([]);
  const [absent, setAbsent] = useState<Ref[]>([]);
  const [ageRange, setAgeRange] = useState<AgeRange | "">("");
  const [assetType, setAssetType] = useState<AssetType>("registry");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [assetDiseases, setAssetDiseases] = useState<Ref[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const add = (list: Ref[], set: (r: Ref[]) => void) => (h: SearchHit) =>
    !list.some((r) => r.id === h.id) && set([...list, { id: h.id, label: h.label }]);

  async function prefill() {
    let profile: PatientProfile;
    try {
      profile = await unwrap(getProfile({ meta: { quiet: true }, cache: "no-store" }));
    } catch {
      toast("Your profile could not be loaded");
      return;
    }
    const d = profile.diseases?.[0];
    if (d) setDisease({ id: d.id, label: d.label });
    setPresent((profile.phenotypes ?? []).filter((p) => !p.excluded).map((p) => ({ id: p.id, label: p.label })));
    setAbsent((profile.phenotypes ?? []).filter((p) => p.excluded).map((p) => ({ id: p.id, label: p.label })));
    if (profile.age_range) setAgeRange(profile.age_range);
    announce("Filled in from your profile. Check it before you contribute.");
  }

  const valid =
    kind === "phenotype_profile" ? !!disease && present.length > 0 : name.trim().length > 1 && (!url || /^https?:\/\//.test(url));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    const body: ContributionCreate =
      kind === "phenotype_profile"
        ? {
            kind,
            payload: {
              disease_id: disease!.id,
              phenotype_ids: present.map((r) => r.id),
              excluded_phenotype_ids: absent.map((r) => r.id),
              age_range: ageRange || null,
            },
          }
        : {
            kind,
            payload: {
              asset_type: assetType,
              name: name.trim(),
              url: url.trim() || null,
              description: description.trim() || null,
              disease_ids: assetDiseases.map((r) => r.id),
            },
          };
    try {
      const created = await unwrap(createContribution({ body, meta: { quiet: true } }));
      onCreated(created);
    } catch (err) {
      const ae = routeGlobalError(err);
      if (ae?.code === "consent_required") reportApiError(ae);
      setError(
        ae?.code === "consent_required"
          ? "Contributing needs your consent first."
          : ae?.code === "not_implemented"
            ? "Contributions are not available yet. Nothing was submitted."
            : ae?.code === "validation_error"
              ? ae.message || "Some fields are not valid. Please check them."
              : ae?.code === "rate_limited"
                ? "You have contributed a lot in the last hour (limit 30). Please try again later."
              : "Your contribution was not submitted. Please try again.",
      );
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-lg border bg-background p-4" data-testid="contribution-form" aria-label="New contribution">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ToggleGroup
          value={[kind]}
          onValueChange={(v: unknown[]) => v[0] && setKind(v[0] as typeof kind)}
          variant="outline"
          size="sm"
          aria-label="What to contribute"
        >
          <ToggleGroupItem value="phenotype_profile" className={PRESSED}>Symptom profile</ToggleGroupItem>
          <ToggleGroupItem value="asset" className={PRESSED}>Resource</ToggleGroupItem>
        </ToggleGroup>
        <Button type="button" variant="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
      </div>

      <p className="rounded-md bg-muted/60 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
        It will be shown as <strong className="font-medium text-foreground">patient-reported</strong>, waits for review, and
        is never treated as cited evidence. Do not include names, birth dates, addresses or anything that identifies a
        person.
      </p>

      {kind === "phenotype_profile" ? (
        <div className="space-y-4">
          <Button type="button" variant="outline" size="sm" onClick={() => void prefill()}>
            Fill in from my profile
          </Button>
          <div className="space-y-2">
            <p className="text-sm font-medium">Diagnosis</p>
            {disease ? (
              <RefList items={[disease]} type="disease" onRemove={() => setDisease(null)} />
            ) : (
              <EntityPicker types={["disease"]} label="Contribution diagnosis" placeholder="Search a diagnosis" onSelect={(h) => setDisease({ id: h.id, label: h.label })} />
            )}
          </div>
          <div className="space-y-2">
            <p className="text-sm font-medium">Symptoms present</p>
            <RefList items={present} type="phenotype" onRemove={(id) => setPresent(present.filter((r) => r.id !== id))} />
            <EntityPicker
              types={["phenotype"]}
              label="Add a symptom present"
              placeholder="Search a symptom"
              exclude={[...present, ...absent].map((r) => r.id)}
              onSelect={add(present, setPresent)}
            />
          </div>
          <div className="space-y-2">
            <p className="text-sm font-medium">Symptoms clearly not present (optional)</p>
            <RefList items={absent} type="phenotype" onRemove={(id) => setAbsent(absent.filter((r) => r.id !== id))} />
            <EntityPicker
              types={["phenotype"]}
              label="Add a symptom not present"
              placeholder="Search a symptom"
              exclude={[...present, ...absent].map((r) => r.id)}
              onSelect={add(absent, setAbsent)}
            />
          </div>
          <label className="block max-w-xs space-y-1 text-sm">
            <span className="font-medium">Age range (optional)</span>
            <NativeSelect value={ageRange} onChange={(e) => setAgeRange(e.target.value as AgeRange | "")}>
              <option value="">Not given</option>
              {AGE_RANGES.map((r) => (
                <option key={r} value={r}>
                  {AGE_RANGE_LABEL[r]}
                </option>
              ))}
            </NativeSelect>
          </label>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span className="font-medium">Type</span>
            <NativeSelect value={assetType} onChange={(e) => setAssetType(e.target.value as AssetType)}>
              {Object.entries(ASSET_TYPE_LABEL).map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </NativeSelect>
          </label>
          <label htmlFor={`${ids}-name`} className="space-y-1 text-sm">
            <span className="font-medium">Name</span>
            <Input id={`${ids}-name`} value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required />
          </label>
          <label htmlFor={`${ids}-url`} className="space-y-1 text-sm sm:col-span-2">
            <span className="font-medium">Public web address (optional)</span>
            <Input id={`${ids}-url`} type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" />
          </label>
          <label htmlFor={`${ids}-desc`} className="space-y-1 text-sm sm:col-span-2">
            <span className="font-medium">Short description (optional)</span>
            <Textarea id={`${ids}-desc`} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={1000} rows={3} />
          </label>
          <div className="space-y-2 sm:col-span-2">
            <p className="text-sm font-medium">Related diagnoses (optional)</p>
            <RefList items={assetDiseases} type="disease" onRemove={(id) => setAssetDiseases(assetDiseases.filter((r) => r.id !== id))} />
            <EntityPicker
              types={["disease"]}
              label="Add a related diagnosis"
              placeholder="Search a diagnosis"
              exclude={assetDiseases.map((r) => r.id)}
              onSelect={add(assetDiseases, setAssetDiseases)}
            />
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex justify-end">
        <Button type="submit" disabled={!valid || busy}>
          {busy && <Loader2 className="animate-spin" aria-hidden />}
          Contribute
        </Button>
      </div>
    </form>
  );
}

function summary(c: Contribution): React.ReactNode {
  const p = c.payload ?? {};
  if (c.kind === "asset") {
    const t = ASSET_TYPE_LABEL[p.asset_type as AssetType] ?? "Resource";
    return (
      <>
        <span className="font-medium">{String(p.name ?? "Resource")}</span>
        <span className="text-muted-foreground"> · {t}</span>
      </>
    );
  }
  if (c.kind === "candidate_edge") {
    return (
      <>
        <span className="font-medium">Suggested link</span>
        <span className="text-muted-foreground">
          {" "}
          · {String(p.source_id ?? "")} → {String(p.target_id ?? "")}
        </span>
      </>
    );
  }
  const present = asStrings(p.phenotype_ids).length;
  const absent = asStrings(p.excluded_phenotype_ids).length;
  return (
    <>
      <span className="font-medium">Symptom profile</span>
      <span className="text-muted-foreground">
        {" "}
        · {String(p.disease_id ?? "")} · {present} present{absent ? `, ${absent} not present` : ""}
      </span>
    </>
  );
}

export function ContributionsSection() {
  const { requireConsent } = useGate();
  const [list, setList] = useState<Contribution[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setList(await unwrap(listContributions({ meta: { quiet: true }, cache: "no-store" })));
      setError(null);
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "";
      setList([]);
      setError(code === "not_implemented" ? "Contributions are not available yet." : "Your contributions could not be loaded.");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch, state set after await
    void load();
  }, [load]);

  async function remove(id: string) {
    setRemoving(id);
    try {
      await unwrap(deleteContribution({ path: { contribution_id: id }, meta: { quiet: true } }));
      setList((l) => (l ?? []).filter((c) => c.id !== id));
      toast("Contribution removed from the atlas");
      announce("Contribution removed.");
    } catch {
      toast("Contribution not removed", { description: "Please try again." });
    } finally {
      setRemoving(null);
    }
  }

  async function open() {
    if (await requireConsent("contribute", "Contributing to the atlas needs an account.")) setFormOpen(true);
  }

  return (
    <div className="space-y-4">
      {error ? (
        <p className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">{error}</p>
      ) : list === null ? null : list.length ? (
        <ul className="space-y-2" data-testid="contribution-list">
          {list.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-2 rounded-lg border bg-background px-3 py-2.5 text-sm" data-testid="contribution">
              <span className="min-w-0 flex-1">{summary(c)}</span>
              <OriginBadge origin="patient_reported" />
              {c.status === "pending_review" ? (
                <StatusFlag status="pending_review" />
              ) : (
                <Badge variant="outline">{c.status === "accepted" ? "Accepted" : "Not accepted"}</Badge>
              )}
              <span className="text-xs text-muted-foreground">{formatDate(c.created_at)}</span>
              <Button variant="ghost" size="sm" onClick={() => void remove(c.id)} disabled={removing === c.id} aria-label="Remove contribution">
                <Trash2 aria-hidden /> Remove
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">You have not contributed anything.</p>
      )}

      {formOpen ? (
        <ContributionForm
          onClose={() => setFormOpen(false)}
          onCreated={(c) => {
            setList((l) => [c, ...(l ?? [])]);
            setFormOpen(false);
            toast("Thank you. Your contribution is waiting for review.");
            announce("Contribution submitted. It is pending review.");
          }}
        />
      ) : (
        <Button variant="outline" onClick={() => void open()} data-testid="contribute-open">
          <Plus aria-hidden /> Contribute a symptom profile or resource
        </Button>
      )}
    </div>
  );
}
