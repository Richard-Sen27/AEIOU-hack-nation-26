"use client";

import { Loader2, Save, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { toast } from "sonner";

import { useSession } from "@/components/providers/session-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Skeleton } from "@/components/ui/skeleton";
import { announce } from "@/lib/a11y";
import { nodeTypeMeta } from "@/lib/graph/meta";
import {
  deleteProfessionalProfile,
  getProfessionalProfile,
  matchAtlasEntry,
  putProfessionalProfile,
  unwrap,
} from "@/lib/api";
import type {
  AtlasEntry,
  AtlasEntryCandidate,
  Institution,
  InstitutionInput,
  ProfessionalProfile,
  ProfessionalProfileUpdate,
} from "@/lib/api/generated/types.gen";
import { cn } from "@/lib/utils";

import { routeGlobalError } from "./api-errors";
import { EntityPicker } from "./entity-picker";

/**
 * Optional, private work details of doctors and researchers (`/me/professional`):
 * names, up to three institutions, an ORCID iD and a private link to their own
 * atlas entry. Self-declared: never a verification, never shown to anyone else.
 * Names go only into request bodies, never into a URL (the institution search
 * sends institution names only).
 */

const MAX_INSTITUTIONS = 3;
const NONE = "__none__";
const INSTITUTION = nodeTypeMeta("institution");

const MATCHED_BY: Record<AtlasEntryCandidate["matched_by"], string> = {
  orcid: "Same ORCID iD",
  name_and_institution: "Same name and institution",
  name: "Same name",
};

/** Accepts a pasted `https://orcid.org/…` link or 16 digits without dashes. */
export function normaliseOrcid(raw: string): string {
  let s = raw.trim().replace(/^https?:\/\/(www\.)?orcid\.org\//i, "").replace(/\/+$/, "").toUpperCase();
  if (/^\d{15}[\dX]$/.test(s)) s = s.replace(/(.{4})(?=.)/g, "$1-");
  return s;
}

/** ORCID iD format plus its ISO 7064 mod 11-2 check digit. */
export function isValidOrcid(id: string): boolean {
  if (!/^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/.test(id)) return false;
  const digits = id.replace(/-/g, "");
  let total = 0;
  for (const c of digits.slice(0, 15)) total = (total + Number(c)) * 2;
  const result = (12 - (total % 11)) % 11;
  return digits[15] === (result === 10 ? "X" : String(result));
}

type Draft = {
  first_name: string;
  last_name: string;
  orcid: string;
  institutions: Institution[];
  atlas_node_id: string | null;
};

type Load =
  | { kind: "loading" }
  | { kind: "ready"; profile: ProfessionalProfile; prefilled: boolean }
  | { kind: "error"; message: string; forbidden?: boolean };

type Matches =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "done"; candidates: AtlasEntryCandidate[] }
  | { kind: "error"; message: string };

function draftFrom(p: ProfessionalProfile): { draft: Draft; prefilled: boolean } {
  const hasName = !!(p.first_name || p.last_name);
  const prefilled = !hasName && !p.updated_at && !!(p.suggested?.first_name || p.suggested?.last_name);
  return {
    prefilled,
    draft: {
      first_name: (prefilled ? p.suggested?.first_name : p.first_name) ?? "",
      last_name: (prefilled ? p.suggested?.last_name : p.last_name) ?? "",
      orcid: p.orcid_id ?? "",
      institutions: p.institutions ?? [],
      atlas_node_id: p.atlas_node_id ?? null,
    },
  };
}

const institutionInputs = (list: Institution[]): InstitutionInput[] =>
  list.map((i) => (i.node_id ? { node_id: i.node_id } : { label: i.label }));

function loadMessage(code: string | undefined): string {
  if (code === "forbidden") return "Work details are for doctors and researchers.";
  if (code === "network_error") return "Amber's server is not reachable. Please try again in a moment.";
  if (code === "not_implemented" || code === "not_found") return "Work details are not available yet.";
  return "Your work details could not be loaded. Please try again.";
}

function EntryCard({
  entry,
  onUnlink,
  className,
}: {
  entry: AtlasEntry;
  onUnlink: () => void;
  className?: string;
}) {
  const href = `/node/${encodeURIComponent(entry.node_id)}`;
  const institutions = (entry.institutions ?? []).map((i) => i.label).join(" · ");
  return (
    <div className={cn("space-y-2 rounded-lg border bg-background p-3", className)} data-testid="linked-entry">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-muted-foreground">You said this is you</p>
        <Button variant="ghost" size="sm" className="-my-1" onClick={onUnlink}>
          Unlink
        </Button>
      </div>
      <div>
        <p className="text-sm font-medium">{entry.label}</p>
        {(institutions || entry.orcid_id) && (
          <p className="text-xs text-muted-foreground">
            {institutions}
            {institutions && entry.orcid_id ? " · " : ""}
            {entry.orcid_id && <span className="font-mono">{entry.orcid_id}</span>}
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <Link href={href} className="font-medium underline underline-offset-2">
          Your entry in the atlas
        </Link>
        <Link href={`/about-data?entry=${encodeURIComponent(entry.node_id)}#claim`} className="text-muted-foreground underline underline-offset-2 hover:text-foreground">
          Claim or correct it
        </Link>
      </div>
    </div>
  );
}

export function WorkDetailsForm({
  variant,
  onDone,
}: {
  /** `welcome`: Save and "Skip for now", then `onDone`. `profile`: Save and Remove. */
  variant: "welcome" | "profile";
  onDone?: () => void;
}) {
  const { refresh } = useSession();
  const ids = useId();
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [initial, setInitial] = useState<Draft | null>(null);
  const [entries, setEntries] = useState<Record<string, AtlasEntry>>({});
  const [matches, setMatches] = useState<Matches>({ kind: "idle" });
  const [orcidTouched, setOrcidTouched] = useState(false);
  const [busy, setBusy] = useState<"save" | "remove" | null>(null);

  const apply = useCallback((p: ProfessionalProfile) => {
    const { draft: d, prefilled } = draftFrom(p);
    setDraft(d);
    setInitial(d);
    setEntries(p.linked_entry ? { [p.linked_entry.node_id]: p.linked_entry } : {});
    setMatches({ kind: "idle" });
    setOrcidTouched(false);
    setLoad({ kind: "ready", profile: p, prefilled });
  }, []);

  const fetchProfile = useCallback(async () => {
    setLoad({ kind: "loading" });
    try {
      apply(await unwrap(getProfessionalProfile({ meta: { quiet: true }, cache: "no-store" })));
    } catch (e) {
      const err = routeGlobalError(e);
      setLoad({ kind: "error", message: loadMessage(err?.code), forbidden: err?.code === "forbidden" });
    }
  }, [apply]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch, state set after await
    void fetchProfile();
  }, [fetchProfile]);

  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(initial), [draft, initial]);

  if (load.kind === "loading" || (load.kind === "ready" && !draft)) {
    return (
      <div className="space-y-3" aria-busy="true" aria-label="Loading your work details">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-2/3" />
      </div>
    );
  }
  if (load.kind === "error") {
    return (
      <div className="space-y-3 rounded-lg border border-dashed p-4 text-sm" role="status" data-testid="work-details-error">
        <p className="text-muted-foreground">{load.message}</p>
        <div className="flex flex-wrap gap-2">
          {!load.forbidden && (
            <Button variant="outline" onClick={() => void fetchProfile()}>
              Try again
            </Button>
          )}
          {variant === "welcome" && (
            <Button variant="ghost" onClick={onDone}>
              Skip for now
            </Button>
          )}
        </div>
      </div>
    );
  }

  const d = draft as Draft;
  const saved = load.profile;
  const update = (patch: Partial<Draft>) => setDraft((x) => (x ? { ...x, ...patch } : x));
  const orcid = normaliseOrcid(d.orcid);
  const orcidInvalid = orcid !== "" && !isValidOrcid(orcid);
  const showOrcidError = orcidInvalid && orcidTouched;
  const canMatch = (!!d.first_name.trim() && !!d.last_name.trim()) || (orcid !== "" && !orcidInvalid);
  const linked = d.atlas_node_id ? entries[d.atlas_node_id] : undefined;
  // A choice in the candidate list is shown there; the card is for a saved link.
  const inList = matches.kind === "done" && matches.candidates.some((c) => c.node_id === d.atlas_node_id);
  const linkedMissing = !!d.atlas_node_id && !linked && d.atlas_node_id === saved.atlas_node_id && !!saved.linked_entry_missing;
  const prefillShown =
    load.prefilled &&
    d.first_name === (saved.suggested?.first_name ?? "") &&
    d.last_name === (saved.suggested?.last_name ?? "");

  async function findMatches() {
    if (!canMatch) return;
    setMatches({ kind: "loading" });
    try {
      const res = await unwrap(
        matchAtlasEntry({
          body: {
            first_name: d.first_name.trim() || null,
            last_name: d.last_name.trim() || null,
            orcid_id: orcid && !orcidInvalid ? orcid : null,
            institutions: institutionInputs(d.institutions),
          },
          meta: { quiet: true },
        }),
      );
      const candidates = res.candidates ?? [];
      setMatches({ kind: "done", candidates });
      setEntries((e) => ({ ...e, ...Object.fromEntries(candidates.map((c) => [c.node_id, c])) }));
      announce(candidates.length ? `${candidates.length} possible ${candidates.length === 1 ? "entry" : "entries"} found.` : "No entry found.");
    } catch (e) {
      const err = routeGlobalError(e);
      setMatches({
        kind: "error",
        message:
          err?.code === "rate_limited"
            ? "Too many searches. Please try again in an hour."
            : err?.code === "validation_error"
              ? "Please check your names and ORCID iD."
              : err?.code === "network_error"
                ? "Amber's server is not reachable. Please try again in a moment."
                : "The search did not work. Please try again.",
      });
    }
  }

  async function save() {
    if (orcidInvalid) {
      setOrcidTouched(true);
      announce("Please check your ORCID iD.", "assertive");
      return;
    }
    setBusy("save");
    const body: ProfessionalProfileUpdate = {
      first_name: d.first_name.trim() || null,
      last_name: d.last_name.trim() || null,
      orcid_id: orcid || null,
      institutions: institutionInputs(d.institutions),
      atlas_node_id: d.atlas_node_id,
    };
    try {
      const p = await unwrap(putProfessionalProfile({ body, meta: { quiet: true } }));
      await refresh();
      toast("Work details saved");
      announce("Work details saved.");
      if (variant === "welcome") {
        onDone?.();
        return;
      }
      apply(p);
    } catch (e) {
      const err = routeGlobalError(e);
      toast("Work details not saved", {
        description:
          err?.code === "validation_error"
            ? "Some fields are not valid. Please check them."
            : err?.code === "forbidden"
              ? "Work details are for doctors and researchers."
              : err?.code === "network_error"
                ? "Amber's server is not reachable."
                : "Please try again in a moment.",
      });
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    setBusy("remove");
    try {
      await unwrap(deleteProfessionalProfile({ meta: { quiet: true } }));
      await refresh();
      toast("Work details removed");
      announce("Work details removed.");
      await fetchProfile();
    } catch (e) {
      const err = routeGlobalError(e);
      toast("Work details not removed", {
        description: err?.code === "network_error" ? "Amber's server is not reachable." : "Please try again in a moment.",
      });
    } finally {
      setBusy(null);
    }
  }

  const radioValue =
    matches.kind === "done"
      ? d.atlas_node_id === null
        ? NONE
        : matches.candidates.some((c) => c.node_id === d.atlas_node_id)
          ? d.atlas_node_id
          : null
      : null;

  return (
    <div className="space-y-6" data-testid="work-details">
      <div className="space-y-2">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span className="font-medium">First name</span>
            <Input
              value={d.first_name}
              onChange={(e) => update({ first_name: e.target.value })}
              maxLength={100}
              autoComplete="given-name"
              spellCheck={false}
            />
          </label>
          <label className="space-y-1 text-sm">
            <span className="font-medium">Last name</span>
            <Input
              value={d.last_name}
              onChange={(e) => update({ last_name: e.target.value })}
              maxLength={100}
              autoComplete="family-name"
              spellCheck={false}
            />
          </label>
        </div>
        {prefillShown && <p className="text-xs text-muted-foreground">From your ChatGPT account. Edit as needed.</p>}
      </div>

      <div className="space-y-2">
        <p className="text-sm font-medium" id={`${ids}-inst`}>
          Institutions <span className="font-normal text-muted-foreground">(up to {MAX_INSTITUTIONS})</span>
        </p>
        {d.institutions.length > 0 && (
          <ul className="flex flex-wrap gap-2" aria-labelledby={`${ids}-inst`}>
            {d.institutions.map((inst, i) => (
              <li
                key={`${inst.node_id ?? "text"}-${inst.label}`}
                className="flex max-w-full items-center gap-1.5 rounded-lg border bg-background py-1 pr-1 pl-2 text-sm"
                data-testid="work-institution"
              >
                <INSTITUTION.icon className="size-3.5 shrink-0" style={{ color: `var(${INSTITUTION.colorVar})` }} aria-hidden />
                <span className="truncate">{inst.label}</span>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => update({ institutions: d.institutions.filter((_, j) => j !== i) })}
                  aria-label={`Remove ${inst.label}`}
                  title="Remove"
                >
                  <Trash2 aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
        )}
        {d.institutions.length < MAX_INSTITUTIONS && (
          <EntityPicker
            types={["institution"]}
            label="Add an institution"
            placeholder="Add an institution"
            idleHint="Type the name of a hospital, university or lab."
            exclude={d.institutions.flatMap((x) => (x.node_id ? [x.node_id] : []))}
            testId="picker-institution"
            onSelect={(h) => {
              update({ institutions: [...d.institutions, { node_id: h.id, label: h.label }] });
              announce(`${h.label} added.`);
            }}
            onFreeText={(text) => {
              if (d.institutions.some((x) => x.label.toLowerCase() === text.toLowerCase())) return;
              update({ institutions: [...d.institutions, { node_id: null, label: text }] });
              announce(`${text} added.`);
            }}
          />
        )}
      </div>

      <label className="block space-y-1 text-sm sm:max-w-xs">
        <span className="font-medium">ORCID iD</span>
        <Input
          value={d.orcid}
          onChange={(e) => update({ orcid: e.target.value })}
          onBlur={() => {
            setOrcidTouched(true);
            if (d.orcid && orcid !== d.orcid) update({ orcid });
          }}
          placeholder="0000-0000-0000-0000"
          inputMode="text"
          autoComplete="off"
          spellCheck={false}
          className="font-mono"
          aria-invalid={showOrcidError}
          aria-describedby={showOrcidError ? `${ids}-orcid-err` : undefined}
        />
        {showOrcidError && (
          <span id={`${ids}-orcid-err`} className="block text-xs text-destructive">
            Not a valid ORCID iD.
          </span>
        )}
      </label>

      <section aria-labelledby={`${ids}-entry`} className="space-y-3 border-t pt-5">
        <div>
          <h3 id={`${ids}-entry`} className="text-[15px] font-semibold tracking-tight">
            Your entry in the atlas
          </h3>
          <p className="text-sm text-muted-foreground">Used to find your entry in the atlas.</p>
        </div>
        {linked && !inList && <EntryCard entry={linked} onUnlink={() => update({ atlas_node_id: null })} />}
        {linkedMissing && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
            Your linked entry is no longer in the atlas.
            <Button variant="ghost" size="sm" className="ml-auto" onClick={() => update({ atlas_node_id: null })}>
              Unlink
            </Button>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" onClick={() => void findMatches()} disabled={!canMatch || matches.kind === "loading"} aria-describedby={canMatch ? undefined : `${ids}-match-hint`}>
            {matches.kind === "loading" ? <Loader2 className="animate-spin" aria-hidden /> : <Search aria-hidden />}
            Find me in the atlas
          </Button>
          {!canMatch && (
            <span id={`${ids}-match-hint`} className="text-xs text-muted-foreground">
              Needs both names or your ORCID iD.
            </span>
          )}
        </div>
        {matches.kind === "error" && (
          <p role="alert" className="text-sm text-destructive">
            {matches.message}
          </p>
        )}
        {matches.kind === "done" &&
          (matches.candidates.length === 0 ? (
            <p className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground" data-testid="no-candidates">
              No entry found.
            </p>
          ) : (
            <RadioGroup
              value={radioValue}
              onValueChange={(v) => update({ atlas_node_id: v === NONE ? null : (v as string) })}
              aria-label="Is this you?"
              className="gap-2"
              data-testid="candidates"
            >
              {matches.candidates.map((c) => (
                <label
                  key={c.node_id}
                  className={cn(
                    "flex cursor-pointer items-start gap-2.5 rounded-lg border bg-background p-3 text-sm transition-colors hover:bg-muted/60",
                    "has-data-checked:border-primary has-data-checked:bg-primary/10 has-focus-visible:ring-3 has-focus-visible:ring-ring/50",
                  )}
                  data-testid="candidate"
                >
                  <RadioGroupItem value={c.node_id} aria-label={c.label} className="mt-0.5" />
                  <span className="min-w-0">
                    <span className="block font-medium">{c.label}</span>
                    <span className="block text-xs text-muted-foreground">
                      {[c.type === "doctor" ? "Doctor" : "Researcher", ...(c.institutions ?? []).map((i) => i.label)].join(" · ")}
                      {c.orcid_id && <span className="font-mono"> · {c.orcid_id}</span>}
                    </span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">{MATCHED_BY[c.matched_by]}</span>
                  </span>
                </label>
              ))}
              <label
                className={cn(
                  "flex cursor-pointer items-center gap-2.5 rounded-lg border bg-background p-3 text-sm transition-colors hover:bg-muted/60",
                  "has-data-checked:border-primary has-data-checked:bg-primary/10 has-focus-visible:ring-3 has-focus-visible:ring-ring/50",
                )}
              >
                <RadioGroupItem value={NONE} aria-label="None of these" />
                None of these
              </label>
            </RadioGroup>
          ))}
      </section>

      <div className="flex flex-col-reverse items-stretch gap-3 border-t pt-5 sm:flex-row sm:items-center">
        {variant === "welcome" ? (
          <Button variant="ghost" onClick={onDone} disabled={busy !== null}>
            Skip for now
          </Button>
        ) : (
          saved.updated_at && (
            <Button variant="ghost" onClick={() => void remove()} disabled={busy !== null} data-testid="remove-work-details">
              {busy === "remove" ? <Loader2 className="animate-spin" aria-hidden /> : <Trash2 aria-hidden />}
              Remove
            </Button>
          )
        )}
        <Button
          className="sm:ml-auto"
          size={variant === "welcome" ? "lg" : "default"}
          onClick={() => void save()}
          disabled={busy !== null || (variant === "profile" && !dirty && !!saved.updated_at)}
        >
          {busy === "save" ? <Loader2 className="animate-spin" aria-hidden /> : <Save aria-hidden />}
          Save
        </Button>
      </div>
      {variant === "profile" && saved.updated_at && !dirty && (
        <p className="-mt-3 text-xs text-muted-foreground">Last saved {new Date(saved.updated_at).toLocaleString("en-GB")}</p>
      )}
    </div>
  );
}

/** The one line that frames the work details wherever they are shown. */
export const WORK_DETAILS_NOTE = "Private to you. Not a verification.";
