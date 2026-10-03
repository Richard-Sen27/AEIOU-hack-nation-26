"use client";

import { useId, useState } from "react";
import { toast } from "sonner";

import { useLens } from "@/components/providers/lens-provider";
import { useSession } from "@/components/providers/session-provider";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";
import { ApiError } from "@/lib/api/errors";
import { apiFetch } from "@/lib/api/fetch";
import type { SessionUser, SettingsUpdate } from "@/lib/api/generated/types.gen";
import { cn } from "@/lib/utils";

import { LANGUAGES, ROLE_COPY, SELECTABLE_ROLES, type SelectableRole } from "./labels";
import { NativeSelect } from "./native-select";

/** Role, language, expert mode: each change is saved immediately (`PATCH /me/settings`). */
export function SettingsSection({ user }: { user: SessionUser }) {
  const { refresh } = useSession();
  const { resetRole } = useLens();
  const ids = useId();
  const [pending, setPending] = useState<keyof SettingsUpdate | null>(null);

  async function patch(body: SettingsUpdate, what: string) {
    const key = Object.keys(body)[0] as keyof SettingsUpdate;
    setPending(key);
    try {
      await apiFetch<SessionUser>("/me/settings", { method: "PATCH", json: body, quiet: true });
      if (body.role) resetRole();
      await refresh();
      toast(`${what} saved`);
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "";
      toast(`${what} not saved`, {
        description: code === "network_error" ? "Amber's server is not reachable." : "Please try again.",
      });
    } finally {
      setPending(null);
    }
  }

  const role = user.role && user.role !== "guest" ? user.role : null;

  return (
    <div className="space-y-6">
      <fieldset className="space-y-2">
        <legend className="mb-1 text-sm font-medium">Role</legend>
        <p className="text-sm text-muted-foreground">
          Decides where you start and how things are explained, never what you can see.
        </p>
        <RadioGroup
          value={role}
          onValueChange={(v) => void patch({ role: v as SelectableRole }, "Role")}
          disabled={pending === "role"}
          className="grid gap-2 sm:grid-cols-3"
        >
          {SELECTABLE_ROLES.map((r) => (
            <label
              key={r}
              className={cn(
                "flex cursor-pointer items-start gap-2 rounded-lg border bg-background p-3 text-sm transition-colors hover:bg-muted/60",
                "has-data-checked:border-primary has-data-checked:bg-primary/10",
              )}
            >
              <RadioGroupItem value={r} aria-label={ROLE_COPY[r].label} className="mt-0.5" />
              <span>
                <span className="font-medium">{ROLE_COPY[r].label}</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">{ROLE_COPY[r].start}</span>
              </span>
            </label>
          ))}
        </RadioGroup>
      </fieldset>

      <div className="grid gap-6 sm:grid-cols-2">
        <label htmlFor={`${ids}-lang`} className="space-y-1.5 text-sm">
          <span className="block font-medium">Language</span>
          <span className="block text-muted-foreground">For Dr. Wu&apos;s answers and explanations.</span>
          <NativeSelect
            id={`${ids}-lang`}
            value={user.language || "en"}
            disabled={pending === "language"}
            onChange={(e) => void patch({ language: e.target.value }, "Language")}
          >
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </NativeSelect>
        </label>

        <div className="space-y-1.5 text-sm">
          <label htmlFor={`${ids}-expert`} className="block font-medium">
            Expert mode
          </label>
          <div className="flex items-start gap-3">
            <Switch
              id={`${ids}-expert`}
              checked={!!user.expert_mode}
              disabled={pending === "expert_mode"}
              onCheckedChange={(v) => void patch({ expert_mode: v }, "Expert mode")}
              className="mt-0.5"
            />
            <span className="text-muted-foreground">
              Lets you ask mechanism questions (for example &ldquo;AAV gene replacement for loss of function&rdquo;) and get
              ranked clusters. Open to everyone.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
