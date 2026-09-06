export type Connection = { url: string; token: string };
export type Identity = {account_id: string | null; name: string; role: string; auth_mode: 'demo' | 'controlled'; credential_kind: 'demo' | 'bootstrap' | 'account' | 'worker'};
export type CreditQuote = {total_inputs: number; credits: number; unit: string; pricing_version: string};
export type Job = {
  id: string; task_type: string; status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  total_inputs: number; total_tasks: number; completed_tasks: number; failed_tasks: number;
  progress_percentage: number; created_at: string; model_id: string | null; model_revision: string | null;
};
export type Worker = {
  id: string; device_id: string | null; hostname: string; name: string; status: string;
  cpu: string; cpu_cores: number; ram_gb: number; gpu: string | null;
  gpu_memory_kind: string | null; gpu_core_count: number | null;
  ram_available_gb: number | null; gpu_available_gb: number | null; gpu_model_memory_gb: number | null;
  cpu_utilization: number | null; memory_utilization: number | null;
  model_id: string | null; model_revision: string | null; supported_tasks: string[];
};
export type Results = {
  job_id: string; status: string; is_final: boolean; total_inputs: number; completed_inputs: number; failed_inputs: number;
  results: ({index: number; text: string} | {index: number; label: string; score: number} | {index: number; names: string[]; dates: string[]; amounts: string[]; action_items: string[]})[];
  failed_tasks: {task_id: string; input_start_index: number; input_count: number; error_code: string}[];
  tasks: {task_id: string; input_start_index: number; input_count: number; worker_id: string | null; worker_name: string | null; status: string; attempt_count: number; execution_time_ms: number | null}[];
};
export type ActivityTask = { task_id: string; job_id: string; task_type: string; worker_name: string | null; status: string; attempt_count: number; elapsed_seconds: number | null; queue_seconds: number | null; error_code: string | null };
export type Activity = { as_of: string; active_tasks: ActivityTask[]; recent_tasks: ActivityTask[]; retries: number; task_counts: Record<string, number>; worker_metrics: {worker_id: string; completed_tasks: number; completed_inputs: number; average_execution_ms: number}[] };
export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}
export async function request<T>(connection: Connection, path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${connection.url}${path}`, {
      ...init, signal: init.signal ?? AbortSignal.timeout(10000),
      headers: { ...(connection.token ? { Authorization: `Bearer ${connection.token}` } : {}),
        ...(init.body ? { 'Content-Type': 'application/json' } : {}) },
    });
  } catch { throw new Error('Cannot reach the backend. Check the URL, network, and backend CORS settings.'); }
  if (!response.ok) {
    const details = await response.json().catch(() => ({}));
    const messages: Record<number, string> = {401: 'Authentication failed. Check your account or demo token.', 402: 'Not enough demo credits. Ask an administrator for credits or wait for reserved work to settle.', 403: 'This credential cannot access this operation. Use an account token in the dashboard.', 404: 'This job or endpoint was not found.', 422: 'The backend rejected the request. Check the input limits.', 503: 'Backend not ready. Ask Abel to check database, migrations, and model configuration.'};
    throw new ApiError(typeof details.detail === 'string' ? details.detail : messages[response.status] ?? `Backend request failed (${response.status}).`, response.status);
  }
  return response.json() as Promise<T>;
}
