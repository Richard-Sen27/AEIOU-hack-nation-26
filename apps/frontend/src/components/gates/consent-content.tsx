"use client";

/**
 * Body of the consent dialog, per consent type: the just-in-time notice
 * (GDPR Art. 9 explicit consent + Art. 13, CCPA notice at collection), the
 * parental-responsibility confirmation for data about a child, and the grant
 * (`POST /consents` with the text version). Nothing is pre-ticked; declining
 * is one click, granting needs an explicit choice, a ticked box and a click.
 */
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import { CONSENT_NOTICES, CONSENT_VERSION } from "@/components/privacy/consent-texts";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { ApiError, reportApiError } from "@/lib/api/errors";
import { grantConsent, unwrap } from "@/lib/api";
import type { ConsentType } from "@/lib/api/types";
import type { ConsentGrant } from "@/lib/api/generated/types.gen";

export type ConsentContentProps = {
  type: ConsentType;
  onGranted: () => void;
  onCancel: () => void;
};

export const CONSENT_TITLES: Record<ConsentType, string> = {
  health_data: "Use of your health information",
  contribute: "Before you contribute to the shared atlas",
};

type Subject = "self" | "child";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-1.5">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      {children}
    </section>
  );
}

function Bullets({ items }: { items: string[] }) {
  return (
    <ul className="list-disc space-y-1 pl-4 marker:text-muted-foreground">
      {items.map((t) => (
        <li key={t}>{t}</li>
      ))}
    </ul>
  );
}

export function ConsentContent({ type, onGranted, onCancel }: ConsentContentProps) {
  const notice = CONSENT_NOTICES[type];
  const ids = useId();
  const [subject, setSubject] = useState<Subject | null>(null);
  const [parental, setParental] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = subject !== null && agreed && (subject === "self" || parental) && !busy;

  async function grant() {
    if (!ready) return;
    setBusy(true);
    setError(null);
    const body: ConsentGrant = {
      consent_type: type,
      version: CONSENT_VERSION[type],
      about_child: subject === "child",
      parental_responsibility_confirmed: subject === "child" ? parental : false,
    };
    try {
      await unwrap(grantConsent({ body, meta: { quiet: true } }));
      onGranted();
    } catch (e) {
      const err = e instanceof ApiError ? e : null;
      if (err?.code === "sign_in_required" || err?.code === "reauth_required") {
        reportApiError(err);
        onCancel();
        return;
      }
      setError(
        err?.code === "not_implemented"
          ? "Saving consent is not available yet. Nothing was granted."
          : err?.code === "network_error"
            ? "Amber's server is not reachable. Nothing was granted; please try again."
            : (err?.message ?? "Something went wrong. Nothing was granted."),
      );
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-col gap-4" data-testid={`consent-content-${type}`}>
      <div
        data-consent-notice
        tabIndex={-1}
        role="region"
        aria-label="What you agree to"
        className="-mx-1 max-h-[46vh] space-y-4 overflow-y-auto px-1 text-sm leading-relaxed text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring sm:max-h-[50vh]"
      >
        <p className="text-foreground">{notice.summary}</p>
        <Section title="What we process">
          <Bullets items={notice.processed} />
        </Section>
        <Section title="Why">
          <p>{notice.purpose}</p>
        </Section>
        <Section title="How it is protected">
          <Bullets items={notice.safeguards} />
        </Section>
        <Section title="How long we keep it">
          <Bullets items={notice.retention} />
        </Section>
        <Section title="Withdrawing">
          <p>{notice.withdrawal}</p>
        </Section>
        <p className="text-xs">
          Read the full{" "}
          <Link href="/privacy" target="_blank" className="font-medium text-foreground underline underline-offset-2">
            privacy notice
          </Link>{" "}
          (opens in a new tab). Consent text version {CONSENT_VERSION[type]}.
        </p>
      </div>

      <div className="space-y-3 rounded-lg border bg-muted/50 p-3">
        <fieldset className="space-y-2">
          <legend className="mb-2 text-sm font-medium">
            {type === "health_data" ? "Whose health information is this?" : "Whose information will you contribute?"}
          </legend>
          <RadioGroup
            value={subject}
            onValueChange={(v) => {
              setSubject(v as Subject);
              if (v !== "child") setParental(false);
            }}
            className="gap-2"
          >
            <label className="flex items-center gap-2.5 text-sm">
              <RadioGroupItem value="self" aria-label={type === "health_data" ? "My own" : "My own, or not about a person"} />
              {type === "health_data" ? "My own" : "My own, or not about a person (e.g. a registry)"}
            </label>
            <label className="flex items-center gap-2.5 text-sm">
              <RadioGroupItem value="child" aria-label="A child I care for" />
              A child I care for
            </label>
          </RadioGroup>
        </fieldset>

        {subject === "child" && (
          <label htmlFor={`${ids}-parental`} className="flex items-start gap-2.5 text-sm">
            <Checkbox
              id={`${ids}-parental`}
              checked={parental}
              onCheckedChange={(v) => setParental(v === true)}
              className="mt-0.5"
            />
            <span>
              I confirm that I hold parental responsibility (I am the parent or legal guardian) for this
              child.
            </span>
          </label>
        )}

        <label htmlFor={`${ids}-agree`} className="flex items-start gap-2.5 text-sm">
          <Checkbox
            id={`${ids}-agree`}
            checked={agreed}
            onCheckedChange={(v) => setAgreed(v === true)}
            className="mt-0.5"
          />
          <span>{notice.agreement}</span>
        </label>
      </div>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="outline" size="lg" onClick={onCancel} disabled={busy}>
          Not now
        </Button>
        <Button size="lg" onClick={() => void grant()} disabled={!ready} aria-disabled={!ready}>
          {busy && <Loader2 className="animate-spin" aria-hidden />}
          {notice.grantLabel}
        </Button>
      </div>
    </div>
  );
}
