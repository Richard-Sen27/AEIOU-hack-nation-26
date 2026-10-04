"use client";

import Link from "next/link";

import { useSession } from "@/components/providers/session-provider";
import { cn } from "@/lib/utils";

import { ConsentsSection } from "./consents-section";
import { ContributionsSection } from "./contributions-section";
import { DataRights, GpcStatus } from "./privacy-choices";
import { ProfileEditor } from "./profile-editor";
import { SettingsSection } from "./settings-section";
import { SessionLoading, SignInPrompt } from "./sign-in-prompt";

const SECTIONS = [
  { id: "health-profile", title: "Health profile" },
  { id: "settings", title: "Settings" },
  { id: "consents", title: "Consents" },
  { id: "contributions", title: "Contributions" },
  { id: "privacy-choices", title: "Privacy choices" },
  { id: "your-data", title: "Your data" },
] as const;

function Panel({
  id,
  title,
  description,
  children,
  className,
}: {
  id: string;
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-h`} className={cn("scroll-mt-20 rounded-xl border bg-card p-5 sm:p-6", className)}>
      <div className="mb-5 max-w-2xl space-y-1">
        <h2 id={`${id}-h`} className="text-lg font-semibold tracking-tight">
          {title}
        </h2>
        {description && <p className="text-sm leading-relaxed text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  );
}

export function ProfilePage() {
  const { user, status } = useSession();
  if (status === "loading") return <SessionLoading />;
  if (!user) {
    return (
      <SignInPrompt
        title="Sign in to see your profile"
        description="Your confirmed diagnoses, genes and symptoms, consents and privacy choices. Private to you."
        returnTo="/profile"
      />
    );
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[200px_minmax(0,1fr)]">
      <nav aria-label="Profile sections" className="hidden lg:block">
        <ul className="sticky top-20 space-y-0.5 text-sm">
          {SECTIONS.map((s) => (
            <li key={s.id}>
              <a href={`#${s.id}`} className="block rounded-md px-2.5 py-1.5 text-muted-foreground hover:bg-muted hover:text-foreground">
                {s.title}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      <div className="min-w-0 space-y-6">
        <Panel
          id="health-profile"
          title="Health profile"
          description={
            <>
              Only what you confirmed, with its source. Edit anything. Never shared.{" "}
              <Link href="/documents" className="font-medium text-foreground underline underline-offset-2">
                Add from a report
              </Link>
            </>
          }
        >
          <ProfileEditor />
        </Panel>
        <Panel id="settings" title="Settings">
          <SettingsSection user={user} />
        </Panel>
        <Panel
          id="consents"
          title="Consents"
          description="One consent covers your health information (chats, profile, documents). Contributing to the shared atlas needs its own. Withdrawing is one click."
        >
          <ConsentsSection />
        </Panel>
        <Panel
          id="contributions"
          title="Contributions"
          description="What you shared with the atlas: labelled patient-reported, reviewed first, never cited as evidence."
        >
          <ContributionsSection />
        </Panel>
        <Panel id="privacy-choices" title="Privacy choices">
          <GpcStatus />
        </Panel>
        <Panel id="your-data" title="Your data">
          <DataRights />
        </Panel>
      </div>
    </div>
  );
}
