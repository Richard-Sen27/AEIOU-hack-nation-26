"use client";

import { ExternalLink, Loader2, Save, Send, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useState } from "react";
import { toast } from "sonner";

import { cardHref, PublicCardView } from "@/components/people/public-card";
import { forgetCard } from "@/components/people/use-people";
import { VerificationLabel } from "@/components/people/verification-label";
import { useSession } from "@/components/providers/session-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { announce } from "@/lib/a11y";
import {
  putMyCard,
  requestVerification,
  startOrcidConfirmation,
  unwrap,
  withdrawVerificationRequest,
  type Schemas,
} from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

import { routeGlobalError } from "./api-errors";
import { formatDate } from "./labels";
import { useMyCard } from "./use-my-card";
import { WORK_DETAILS_NOTE } from "./work-details";

type MyCard = Schemas.MyCard;

const MAX_HEADLINE = 160;

/** `?orcid=` on the way back from ORCID sign-in (`POST /me/professional/orcid/start`). */
const ORCID_RESULT: Record<string, { text: string; ok: boolean }> = {
  confirmed: { text: "ORCID iD confirmed.", ok: true },
  denied: { text: "ORCID sign-in was cancelled.", ok: false },
  failed: { text: "ORCID check failed. Please try again.", ok: false },
  already_linked: { text: "This ORCID iD is already confirmed on another Amber account.", ok: false },
};

const BLOCKED: Record<NonNullable<MyCard["blocked_reason"]>, string> = {
  role: "Cards are for doctors and researchers.",
  not_verified: "Confirm who you are first.",
  no_name: "Add your name above first.",
};

function errorText(err: ApiError | null, fallback: string): string {
  switch (err?.code) {
    case "network_error":
      return "Amber's server is not reachable.";
    case "rate_limited":
      return "Too many tries. Please try again later.";
    case "not_implemented":
      return "ORCID sign-in is not set up on this server.";
    case "conflict":
    case "forbidden":
      return err.message || fallback;
    default:
      return fallback;
  }
}

/** The panel's one-line note: the original promise, reworded only once a card is switched on. */
export function WorkNote() {
  const { card } = useMyCard();
  return <span data-testid="work-note">{card?.settings.visible ? "Your public card shows only what you switch on below." : WORK_DETAILS_NOTE}</span>;
}

/**
 * Verification and the opt-in public card of doctors and researchers, below
 * their work details on the profile. Verification: ORCID sign-in, or a manual
 * check by the Amber team. Card: off by default, every part a choice.
 */
export function CardSection() {
  const my = useMyCard();
  const { refresh } = useSession();
  const [orcidResult, setOrcidResult] = useState<string | null>(null);

  // Coming back from ORCID: read the result once, drop it from the address bar, re-read the state.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const result = params.get("orcid");
    if (!result) return;
    params.delete("orcid");
    const rest = params.toString();
    window.history.replaceState(window.history.state, "", `${window.location.pathname}${rest ? `?${rest}` : ""}#your-work`);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time read of the return URL
    setOrcidResult(ORCID_RESULT[result] ? result : "failed");
    announce(ORCID_RESULT[result]?.text ?? ORCID_RESULT.failed.text);
    document.getElementById("your-work")?.scrollIntoView({ block: "start" });
    void refresh();
    void my.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once on mount
  }, []);

  if (my.status === "idle" || my.status === "loading" || (my.status === "ready" && !my.card)) {
    return (
      <div className="space-y-3 border-t pt-5" aria-busy="true" aria-label="Loading your verification">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }
  if (my.status === "error") {
    return (
      <div className="flex flex-wrap items-center gap-3 border-t pt-5 text-sm text-muted-foreground" role="status" data-testid="card-section-error">
        {my.error?.code === "network_error" ? "Amber's server is not reachable." : "Your verification could not be loaded."}
        <Button variant="outline" size="sm" onClick={() => void my.reload()}>
          Try again
        </Button>
      </div>
    );
  }

  const card = my.card as MyCard;
  const result = orcidResult ? ORCID_RESULT[orcidResult] : null;
  return (
    <div className="space-y-6" data-testid="card-section">
      {result && (
        <p
          role="status"
          className={cn(
            "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm",
            result.ok ? "border-confidence-high/40 bg-confidence-high/10" : "border-status-flag/40 bg-status-flag/10",
          )}
          data-testid="orcid-result"
          data-result={orcidResult}
        >
          <span className="flex-1">{result.text}</span>
          <Button variant="ghost" size="icon-sm" onClick={() => setOrcidResult(null)} aria-label="Dismiss">
            <X aria-hidden />
          </Button>
        </p>
      )}
      <VerificationBlock card={card} onCard={my.apply} reload={my.reload} />
      <CardSettingsBlock card={card} onCard={my.apply} reload={my.reload} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Verification

function VerificationBlock({
  card,
  onCard,
  reload,
}: {
  card: MyCard;
  onCard: (c: MyCard) => void;
  reload: () => Promise<void>;
}) {
  const { refresh } = useSession();
  const ids = useId();
  const v = card.verification;
  const [formOpen, setFormOpen] = useState(false);
  const [busy, setBusy] = useState<"orcid" | "withdraw" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function startOrcid() {
    setError(null);
    setBusy("orcid");
    try {
      const res = await unwrap(startOrcidConfirmation({ body: { return_to: "/profile" }, meta: { quiet: true } }));
      window.location.assign(res.authorize_url);
    } catch (e) {
      setError(errorText(routeGlobalError(e), "ORCID sign-in could not start. Please try again."));
      setBusy(null);
    }
  }

  async function withdraw() {
    setError(null);
    setBusy("withdraw");
    try {
      await unwrap(withdrawVerificationRequest({ meta: { quiet: true } }));
      announce("Request withdrawn.");
      await reload();
    } catch (e) {
      setError(errorText(routeGlobalError(e), "Could not withdraw. Please try again."));
    } finally {
      setBusy(null);
    }
  }

  const request = v.request;
  const showForm = !v.verified && request?.status !== "pending" && (formOpen || !v.orcid_available);

  return (
    <section aria-labelledby={`${ids}-h`} className="space-y-3 border-t pt-5" data-testid="verification">
      <h3 id={`${ids}-h`} className="text-[15px] font-semibold tracking-tight">
        Verification
      </h3>

      {v.verified && v.method && v.label ? (
        <div className="space-y-1" data-testid="verified">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <VerificationLabel verification={{ method: v.method, label: v.label, simulated: !!v.simulated }} className="text-sm" />
            {v.verified_at && <span className="text-xs text-muted-foreground">{formatDate(v.verified_at)}</span>}
          </p>
          {v.method === "institutional_email" && (
            <p className="text-xs text-muted-foreground" data-testid="reviewed-note">
              Changing your name or institutions ends it.
            </p>
          )}
        </div>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">Confirm who you are to switch on a public card.</p>

          {request?.status === "pending" ? (
            <div className="space-y-2 rounded-lg border bg-background p-3 text-sm" data-testid="request-pending">
              <p>
                <span className="font-medium">Request sent</span>{" "}
                <span className="text-muted-foreground">{formatDate(request.requested_at)}</span>
              </p>
              {(request.institutional_email || request.profile_url) && (
                <p className="text-xs break-all text-muted-foreground">
                  {[request.institutional_email, request.profile_url].filter(Boolean).join(" · ")}
                </p>
              )}
              <Button variant="outline" size="sm" onClick={() => void withdraw()} disabled={busy !== null}>
                {busy === "withdraw" && <Loader2 className="animate-spin" aria-hidden />}
                Withdraw
              </Button>
            </div>
          ) : (
            <>
              {request?.status === "rejected" && (
                <div className="flex flex-wrap items-center gap-2 rounded-lg border border-status-flag/40 bg-status-flag/10 p-3 text-sm" data-testid="request-rejected">
                  <span className="flex-1">
                    Not approved{request.decided_at ? ` (${formatDate(request.decided_at)})` : ""}. You can send a new request.
                  </span>
                  <Button variant="ghost" size="sm" onClick={() => void withdraw()} disabled={busy !== null}>
                    {busy === "withdraw" && <Loader2 className="animate-spin" aria-hidden />}
                    Dismiss
                  </Button>
                </div>
              )}
              {v.orcid_available && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                  <Button onClick={() => void startOrcid()} disabled={busy !== null} data-testid="orcid-start">
                    {busy === "orcid" ? <Loader2 className="animate-spin" aria-hidden /> : <ExternalLink aria-hidden />}
                    Confirm with ORCID
                  </Button>
                  {v.orcid_simulated && (
                    <span className="text-xs text-status-flag" data-testid="orcid-simulated">
                      Demo: simulated sign-in
                    </span>
                  )}
                  {!formOpen && (
                    <Button variant="link" size="sm" className="px-0" onClick={() => setFormOpen(true)} data-testid="request-open">
                      No ORCID iD?
                    </Button>
                  )}
                </div>
              )}
            </>
          )}

          {showForm && (
            <RequestForm
              simulated={!!v.orcid_simulated}
              onCancel={v.orcid_available ? () => setFormOpen(false) : undefined}
              onDone={async (c) => {
                setFormOpen(false);
                onCard(c);
                if (c.verification.verified) await refresh();
              }}
              onConflict={reload}
            />
          )}
        </>
      )}

      {error && (
        <p role="alert" className="text-sm text-destructive" data-testid="verification-error">
          {error}
        </p>
      )}
    </section>
  );
}

function RequestForm({
  simulated,
  onCancel,
  onDone,
  onConflict,
}: {
  simulated: boolean;
  onCancel?: () => void;
  onDone: (c: MyCard) => Promise<void>;
  onConflict: () => Promise<void>;
}) {
  const ids = useId();
  const [email, setEmail] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const urlInvalid = url.trim() !== "" && !/^https:\/\/\S+\.\S+/i.test(url.trim());
  const emailInvalid = email.trim() !== "" && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());
  const ready = !!email.trim() && !!url.trim() && !urlInvalid && !emailInvalid;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      const c = await unwrap(
        requestVerification({ body: { institutional_email: email.trim(), profile_url: url.trim() }, meta: { quiet: true } }),
      );
      const auto = c.verification.verified;
      toast(auto ? "Verified (demo, simulated)" : "Request sent");
      announce(auto ? "Verified. Demo, verification simulated." : "Request sent.");
      await onDone(c);
    } catch (err) {
      const apiErr = routeGlobalError(err);
      if (apiErr?.code === "conflict") await onConflict();
      setError(
        apiErr?.code === "validation_error"
          ? "Please check the e-mail and the link (https)."
          : apiErr?.code === "rate_limited"
            ? "Too many requests. Please try again tomorrow."
            : errorText(apiErr, "The request was not sent. Please try again."),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-3 rounded-lg border bg-background p-3" data-testid="request-form" noValidate>
      <p className="text-sm">
        <span className="font-medium">Manual check.</span>{" "}
        <span className="text-muted-foreground">The Amber team checks your work e-mail and a public staff page.</span>
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-sm">
          <span className="font-medium">Work e-mail</span>
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            maxLength={254}
            autoComplete="email"
            spellCheck={false}
            aria-invalid={emailInvalid}
            placeholder="name@hospital.org"
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="font-medium">Staff or profile page</span>
          <Input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            maxLength={500}
            spellCheck={false}
            aria-invalid={urlInvalid}
            aria-describedby={urlInvalid ? `${ids}-url-err` : undefined}
            placeholder="https://"
          />
          {urlInvalid && (
            <span id={`${ids}-url-err`} className="block text-xs text-destructive">
              Needs an https link.
            </span>
          )}
        </label>
      </div>
      {simulated && (
        <p className="text-xs text-status-flag" data-testid="request-simulated">
          Demo: approved at once and marked simulated.
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive" data-testid="request-error">
          {error}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" disabled={!ready || busy}>
          {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Send aria-hidden />}
          Send request
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" size="sm" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Card settings and preview

type Draft = { headline: string; accepts: boolean; showInst: boolean; showAtlas: boolean };

const draftFrom = (c: MyCard): Draft => ({
  headline: c.settings.headline ?? "",
  accepts: !!c.settings.accepts_patient_messages,
  showInst: c.settings.show_institutions ?? true,
  showAtlas: c.settings.show_atlas_entry ?? true,
});

function CardSettingsBlock({
  card,
  onCard,
  reload,
}: {
  card: MyCard;
  onCard: (c: MyCard) => void;
  reload: () => Promise<void>;
}) {
  const ids = useId();
  const saved = draftFrom(card);
  const savedKey = JSON.stringify(saved);
  const [draft, setDraft] = useState<Draft>(saved);
  const [base, setBase] = useState(savedKey);
  const [busy, setBusy] = useState<"visible" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);

  // A new server state (save, ORCID return, work details change) resets the draft.
  if (base !== savedKey) {
    setBase(savedKey);
    setDraft(saved);
  }

  const visible = !!card.settings.visible;
  const dirty = JSON.stringify(draft) !== savedKey;
  const headlineTooLong = draft.headline.length > MAX_HEADLINE;

  async function put(nextVisible: boolean, what: "visible" | "save") {
    setBusy(what);
    setError(null);
    // The switch sends the saved settings, so an unsaved (or invalid) draft never blocks switching off.
    const s = what === "save" ? draft : saved;
    try {
      const c = await unwrap(
        putMyCard({
          body: {
            visible: nextVisible,
            headline: s.headline.trim() || null,
            accepts_patient_messages: s.accepts,
            show_institutions: s.showInst,
            show_atlas_entry: s.showAtlas,
          },
          meta: { quiet: true },
        }),
      );
      forgetCard(c.card_id);
      onCard(c);
      const text = what === "save" ? "Card saved" : c.settings.visible ? "Card switched on" : "Card switched off";
      toast(text);
      announce(`${text}.`);
    } catch (e) {
      const err = routeGlobalError(e);
      if (err?.code === "conflict" || err?.code === "forbidden") await reload();
      setError(
        err?.code === "validation_error"
          ? "The headline can't contain e-mail addresses, links or phone numbers."
          : errorText(err, "Not saved. Please try again."),
      );
    } finally {
      setBusy(null);
    }
  }

  const blocked = card.blocked_reason ? BLOCKED[card.blocked_reason] : null;

  return (
    <section aria-labelledby={`${ids}-h`} className="space-y-4 border-t pt-5" data-testid="card-settings">
      <h3 id={`${ids}-h`} className="text-[15px] font-semibold tracking-tight">
        Public card
      </h3>

      <div className="flex items-start gap-3">
        <Switch
          id={`${ids}-visible`}
          checked={visible}
          disabled={busy !== null || (!visible && !card.can_show)}
          onCheckedChange={(on) => void put(on, "visible")}
          className="mt-0.5"
          aria-describedby={`${ids}-visible-d`}
          data-testid="card-visible"
        />
        <div className="space-y-0.5 text-sm">
          <label htmlFor={`${ids}-visible`} className="font-medium">
            Show my card
          </label>
          <p id={`${ids}-visible-d`} className="text-muted-foreground" data-testid="card-visible-note">
            {blocked ?? (visible ? "On. Signed-in users can see it." : "Off. Only signed-in users would see it.")}
          </p>
        </div>
      </div>

      {card.can_show && (
        <div className="space-y-4">
          <label className="block space-y-1 text-sm">
            <span className="font-medium">Headline</span>{" "}
            <span className="text-xs text-muted-foreground">(optional)</span>
            <Input
              value={draft.headline}
              onChange={(e) => setDraft({ ...draft, headline: e.target.value })}
              maxLength={MAX_HEADLINE}
              placeholder="e.g. Child neurologist, epilepsy genetics"
              aria-invalid={headlineTooLong}
              aria-describedby={`${ids}-headline-d`}
              data-testid="card-headline-input"
            />
            <span id={`${ids}-headline-d`} className="flex justify-between gap-2 text-xs text-muted-foreground">
              <span>No e-mail, links or phone numbers.</span>
              <span className="tabular">
                {draft.headline.length}/{MAX_HEADLINE}
              </span>
            </span>
          </label>

          <div className="grid gap-3 sm:grid-cols-2">
            <Toggle label="Show institutions" checked={draft.showInst} onChange={(v) => setDraft({ ...draft, showInst: v })} testId="card-show-institutions" />
            {card.verification.atlas_link_verified && (
              <Toggle label="Show atlas entry" checked={draft.showAtlas} onChange={(v) => setDraft({ ...draft, showAtlas: v })} testId="card-show-atlas" />
            )}
            <Toggle
              label="Accept messages from patients"
              hint="They send a request; you accept or decline."
              checked={draft.accepts}
              onChange={(v) => setDraft({ ...draft, accepts: v })}
              testId="card-accepts-messages-toggle"
            />
          </div>

          {dirty && (
            <Button size="sm" onClick={() => void put(visible, "save")} disabled={busy !== null || headlineTooLong} data-testid="card-save">
              {busy === "save" ? <Loader2 className="animate-spin" aria-hidden /> : <Save aria-hidden />}
              Save card
            </Button>
          )}
        </div>
      )}

      {error && (
        <p role="alert" className="text-sm text-destructive" data-testid="card-error">
          {error}
        </p>
      )}

      {card.preview && (
        <div className="space-y-2" data-testid="card-preview">
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Preview</span>
            <span>{visible ? "What signed-in users see." : "Hidden. Nobody sees it."}</span>
            {dirty && <span>Save to update.</span>}
            {visible && card.card_id && (
              <Link href={cardHref(card.card_id)} className="underline underline-offset-2 hover:text-foreground" data-testid="card-open">
                Open your card
              </Link>
            )}
          </p>
          <PublicCardView card={card.preview} heading="h4" className={cn(!visible && "opacity-70")} />
        </div>
      )}
    </section>
  );
}

function Toggle({
  label,
  hint,
  checked,
  onChange,
  testId,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  testId: string;
}) {
  const id = useId();
  return (
    <div className="flex items-start gap-3 text-sm">
      <Switch id={id} checked={checked} onCheckedChange={onChange} className="mt-0.5" data-testid={testId} />
      <span className="space-y-0.5">
        <label htmlFor={id} className="block font-medium">
          {label}
        </label>
        {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
      </span>
    </div>
  );
}
