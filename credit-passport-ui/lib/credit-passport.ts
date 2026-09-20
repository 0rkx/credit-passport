/**
 * Shared API response types.
 *
 * Values that affect scoring, eligibility, evidence and guidance are returned by
 * the Credit Passport API. This module intentionally contains no runtime records,
 * score weights or fallback data.
 */

export const productValues = ["credit-card", "personal-loan", "student-loan"] as const;
export type ProductType = (typeof productValues)[number];

export type EvidenceType =
  | "bank-statement"
  | "payroll"
  | "rent"
  | "utility"
  | "remittance"
  | "wallet"
  | "platform-earnings"
  | "asset-repayment"
  | "insurance"
  | "merchant-sales"
  | "other";

export type Direction = "credit" | "debit";
export type TransitionEvent = "moving-abroad" | "job-change" | "returning-india";
export type ReliabilityBand = "High" | "Medium" | "Low";
export type GuideIntent =
  | "general"
  | "moving-abroad"
  | "returning-india"
  | "job-change"
  | "account-choices"
  | "residential-status"
  | "account-conversion"
  | "kyc-fatca-crs";

export interface Applicant {
  id: string;
  name: string;
  corridor: string;
  product: ProductType;
  requested_amount: number | null;
  currency: string;
  employment: string | null;
  residency: string | null;
  created_at: string;
  updated_at: string;
  score: number | null;
  reliability: number;
  reliability_band: ReliabilityBand;
  assertion_count: number;
  unique_event_count: number;
}

export interface EvidenceSource {
  id: string;
  applicant_id: string;
  source_type: EvidenceType;
  provider: string;
  currency: string;
  period_start: string;
  period_end: string;
  assertion_count: number;
  unique_event_count: number;
  corroborated_count: number;
  created_at: string;
}

export interface EconomicEvent {
  id: string;
  date: string;
  event_type: string;
  amount: number;
  currency: string;
  direction: Direction;
  source_ids: string[];
  source_types: EvidenceType[];
  construct: string;
  status: "scored" | "corroborated" | "policy-only";
  reference: string | null;
  description: string | null;
}

export interface EvidenceResponse {
  applicant_id: string;
  assertion_count: number;
  unique_event_count: number;
  corroborated_count: number;
  sources: EvidenceSource[];
  events: EconomicEvent[];
}

export interface ReasonCode {
  code: string;
  domain: string;
  message: string;
  evidence_ids: string[];
  value: string | null;
}

export interface DomainResult {
  key: string;
  label: string;
  observed: number;
  reliability: number;
  adjusted: number;
  weight: number;
  contribution: number;
  evidence_count: number;
  reason_codes: ReasonCode[];
}

export interface ScoreResponse {
  applicant_id: string;
  product: ProductType;
  score: number;
  band: ReliabilityBand;
  reliability: number;
  reliability_band: ReliabilityBand;
  assertion_count: number;
  unique_event_count: number;
  corroborated_count: number;
  score_range: { p10: number; p90: number };
  domains: DomainResult[];
  reason_codes: ReasonCode[];
  generated_at: string;
}

export interface ChallengerBlend {
  transparent_score: number;
  challenger_score: number;
  model_weight: number;
  model_contribution: number;
  blended_score: number;
  decision_use: "research-only";
}

export interface ChallengerScoreResponse {
  applicant_id: string;
  product: ProductType;
  model_name: string;
  task: "adverse_outcome_probability";
  probability: number;
  risk_band: "low" | "medium" | "high";
  feature_values: Record<string, number>;
  artifact_version: string;
  validation_summary: Record<string, unknown>;
  provenance: Record<string, unknown>;
  blend: ChallengerBlend;
  generated_at: string;
}

export interface ProductConfig {
  product: ProductType;
  label: string;
  weights: Record<string, number>;
}

export interface DomainConfig {
  key: string;
  label: string;
  description: string;
}

export interface ConfigResponse {
  products: ProductConfig[];
  domains: DomainConfig[];
  evidence_types: EvidenceType[];
  transition_events: TransitionEvent[];
  scoring_version: string;
}

export interface StatementIngestResponse {
  applicant_id: string;
  source: EvidenceSource;
  parsed_rows: number;
  score: ScoreResponse;
}

export interface GuidanceTask {
  id: string;
  title: string;
  action: string;
  priority: "now" | "next" | "when-ready";
  score_effect: "none";
  sources: string[];
}

export interface TransitionResponse {
  applicant_id: string;
  event: TransitionEvent | null;
  country_from: string | null;
  country_to: string | null;
  facts: Record<string, unknown>;
  tasks: GuidanceTask[];
  disclaimer: string;
  updated_at: string | null;
}

export interface ApplicantCreate {
  name: string;
  corridor: string;
  product: ProductType;
  requested_amount?: number | null;
  currency: string;
  employment?: string | null;
  residency?: string | null;
}

export interface TransitionUpdate {
  event: TransitionEvent | null;
  country_from?: string | null;
  country_to?: string | null;
  facts?: Record<string, unknown>;
}

export interface GuideQueryRequest {
  query: string;
  intent?: GuideIntent;
  session_id?: string;
  country_from?: string | null;
  country_to?: string | null;
  facts?: Record<string, unknown>;
  max_sources?: number;
}

export interface GuideCitation {
  id: string;
  title: string;
  publisher: string;
  url: string;
  locator: string | null;
  matched_topics: string[];
}

export interface GuidePrompt {
  id: string;
  label: string;
  query: string;
  intent: GuideIntent;
}

export interface GuideResponse {
  query: string;
  answer: string;
  bullets: string[];
  follow_up_questions: string[];
  citations: GuideCitation[];
  suggested_prompts: GuidePrompt[];
  grounded: boolean;
  abstained: boolean;
  provider: "deterministic" | "gemini";
  provider_status: "keyless" | "configured" | "fallback";
  session_id: string | null;
  disclaimer: string;
}

export interface ModelValidationResponse {
  status: "available" | "unavailable" | "invalid";
  metrics: Record<string, unknown> | null;
  message: string;
}

export function initials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function productLabel(value: ProductType): string {
  return value
    .split("-")
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

export function evidenceTypeLabel(value: EvidenceType): string {
  return value
    .split("-")
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

export function transitionEventLabel(value: TransitionEvent): string {
  return value
    .split("-")
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

export function reliabilityBand(value: number): ReliabilityBand {
  if (value >= 75) return "High";
  if (value >= 55) return "Medium";
  return "Low";
}

export function formatMoney(value: number | null | undefined, currency = "INR"): string {
  if (value === null || value === undefined) return "Not provided";
  try {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 0 }).format(value);
  } catch {
    return `${currency} ${value.toLocaleString("en-IN")}`;
  }
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "Not available";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric" }).format(parsed);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "Not available";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(parsed);
}
