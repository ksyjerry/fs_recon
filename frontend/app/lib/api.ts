export interface UploadResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface LogEntry {
  time: string;
  msg: string;
}

export interface StatusResponse {
  job_id: string;
  status: "processing" | "completed" | "failed";
  progress: number;
  step: string;
  error: string | null;
  logs: LogEntry[];
}

export async function uploadFiles(
  dsdFile: File,
  enFile: File
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("dsd_file", dsdFile);
  form.append("en_file", enFile);

  const res = await fetch("/api/upload", { method: "POST", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `업로드 실패 (${res.status})`);
  }
  return res.json();
}

export async function fetchStatus(jobId: string): Promise<StatusResponse> {
  const res = await fetch(`/api/status/${jobId}`);
  if (!res.ok) throw new Error(`상태 조회 실패 (${res.status})`);
  return res.json();
}

export function downloadUrl(jobId: string): string {
  return `/api/download/${jobId}`;
}
