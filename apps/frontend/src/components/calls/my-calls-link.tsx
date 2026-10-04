"use client";

import { FilePen, Plus } from "lucide-react";
import Link from "next/link";

import { useSession } from "@/components/providers/session-provider";
import { buttonVariants } from "@/components/ui/button";

/** Doctors and researchers only: their own calls and the form. Patients never see it. */
export function MyCallsLink() {
  const { user } = useSession();
  if (user?.role !== "doctor" && user?.role !== "researcher") return null;
  return (
    <>
      <Link href="/calls/mine" className={buttonVariants({ variant: "outline", size: "sm" })} data-testid="my-calls-link">
        <FilePen data-icon="inline-start" aria-hidden /> My calls
      </Link>
      <Link href="/calls/mine/new" className={buttonVariants({ size: "sm" })} data-testid="new-call-link">
        <Plus data-icon="inline-start" aria-hidden /> New call
      </Link>
    </>
  );
}
