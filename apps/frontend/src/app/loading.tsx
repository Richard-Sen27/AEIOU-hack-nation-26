import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 py-10 sm:px-6" role="status" aria-label="Loading">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="mt-3 h-8 w-80 max-w-full" />
      <Skeleton className="mt-3 h-4 w-[32rem] max-w-full" />
      <Skeleton className="mt-8 h-72 w-full rounded-xl" />
    </div>
  );
}
