import { ref } from "vue";

const TOKEN_KEY = "stunsail.adminToken";
const BASE = "/api/v1";

// Set when any call returns 401 so the shell can point the user at Settings.
export const authRequired = ref(false);

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

export const getToken = (): string => localStorage.getItem(TOKEN_KEY) ?? "";

export const messageOf = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

export function setToken(token: string): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
  authRequired.value = false;
}

function headers(json: boolean): Record<string, string> {
  const result: Record<string, string> = {};
  if (json) result["Content-Type"] = "application/json";
  const token = getToken();
  if (token) result["Authorization"] = `Bearer ${token}`;
  return result;
}

async function failure(response: Response): Promise<ApiError> {
  if (response.status === 401) authRequired.value = true;
  let code = "error";
  let message = `${response.status} ${response.statusText}`;
  try {
    const body = await response.json();
    if (body?.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
    } else if (Array.isArray(body?.detail)) {
      code = "validation_error";
      message = body.detail
        .map(
          (d: { loc?: unknown[]; msg: string }) =>
            `${d.loc?.slice(1).join(".")}: ${d.msg}`,
        )
        .join("; ");
    }
  } catch {
    // Non-JSON error body: keep the status text.
  }
  return new ApiError(response.status, code, message);
}

export async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method,
    headers: headers(body !== undefined),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

export async function download(path: string, filename: string): Promise<void> {
  const response = await fetch(`${BASE}${path}`, { headers: headers(false) });
  if (!response.ok) throw await failure(response);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

// Decimal values arrive as strings so money and weights never pass through floats.
export interface Job {
  id: string;
  agent_id: string;
  printer_id: string | null;
  filename: string | null;
  state: string;
  started_at: string;
  ended_at: string | null;
  duration_s: number | null;
  filament_used_mm: number | null;
  finalised_at: string | null;
  spool_id: string | null;
}

export interface Energy {
  revision: number;
  kwh: string;
  covered_s: number;
  uncovered_s: number;
  invalid_samples: number;
  basis: string;
  method: string;
  profile_id: string;
  profile_version: number;
  computed_at: string;
}

export interface Cost {
  kind: string;
  revision: number;
  currency: string;
  amount: string;
  details: Record<string, unknown>;
}

export interface JobDetail extends Job {
  energy: Energy | null;
  costs: Cost[];
  total_cost: string | null;
  total_cost_currency: string | null;
}

export interface Spool {
  id: string;
  name: string;
  material: string;
  brand: string | null;
  colour: string | null;
  diameter_mm: string;
  density_g_cm3: string;
  opening_weight_g: string;
  purchase_cost: string | null;
  currency: string | null;
  status: string;
  remaining_g: string | null;
}

export interface LedgerEntry {
  id: number;
  movement_type: string;
  weight_delta_g: string;
  occurred_at: string;
  notes: string | null;
  job_id: string | null;
}

export interface Printer {
  id: string;
  agent_id: string;
  name: string;
  calibration_profile_id: string | null;
}

export interface Profile {
  id: string;
  name: string;
  version: number;
  calibrated_against_meter: boolean;
  data: Record<string, unknown>;
}

export interface Tariff {
  id: string;
  currency: string;
  rate_per_kwh: string;
  effective_from: string;
  effective_to: string | null;
  notes: string | null;
}

export interface Live {
  printer_id: string;
  agent_last_sync_at: string | null;
  sample_observed_at: string | null;
  sample_age_s: number | null;
  status: Record<string, Record<string, unknown>> | null;
  active_job: Job | null;
}

export interface Summary {
  currency: string | null;
  mixed_currencies: boolean;
  jobs: number;
  jobs_without_cost: number;
  kwh: string;
  filament_g: string;
  electricity_cost: string;
  filament_cost: string;
  total_cost: string;
  by_month: {
    period: string;
    jobs: number;
    kwh: string;
    filament_g: string;
    electricity_cost: string;
    filament_cost: string;
  }[];
}
