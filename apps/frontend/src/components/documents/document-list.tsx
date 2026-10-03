"use client";

import { FileText, Loader2, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { DOC_TYPE_LABEL, formatDate } from "@/components/account/labels";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { announce } from "@/lib/a11y";
import { apiFetch } from "@/lib/api/fetch";
import type { Document, DocumentStatus } from "@/lib/api/generated/types.gen";
import { cn } from "@/lib/utils";

const STATUS: Record<DocumentStatus, { label: string; variant: "secondary" | "outline" | "destructive" }> = {
  queued: { label: "Waiting", variant: "outline" },
  processing: { label: "Reading", variant: "outline" },
  ready: { label: "Ready to review", variant: "secondary" },
  failed: { label: "Could not be read", variant: "destructive" },
};

export function DeleteDocumentButton({
  id,
  onDeleted,
  label = "Delete",
}: {
  id: string;
  onDeleted: () => void;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  async function remove() {
    setBusy(true);
    try {
      await apiFetch(`/documents/${encodeURIComponent(id)}`, { method: "DELETE", quiet: true });
      setOpen(false);
      toast("Document deleted", { description: "Its findings were deleted too." });
      announce("Document and its findings deleted.");
      onDeleted();
    } catch {
      toast("Document not deleted", { description: "Please try again." });
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)} aria-label="Delete document" data-testid="delete-document">
        <Trash2 aria-hidden /> {label}
      </Button>
      <AlertDialog open={open} onOpenChange={(o) => !busy && setOpen(o)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this document?</AlertDialogTitle>
            <AlertDialogDescription>
              Its findings are deleted too, and so are the items in your profile that came from this document.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Keep</AlertDialogCancel>
            <Button variant="destructive" onClick={() => void remove()} disabled={busy}>
              {busy && <Loader2 className="animate-spin" aria-hidden />}
              Delete
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

export function DocumentList({
  documents,
  error,
  onChanged,
}: {
  documents: Document[] | null;
  error: string | null;
  onChanged: () => void;
}) {
  if (error) {
    return <p className="rounded-lg border border-dashed px-4 py-3 text-sm text-muted-foreground">{error}</p>;
  }
  if (documents === null) {
    return <p className="text-sm text-muted-foreground">Loading your documents…</p>;
  }
  if (!documents.length) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-3 text-sm text-muted-foreground">
        No documents yet. Uploaded files are never kept; only the findings you review are listed here.
      </p>
    );
  }
  const sorted = [...documents].sort((a, b) => b.created_at.localeCompare(a.created_at));
  return (
    <ul className="divide-y overflow-hidden rounded-xl border bg-card" data-testid="document-list">
      {sorted.map((d) => (
        <li key={d.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3" data-testid="document-row">
          <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">{d.doc_type ? DOC_TYPE_LABEL[d.doc_type] : "Document"}</p>
            <p className="text-xs text-muted-foreground">
              Uploaded {formatDate(d.created_at, true)}
              {d.page_count ? ` · ${d.page_count} ${d.page_count === 1 ? "page" : "pages"}` : ""}
              {d.raw_deleted_at ? " · original file deleted" : ""}
            </p>
          </div>
          <Badge variant={STATUS[d.status].variant}>{STATUS[d.status].label}</Badge>
          {d.status === "ready" && (
            <Link href={`/documents/${d.id}`} className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
              Review
            </Link>
          )}
          <DeleteDocumentButton id={d.id} onDeleted={onChanged} />
        </li>
      ))}
    </ul>
  );
}
