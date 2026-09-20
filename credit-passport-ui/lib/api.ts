import type {
  Applicant,
  ApplicantCreate,
  ChallengerScoreResponse,
  ConfigResponse,
  EvidenceResponse,
  GuidePrompt,
  GuideQueryRequest,
  GuideResponse,
  ModelValidationResponse,
  ProductType,
  ScoreResponse,
  StatementIngestResponse,
  TransitionEvent,
  TransitionResponse,
  TransitionUpdate,
} from "@/lib/credit-passport";

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly path: string;

  constructor(message: string, status: number, path: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.path = path;
  }
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown; message?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((item) => (typeof item === "string" ? item : JSON.stringify(item))).join("; ");
    if (typeof body.message === "string") return body.message;
  } catch {
    // The server may return an empty or non-JSON error response.
  }
  return response.statusText || `Request failed with status ${response.status}`;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  headers.set("Accept", "application/json");
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers, cache: "no-store" });
  } catch {
    throw new ApiError(`Cannot connect to the Credit Passport API at ${API_BASE_URL}.`, 0, path);
  }
  if (!response.ok) throw new ApiError(await readError(response), response.status, path);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const creditPassportApi = {
  getConfig(): Promise<ConfigResponse> {
    return request<ConfigResponse>("/config");
  },
  listApplicants(): Promise<Applicant[]> {
    return request<Applicant[]>("/applicants");
  },
  getApplicant(applicantId: string): Promise<Applicant> {
    return request<Applicant>(`/applicants/${encodeURIComponent(applicantId)}`);
  },
  createApplicant(payload: ApplicantCreate): Promise<Applicant> {
    return request<Applicant>("/applicants", { method: "POST", body: JSON.stringify(payload) });
  },
  getEvidence(applicantId: string): Promise<EvidenceResponse> {
    return request<EvidenceResponse>(`/applicants/${encodeURIComponent(applicantId)}/evidence`);
  },
  getScore(applicantId: string, product: ProductType): Promise<ScoreResponse> {
    return request<ScoreResponse>(`/applicants/${encodeURIComponent(applicantId)}/score?product=${encodeURIComponent(product)}`);
  },
  getChallengerScore(applicantId: string, product: ProductType): Promise<ChallengerScoreResponse> {
    return request<ChallengerScoreResponse>(`/applicants/${encodeURIComponent(applicantId)}/challenger-score?product=${encodeURIComponent(product)}`);
  },
  uploadStatement(
    applicantId: string,
    file: File,
    metadata: { provider: string; sourceType: string; currency: string },
  ): Promise<StatementIngestResponse> {
    const body = new FormData();
    body.append("file", file, file.name);
    body.append("source_type", metadata.sourceType);
    body.append("provider", metadata.provider);
    body.append("currency", metadata.currency);
    body.append("consent", "true");
    return request<StatementIngestResponse>(`/applicants/${encodeURIComponent(applicantId)}/statements`, { method: "POST", body });
  },
  getTransition(applicantId: string, event?: TransitionEvent | null): Promise<TransitionResponse> {
    const suffix = event ? `?event=${encodeURIComponent(event)}` : "";
    return request<TransitionResponse>(`/applicants/${encodeURIComponent(applicantId)}/transition${suffix}`);
  },
  updateTransition(applicantId: string, payload: TransitionUpdate): Promise<TransitionResponse> {
    return request<TransitionResponse>(`/applicants/${encodeURIComponent(applicantId)}/transition`, { method: "PUT", body: JSON.stringify(payload) });
  },
  health(): Promise<{ status: "ok"; service: string; database: "ok"; scoring_version: string }> {
    return request<{ status: "ok"; service: string; database: "ok"; scoring_version: string }>("/health");
  },
  getModelValidation(): Promise<ModelValidationResponse> {
    return request<ModelValidationResponse>("/model/validation");
  },
  getGuidePrompts(): Promise<GuidePrompt[]> {
    return request<GuidePrompt[]>("/guide/suggested-prompts");
  },
  queryGuide(payload: GuideQueryRequest): Promise<GuideResponse> {
    return request<GuideResponse>("/guide/query", { method: "POST", body: JSON.stringify(payload) });
  },
};
