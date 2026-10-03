import type { Metadata } from "next";
import { Suspense } from "react";

import { PathView } from "@/components/path/path-view";
import { PageContainer } from "@/components/shell/page-placeholder";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = {
  title: "Path",
  description:
    "The most trustworthy cited route between two nodes, step by step, with an explanation in your lens and what you could do together.",
};

function PathFallback() {
  return (
    <PageContainer className="space-y-8">
      <div className="space-y-3">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-8 w-2/3 max-w-xl" />
        <Skeleton className="h-4 w-full max-w-2xl" />
      </div>
      <Skeleton className="h-36 w-full rounded-xl" />
    </PageContainer>
  );
}

/** `/path?from=<id>&to=<id>&family=dna|symptoms|research|all` */
export default function PathPage() {
  return (
    <Suspense fallback={<PathFallback />}>
      <PathView />
    </Suspense>
  );
}
