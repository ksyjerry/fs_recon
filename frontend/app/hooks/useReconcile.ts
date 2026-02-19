"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { downloadUrl, fetchStatus, LogEntry, uploadFiles } from "../lib/api";

export type ReconcileState =
  | "idle"
  | "uploading"
  | "processing"
  | "completed"
  | "failed";

export interface ReconcileStatus {
  state: ReconcileState;
  progress: number;
  step: string;
  error: string | null;
  jobId: string | null;
}

export function useReconcile() {
  const [dsdFile, setDsdFile] = useState<File | null>(null);
  const [enFile, setEnFile] = useState<File | null>(null);
  const [status, setStatus] = useState<ReconcileStatus>({
    state: "idle",
    progress: 0,
    step: "",
    error: null,
    jobId: null,
  });
  const [logs, setLogs] = useState<LogEntry[]>([]);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const failCountRef = useRef(0);

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    failCountRef.current = 0;
  }, []);

  // 컴포넌트 언마운트 시 인터벌 클리어
  useEffect(() => () => stopPolling(), [stopPolling]);

  const startPolling = useCallback((jobId: string) => {
    stopPolling();
    intervalRef.current = setInterval(async () => {
      try {
        const s = await fetchStatus(jobId);
        setStatus((prev) => ({
          ...prev,
          progress: s.progress,
          step: s.step,
          error: s.error,
          state: s.status === "completed"
            ? "completed"
            : s.status === "failed"
            ? "failed"
            : "processing",
        }));
        if (s.logs) setLogs(s.logs);
        failCountRef.current = 0;
        if (s.status === "completed" || s.status === "failed") {
          stopPolling();
        }
      } catch (err) {
        failCountRef.current += 1;
        // 404(서버 재시작으로 job 소멸) 또는 연속 3회 실패 시 초기화
        const is404 = err instanceof Error && err.message.includes("404");
        if (is404 || failCountRef.current >= 3) {
          stopPolling();
          setStatus((prev) => ({
            ...prev,
            state: "failed",
            error: is404
              ? "서버가 재시작되어 작업 정보가 초기화되었습니다. 다시 시작해주세요."
              : "서버 연결이 끊어졌습니다. 다시 시작해주세요.",
          }));
        }
      }
    }, 2000);
  }, [stopPolling]);

  const start = useCallback(async () => {
    if (!dsdFile || !enFile) return;

    setLogs([]);
    setStatus({ state: "uploading", progress: 0, step: "파일 업로드 중...", error: null, jobId: null });

    try {
      const res = await uploadFiles(dsdFile, enFile);
      setStatus((prev) => ({
        ...prev,
        state: "processing",
        jobId: res.job_id,
        step: "처리 시작...",
        progress: 2,
      }));
      startPolling(res.job_id);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "알 수 없는 오류";
      setStatus({ state: "failed", progress: 0, step: "", error: msg, jobId: null });
    }
  }, [dsdFile, enFile, startPolling]);

  const reset = useCallback(() => {
    stopPolling();
    setDsdFile(null);
    setEnFile(null);
    setLogs([]);
    setStatus({ state: "idle", progress: 0, step: "", error: null, jobId: null });
  }, [stopPolling]);

  const downloadHref = status.jobId ? downloadUrl(status.jobId) : null;

  return {
    dsdFile, setDsdFile,
    enFile,  setEnFile,
    status,
    logs,
    start,
    reset,
    downloadHref,
    canStart: !!dsdFile && !!enFile && status.state === "idle",
  };
}
