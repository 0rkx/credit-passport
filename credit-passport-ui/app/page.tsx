"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BriefcaseBusiness,
  Check,
  ChevronRight,
  CircleDollarSign,
  CircleHelp,
  Database,
  FileCheck2,
  Gauge,
  Landmark,
  LayoutList,
  LoaderCircle,
  Menu,
  MessageCircle,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  Upload,
  UserRound,
  Users,
  WalletCards,
  Waypoints,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { creditPassportApi, ApiError } from "@/lib/api";
import {
  evidenceTypeLabel,
  formatDate,
  formatDateTime,
  formatMoney,
  initials,
  productLabel,
  reliabilityBand,
  transitionEventLabel,
  type Applicant,
  type ApplicantCreate,
  type ChallengerScoreResponse,
  type ConfigResponse,
  type EvidenceResponse,
  type GuidePrompt,
  type GuideResponse,
  type ProductType,
  type ScoreResponse,
  type TransitionEvent,
  type TransitionResponse,
} from "@/lib/credit-passport";

type Mode = "applicant" | "lender";
type View = "home" | "evidence" | "score" | "transition" | "queue" | "case";

const navApplicant = [
  { id: "home" as View, label: "Home", icon: LayoutList },
  { id: "evidence" as View, label: "My evidence", icon: Database },
  { id: "score" as View, label: "My score", icon: Gauge },
  { id: "transition" as View, label: "Moving or returning", icon: Waypoints },
];

const navLender = [
  { id: "queue" as View, label: "Review queue", icon: Users },
  { id: "case" as View, label: "Application review", icon: UserRound },
  { id: "evidence" as View, label: "Evidence review", icon: Database },
  { id: "score" as View, label: "Decision score", icon: Gauge },
];

const inputClass =
  "h-11 w-full rounded-md border border-[#ccd6df] bg-white px-3 text-sm text-[#263a4b] outline-none transition focus:border-[#2f61c5] focus:ring-2 focus:ring-[#2f61c5]/15";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

function statusFor(applicant: Applicant): { label: string; className: string } {
  if (applicant.score === null) return { label: "Evidence needed", className: "border-amber-200 bg-amber-50 text-amber-800" };
  if (applicant.reliability >= 75) return { label: "Review ready", className: "border-teal-200 bg-teal-50 text-teal-800" };
  return { label: "Check evidence", className: "border-amber-200 bg-amber-50 text-amber-800" };
}

function scoreBand(score: number | null): { label: string; className: string } {
  if (score === null) return { label: "Not scored", className: "border-slate-300 bg-slate-100 text-slate-700" };
  if (score >= 75) return { label: "Strong", className: "border-teal-200 bg-teal-50 text-teal-800" };
  if (score >= 60) return { label: "Needs review", className: "border-amber-200 bg-amber-50 text-amber-800" };
  return { label: "Limited", className: "border-rose-200 bg-rose-50 text-rose-800" };
}

function scoreTone(value: number, evidenceStrength: number): { barColor: string; valueClass: string } {
  if (evidenceStrength === 0) return { barColor: "#c58a1b", valueClass: "text-[#94640f]" };
  if (value >= 75) return { barColor: "#16836d", valueClass: "text-[#116b5c]" };
  if (value >= 60) return { barColor: "#c58a1b", valueClass: "text-[#94640f]" };
  return { barColor: "#c94a4a", valueClass: "text-[#b42318]" };
}

type ProductScoreProfile = {
  order: string[];
  labels: Record<string, string>;
  focus: Record<string, string>;
};

const productScoreProfiles: Record<ProductType, ProductScoreProfile> = {
  "personal-loan": {
    order: ["capacity", "income", "commitment", "liquidity", "shock", "momentum", "cross_border"],
    labels: {
      commitment: "Payment track record",
      income: "Income stability",
      capacity: "Room for new payments",
      liquidity: "Cash buffer",
      shock: "Financial resilience",
      momentum: "Income trend",
      cross_border: "Cross-border consistency",
    },
    focus: {
      commitment: "A personal loan needs a dependable record of meeting scheduled payments.",
      income: "Stable, recurring income supports the longer repayment period.",
      capacity: "The key question is whether regular income leaves room for another instalment.",
      liquidity: "A cash buffer helps absorb a large, fixed monthly payment.",
      shock: "Reserves and protection reduce the impact of an unexpected setback.",
      momentum: "The recent direction of income helps distinguish stability from deterioration.",
      cross_border: "Consistent activity across currencies helps connect the applicant's financial history.",
    },
  },
  "credit-card": {
    order: ["commitment", "liquidity", "capacity", "income", "shock", "momentum", "cross_border"],
    labels: {
      commitment: "Repayment history",
      income: "Income continuity",
      capacity: "Room for card payments",
      liquidity: "Cash on hand",
      shock: "Emergency buffer",
      momentum: "Income trend",
      cross_border: "Cross-border consistency",
    },
    focus: {
      commitment: "On-time repayments are the clearest signal for revolving credit.",
      income: "Regular inflows support day-to-day card repayment capacity.",
      capacity: "Existing commitments indicate how much room remains for card obligations.",
      liquidity: "Available cash is especially important when card balances can fluctuate.",
      shock: "A reserve provides protection if spending or income changes unexpectedly.",
      momentum: "Recent income direction shows whether repayment capacity is improving or weakening.",
      cross_border: "Consistent activity across currencies helps verify the cardholder's financial pattern.",
    },
  },
  "student-loan": {
    order: ["capacity", "shock", "income", "commitment", "momentum", "liquidity", "cross_border"],
    labels: {
      commitment: "Payment history",
      income: "Income continuity",
      capacity: "Affordability",
      liquidity: "Cash buffer",
      shock: "Financial resilience",
      momentum: "Income trend",
      cross_border: "Cross-border continuity",
    },
    focus: {
      commitment: "A dependable repayment record supports confidence through the study period.",
      income: "Continuity matters when repayment may span changing work or residency conditions.",
      capacity: "Affordability tests whether observed resources can support the requested commitment.",
      liquidity: "Liquid funds can bridge education, relocation, or early-career cost changes.",
      shock: "Reserves and protection are important when income is exposed to life-stage disruption.",
      momentum: "The direction of income shows whether the applicant's financial position is strengthening.",
      cross_border: "Cross-border continuity helps carry evidence across education and migration transitions.",
    },
  },
};

function countLabel(value: number, singular: string, plural = `${singular}s`): string {
  return `${value} ${value === 1 ? singular : plural}`;
}

function domainExplanation(domain: ScoreResponse["domains"][number], product: ProductType): { why: string; effect: string; focus: string } {
  const profile = productScoreProfiles[product];
  const message = domain.reason_codes[0]?.message ?? "The available records provide a limited picture for this area.";
  const noEvidence = domain.reliability === 0;
  let why = noEvidence ? "No records were found for this area." : "The available records provide a mixed picture for this area.";

  if (!noEvidence && domain.key === "commitment") {
    const scheduled = message.match(/(\d+) of (\d+) scheduled commitments were paid/i);
    const observed = message.match(/(\d+) commitment payment\(s\) were observed across (\d+) month\(s\)/i);
    if (scheduled) {
      const onTime = Number(scheduled[1]);
      const total = Number(scheduled[2]);
      const percentage = total ? Math.round((onTime / total) * 100) : 0;
      why = `${countLabel(onTime, "scheduled payment")} out of ${total} were on time (${percentage}%).`;
    } else if (observed) {
      why = `We found ${countLabel(Number(observed[1]), "recurring payment")} across ${observed[2]} months, but the records did not include due dates to check timing.`;
    } else {
      why = "No recurring payments with usable timing information were found.";
    }
  } else if (!noEvidence && domain.key === "income") {
    const income = message.match(/(\d+) observed income month\(s\); recurring inflows are (\d+)% consistent/i);
    if (income) why = `Income appeared across ${income[1]} months, and recurring amounts were ${income[2]}% consistent.`;
    else why = "The records did not show enough regular income to assess stability clearly.";
  } else if (!noEvidence && domain.key === "capacity") {
    const capacity = message.match(/commitment outflows were (\d+)% of classified income inflows/i);
    if (capacity) {
      const committed = Number(capacity[1]);
      const remaining = Math.max(0, 100 - committed);
      why = `Regular commitments used ${committed}% of classified income, leaving about ${remaining}% before other spending.`;
    } else if (/no inflows could be classified/i.test(message)) {
      why = "Commitments were present, but the records did not identify usable income, so this area stayed neutral.";
    } else {
      why = "There was not enough usable income and payment information to assess room for new payments.";
    }
  } else if (!noEvidence && domain.key === "liquidity") {
    const liquidity = message.match(/(\d+) of (\d+) observed month\(s\) had non-negative net flow/i);
    if (liquidity) why = `Money was left after spending in ${liquidity[1]} of ${liquidity[2]} observed months.`;
    else why = "The records did not show enough balance or spending history to assess the cash buffer clearly.";
  } else if (!noEvidence && domain.key === "shock") {
    const shock = message.match(/Observed (\d+) reserve\/deposit event\(s\) and (\d+) protection payment\(s\)/i);
    if (shock) {
      const reserves = Number(shock[1]);
      const protection = Number(shock[2]);
      why = reserves || protection
        ? `The records show ${countLabel(reserves, "reserve or deposit event")} and ${countLabel(protection, "protection payment")}.`
        : "No reserve, deposit or protection-payment activity was found.";
    } else {
      why = "The records did not show reserves, protection payments or another clear buffer for disruption.";
    }
  } else if (!noEvidence && domain.key === "momentum") {
    const momentum = message.match(/([+-]?\d+)% from early to late observed income/i);
    if (momentum) {
      const change = Number(momentum[1]);
      why = `Income ${change < 0 ? "fell" : "rose"} ${Math.abs(change)}% from the early period to the late period.`;
    } else if (/one observed month/i.test(message)) {
      why = "Only one month of income was available, so a trend could not be established.";
    } else {
      why = "The records did not show enough income history to establish a clear trend.";
    }
  } else if (!noEvidence && domain.key === "cross_border") {
    const crossBorder = message.match(/(\d+) cross-border event\(s\) across (\d+) month\(s\) and (\d+) currency/i);
    if (crossBorder) why = `We found ${countLabel(Number(crossBorder[1]), "cross-border transfer")} across ${crossBorder[2]} months and ${crossBorder[3]} currencies.`;
    else if (/no cross-border transfer events/i.test(message)) why = "No cross-border transfers were found to add support in this area.";
    else why = "The records showed limited cross-border activity for this area.";
  }

  const effect = noEvidence
    ? `This area is ${domain.weight}% of the passport score. No records were found, so this stayed neutral.`
    : domain.adjusted >= 75
    ? `This area is ${domain.weight}% of the passport score and helped the result.`
    : domain.adjusted >= 60
      ? `This area is ${domain.weight}% of the passport score and needs attention.`
      : `This area is ${domain.weight}% of the passport score and pulled the result down.`;
  return { why, effect, focus: profile.focus[domain.key] ?? "This area adds context to the product-specific review." };
}

function HelpTip({ label, children, className = "text-[#6f8093]" }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`More about ${label}`}
          onClick={(event) => event.stopPropagation()}
          className={`inline-grid size-5 shrink-0 place-items-center rounded-full transition hover:bg-[#edf2f7] hover:text-[#2f61c5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#2f61c5] focus-visible:ring-offset-1 ${className}`}
        >
          <CircleHelp className="size-3.5" aria-hidden="true" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" align="start" sideOffset={6} className="max-w-xs leading-5">
        {children}
      </TooltipContent>
    </Tooltip>
  );
}

function SectionHeading({ eyebrow, title, detail, action }: { eyebrow?: string; title: string; detail?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
      <div>
        {eyebrow ? <p className="mb-1 text-xs font-bold uppercase tracking-[0.13em] text-[#2f61c5]">{eyebrow}</p> : null}
        <div className="flex items-center gap-2">
          <h1 className="text-3xl font-semibold tracking-[-0.035em] text-[#182b3a]">{title}</h1>
          {detail ? <HelpTip label={title}>{detail}</HelpTip> : null}
        </div>
      </div>
      {action}
    </div>
  );
}

function Metric({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="border-l-2 border-[#d8e2ef] pl-4">
      <div className="flex items-center gap-1">
        <p className="text-xs font-bold uppercase tracking-[0.1em] text-[#7b8aa0]">{label}</p>
        {note ? <HelpTip label={label}>{note}</HelpTip> : null}
      </div>
      <p className="mt-1 text-2xl font-semibold tabular-nums tracking-tight text-[#182b3a]">{value}</p>
    </div>
  );
}

function CreateApplicantDialog({ onCreated, compact = false }: { onCreated: (applicant: Applicant) => void | Promise<void>; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<ApplicantCreate>({
    name: "",
    corridor: "",
    product: "personal-loan",
    requested_amount: null,
    currency: "INR",
    employment: "",
    residency: "",
  });

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const applicant = await creditPassportApi.createApplicant(form);
      setOpen(false);
      await onCreated(applicant);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="bg-[#2f61c5] hover:bg-[#244fa5]" size={compact ? "sm" : "default"}><Plus /> Create passport</Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Create a Credit Passport</DialogTitle>
            <DialogDescription className="sr-only">Enter applicant and product details.</DialogDescription>
          </DialogHeader>
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <label className="sm:col-span-2"><span className="mb-1.5 block text-sm font-semibold">Full name</span><input required className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label><span className="mb-1.5 block text-sm font-semibold">Migration corridor</span><input required placeholder="UAE → India" className={inputClass} value={form.corridor} onChange={(e) => setForm({ ...form, corridor: e.target.value })} /></label>
            <label><span className="mb-1.5 block text-sm font-semibold">Credit product</span><select className={inputClass} value={form.product} onChange={(e) => setForm({ ...form, product: e.target.value as ProductType })}><option value="personal-loan">Personal loan</option><option value="credit-card">Credit card</option><option value="student-loan">Student loan</option></select></label>
            <label><span className="mb-1.5 block text-sm font-semibold">Requested amount</span><input min="0" type="number" className={inputClass} value={form.requested_amount ?? ""} onChange={(e) => setForm({ ...form, requested_amount: e.target.value ? Number(e.target.value) : null })} /></label>
            <label><span className="mb-1.5 block text-sm font-semibold">Currency</span><input required maxLength={3} className={inputClass} value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })} /></label>
            <label><span className="mb-1.5 block text-sm font-semibold">Employment</span><input className={inputClass} value={form.employment ?? ""} onChange={(e) => setForm({ ...form, employment: e.target.value })} /></label>
            <label><span className="mb-1.5 block text-sm font-semibold">Residency context</span><input className={inputClass} value={form.residency ?? ""} onChange={(e) => setForm({ ...form, residency: e.target.value })} /></label>
          </div>
          {error ? <p className="mt-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p> : null}
          <DialogFooter className="mt-6"><Button type="submit" disabled={pending} className="bg-[#2f61c5] hover:bg-[#244fa5]">{pending ? <LoaderCircle className="animate-spin" /> : <Plus />} {pending ? "Creating…" : "Create passport"}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

type UploadImpact = {
  beforeScore: ScoreResponse | null;
  afterScore: ScoreResponse;
  beforeEvidence: EvidenceResponse | null;
  afterEvidence: EvidenceResponse;
  beforeRisk: number | null;
  afterRisk: number | null;
  parsedRows: number;
};

function formatDelta(after: number | null, before: number | null, suffix = ""): string {
  if (after === null) return "Not available";
  if (before === null) return `— → ${after.toFixed(1)}${suffix}`;
  const delta = after - before;
  return `${before.toFixed(1)} → ${after.toFixed(1)}${suffix} (${delta >= 0 ? "+" : ""}${delta.toFixed(1)})`;
}

function UploadImpactReasons({ impact, product }: { impact: UploadImpact; product: ProductType }) {
  const beforeDomains = new Map((impact.beforeScore?.domains ?? []).map((domain) => [domain.key, domain]));
  const changes = impact.afterScore.domains
    .map((domain) => ({ domain, delta: domain.adjusted - (beforeDomains.get(domain.key)?.adjusted ?? domain.adjusted) }))
    .sort((left, right) => Math.abs(right.delta) - Math.abs(left.delta));
  const changed = changes.filter(({ delta }) => Math.abs(delta) >= 0.05);
  const selected = (changed.length ? changed : changes).slice(0, 3);

  return <div className="mt-5 rounded-lg border border-[#dbe3ea] bg-[#f8fafb] p-4"><p className="text-xs font-bold uppercase tracking-wide text-[#718198]">What moved the result</p><div className="mt-3 space-y-3">{selected.map(({ domain, delta }) => { const explanation = domainExplanation(domain, product); const label = productScoreProfiles[product].labels[domain.key] ?? domain.label; return <div key={domain.key} className="flex gap-3 text-sm"><span className={`mt-0.5 grid size-5 shrink-0 place-items-center rounded-full text-xs font-bold ${delta >= 0 ? "bg-[#d9f2e9] text-[#176c5e]" : "bg-[#fde4e1] text-[#a52a21]"}`}>{delta >= 0 ? "↑" : "↓"}</span><p className="leading-5 text-[#34495c]"><span className="font-semibold">{label} {delta >= 0 ? "improved" : "fell"}.</span> {explanation.why}</p></div>; })}</div></div>;
}

function UploadStatementDialog({ applicant, config, onUploaded }: { applicant: Applicant; config: ConfigResponse; onUploaded: () => void | Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [provider, setProvider] = useState("");
  const [sourceType, setSourceType] = useState("bank-statement");
  const [currency, setCurrency] = useState(applicant.currency);
  const [consent, setConsent] = useState(false);
  const [pending, setPending] = useState(false);
  const [impact, setImpact] = useState<UploadImpact | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || !provider || !consent) return;
    setPending(true);
    setError(null);
    setImpact(null);
    try {
      const [beforeScore, beforeEvidence, beforeChallenger] = await Promise.all([
        creditPassportApi.getScore(applicant.id, applicant.product).catch(() => null),
        creditPassportApi.getEvidence(applicant.id).catch(() => null),
        creditPassportApi.getChallengerScore(applicant.id, applicant.product).catch(() => null),
      ]);
      const response = await creditPassportApi.uploadStatement(applicant.id, file, { provider, sourceType, currency });
      const [afterEvidence, afterScore, afterChallenger] = await Promise.all([
        creditPassportApi.getEvidence(applicant.id),
        creditPassportApi.getScore(applicant.id, applicant.product).catch(() => response.score),
        creditPassportApi.getChallengerScore(applicant.id, applicant.product).catch(() => null),
      ]);
      setImpact({
        beforeScore,
        afterScore,
        beforeEvidence,
        afterEvidence,
        beforeRisk: beforeChallenger?.probability === undefined ? null : beforeChallenger.probability * 100,
        afterRisk: afterChallenger?.probability === undefined ? null : afterChallenger.probability * 100,
        parsedRows: response.parsed_rows,
      });
      await onUploaded();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setPending(false);
    }
  }

  function close(next: boolean) {
    setOpen(next);
    if (!next) {
      setImpact(null);
      setError(null);
      setFile(null);
      setProvider("");
      setSourceType("bank-statement");
      setCurrency(applicant.currency);
      setConsent(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogTrigger asChild><Button className="bg-[#2f61c5] hover:bg-[#244fa5]"><Upload /> Add records</Button></DialogTrigger>
      <DialogContent className="max-w-md">
        <form onSubmit={submit}>
          <DialogHeader><DialogTitle>{impact ? "Upload impact" : "Add records"}</DialogTitle><DialogDescription className="sr-only">{impact ? "Review how the uploaded file changed the active product score." : "Upload a complete statement or workbook from one financial source."}</DialogDescription></DialogHeader>
          {impact ? (
            <div className="mt-5"><div className="rounded-lg border border-teal-200 bg-teal-50 p-4"><div className="flex items-start gap-3"><FileCheck2 className="mt-0.5 size-6 shrink-0 text-teal-700" /><div><p className="font-semibold text-teal-900">{impact.parsedRows.toLocaleString("en-IN")} records added</p><p className="mt-1 text-sm leading-5 text-teal-800">{productLabel(applicant.product)} recalculated from the updated evidence.</p></div></div></div><div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3"><div className="rounded-md border border-[#dbe3ea] bg-white p-3"><p className="text-[10px] font-bold uppercase tracking-wide text-[#718198]">Score</p><p className="mt-1 text-sm font-semibold tabular-nums text-[#182b3a]">{formatDelta(impact.afterScore.score, impact.beforeScore?.score ?? null)}</p></div><div className="rounded-md border border-[#dbe3ea] bg-white p-3"><p className="text-[10px] font-bold uppercase tracking-wide text-[#718198]">90-day risk</p><p className="mt-1 text-sm font-semibold tabular-nums text-[#182b3a]">{formatDelta(impact.afterRisk, impact.beforeRisk, "%")}</p></div><div className="rounded-md border border-[#dbe3ea] bg-white p-3"><p className="text-[10px] font-bold uppercase tracking-wide text-[#718198]">Evidence</p><p className="mt-1 text-sm font-semibold tabular-nums text-[#182b3a]">{impact.beforeEvidence?.unique_event_count ?? "—"} → {impact.afterEvidence.unique_event_count} activities</p></div></div><UploadImpactReasons impact={impact} product={applicant.product} /></div>
          ) : (
            <div className="mt-5 space-y-4">
              <label><span className="mb-1.5 block text-sm font-semibold">Source type</span><select className={inputClass} value={sourceType} onChange={(e) => setSourceType(e.target.value)}>{config.evidence_types.map((type) => <option key={type} value={type}>{evidenceTypeLabel(type)}</option>)}</select></label>
              <label><span className="mb-1.5 block text-sm font-semibold">Provider</span><input required placeholder="Bank or source name" className={inputClass} value={provider} onChange={(e) => setProvider(e.target.value)} /></label>
              <div className="grid gap-4 sm:grid-cols-[1fr_120px]">
                <label><span className="mb-1.5 block text-sm font-semibold">Statement or workbook</span><input required type="file" accept=".csv,.xlsx,.xls,.pdf,text/csv,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full rounded-md border border-[#ccd6df] bg-[#f8fafb] p-3 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-[#eaf0fb] file:px-3 file:py-2 file:font-semibold file:text-[#2f61c5]" /></label>
                <label><span className="mb-1.5 block text-sm font-semibold">Currency</span><input required maxLength={3} className={inputClass} value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} /></label>
              </div>
              <label className="flex items-start gap-3 rounded-md border border-[#dbe3ea] bg-[#f8fafb] p-3 text-sm leading-5"><input required type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-1 size-4 accent-[#2f61c5]" /><span>I have permission to share this file.</span></label>
            </div>
          )}
          {error ? <p className="mt-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p> : null}
          <DialogFooter className="mt-6">{!impact ? <Button type="submit" disabled={!file || !provider || !consent || pending} className="bg-[#2f61c5] hover:bg-[#244fa5]">{pending ? <LoaderCircle className="animate-spin" /> : <Upload />} {pending ? "Uploading…" : "Upload"}</Button> : <Button type="button" onClick={() => close(false)}>Done</Button>}</DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EmptyWorkspace({ onCreated }: { onCreated: (applicant: Applicant) => void | Promise<void> }) {
  return (
    <div className="mx-auto flex min-h-[calc(100vh-140px)] max-w-3xl items-center justify-center">
      <section className="w-full rounded-2xl border border-[#dbe3ea] bg-white px-6 py-12 text-center shadow-[0_16px_50px_rgba(24,43,58,0.08)] sm:px-12">
        <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-[#eaf0fb] text-[#2f61c5]"><ShieldCheck className="size-7" /></span>
        <h1 className="mt-6 text-3xl font-semibold tracking-[-0.035em] text-[#182b3a]">Build your Credit Passport</h1>
        <div className="mx-auto mt-7 grid max-w-2xl gap-3 text-left sm:grid-cols-3">
          {[['1', 'Create'], ['2', 'Add evidence'], ['3', 'Review']].map(([number, title]) => <div key={number} className="rounded-lg bg-[#f6f8fa] p-4"><span className="grid size-7 place-items-center rounded-full bg-[#2f61c5] text-xs font-bold text-white">{number}</span><p className="mt-3 font-semibold text-[#263a4b]">{title}</p></div>)}
        </div>
        <div className="mt-8"><CreateApplicantDialog onCreated={onCreated} /></div>
      </section>
    </div>
  );
}

function HomeView({ applicant, evidence, score, config, onNavigate, onRefresh }: { applicant: Applicant; evidence: EvidenceResponse; score: ScoreResponse; config: ConfigResponse; onNavigate: (view: View) => void; onRefresh: () => void }) {
  const hasEvidence = evidence.assertion_count > 0 && score.reliability > 0;
  const displayScore = hasEvidence ? score.score : null;
  const band = scoreBand(displayScore);
  return (
    <div className="mx-auto max-w-[1120px]">
      <SectionHeading eyebrow={`Hello, ${applicant.name.split(" ")[0]}`} title="Your Credit Passport" />
      <section className="overflow-hidden rounded-2xl bg-[#182b3a] text-white shadow-[0_18px_50px_rgba(24,43,58,0.16)]">
        <div className="grid lg:grid-cols-[1.15fr_0.85fr]">
          <div className="p-6 sm:p-8">
            <p className="text-xs font-bold uppercase tracking-[0.14em] text-[#a9bac8]">Current passport score</p>
            <div className="mt-3 flex flex-wrap items-end gap-4"><span className="text-7xl font-semibold tabular-nums tracking-[-0.07em]">{displayScore ?? "—"}</span><div className="pb-2"><span className={`inline-flex rounded-full border px-3 py-1 text-sm font-semibold ${band.className}`}>{band.label}</span><p className="mt-2 text-sm text-[#b9c6d0]">{productLabel(applicant.product)}</p></div></div>
            <div className="mt-7 grid grid-cols-2 gap-5 border-t border-white/15 pt-5 sm:grid-cols-3">
              <div>
                <p className="text-2xl font-semibold tabular-nums">{hasEvidence ? `${score.reliability}%` : "—"}</p>
                <div className="mt-1 flex items-center gap-1 text-xs text-[#a9bac8]"><span>Evidence strength</span><HelpTip label="Evidence strength" className="text-[#a9bac8] hover:bg-white/10 hover:text-white">This reflects how complete the uploaded records are, how much of the activity they cover, and how well separate sources support one another. It describes the records, not the accuracy of the system.</HelpTip></div>
              </div>
              <div><p className="text-2xl font-semibold tabular-nums">{evidence.unique_event_count}</p><p className="mt-1 text-xs text-[#a9bac8]">Activity records</p></div>
              <div><p className="text-2xl font-semibold tabular-nums">{evidence.sources.length}</p><p className="mt-1 text-xs text-[#a9bac8]">Sources connected</p></div>
            </div>
          </div>
          <div className="border-t border-white/10 bg-[#203746] p-6 sm:p-8 lg:border-l lg:border-t-0">
            <p className="text-xs font-bold uppercase tracking-[0.14em] text-[#a9bac8]">Next action</p>
            {hasEvidence ? <><h2 className="mt-4 text-xl font-semibold">Review what shaped the result</h2><Button onClick={() => onNavigate("score")} className="mt-5 bg-white text-[#182b3a] hover:bg-[#eef2f5]">Open score <ArrowRight /></Button></> : <><h2 className="mt-4 text-xl font-semibold">Add a complete statement</h2><div className="mt-5"><UploadStatementDialog applicant={applicant} config={config} onUploaded={onRefresh} /></div></>}
          </div>
        </div>
      </section>
      <div className="mt-6 grid gap-5 lg:grid-cols-[1.05fr_0.95fr]">
        <section className="rounded-xl border border-[#dbe3ea] bg-white p-5 sm:p-6"><div className="flex items-center justify-between"><div><h2 className="text-lg font-semibold text-[#182b3a]">Connected sources</h2><p className="mt-1 text-sm text-[#6b7a8e]">{evidence.sources.length ? `${evidence.sources.length} source${evidence.sources.length === 1 ? "" : "s"} in this passport.` : "No source has been added yet."}</p></div><button onClick={() => onNavigate("evidence")} className="text-sm font-semibold text-[#2f61c5] hover:underline">View all</button></div>{evidence.sources.length ? <div className="mt-5 divide-y divide-[#edf0f3]">{evidence.sources.slice(0, 4).map((source) => <div key={source.id} className="flex items-center gap-3 py-3"><span className="grid size-9 place-items-center rounded-lg bg-[#eef3fc] text-[#2f61c5]"><Database className="size-4" /></span><div className="min-w-0 flex-1"><p className="text-sm font-semibold text-[#263a4b]">{evidenceTypeLabel(source.source_type)}</p><p className="truncate text-xs text-[#7b899c]">{source.provider}</p></div><p className="text-right text-xs font-medium text-[#39736e]">{source.assertion_count} records</p></div>)}</div> : <div className="mt-5 rounded-lg border border-dashed border-[#cad4de] p-6 text-center text-sm text-[#718198]">Your sources will appear here after you add a file.</div>}<div className="mt-4"><UploadStatementDialog applicant={applicant} config={config} onUploaded={onRefresh} /></div></section>
        <section className="rounded-xl border border-[#dbe3ea] bg-white p-5 sm:p-6"><p className="text-xs font-bold uppercase tracking-[0.12em] text-[#7051b8]">Passport contents</p><h2 className="mt-2 text-xl font-semibold text-[#182b3a]">What a lender can review</h2><div className="mt-5 space-y-3 rounded-lg bg-[#f6f8fa] p-4 text-sm">{["Product-specific score", "Evidence strength", "Activity records", "Reasons linked to records"].map((item) => <div key={item} className="flex items-center gap-2 text-[#34495c]"><Check className="size-4 text-[#008b78]" />{item}</div>)}</div><Button onClick={() => onNavigate("evidence")} variant="outline" className="mt-5 w-full border-[#cad4de]">View all sources</Button></section>
      </div>
    </div>
  );
}

function EvidenceView({ applicant, evidence, config, onRefresh, audience = "applicant" }: { applicant: Applicant; evidence: EvidenceResponse; config: ConfigResponse; onRefresh: () => void; audience?: Mode }) {
  const dateRange = evidence.sources.length
    ? formatDate(evidence.sources.map((source) => source.period_start).sort()[0]) + " – " + formatDate(evidence.sources.map((source) => source.period_end).sort().at(-1))
    : "Not available";
  const lenderView = audience === "lender";

  return (
    <div className="mx-auto max-w-[1120px]">
      <SectionHeading eyebrow={lenderView ? "Lender review" : "Credit Passport"} title={lenderView ? "Evidence review" : "My evidence"} detail={lenderView ? "Review the records supplied for this application. Evidence strength describes coverage and corroboration, not an approval decision." : undefined} />
      <section className="mb-6 rounded-xl border border-[#dbe3ea] bg-white p-5 sm:p-6">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="grid flex-1 gap-5 sm:grid-cols-3 sm:items-end">
            <div><p className="text-xs font-bold uppercase tracking-wide text-[#718198]">Connected sources</p><p className="mt-2 text-2xl font-semibold tabular-nums text-[#182b3a]">{evidence.sources.length}</p></div>
            <div><p className="text-xs font-bold uppercase tracking-wide text-[#718198]">Records</p><p className="mt-2 text-2xl font-semibold tabular-nums text-[#182b3a]">{evidence.unique_event_count.toLocaleString("en-IN")}</p></div>
            <div><p className="text-xs font-bold uppercase tracking-wide text-[#718198]">Date range</p><p className="mt-2 text-base font-semibold text-[#263a4b]">{dateRange}</p></div>
          </div>
          {!lenderView ? <div className="shrink-0"><UploadStatementDialog applicant={applicant} config={config} onUploaded={onRefresh} /></div> : null}
        </div>
      </section>

      <section className="overflow-hidden rounded-xl border border-[#dbe3ea] bg-white">
        <div className="border-b border-[#e5eaee] px-5 py-4 sm:px-6"><h2 className="text-lg font-semibold text-[#182b3a]">{lenderView ? "Submitted sources" : "Sources"}</h2><p className="mt-1 text-sm text-[#718198]">{lenderView ? "Each source can be traced back to the activity used in the decision score." : "Connected sources and their covered periods."}</p></div>
        {evidence.sources.length ? (
          <div>
            <div className="hidden grid-cols-[1.1fr_1fr_1.4fr_90px_130px] gap-4 bg-[#f5f8fa] px-5 py-3 text-xs font-bold uppercase tracking-wide text-[#718198] md:grid sm:px-6"><span>Source type</span><span>Provider</span><span>Covered period</span><span>Records</span><span>Status</span></div>
            {evidence.sources.map((source) => {
              const status = source.unique_event_count > 0
                ? { label: "Ready to review", className: "border-teal-200 bg-teal-50 text-teal-800" }
                : { label: "Needs records", className: "border-amber-200 bg-amber-50 text-amber-800" };
              return <div key={source.id} className="grid gap-4 border-t border-[#edf0f3] px-5 py-4 md:grid-cols-[1.1fr_1fr_1.4fr_90px_130px] md:items-center sm:px-6">
                <div><p className="text-xs font-bold uppercase tracking-wide text-[#718198] md:hidden">Source type</p><p className="mt-1 font-semibold text-[#263a4b] md:mt-0">{evidenceTypeLabel(source.source_type)}</p></div>
                <div><p className="text-xs font-bold uppercase tracking-wide text-[#718198] md:hidden">Provider</p><p className="mt-1 text-sm text-[#34495c] md:mt-0">{source.provider || "Not provided"}</p></div>
                <div><p className="text-xs font-bold uppercase tracking-wide text-[#718198] md:hidden">Covered period</p><p className="mt-1 text-sm text-[#34495c] md:mt-0">{formatDate(source.period_start)} – {formatDate(source.period_end)}</p></div>
                <div><p className="text-xs font-bold uppercase tracking-wide text-[#718198] md:hidden">Records</p><p className="mt-1 font-semibold tabular-nums text-[#263a4b] md:mt-0">{source.unique_event_count.toLocaleString("en-IN")}</p></div>
                <div><p className="text-xs font-bold uppercase tracking-wide text-[#718198] md:hidden">Status</p><span className={status.className + " mt-1 inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold md:mt-0"}>{status.label}</span></div>
              </div>;
            })}
          </div>
        ) : (
          <div className="px-5 py-12 text-center sm:px-6"><p className="font-semibold text-[#263a4b]">No sources yet</p><p className="mt-1 text-sm text-[#718198]">Add a CSV file to start building your evidence library.</p></div>
        )}
      </section>
    </div>
  );
}

function ScoreView({
  score,
  product,
  onProductChange,
  audience = "applicant",
}: {
  score: ScoreResponse;
  product: ProductType;
  onProductChange: (product: ProductType) => void;
  audience?: Mode;
}) {
  const [challenger, setChallenger] = useState<ChallengerScoreResponse | null>(null);
  const [challengerLoading, setChallengerLoading] = useState(true);
  const [challengerError, setChallengerError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void creditPassportApi.getChallengerScore(score.applicant_id, product)
      .then((value) => { if (active) setChallenger(value); })
      .catch((cause) => { if (active) setChallengerError(errorMessage(cause)); })
      .finally(() => { if (active) setChallengerLoading(false); });
    return () => { active = false; };
  }, [product, score.applicant_id]);

  const hasEvidence = score.assertion_count > 0 && score.reliability > 0;
  const profile = productScoreProfiles[product];
  const productIsUpdating = score.product !== product;
  const orderedDomains = [...score.domains].sort((left, right) => {
    const weightDifference = right.weight - left.weight;
    if (weightDifference !== 0) return weightDifference;
    return (profile.order.indexOf(left.key) < 0 ? Number.MAX_SAFE_INTEGER : profile.order.indexOf(left.key)) - (profile.order.indexOf(right.key) < 0 ? Number.MAX_SAFE_INTEGER : profile.order.indexOf(right.key));
  });
  const decisionScore = productIsUpdating ? null : score.score;
  const riskPercent = challenger ? challenger.probability * 100 : null;
  const featureOrder = [
    "active_month_count",
    "income_total",
    "commitment_total",
    "obligation_to_income_ratio",
    "commitment_on_time_rate",
    "balance_last",
    "net_flow_total",
    "currency_count",
  ];
  const featureLabels: Record<string, string> = {
    active_month_count: "Months reviewed",
    income_total: "Income found",
    commitment_total: "Regular payments",
    obligation_to_income_ratio: "Payment burden",
    commitment_on_time_rate: "On-time payments found",
    balance_last: "Latest balance",
    net_flow_total: "Money left after spending",
    currency_count: "Currencies found",
  };
  const featureValue = (key: string, value: number) => {
    if (key.endsWith("_rate") || key.endsWith("_ratio")) return `${(value * 100).toFixed(1)}%`;
    if (["income_total", "commitment_total", "balance_last", "net_flow_total"].includes(key)) return value.toLocaleString("en-IN", { maximumFractionDigits: 0 });
    return value.toLocaleString("en-IN", { maximumFractionDigits: 1 });
  };

  return <>
    <SectionHeading
      eyebrow={audience === "lender" ? "Lender review" : "Credit Passport"}
      title={audience === "lender" ? "Decision score" : "Overall credit score"}
      detail={audience === "lender" ? "A transparent, product-specific scorecard. Review the underlying evidence before making a lending decision." : undefined}
      action={<select className={`${inputClass} w-[190px]`} value={product} onChange={(e) => onProductChange(e.target.value as ProductType)}><option value="personal-loan">Personal loan</option><option value="credit-card">Credit card</option><option value="student-loan">Student loan</option></select>}
    />
    {productIsUpdating ? <div role="status" className="mb-5 flex items-center gap-2 rounded-lg border border-[#cbd8ec] bg-[#f2f6fd] px-4 py-3 text-sm font-medium text-[#274e9d]"><LoaderCircle className="size-4 animate-spin" /> Updating the {productLabel(product).toLowerCase()} criteria and results…</div> : null}
    <div className="grid gap-5 lg:grid-cols-[280px_1fr]">
      <section className="rounded-xl bg-[#182b3a] p-6 text-white">
        <p className="text-xs font-bold uppercase tracking-[0.12em] text-[#9fb1c2]">{productLabel(product)}</p>
        <div className="mt-4 flex items-end gap-2"><span className="text-6xl font-semibold tabular-nums tracking-[-0.06em]">{productIsUpdating ? "…" : hasEvidence ? decisionScore : "—"}</span>{hasEvidence && !productIsUpdating ? <span className="mb-2 text-lg text-[#aebdca]">/100</span> : null}</div>
        <span className={`mt-4 inline-flex rounded-full border px-3 py-1 text-sm font-semibold ${scoreBand(hasEvidence && !productIsUpdating ? decisionScore : null).className}`}>{productIsUpdating ? "Updating" : scoreBand(hasEvidence ? decisionScore : null).label}</span>
        <div className="mt-6 grid grid-cols-2 gap-4 border-t border-white/15 pt-5">
          <div>
            <div className="flex items-center gap-1 text-xs uppercase tracking-wide text-[#aebdca]"><span>90-day payment risk</span><HelpTip label="90-day payment risk" className="text-[#aebdca] hover:bg-white/10 hover:text-white">The estimated chance of a missed payment or adverse restructure in the next 90 days, based on the records provided.</HelpTip></div>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{productIsUpdating || challengerLoading ? "…" : riskPercent === null ? "—" : `${riskPercent.toFixed(1)}%`}</p>
          </div>
          <div>
            <div className="flex items-center gap-1 text-xs uppercase tracking-wide text-[#aebdca]"><span>Evidence strength</span><HelpTip label="Evidence strength" className="text-[#aebdca] hover:bg-white/10 hover:text-white">This reflects how complete the uploaded records are, how much of the activity they cover, and how well separate sources support one another. It describes the records, not the accuracy of the system.</HelpTip></div>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{productIsUpdating ? "…" : hasEvidence ? `${score.reliability}%` : "—"}</p>
          </div>
        </div>
      </section>
      <section className="overflow-hidden rounded-xl border border-[#dbe3ea] bg-white">
        <div className="grid min-w-[520px] grid-cols-[minmax(260px,1fr)_100px_90px] gap-2 border-b border-[#dbe3ea] bg-[#f5f8fa] px-4 py-3 text-xs font-bold uppercase tracking-wide text-[#718198]"><span>What we looked at</span><span>Result</span><span className="text-right">Weight</span></div>
        <div className="overflow-x-auto">{productIsUpdating ? <div className="grid min-h-64 place-items-center px-5 text-center text-sm text-[#718198]"><div><LoaderCircle className="mx-auto size-6 animate-spin text-[#2f61c5]" /><p className="mt-3 font-medium">Waiting for the {productLabel(product).toLowerCase()} scorecard…</p></div></div> : orderedDomains.map((domain) => { const label = profile.labels[domain.key] ?? domain.label; const tone = scoreTone(domain.adjusted, domain.reliability); const explanation = domainExplanation(domain, product); return <div key={domain.key} className="grid min-w-[520px] grid-cols-[minmax(260px,1fr)_100px_90px] items-center gap-2 border-b border-[#edf0f3] px-4 py-4 last:border-b-0"><div><div className="flex items-center justify-between gap-3"><span className="font-semibold text-[#263a4b]">{label}</span><HelpTip label={`Why ${label} has this result`}><div className="space-y-2"><p><span className="font-semibold">What this product values:</span> {explanation.focus}</p><p><span className="font-semibold">What the records show:</span> {explanation.why}</p><p><span className="font-semibold">Effect:</span> {explanation.effect}</p></div></HelpTip></div><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#e7edf2]"><div className="h-full rounded-full" style={{ width: `${domain.adjusted}%`, backgroundColor: tone.barColor }} /></div></div><span className={`font-semibold tabular-nums ${tone.valueClass}`}>{domain.adjusted.toFixed(1)}</span><span className="text-right font-semibold tabular-nums text-[#52657a]">{domain.weight}%</span></div>; })}</div>
      </section>
    </div>

    <section className="mt-5 rounded-xl border border-[#d8dee5] bg-white p-5">
      <details>
        <summary className="cursor-pointer select-none text-sm font-semibold text-[#2f61c5] outline-none focus-visible:ring-2 focus-visible:ring-[#2f61c5] focus-visible:ring-offset-2">View model inputs</summary>
        {challengerLoading ? <div className="grid min-h-24 place-items-center"><LoaderCircle className="size-6 animate-spin text-[#7051b8]" /></div> : challengerError ? <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm font-medium text-rose-800">{challengerError}</div> : challenger ? <div className="mt-4 border-t border-[#e6eaee] pt-4"><p className="text-sm leading-6 text-[#52657a]">These are the records used to estimate 90-day payment risk.</p><div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{featureOrder.filter((key) => key in challenger.feature_values).map((key) => <div key={key} className="rounded-md bg-[#f5f7f9] px-3 py-2"><p className="text-[11px] font-semibold uppercase tracking-wide text-[#718198]">{featureLabels[key] ?? key}</p><p className="mt-1 font-semibold tabular-nums text-[#263a4b]">{featureValue(key, challenger.feature_values[key])}</p></div>)}</div></div> : <p className="mt-4 text-sm text-[#718198]">Model inputs are unavailable until records are ready.</p>}
      </details>
    </section>
  </>;
}

function GuidePanel({ applicant, transition }: { applicant: Applicant | null; transition: TransitionResponse | null }) {
  const [open, setOpen] = useState(false);
  const [prompts, setPrompts] = useState<GuidePrompt[]>([]);
  const [responses, setResponses] = useState<GuideResponse[]>([]);
  const [query, setQuery] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const wasOpenRef = useRef(false);
  const sessionId = useMemo(() => "guide-" + (applicant?.id ?? "visitor"), [applicant?.id]);

  useEffect(() => {
    let active = true;
    void creditPassportApi.getGuidePrompts().then((value) => {
      if (active) setPrompts(value);
    }).catch(() => {
      if (active) setPrompts([]);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!open) {
      if (wasOpenRef.current) launcherRef.current?.focus();
      wasOpenRef.current = false;
      return;
    }
    wasOpenRef.current = true;
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  async function ask(question: string, intent?: GuidePrompt["intent"]) {
    const trimmed = question.trim();
    if (!trimmed || pending) return;
    setPending(true);
    setError(null);
    try {
      const response = await creditPassportApi.queryGuide({
        query: trimmed,
        intent,
        session_id: sessionId,
        country_from: transition?.country_from ?? null,
        country_to: transition?.country_to ?? "India",
        facts: transition?.facts ?? {},
        max_sources: 4,
      });
      setResponses((current) => [...current, response]);
      if (response.suggested_prompts.length) setPrompts(response.suggested_prompts);
      setQuery("");
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setPending(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    await ask(query);
  }

  return <>
    <button
      ref={launcherRef}
      type="button"
      aria-label={open ? "Close guide" : "Open guide"}
      aria-expanded={open}
      onClick={() => setOpen((current) => !current)}
      className="fixed bottom-4 right-4 z-40 inline-flex items-center gap-2 rounded-full bg-[#182b3a] px-4 py-3 text-sm font-semibold text-white shadow-[0_10px_30px_rgba(24,43,58,0.2)] transition hover:bg-[#243b4b] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#2f61c5] focus-visible:ring-offset-2 sm:bottom-6 sm:right-6"
    >
      {open ? <X className="size-4" aria-hidden="true" /> : <MessageCircle className="size-4" aria-hidden="true" />}
      <span>Guide</span>
    </button>

    {open ? (
      <section
        role="dialog"
        aria-modal="false"
        aria-labelledby="guide-panel-title"
        className="fixed inset-3 z-50 flex min-h-0 flex-col overflow-hidden rounded-2xl border border-[#cfd9e2] bg-[#f7f9fa] shadow-[0_20px_70px_rgba(24,43,58,0.24)] sm:inset-auto sm:bottom-6 sm:right-6 sm:h-[min(680px,calc(100vh-3rem))] sm:w-[390px]"
      >
        <header className="flex items-center justify-between border-b border-[#dbe3ea] bg-white px-4 py-3">
          <div>
            <h2 id="guide-panel-title" className="font-semibold text-[#182b3a]">Guide</h2>
            <p className="mt-0.5 text-xs text-[#718198]">Moving, returning, and India account questions</p>
          </div>
          <button type="button" aria-label="Close guide" onClick={() => setOpen(false)} className="grid size-9 place-items-center rounded-md text-[#52657a] hover:bg-[#eef2f4] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#2f61c5]"><X className="size-4" /></button>
        </header>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          {!responses.length && prompts.length ? <div><p className="text-xs font-bold uppercase tracking-wide text-[#718198]">Suggested questions</p><div className="mt-2 flex flex-wrap gap-2">{prompts.map((prompt) => <button key={prompt.id} type="button" onClick={() => void ask(prompt.query, prompt.intent)} disabled={pending} className="rounded-full border border-[#cbd8e6] bg-white px-3 py-2 text-left text-xs font-medium text-[#2f61c5] transition hover:border-[#2f61c5] hover:bg-[#f3f6fc] disabled:cursor-not-allowed disabled:opacity-50">{prompt.label}</button>)}</div></div> : null}
          {responses.map((response, index) => <article key={index} className="space-y-3">
            <div className="ml-5 rounded-lg bg-[#eaf0fb] px-3 py-2.5 text-sm text-[#203f82]"><p className="text-[10px] font-bold uppercase tracking-wide text-[#5872a6]">Your question</p><p className="mt-1 leading-5">{response.query}</p></div>
            <div className="rounded-lg border border-[#dbe3ea] bg-white p-3.5"><p className="text-sm leading-6 text-[#34495c]">{response.answer}</p>{response.bullets.length ? <ul className="mt-3 space-y-1.5 pl-5 text-sm leading-5 text-[#34495c]">{response.bullets.map((bullet) => <li key={bullet} className="list-disc">{bullet}</li>)}</ul> : null}{response.citations.length ? <div className="mt-3 border-t border-[#edf0f3] pt-3"><p className="text-[10px] font-bold uppercase tracking-wide text-[#718198]">Official sources</p><div className="mt-2 space-y-1.5">{response.citations.map((citation) => <a key={citation.id} href={citation.url} target="_blank" rel="noreferrer" className="block rounded-md border border-[#e1e7ed] px-2.5 py-2 text-xs transition hover:border-[#2f61c5] hover:bg-[#f8fafc]"><span className="font-semibold text-[#2f61c5]">{citation.title}</span><span className="mt-0.5 block text-[#718198]">{citation.publisher}{citation.locator ? " · " + citation.locator : ""}</span></a>)}</div></div> : null}{response.follow_up_questions.length ? <div className="mt-3 border-t border-[#edf0f3] pt-3"><p className="text-[10px] font-bold uppercase tracking-wide text-[#718198]">Follow-up questions</p><div className="mt-2 flex flex-wrap gap-2">{response.follow_up_questions.map((followUp) => <button key={followUp} type="button" onClick={() => void ask(followUp)} disabled={pending} className="rounded-full border border-[#d5dde6] px-2.5 py-1.5 text-left text-xs font-medium text-[#2f61c5] hover:border-[#2f61c5] disabled:opacity-50">{followUp}</button>)}</div></div> : null}<p className="mt-3 border-t border-[#edf0f3] pt-3 text-[11px] leading-5 text-[#718198]">{response.disclaimer}</p></div>
          </article>)}
          {pending ? <div role="status" className="flex items-center gap-2 text-xs text-[#718198]"><LoaderCircle className="size-4 animate-spin" /> Checking the available sources…</div> : null}
          {error ? <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 p-3 text-xs leading-5 text-rose-800">{error}</p> : null}
        </div>

        <form onSubmit={submit} className="border-t border-[#dbe3ea] bg-white p-3">
          <label htmlFor="guide-question" className="sr-only">Ask the guide</label>
          <div className="flex items-end gap-2"><textarea ref={inputRef} id="guide-question" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={4000} rows={2} placeholder="Ask a question" className="min-h-11 flex-1 resize-none rounded-md border border-[#cbd6df] bg-white px-3 py-2.5 text-sm leading-5 text-[#263a4b] outline-none focus:border-[#2f61c5] focus:ring-2 focus:ring-[#2f61c5]/15" /><Button type="submit" size="icon" aria-label="Send question" disabled={!query.trim() || pending} className="shrink-0 bg-[#2f61c5] hover:bg-[#244fa5]">{pending ? <LoaderCircle className="animate-spin" /> : <Send />}</Button></div>
        </form>
      </section>
    ) : null}
  </>;
}

function TransitionView({ applicant, transition, onSaved }: { applicant: Applicant; transition: TransitionResponse; onSaved: (value: TransitionResponse) => void }) {
  const [event, setEvent] = useState<TransitionEvent>(transition.event ?? "returning-india");
  const [countryFrom, setCountryFrom] = useState(transition.country_from ?? "");
  const [countryTo, setCountryTo] = useState(transition.country_to ?? "India");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save() { setPending(true); setError(null); try { onSaved(await creditPassportApi.updateTransition(applicant.id, { event, country_from: countryFrom || null, country_to: countryTo || null, facts: {} })); } catch (cause) { setError(errorMessage(cause)); } finally { setPending(false); } }
  const tasks = transition.event === event ? transition.tasks : [];
  return <><SectionHeading eyebrow="Cross-border transition" title="Moving or returning" detail="Record the life event and get source-backed actions. Transition context remains outside the behavioural score." /><div className="grid gap-5 lg:grid-cols-[0.7fr_1.3fr]"><section className="rounded-xl border border-[#dbe3ea] bg-white p-5"><label><span className="mb-1.5 block text-sm font-semibold">Life event</span><select className={inputClass} value={event} onChange={(e) => setEvent(e.target.value as TransitionEvent)}><option value="moving-abroad">Moving abroad</option><option value="job-change">Job change or loss</option><option value="returning-india">Returning to India</option></select></label><div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-1"><label><span className="mb-1.5 block text-sm font-semibold">From</span><input className={inputClass} value={countryFrom} onChange={(e) => setCountryFrom(e.target.value)} /></label><label><span className="mb-1.5 block text-sm font-semibold">To</span><input className={inputClass} value={countryTo} onChange={(e) => setCountryTo(e.target.value)} /></label></div>{error ? <p className="mt-4 text-sm text-rose-700">{error}</p> : null}<Button onClick={save} disabled={pending} className="mt-5 w-full bg-[#2f61c5] hover:bg-[#244fa5]">{pending ? <LoaderCircle className="animate-spin" /> : <FileCheck2 />} {pending ? "Saving…" : "Save and generate actions"}</Button><div className="mt-5 rounded-lg bg-[#eaf7f4] p-4"><div className="flex gap-3"><ShieldCheck className="mt-0.5 size-5 text-[#008b78]" /><div><p className="font-semibold text-[#145f58]">Score impact: none</p><p className="mt-1 text-sm leading-5 text-[#39736e]">Guidance preserves context; it never adds behavioural points.</p></div></div></div></section><section className="rounded-xl border border-[#dbe3ea] bg-white p-5"><h2 className="text-lg font-semibold text-[#182b3a]">{transitionEventLabel(event)}</h2>{tasks.length ? <div className="mt-5 space-y-3">{tasks.map((task) => <div key={task.id} className="rounded-lg border border-[#dfe5ea] p-4"><div className="flex items-start justify-between gap-4"><div><p className="font-semibold text-[#263a4b]">{task.title}</p><p className="mt-1 text-sm leading-6 text-[#637388]">{task.action}</p></div><span className="rounded-full bg-[#eef3fc] px-2.5 py-1 text-xs font-semibold text-[#2f61c5]">{task.priority}</span></div>{task.sources.length ? <div className="mt-3 flex flex-wrap gap-2">{task.sources.map((source) => <a key={source} href={source} target="_blank" rel="noreferrer" className="text-xs font-semibold text-[#2f61c5] hover:underline">Official source</a>)}</div> : null}</div>)}</div> : <div className="mt-5 rounded-lg border border-dashed border-[#cad4de] p-8 text-center text-sm text-[#718198]">Save this life event to generate the current action list.</div>}<p className="mt-5 border-t border-[#e5eaee] pt-4 text-xs leading-5 text-[#718198]">{transition.disclaimer}</p></section></div></>;
}

function QueueView({ applicants, onOpen }: { applicants: Applicant[]; onOpen: (applicant: Applicant) => void }) {
  const reviewReady = applicants.filter((item) => item.reliability >= 75 && item.score !== null).length;
  const needsReview = applicants.filter((item) => item.score !== null && item.reliability < 75).length;
  const needsEvidence = applicants.filter((item) => item.score === null).length;

  return <>
    <SectionHeading eyebrow="Lender workspace" title="Applications to review" detail="Compare submitted applications before making a lending decision. The queue shows evidence readiness; it never approves or declines an application." />
    <section className="mb-6 rounded-xl border border-[#dbe3ea] bg-white p-5 sm:p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div><p className="text-sm font-semibold text-[#182b3a]">Decision context</p><p className="mt-1 max-w-2xl text-sm leading-6 text-[#637388]">Open an application to inspect the product-specific score, requested amount, evidence coverage, and reasons behind each result.</p></div>
        <span className="inline-flex w-fit items-center gap-2 rounded-full border border-[#cbe5dc] bg-[#eef9f5] px-3 py-1.5 text-xs font-semibold text-[#176c5e]"><span className="size-2 rounded-full bg-[#16836d]" /> Evidence-linked review</span>
      </div>
    </section>
    <div className="mb-6 grid gap-4 sm:grid-cols-3"><Metric label="Review ready" value={String(reviewReady)} note="Records meet the review threshold. This is not an approval or lending outcome." /><Metric label="Needs review" value={String(needsReview)} note="A score is available, but evidence coverage needs closer review." /><Metric label="Evidence needed" value={String(needsEvidence)} note="No score is available until usable records are added." /></div>
    <section className="overflow-hidden rounded-xl border border-[#dbe3ea] bg-white"><div className="overflow-x-auto"><table className="w-full min-w-[980px] text-left text-sm"><thead className="bg-[#f5f8fa] text-xs uppercase tracking-wide text-[#65758a]"><tr><th className="px-5 py-3">Application</th><th className="px-4 py-3">Product</th><th className="px-4 py-3">Requested</th><th className="px-4 py-3">Score</th><th className="px-4 py-3"><span className="inline-flex items-center gap-1">Evidence strength <HelpTip label="Evidence strength">This reflects how complete the submitted records are, how much activity they cover, and how well separate sources support one another. It describes the evidence, not the accuracy of the system.</HelpTip></span></th><th className="px-4 py-3">Review status</th><th className="px-4 py-3 text-right">Open review</th></tr></thead><tbody>{applicants.map((applicant) => { const status = statusFor(applicant); return <tr key={applicant.id} onClick={() => onOpen(applicant)} className="cursor-pointer border-t border-[#edf0f3] transition hover:bg-[#f8fafb]"><td className="px-5 py-4"><div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-full bg-[#eaf0fb] text-xs font-bold text-[#2f61c5]">{initials(applicant.name)}</span><div><p className="font-semibold text-[#203445]">{applicant.name}</p><p className="mt-0.5 text-xs text-[#738298]">{applicant.id} · {applicant.corridor}</p></div></div></td><td className="px-4 py-4 font-medium text-[#34495c]">{productLabel(applicant.product)}</td><td className="px-4 py-4 font-medium tabular-nums text-[#34495c]">{formatMoney(applicant.requested_amount, applicant.currency)}</td><td className="px-4 py-4 font-semibold tabular-nums text-[#203445]">{applicant.score ?? "No score yet"}</td><td className="px-4 py-4">{applicant.score === null ? "—" : `${applicant.reliability}%`}</td><td className="px-4 py-4"><span className="inline-flex items-center gap-1"><span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${status.className}`}>{status.label}</span>{status.label === "Review ready" ? <HelpTip label="Review ready">The evidence pack is complete enough to inspect. It is not an approval or lending outcome.</HelpTip> : null}</span></td><td className="px-4 py-4 text-right"><span className="inline-flex items-center gap-1 font-semibold text-[#2f61c5]">Review <ChevronRight className="size-4" /></span></td></tr>})}</tbody></table></div></section>
  </>;
}

function CaseView({ applicant, evidence, score, onNavigate }: { applicant: Applicant; evidence: EvidenceResponse; score: ScoreResponse; onNavigate: (view: View) => void }) {
  const hasEvidence = score.assertion_count > 0 && score.reliability > 0;
  return <><SectionHeading eyebrow={`Lender review · ${applicant.id}`} title="Application review" detail={`${applicant.name} · ${applicant.corridor} · ${productLabel(score.product)} · Created ${formatDateTime(applicant.created_at)}`} /><div className="grid gap-5 lg:grid-cols-[1.25fr_0.75fr]"><section className="rounded-xl border border-[#dbe3ea] bg-white p-5"><div className="flex flex-col justify-between gap-5 sm:flex-row"><div><p className="text-xs font-bold uppercase tracking-wide text-[#718198]">Decision score</p><p className="mt-2 text-6xl font-semibold tracking-[-0.06em] text-[#182b3a]">{hasEvidence ? score.score : "—"}</p><span className={`mt-3 inline-flex rounded-full border px-3 py-1 text-sm font-semibold ${scoreBand(hasEvidence ? score.score : null).className}`}>{scoreBand(hasEvidence ? score.score : null).label}</span><p className="mt-3 text-sm font-medium text-[#637388]">{productLabel(score.product)} · {formatMoney(applicant.requested_amount, applicant.currency)} requested</p></div><div className="min-w-[240px] border-l border-[#e1e7ed] pl-5"><div className="flex items-center gap-1 text-xs font-bold uppercase tracking-wide text-[#718198]"><span>Evidence strength</span><HelpTip label="Evidence strength">This reflects how complete the submitted records are, how much of the activity they cover, and how well separate sources support one another. It describes the evidence, not the accuracy of the system.</HelpTip></div><p className="mt-2 text-3xl font-semibold">{hasEvidence ? `${score.reliability}%` : "Not available"}</p><Progress value={hasEvidence ? score.reliability : 0} className="mt-3 h-2" /><p className="mt-2 text-sm text-[#617087]">{hasEvidence ? reliabilityBand(score.reliability) : "Awaiting records"}</p></div></div><div className="mt-6 grid grid-cols-3 gap-4 border-t border-[#e3e8ed] pt-5"><Metric label="Source records" value={String(evidence.assertion_count)} note="Rows submitted across the applicant's connected sources." /><Metric label="Unique activity" value={String(evidence.unique_event_count)} note="Repeated observations describing the same activity are counted once." /><Metric label="Corroborated" value={String(evidence.corroborated_count)} note="Activity supported by more than one source." /></div></section><aside className="rounded-xl bg-[#182b3a] p-5 text-white"><p className="text-xs font-bold uppercase tracking-wide text-[#9fb1c2]">Review path</p><h2 className="mt-3 text-xl font-semibold">{hasEvidence ? "Inspect reasons and records" : "Request more evidence"}</h2><p className="mt-2 text-sm leading-6 text-[#d4dde5]">{hasEvidence ? "Move from the headline score into the product-specific criteria and source coverage." : "The application does not yet have enough usable records for a score."}</p><Button onClick={() => onNavigate(hasEvidence ? "score" : "evidence")} className="mt-5 w-full bg-white text-[#182b3a] hover:bg-[#edf2f5]">{hasEvidence ? "Review decision score" : "Review evidence"} <ArrowRight /></Button></aside></div><div className="mt-5 grid gap-5 lg:grid-cols-2"><section className="rounded-xl border border-[#dbe3ea] bg-white p-5"><h2 className="font-semibold text-[#182b3a]">Application details</h2><dl className="mt-4 grid gap-4 sm:grid-cols-2">{[["Applicant", applicant.name, UserRound], ["Employment", applicant.employment ?? "Not provided", BriefcaseBusiness], ["Requested amount", formatMoney(applicant.requested_amount, applicant.currency), CircleDollarSign], ["Residency", applicant.residency ?? "Not provided", Landmark], ["Product", productLabel(score.product), WalletCards]].map(([label, value, Icon]) => <div key={String(label)} className="flex gap-3 border-t border-[#edf0f3] pt-3"><Icon className="mt-0.5 size-4 text-[#2f61c5]" /><div><dt className="text-xs font-bold uppercase tracking-wide text-[#8190a3]">{String(label)}</dt><dd className="mt-1 text-sm font-medium text-[#34495c]">{String(value)}</dd></div></div>)}</dl></section><section className="rounded-xl border border-[#dbe3ea] bg-white p-5"><div className="flex items-center gap-1"><h2 className="font-semibold text-[#182b3a]">Evidence coverage</h2><HelpTip label="Evidence coverage">This shows which connected sources have contributed records to the application review.</HelpTip></div><div className="mt-4 space-y-3">{evidence.sources.slice(0, 5).map((source) => <div key={source.id} className="flex items-center justify-between rounded-md bg-[#f7f9fa] px-3 py-2.5"><span className="text-sm font-medium">{evidenceTypeLabel(source.source_type)}</span><span className="text-xs text-[#718198]">{source.assertion_count} records</span></div>)}{!evidence.sources.length ? <p className="rounded-md bg-[#f7f9fa] p-4 text-sm text-[#718198]">No connected sources.</p> : null}</div><Button onClick={() => onNavigate("evidence")} variant="outline" className="mt-4 w-full border-[#cad4de]">Open full evidence review <ArrowRight /></Button></section></div></>;
}

export default function Home() {
  const [mode, setMode] = useState<Mode>("applicant");
  const [view, setView] = useState<View>("home");
  const [mobileNav, setMobileNav] = useState(false);
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [applicants, setApplicants] = useState<Applicant[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Applicant | null>(null);
  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null);
  const [score, setScore] = useState<ScoreResponse | null>(null);
  const [transition, setTransition] = useState<TransitionResponse | null>(null);
  const [product, setProduct] = useState<ProductType>("personal-loan");
  const [loading, setLoading] = useState(true);
  const [caseLoading, setCaseLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scoreRequestRef = useRef(0);

  const loadCase = useCallback(async (id: string, selectedProduct?: ProductType) => {
    setCaseLoading(true);
    try {
      const applicant = await creditPassportApi.getApplicant(id);
      const nextProduct = selectedProduct ?? applicant.product;
      const [nextEvidence, nextScore, nextTransition] = await Promise.all([creditPassportApi.getEvidence(id), creditPassportApi.getScore(id, nextProduct), creditPassportApi.getTransition(id)]);
      setSelected(applicant); setSelectedId(id); setProduct(nextProduct); setEvidence(nextEvidence); setScore(nextScore); setTransition(nextTransition);
    } catch (cause) { setError(errorMessage(cause)); } finally { setCaseLoading(false); }
  }, []);

  const bootstrap = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [nextConfig, nextApplicants] = await Promise.all([creditPassportApi.getConfig(), creditPassportApi.listApplicants()]);
      setConfig(nextConfig); setApplicants(nextApplicants);
      if (nextApplicants.length) await loadCase(nextApplicants[0].id);
      else { setSelectedId(null); setSelected(null); setEvidence(null); setScore(null); setTransition(null); }
    } catch (cause) { setError(errorMessage(cause)); } finally { setLoading(false); }
  }, [loadCase]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => void bootstrap());
    return () => window.cancelAnimationFrame(frame);
  }, [bootstrap]);
  useEffect(() => { window.scrollTo({ top: 0, behavior: "auto" }); }, [view, mode]);

  async function created(applicant: Applicant) {
    setApplicants((current) => [applicant, ...current.filter((item) => item.id !== applicant.id)]);
    await loadCase(applicant.id, applicant.product);
    setMode("applicant"); setView("home");
  }
  function navigate(next: View) { setView(next); setMobileNav(false); }
  function switchMode(next: Mode) { setMode(next); setView(next === "applicant" ? "home" : "queue"); setMobileNav(false); }
  async function refreshCase() {
    if (!selectedId) return;
    await loadCase(selectedId, product);
    const refreshed = await creditPassportApi.listApplicants();
    setApplicants(refreshed);
  }
  async function changeProduct(next: ProductType) {
    if (next === product) return;
    const requestId = scoreRequestRef.current + 1;
    scoreRequestRef.current = requestId;
    setProduct(next);
    if (!selectedId) return;
    setCaseLoading(true);
    try {
      const nextScore = await creditPassportApi.getScore(selectedId, next);
      if (requestId === scoreRequestRef.current) setScore(nextScore);
    } catch (cause) {
      if (requestId === scoreRequestRef.current) setError(errorMessage(cause));
    } finally {
      if (requestId === scoreRequestRef.current) setCaseLoading(false);
    }
  }
  const nav = mode === "applicant" ? navApplicant : navLender;
  const evidencePeriod = useMemo(() => {
    if (!evidence?.sources.length) return "No evidence period";
    const starts = evidence.sources.map((source) => source.period_start).sort();
    const ends = evidence.sources.map((source) => source.period_end).sort();
    return `${formatDate(starts[0])} – ${formatDate(ends[ends.length - 1])}`;
  }, [evidence]);

  if (loading) return <TooltipProvider delayDuration={140}><main className="grid min-h-screen place-items-center bg-[#f5f7f8]"><div className="text-center"><LoaderCircle className="mx-auto size-8 animate-spin text-[#2f61c5]" /><p className="mt-4 text-sm font-medium text-[#52657a]">Connecting to Credit Passport…</p></div></main></TooltipProvider>;
  if (error && !config) return <TooltipProvider delayDuration={140}><main className="grid min-h-screen place-items-center bg-[#f5f7f8] p-6"><section className="max-w-lg rounded-xl border border-rose-200 bg-white p-7 text-center"><AlertTriangle className="mx-auto size-8 text-rose-600" /><h1 className="mt-4 text-xl font-semibold text-[#182b3a]">The API is not available</h1><p className="mt-2 text-sm leading-6 text-[#637388]">{error}</p><Button onClick={() => void bootstrap()} className="mt-5 bg-[#2f61c5] hover:bg-[#244fa5]"><RefreshCw /> Retry connection</Button></section></main></TooltipProvider>;

  return (
    <TooltipProvider delayDuration={140}>
      <main className="min-h-screen bg-[#f5f7f8] text-[#263a4b]">
      {mobileNav ? <button aria-label="Close navigation" className="fixed inset-0 z-30 bg-[#0d1c27]/45 lg:hidden" onClick={() => setMobileNav(false)} /> : null}
      <aside className={`fixed inset-y-0 left-0 z-40 w-[236px] border-r border-[#243b4b] bg-[#182b3a] px-3 py-4 text-white transition-transform lg:translate-x-0 ${mobileNav ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="flex h-full flex-col"><div className="flex items-center justify-between px-2 pb-5"><div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-lg bg-[#2f61c5] font-bold">CP</span><div><p className="font-semibold leading-4">Credit Passport</p><p className="mt-1 text-[11px] text-[#9eb0bf]">{mode === "applicant" ? "My passport" : "Lender workspace"}</p></div></div><Button size="icon-sm" variant="ghost" className="lg:hidden" onClick={() => setMobileNav(false)}><X /></Button></div>
          <div className="mb-4 grid grid-cols-2 rounded-lg bg-white/7 p-1"><button onClick={() => switchMode("applicant")} className={`rounded-md px-2 py-2 text-xs font-semibold ${mode === "applicant" ? "bg-white text-[#182b3a]" : "text-[#b8c6d1]"}`}>Applicant</button><button onClick={() => switchMode("lender")} className={`rounded-md px-2 py-2 text-xs font-semibold ${mode === "lender" ? "bg-white text-[#182b3a]" : "text-[#b8c6d1]"}`}>Lender</button></div>
          <nav aria-label="Primary navigation" className="space-y-1">{nav.map((item) => { const Icon = item.icon; return <button key={item.id} onClick={() => navigate(item.id)} disabled={!selected && item.id !== "queue"} className={`flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-35 ${view === item.id ? "bg-white text-[#182b3a]" : "text-[#c5d0d9] hover:bg-white/8 hover:text-white"}`}><Icon className="size-4" />{item.label}</button>; })}</nav>
          <div className="mt-auto rounded-lg border border-white/10 bg-white/5 p-3"><div className="flex items-center gap-2 text-xs font-semibold text-[#dce5eb]"><span className="size-2 rounded-full bg-[#42c8a8]" /> API connected</div></div>
        </div>
      </aside>
      <div className="lg:pl-[236px]"><header className="sticky top-0 z-20 flex min-h-[68px] items-center justify-between border-b border-[#dbe3e9] bg-white/95 px-4 backdrop-blur sm:px-6 lg:px-8"><div className="flex items-center gap-3"><Button size="icon" variant="ghost" className="lg:hidden" onClick={() => setMobileNav(true)}><Menu /></Button><div><p className="text-xs font-semibold uppercase tracking-[0.1em] text-[#8090a4]">{mode === "lender" ? "Selected application" : "Evidence period"}</p><p className="text-sm font-semibold text-[#34495c]">{mode === "lender" && selected ? `${selected.name} · ${productLabel(product)}` : evidencePeriod}</p></div></div><div className="flex items-center gap-3">{mode === "applicant" ? <CreateApplicantDialog compact onCreated={created} /> : null}{selected ? <><select aria-label={mode === "lender" ? "Selected application" : "Selected applicant"} className="hidden h-9 max-w-[230px] rounded-md border border-[#d4dde5] bg-white px-3 text-sm sm:block" value={selected.id} onChange={(e) => void loadCase(e.target.value)}>{applicants.map((applicant) => <option key={applicant.id} value={applicant.id}>{applicant.name} · {applicant.id}</option>)}</select><span className="grid size-9 place-items-center rounded-full bg-[#eaf0fb] text-xs font-bold text-[#2f61c5]">{initials(selected.name)}</span></> : null}</div></header>
        <div className="mx-auto max-w-[1380px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{error ? <div className="mb-5 flex items-start justify-between gap-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800"><span>{error}</span><button onClick={() => setError(null)}><X className="size-4" /></button></div> : null}{caseLoading ? <div className="mb-4 flex items-center gap-2 text-sm text-[#617087]"><LoaderCircle className="size-4 animate-spin" /> {mode === "lender" ? "Loading application review…" : "Refreshing passport…"}</div> : null}{view === "queue" ? <QueueView applicants={applicants} onOpen={(applicant) => { void loadCase(applicant.id); setView("case"); }} /> : !selected || !config || !evidence || !score || !transition ? <EmptyWorkspace onCreated={created} /> : view === "home" ? <HomeView applicant={selected} evidence={evidence} score={score} config={config} onNavigate={navigate} onRefresh={() => void refreshCase()} /> : view === "evidence" ? <EvidenceView applicant={selected} evidence={evidence} config={config} onRefresh={() => void refreshCase()} audience={mode} /> : view === "score" ? <ScoreView key={`${score.applicant_id}:${product}`} score={score} product={product} onProductChange={(next) => void changeProduct(next)} audience={mode} /> : view === "transition" ? <TransitionView applicant={selected} transition={transition} onSaved={setTransition} /> : <CaseView applicant={selected} evidence={evidence} score={score} onNavigate={navigate} />}</div>
      </div>
      {mode === "applicant" ? <GuidePanel applicant={selected} transition={transition} /> : null}
      </main>
    </TooltipProvider>
  );
}
