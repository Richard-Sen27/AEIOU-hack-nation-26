import { PRIVACY_EMAIL } from "@/lib/api/config";
import { cn } from "@/lib/utils";

/**
 * The privacy e-mail from NEXT_PUBLIC_PRIVACY_EMAIL, or a clearly marked
 * placeholder. Never invent a controller or address.
 */
export function PrivacyEmail({ className }: { className?: string }) {
  if (PRIVACY_EMAIL) {
    return (
      <a
        href={`mailto:${PRIVACY_EMAIL}`}
        className={cn("font-medium text-foreground underline underline-offset-2", className)}
      >
        {PRIVACY_EMAIL}
      </a>
    );
  }
  return <ToBeCompleted className={className}>privacy e-mail address</ToBeCompleted>;
}

export function ToBeCompleted({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <mark
      data-testid="to-be-completed"
      className={cn(
        "rounded-sm border border-dashed border-status-flag bg-status-flag/10 px-1 py-px text-foreground",
        className,
      )}
    >
      [{children}: to be completed before launch]
    </mark>
  );
}
