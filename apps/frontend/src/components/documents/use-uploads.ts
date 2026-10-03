"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { announce } from "@/lib/a11y";
import { ApiError, reportApiError } from "@/lib/api/errors";
import { apiFetch } from "@/lib/api/fetch";
import type { JobAccepted, JobStage } from "@/lib/api/generated/types.gen";
import { streamSSE } from "@/lib/api/sse";

import { anonymousName, precheck, uploadErrorMessage } from "./errors";

export type UploadStatus = "uploading" | "processing" | "done" | "failed";

export type UploadItem = {
  key: string;
  /** Local file name, kept in memory for display only; never sent. */
  name: string;
  size: number;
  status: UploadStatus;
  stage: JobStage | "uploading";
  percent: number;
  documentId?: string;
  findingCount?: number;
  error?: { code: string; message: string };
};

type JobEvt =
  | { type: "progress"; stage: JobStage; percent: number }
  | { type: "done"; document_id?: string | null; finding_count?: number }
  | { type: "error"; code: string; message: string };

const GLOBAL = new Set(["sign_in_required", "reauth_required", "age_confirmation_required", "consent_required"]);

let seq = 0;

/** Upload queue: POST /documents → GET /jobs/{id} (SSE), one file at a time. */
export type UploadDone = { key: string; documentId: string; findingCount: number };

export function useUploads({ onDone }: { onDone?: (done: UploadDone) => void } = {}) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const ctrls = useRef(new Set<AbortController>());
  const chain = useRef<Promise<void>>(Promise.resolve());
  const onDoneRef = useRef(onDone);
  useEffect(() => {
    onDoneRef.current = onDone;
  });

  useEffect(() => {
    const set = ctrls.current;
    return () => set.forEach((c) => c.abort());
  }, []);

  const patch = useCallback((key: string, p: Partial<UploadItem>) => {
    setItems((list) => list.map((it) => (it.key === key ? { ...it, ...p } : it)));
  }, []);

  const fail = useCallback(
    (key: string, code: string, message?: string) => {
      const msg = uploadErrorMessage(code, message);
      patch(key, { status: "failed", error: { code, message: msg } });
      announce(`Upload failed. ${msg}`, "assertive");
    },
    [patch],
  );

  const run = useCallback(
    async (file: File, key: string) => {
      const pre = precheck(file);
      if (pre) return fail(key, pre);

      const form = new FormData();
      form.append("file", file, anonymousName(file));
      let job: JobAccepted;
      try {
        job = await apiFetch<JobAccepted>("/documents", { method: "POST", rawBody: form, quiet: true });
      } catch (e) {
        const err = e instanceof ApiError ? e : new ApiError("network_error", "", 0);
        if (GLOBAL.has(err.code)) reportApiError(err);
        return fail(key, err.code, err.message);
      }
      patch(key, { status: "processing", stage: "queued", percent: 5, documentId: job.document_id });
      announce("Upload received. Reading the document.");

      const ctrl = new AbortController();
      ctrls.current.add(ctrl);
      let finished = false;
      try {
        await streamSSE<JobEvt>(`/jobs/${encodeURIComponent(job.job_id)}`, {
          method: "GET",
          signal: ctrl.signal,
          quiet: true,
          onEvent: (evt) => {
            if (evt.type === "progress") {
              patch(key, { stage: evt.stage, percent: Math.max(5, Math.min(100, evt.percent ?? 0)) });
            } else if (evt.type === "done") {
              finished = true;
              const done: Partial<UploadItem> = {
                status: "done",
                stage: "done",
                percent: 100,
                documentId: evt.document_id ?? job.document_id,
                findingCount: evt.finding_count ?? 0,
              };
              patch(key, done);
              announce(`Document read. ${done.findingCount} findings to review.`);
              onDoneRef.current?.({ key, documentId: done.documentId!, findingCount: done.findingCount ?? 0 });
            } else if (evt.type === "error") {
              finished = true;
              fail(key, evt.code, evt.message);
            }
          },
        });
        if (!finished && !ctrl.signal.aborted) fail(key, "stream_ended", "The progress stream ended early. Check your documents list below.");
      } catch (e) {
        const err = e instanceof ApiError ? e : new ApiError("network_error", "", 0);
        if (GLOBAL.has(err.code)) reportApiError(err);
        if (!finished) fail(key, err.code, err.message);
      } finally {
        ctrls.current.delete(ctrl);
      }
    },
    [fail, patch],
  );

  const add = useCallback(
    (files: File[]) => {
      for (const file of files) {
        const key = `u${++seq}`;
        setItems((list) => [
          ...list,
          { key, name: file.name, size: file.size, status: "uploading", stage: "uploading", percent: 2 },
        ]);
        chain.current = chain.current.then(() => run(file, key));
      }
    },
    [run],
  );

  const dismiss = useCallback((key: string) => setItems((list) => list.filter((i) => i.key !== key)), []);

  return { items, add, dismiss };
}
