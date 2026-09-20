"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BadgeCheck,
  BarChart3,
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
  type ModelValidationResponse,
  type ProductType,
  type ScoreResponse,
  type TransitionEvent,
  type TransitionResponse,
} from "@/lib/credit-passport";

type Mode = "applicant" | "lender";
type View = "home" | "evidence" | "score" | "transition" | "guide" | "queue" | "case" | "validation";

const navApplicant = [
  { id: "home" as View, label: "Home", icon: LayoutList },
  { id: "evidence" as View, label: "My evidence", icon: Database },
  { id: "score" as View, label: "My score", icon: Gauge },
  { id: "transition" as View, label: "Moving or returning", icon: Waypoints },
  { id: "guide" as View, label: "Guide", icon: MessageCircle },
];

const navLender = [
  { id: "queue" as View, label: "Review queue", icon: Users },
  { id: "case" as View, label: "Applicant", icon: UserRound },
  { id: "evidence" as View, label: "Evidence", icon: Database },
  { id: "score" as View, label: "Score", icon: Gauge },
  { id: "guide" as View, label: "Guide", icon: MessageCircle },
  { id: "validation" as View, label: "Score quality", icon: BarChart3 },
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
  return { label: "Check evidence", className: "border-orange-200 bg-orange-50 text-orange-800" };
}

function scoreBand(score: number | null): { label: string; className: string } {
  if (score === null) return { label: "Not scored", className: "border-slate-300 bg-slate-100 text-slate-700" };
  if (score >= 75) return { label: "Strong", className: "border-teal-200 bg-teal-50 text-teal-800" };
  if (score >= 60) return { label: "Review", className: "border-amber-200 bg-amber-50 text-amber-800" };
  return { label: "Limited", className: "border-rose-200 bg-rose-50 text-rose-800" };
}

function HelpTip({ label, children, className = "text-[#6f8093]" }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`More about ${label}`}
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

function UploadStatementDialog({ applicant, config, onUploaded }: { applicant: Applicant; config: ConfigResponse; onUploaded: () => void }) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [provider, setProvider] = useState("");
  const [sourceType, setSourceType] = useState("bank-statement");
  const [currency, setCurrency] = useState(applicant.currency);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setPending(true);
    setError(null);
    setResult(null);
    try {
      const response = await creditPassportApi.uploadStatement(applicant.id, file, { provider, sourceType, currency });
      setResult(`${response.parsed_rows.toLocaleString("en-IN")} rows accepted and scored.`);
      onUploaded();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setPending(false);
    }
  }

  function close(next: boolean) {
    setOpen(next);
    if (!next) {
      setResult(null);
      setError(null);
      setFile(null);
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogTrigger asChild><Button className="bg-[#2f61c5] hover:bg-[#244fa5]"><Upload /> Add complete statement</Button></DialogTrigger>
      <DialogContent className="max-w-lg">
        <form onSubmit={submit}>
          <DialogHeader><DialogTitle>Add a complete statement</DialogTitle><DialogDescription className="sr-only">Upload a CSV financial statement.</DialogDescription></DialogHeader>
          {result ? (
            <div className="mt-5 rounded-lg border border-teal-200 bg-teal-50 p-5"><FileCheck2 className="size-7 text-teal-700" /><p className="mt-3 font-semibold text-teal-900">Statement processed</p><p className="mt-1 text-sm text-teal-800">{result}</p></div>
          ) : (
            <div className="mt-5 space-y-4">
              <label><span className="mb-1.5 block text-sm font-semibold">Provider</span><input required placeholder="Bank or source name" className={inputClass} value={provider} onChange={(e) => setProvider(e.target.value)} /></label>
              <div className="grid gap-4 sm:grid-cols-2">
                <label><span className="mb-1.5 block text-sm font-semibold">Evidence type</span><select className={inputClass} value={sourceType} onChange={(e) => setSourceType(e.target.value)}>{config.evidence_types.map((type) => <option key={type} value={type}>{evidenceTypeLabel(type)}</option>)}</select></label>
                <label><span className="mb-1.5 block text-sm font-semibold">Currency</span><input required maxLength={3} className={inputClass} value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} /></label>
              </div>
              <label><span className="mb-1.5 block text-sm font-semibold">CSV statement</span><input required type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full rounded-md border border-[#ccd6df] bg-[#f8fafb] p-3 text-sm file:mr-4 file:rounded-md file:border-0 file:bg-[#eaf0fb] file:px-3 file:py-2 file:font-semibold file:text-[#2f61c5]" /><span className="mt-2 block text-xs leading-5 text-[#718198]">Required columns: date and amount. PDF and XLSX are rejected rather than silently accepted.</span></label>
            </div>
          )}
          {error ? <p className="mt-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p> : null}
          <DialogFooter className="mt-6">{!result ? <Button type="submit" disabled={!file || !provider || pending} className="bg-[#2f61c5] hover:bg-[#244fa5]">{pending ? <LoaderCircle className="animate-spin" /> : <Upload />} {pending ? "Processing…" : "Process statement"}</Button> : <Button type="button" onClick={() => close(false)}>Done</Button>}</DialogFooter>
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

function EvidenceView({ applicant, evidence, config, onRefresh }: { applicant: Applicant; evidence: EvidenceResponse; config: ConfigResponse; onRefresh: () => void }) {
  const visibleEvents = evidence.events.slice(0, 50);
  const humanize = (value: string) => value.replaceAll("_", " ").replaceAll("-", " ");
  return <><SectionHeading eyebrow={applicant.id} title="Financial records" detail="Sources are checked for completeness and matching activity is counted once. This keeps the score from counting the same behaviour twice." action={<UploadStatementDialog applicant={applicant} config={config} onUploaded={onRefresh} />} /><div className="mb-6 grid gap-4 sm:grid-cols-3"><Metric label="Records received" value={String(evidence.assertion_count)} note={`Across ${evidence.sources.length} connected source${evidence.sources.length === 1 ? "" : "s"}.`} /><Metric label="Activity records" value={String(evidence.unique_event_count)} note="Repeated rows that describe the same activity are counted once." /><Metric label="Matching records" value={String(evidence.corroborated_count)} note="Records from more than one source that support the same activity." /></div><section className="rounded-xl border border-[#dbe3ea] bg-white"><div className="border-b border-[#e5eaee] px-5 py-4"><h2 className="font-semibold text-[#182b3a]">Connected sources</h2></div>{evidence.sources.length ? <div className="grid md:grid-cols-2">{evidence.sources.map((source) => <div key={source.id} className="border-b border-r border-[#edf0f3] p-5"><div className="flex items-start justify-between gap-4"><div><p className="font-semibold text-[#263a4b]">{evidenceTypeLabel(source.source_type)}</p><p className="mt-1 text-sm text-[#718198]">{source.provider}</p></div><BadgeCheck aria-label="Source connected" className="size-5 text-[#008b78]" /></div><div className="mt-5 grid grid-cols-3 gap-3 text-sm"><div><p className="font-semibold tabular-nums">{source.assertion_count}</p><p className="text-xs text-[#8290a2]">records</p></div><div><p className="font-semibold tabular-nums">{source.unique_event_count}</p><p className="text-xs text-[#8290a2]">activity</p></div><div><p className="font-semibold tabular-nums">{source.corroborated_count}</p><p className="text-xs text-[#8290a2]">matches</p></div></div><p className="mt-4 text-xs text-[#8290a2]">Covers {formatDate(source.period_start)} – {formatDate(source.period_end)}</p></div>)}</div> : <div className="p-10 text-center text-[#718198]">No connected sources yet.</div>}</section><section className="mt-6 overflow-hidden rounded-xl border border-[#dbe3ea] bg-white"><div className="flex items-center justify-between border-b border-[#e5eaee] px-5 py-4"><h2 className="font-semibold text-[#182b3a]">Activity</h2><p className="text-xs font-medium text-[#718198]">Showing {visibleEvents.length} of {evidence.events.length}</p></div><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead className="bg-[#f5f8fa] text-xs uppercase tracking-wide text-[#718198]"><tr><th className="px-5 py-3">Date</th><th className="px-4 py-3">Activity</th><th className="px-4 py-3">Amount</th><th className="px-4 py-3">Category</th><th className="px-4 py-3">Source match</th></tr></thead><tbody>{visibleEvents.map((event) => <tr key={event.id} className="border-t border-[#edf0f3]"><td className="px-5 py-4 text-[#6d7b8e]">{formatDate(event.date)}</td><td className="px-4 py-4"><p className="font-semibold capitalize text-[#263a4b]">{humanize(event.event_type)}</p><p className="mt-1 text-xs text-[#7f8da0]">{event.reference ?? event.id}</p></td><td className="px-4 py-4 font-medium tabular-nums">{formatMoney(event.amount, event.currency)}</td><td className="px-4 py-4 capitalize">{humanize(event.construct)}</td><td className="px-4 py-4 text-xs text-[#52657a]">{event.source_ids.length > 1 ? `${event.source_ids.length} matching sources` : "One source"}</td></tr>)}{!visibleEvents.length ? <tr><td colSpan={5} className="px-5 py-12 text-center text-[#718198]">No activity yet.</td></tr> : null}</tbody></table></div></section></>;
}

function ScoreView({
  score,
  product,
  onProductChange,
}: {
  score: ScoreResponse;
  product: ProductType;
  onProductChange: (product: ProductType) => void;
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
  const colors = ["#2f61c5", "#008b78", "#cc7515", "#7051b8", "#49718a", "#98721d", "#5261a8"];
  const domainLabels: Record<string, string> = {
    commitment: "Payment history",
    income: "Income stability",
    capacity: "Room for new payments",
    liquidity: "Cash buffer",
    shock: "Financial buffer",
    momentum: "Income trend",
    cross_border: "Cross-border consistency",
  };
  const decisionScore = score.score;
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
      eyebrow="Credit Passport"
      title="Overall credit score"
      action={<select className={`${inputClass} w-[190px]`} value={product} onChange={(e) => onProductChange(e.target.value as ProductType)}><option value="personal-loan">Personal loan</option><option value="credit-card">Credit card</option><option value="student-loan">Student loan</option></select>}
    />
    <div className="grid gap-5 lg:grid-cols-[280px_1fr]">
      <section className="rounded-xl bg-[#182b3a] p-6 text-white">
        <p className="text-xs font-bold uppercase tracking-[0.12em] text-[#9fb1c2]">{productLabel(product)}</p>
        <div className="mt-4 flex items-end gap-2"><span className="text-6xl font-semibold tabular-nums tracking-[-0.06em]">{hasEvidence ? decisionScore : "—"}</span>{hasEvidence ? <span className="mb-2 text-lg text-[#aebdca]">/100</span> : null}</div>
        <span className={`mt-4 inline-flex rounded-full border px-3 py-1 text-sm font-semibold ${scoreBand(hasEvidence ? decisionScore : null).className}`}>{scoreBand(hasEvidence ? decisionScore : null).label}</span>
        <div className="mt-6 grid grid-cols-2 gap-4 border-t border-white/15 pt-5">
          <div>
            <div className="flex items-center gap-1 text-xs uppercase tracking-wide text-[#aebdca]"><span>90-day payment risk</span><HelpTip label="90-day payment risk" className="text-[#aebdca] hover:bg-white/10 hover:text-white">The estimated chance of a missed payment or adverse restructure in the next 90 days, based on the records provided.</HelpTip></div>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{challengerLoading ? "…" : riskPercent === null ? "—" : `${riskPercent.toFixed(1)}%`}</p>
          </div>
          <div>
            <div className="flex items-center gap-1 text-xs uppercase tracking-wide text-[#aebdca]"><span>Evidence strength</span><HelpTip label="Evidence strength" className="text-[#aebdca] hover:bg-white/10 hover:text-white">This reflects how complete the uploaded records are, how much of the activity they cover, and how well separate sources support one another. It describes the records, not the accuracy of the system.</HelpTip></div>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{hasEvidence ? `${score.reliability}%` : "—"}</p>
          </div>
        </div>
      </section>
      <section className="overflow-hidden rounded-xl border border-[#dbe3ea] bg-white">
        <div className="grid min-w-[520px] grid-cols-[minmax(260px,1fr)_100px_90px] gap-2 border-b border-[#dbe3ea] bg-[#f5f8fa] px-4 py-3 text-xs font-bold uppercase tracking-wide text-[#718198]"><span>What we looked at</span><span>Result</span><span className="text-right">Weight</span></div>
        <div className="overflow-x-auto">{score.domains.map((domain, index) => { const label = domainLabels[domain.key] ?? domain.label; return <div key={domain.key} className="grid min-w-[520px] grid-cols-[minmax(260px,1fr)_100px_90px] items-center gap-2 border-b border-[#edf0f3] px-4 py-4 last:border-b-0"><div><div className="flex items-center justify-between gap-3"><span className="font-semibold text-[#263a4b]">{label}</span><HelpTip label={`${label} evidence coverage`}>Evidence coverage is {domain.reliability}%. {domain.reason_codes[0]?.message ?? "There is not enough supporting information for this area yet."}</HelpTip></div><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#e7edf2]"><div className="h-full rounded-full" style={{ width: `${domain.adjusted}%`, backgroundColor: colors[index % colors.length] }} /></div></div><span className="font-semibold tabular-nums">{domain.adjusted.toFixed(1)}</span><span className="text-right font-semibold tabular-nums text-[#2f61c5]">{domain.weight}%</span></div>; })}</div>
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

function GuideView({ applicant, transition }: { applicant: Applicant | null; transition: TransitionResponse | null }) {
  const [prompts, setPrompts] = useState<GuidePrompt[]>([]);
  const [responses, setResponses] = useState<GuideResponse[]>([]);
  const [query, setQuery] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionId = useMemo(() => `guide-${applicant?.id ?? "visitor"}`, [applicant?.id]);

  useEffect(() => {
    let active = true;
    void creditPassportApi.getGuidePrompts().then((value) => {
      if (active) setPrompts(value);
    }).catch(() => {
      if (active) setPrompts([]);
    });
    return () => { active = false; };
  }, []);

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
    <SectionHeading eyebrow="Transition guide" title="Ask about moving or returning" detail="Get practical guidance about India account choices, residency, KYC and related steps. Answers are linked to official sources." />
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_280px]">
      <section className="overflow-hidden rounded-xl border border-[#dbe3ea] bg-white">
        <div className="border-b border-[#e5eaee] p-5 sm:p-6">
          <h2 className="text-lg font-semibold text-[#182b3a]">What do you need to know?</h2>
          <p className="mt-1 text-sm text-[#68798c]">Choose a question or write your own.</p>
          {prompts.length ? <div className="mt-4 flex flex-wrap gap-2">{prompts.map((prompt) => <button key={prompt.id} type="button" onClick={() => void ask(prompt.query, prompt.intent)} disabled={pending} className="rounded-full border border-[#cbd8e6] bg-white px-3 py-2 text-left text-sm font-medium text-[#2f61c5] transition hover:border-[#2f61c5] hover:bg-[#f3f6fc] disabled:cursor-not-allowed disabled:opacity-50">{prompt.label}</button>)}</div> : null}
        </div>
        <div className="space-y-5 p-5 sm:p-6">
          {responses.map((response, index) => <article key={`${response.query}-${index}`} className="space-y-3">
            <div className="ml-auto max-w-[90%] rounded-lg bg-[#eaf0fb] px-4 py-3 text-sm text-[#203f82]"><p className="text-[11px] font-bold uppercase tracking-wide text-[#5872a6]">Your question</p><p className="mt-1 leading-6">{response.query}</p></div>
            <div className="max-w-[95%] rounded-lg border border-[#dbe3ea] bg-white px-4 py-4"><div className="flex items-center gap-2"><p className="text-[11px] font-bold uppercase tracking-wide text-[#7051b8]">Guide</p>{response.abstained ? <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-800">Outside current scope</span> : null}</div><p className="mt-2 whitespace-pre-line text-sm leading-6 text-[#34495c]">{response.answer}</p>{response.bullets.length ? <ul className="mt-3 space-y-2 pl-5 text-sm leading-6 text-[#34495c]">{response.bullets.map((bullet) => <li key={bullet} className="list-disc">{bullet}</li>)}</ul> : null}{response.citations.length ? <div className="mt-4 border-t border-[#edf0f3] pt-3"><p className="text-xs font-bold uppercase tracking-wide text-[#718198]">Sources</p><div className="mt-2 space-y-2">{response.citations.map((citation) => <a key={citation.id} href={citation.url} target="_blank" rel="noreferrer" className="block rounded-md border border-[#e1e7ed] px-3 py-2 text-sm transition hover:border-[#2f61c5] hover:bg-[#f8fafc]"><span className="font-semibold text-[#2f61c5]">{citation.title}</span><span className="mt-0.5 block text-xs text-[#718198]">{citation.publisher}{citation.locator ? ` · ${citation.locator}` : ""}</span></a>)}</div></div> : null}{response.follow_up_questions.length ? <div className="mt-4 border-t border-[#edf0f3] pt-3"><p className="text-xs font-bold uppercase tracking-wide text-[#718198]">You could also ask</p><div className="mt-2 flex flex-wrap gap-2">{response.follow_up_questions.map((followUp) => <button key={followUp} type="button" onClick={() => void ask(followUp)} disabled={pending} className="rounded-full border border-[#d5dde6] px-3 py-1.5 text-left text-xs font-medium text-[#2f61c5] hover:border-[#2f61c5] disabled:opacity-50">{followUp}</button>)}</div></div> : null}<p className="mt-4 border-t border-[#edf0f3] pt-3 text-xs leading-5 text-[#718198]">{response.disclaimer}</p></div>
          </article>)}
          {error ? <p className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p> : null}
        </div>
        <form onSubmit={submit} className="border-t border-[#e5eaee] bg-[#f8fafb] p-5 sm:p-6"><label htmlFor="guide-question" className="sr-only">Ask the guide</label><textarea id="guide-question" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={4000} rows={3} placeholder="For example: What should I review before returning to India?" className="w-full resize-y rounded-md border border-[#cbd6df] bg-white px-3 py-3 text-sm leading-6 text-[#263a4b] outline-none focus:border-[#2f61c5] focus:ring-2 focus:ring-[#2f61c5]/15" /><div className="mt-3 flex justify-end"><Button type="submit" disabled={!query.trim() || pending} className="shrink-0 bg-[#2f61c5] hover:bg-[#244fa5]">{pending ? <LoaderCircle className="animate-spin" /> : <Send />} {pending ? "Checking…" : "Ask guide"}</Button></div></form>
      </section>
      <aside className="h-fit rounded-xl border border-[#dbe3ea] bg-white p-5"><h2 className="font-semibold text-[#182b3a]">Guide scope</h2><p className="mt-2 text-sm leading-6 text-[#617087]">Use it for questions about:</p><ul className="mt-4 space-y-3 text-sm text-[#34495c]"><li className="flex gap-2"><Check className="mt-0.5 size-4 shrink-0 text-[#008b78]" />NRI and NRO account choices</li><li className="flex gap-2"><Check className="mt-0.5 size-4 shrink-0 text-[#008b78]" />Moving abroad or returning to India</li><li className="flex gap-2"><Check className="mt-0.5 size-4 shrink-0 text-[#008b78]" />Residency, KYC, FATCA and CRS</li></ul><p className="mt-5 border-t border-[#edf0f3] pt-4 text-xs leading-5 text-[#718198]">If a question falls outside the available sources, the guide will say so.</p></aside>
    </div>
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
  return <><SectionHeading eyebrow="Applications" title="Review queue" detail="Applications awaiting a lending decision." /><div className="mb-6 grid gap-4 sm:grid-cols-3"><Metric label="Review ready" value={String(applicants.filter((item) => item.reliability >= 75 && item.score !== null).length)} note="Records are complete enough for a confident review. This status describes the records, not a lending outcome." /><Metric label="Check evidence" value={String(applicants.filter((item) => item.score !== null && item.reliability < 75).length)} note="A score is available, but the records need a closer look." /><Metric label="Evidence needed" value={String(applicants.filter((item) => item.score === null).length)} note="No score is available until usable records are added." /></div><section className="overflow-hidden rounded-xl border border-[#dbe3ea] bg-white"><div className="overflow-x-auto"><table className="w-full min-w-[820px] text-left text-sm"><thead className="bg-[#f5f8fa] text-xs uppercase tracking-wide text-[#65758a]"><tr><th className="px-5 py-3">Applicant</th><th className="px-4 py-3">Product</th><th className="px-4 py-3">Score</th><th className="px-4 py-3"><span className="inline-flex items-center gap-1">Evidence strength <HelpTip label="Evidence strength">This reflects how complete the uploaded records are, how much of the activity they cover, and how well separate sources support one another. It describes the records, not the accuracy of the system.</HelpTip></span></th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Open</th></tr></thead><tbody>{applicants.map((applicant) => { const status = statusFor(applicant); return <tr key={applicant.id} onClick={() => onOpen(applicant)} className="cursor-pointer border-t border-[#edf0f3] transition hover:bg-[#f8fafb]"><td className="px-5 py-4"><div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-full bg-[#eaf0fb] text-xs font-bold text-[#2f61c5]">{initials(applicant.name)}</span><div><p className="font-semibold text-[#203445]">{applicant.name}</p><p className="mt-0.5 text-xs text-[#738298]">{applicant.id} · {applicant.corridor}</p></div></div></td><td className="px-4 py-4">{productLabel(applicant.product)}</td><td className="px-4 py-4 font-semibold tabular-nums">{applicant.score ?? "No score yet"}</td><td className="px-4 py-4">{applicant.score === null ? "—" : `${applicant.reliability}%`}</td><td className="px-4 py-4"><span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${status.className}`}>{status.label}</span></td><td className="px-4 py-4 text-right"><ChevronRight className="ml-auto size-4" /></td></tr>})}</tbody></table></div></section></>;
}

function CaseView({ applicant, evidence, score, onNavigate }: { applicant: Applicant; evidence: EvidenceResponse; score: ScoreResponse; onNavigate: (view: View) => void }) {
  const hasEvidence = score.assertion_count > 0 && score.reliability > 0;
  return <><SectionHeading eyebrow={applicant.id} title={applicant.name} detail={`${applicant.corridor} · ${productLabel(applicant.product)} · Created ${formatDateTime(applicant.created_at)}`} /><div className="grid gap-5 lg:grid-cols-[1.25fr_0.75fr]"><section className="rounded-xl border border-[#dbe3ea] bg-white p-5"><div className="flex flex-col justify-between gap-5 sm:flex-row"><div><p className="text-xs font-bold uppercase tracking-wide text-[#718198]">Passport score</p><p className="mt-2 text-6xl font-semibold tracking-[-0.06em] text-[#182b3a]">{hasEvidence ? score.score : "—"}</p><span className={`mt-3 inline-flex rounded-full border px-3 py-1 text-sm font-semibold ${scoreBand(hasEvidence ? score.score : null).className}`}>{scoreBand(hasEvidence ? score.score : null).label}</span></div><div className="min-w-[240px] border-l border-[#e1e7ed] pl-5"><div className="flex items-center gap-1 text-xs font-bold uppercase tracking-wide text-[#718198]"><span>Evidence strength</span><HelpTip label="Evidence strength">This reflects how complete the uploaded records are, how much of the activity they cover, and how well separate sources support one another. It describes the records, not the accuracy of the system.</HelpTip></div><p className="mt-2 text-3xl font-semibold">{hasEvidence ? `${score.reliability}%` : "Not available"}</p><Progress value={hasEvidence ? score.reliability : 0} className="mt-3 h-2" /><p className="mt-2 text-sm text-[#617087]">{hasEvidence ? reliabilityBand(score.reliability) : "Awaiting records"}</p></div></div><div className="mt-6 grid grid-cols-3 gap-4 border-t border-[#e3e8ed] pt-5"><Metric label="Records" value={String(evidence.assertion_count)} note="Source rows received for this applicant." /><Metric label="Activity" value={String(evidence.unique_event_count)} note="Repeated rows describing the same activity are counted once." /><Metric label="Matching records" value={String(evidence.corroborated_count)} note="Records from more than one source supporting the same activity." /></div></section><aside className="rounded-xl bg-[#182b3a] p-5 text-white"><p className="text-xs font-bold uppercase tracking-wide text-[#9fb1c2]">Next step</p><h2 className="mt-3 text-xl font-semibold">{hasEvidence ? "Inspect reasons and records" : "Request a complete statement"}</h2><p className="mt-2 text-sm leading-6 text-[#d4dde5]">{hasEvidence ? "Review the score and the records behind each result." : "The API has not received enough records to produce an applicant result."}</p><Button onClick={() => onNavigate(hasEvidence ? "score" : "evidence")} className="mt-5 w-full bg-white text-[#182b3a] hover:bg-[#edf2f5]">{hasEvidence ? "View score details" : "Open records"} <ArrowRight /></Button></aside></div><div className="mt-5 grid gap-5 lg:grid-cols-2"><section className="rounded-xl border border-[#dbe3ea] bg-white p-5"><h2 className="font-semibold text-[#182b3a]">Applicant profile</h2><dl className="mt-4 grid gap-4 sm:grid-cols-2">{[["Employment", applicant.employment ?? "Not provided", BriefcaseBusiness], ["Requested amount", formatMoney(applicant.requested_amount, applicant.currency), CircleDollarSign], ["Residency", applicant.residency ?? "Not provided", Landmark], ["Product", productLabel(applicant.product), WalletCards]].map(([label, value, Icon]) => <div key={String(label)} className="flex gap-3 border-t border-[#edf0f3] pt-3"><Icon className="mt-0.5 size-4 text-[#2f61c5]" /><div><dt className="text-xs font-bold uppercase tracking-wide text-[#8190a3]">{String(label)}</dt><dd className="mt-1 text-sm font-medium text-[#34495c]">{String(value)}</dd></div></div>)}</dl></section><section className="rounded-xl border border-[#dbe3ea] bg-white p-5"><div className="flex items-center gap-1"><h2 className="font-semibold text-[#182b3a]">Evidence coverage</h2><HelpTip label="Evidence coverage">This shows which connected sources have contributed records to the applicant’s profile.</HelpTip></div><div className="mt-4 space-y-3">{evidence.sources.slice(0, 5).map((source) => <div key={source.id} className="flex items-center justify-between rounded-md bg-[#f7f9fa] px-3 py-2.5"><span className="text-sm font-medium">{evidenceTypeLabel(source.source_type)}</span><span className="text-xs text-[#718198]">{source.assertion_count} records</span></div>)}{!evidence.sources.length ? <p className="rounded-md bg-[#f7f9fa] p-4 text-sm text-[#718198]">No connected sources.</p> : null}</div></section></div></>;
}

function metricNumber(metrics: Record<string, unknown> | null | undefined, path: string[]): number | null {
  let current: unknown = metrics;
  for (const key of path) { if (!current || typeof current !== "object" || !(key in current)) return null; current = (current as Record<string, unknown>)[key]; }
  return typeof current === "number" ? current : null;
}

function ValidationView({ validation, loading, onLoad }: { validation: ModelValidationResponse | null; loading: boolean; onLoad: () => void }) {
  useEffect(() => { if (!validation && !loading) onLoad(); }, [validation, loading, onLoad]);
  const metrics = validation?.metrics;
  const auc = metricNumber(metrics, ["metrics", "roc_auc"]);
  const pr = metricNumber(metrics, ["metrics", "pr_auc_average_precision"]);
  const brier = metricNumber(metrics, ["metrics", "brier"]);
  const ece = metricNumber(metrics, ["metrics", "expected_calibration_error_10_bins"]);
  const rows = metricNumber(metrics, ["rows", "total"]);
  const prevalence = metricNumber(metrics, ["test_prevalence"]);
  return <><SectionHeading eyebrow="Score quality" title="How the score performs" action={<Button variant="outline" onClick={onLoad} disabled={loading}><RefreshCw className={loading ? "animate-spin" : ""} /> Refresh</Button>} />{loading ? <div className="grid min-h-64 place-items-center"><LoaderCircle className="size-7 animate-spin text-[#2f61c5]" /></div> : validation?.status !== "available" ? <div className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-amber-900"><AlertTriangle /><p className="mt-3 font-semibold">Score quality is unavailable</p><p className="mt-1 text-sm">{validation?.message ?? "The API did not return score quality details."}</p></div> : <><div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"><Metric label="Ranking quality" value={auc?.toFixed(3) ?? "—"} note="How well higher-risk cases are ranked in the latest time period." /><Metric label="High-risk precision" value={pr?.toFixed(3) ?? "—"} note={prevalence === null ? "How well the check identifies higher-risk cases." : `Higher-risk cases make up ${(prevalence * 100).toFixed(1)}% of this group.`} /><Metric label="Probability accuracy" value={brier?.toFixed(3) ?? "—"} note="How close the predicted percentages are to outcomes. Lower is better." /><Metric label="Calibration gap" value={ece?.toFixed(3) ?? "—"} note="Difference between predicted and observed rates. Lower is better." /></div><section className="mt-6 overflow-hidden rounded-xl border border-[#dbe3ea] bg-white"><div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4"><div><p className="text-xs font-bold uppercase tracking-wide text-[#718198]">Records checked</p><p className="mt-2 text-lg font-semibold tabular-nums">{rows?.toLocaleString("en-IN") ?? "—"}</p></div><div><p className="text-xs font-bold uppercase tracking-wide text-[#718198]">What we check</p><p className="mt-2 text-sm font-semibold">30+ days late or a restructure within 90 days</p></div><div><p className="text-xs font-bold uppercase tracking-wide text-[#718198]">Time test</p><p className="mt-2 text-sm font-semibold">Earlier records tested against later records</p></div><div><p className="text-xs font-bold uppercase tracking-wide text-[#718198]">People kept separate</p><p className="mt-2 text-sm font-semibold text-[#008b78]">No person appears in more than one group</p></div></div></section></>}</>;
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
  const [validation, setValidation] = useState<ModelValidationResponse | null>(null);
  const [validationLoading, setValidationLoading] = useState(false);

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
    setProduct(next);
    if (!selectedId) return;
    setCaseLoading(true);
    try { setScore(await creditPassportApi.getScore(selectedId, next)); } catch (cause) { setError(errorMessage(cause)); } finally { setCaseLoading(false); }
  }
  const loadValidation = useCallback(async () => { setValidationLoading(true); try { setValidation(await creditPassportApi.getModelValidation()); } catch (cause) { setValidation({ status: "invalid", metrics: null, message: errorMessage(cause) }); } finally { setValidationLoading(false); } }, []);

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
        <div className="flex h-full flex-col"><div className="flex items-center justify-between px-2 pb-5"><div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-lg bg-[#2f61c5] font-bold">CP</span><div><p className="font-semibold leading-4">Credit Passport</p><p className="mt-1 text-[11px] text-[#9eb0bf]">{mode === "applicant" ? "My passport" : "Lender review"}</p></div></div><Button size="icon-sm" variant="ghost" className="lg:hidden" onClick={() => setMobileNav(false)}><X /></Button></div>
          <div className="mb-4 grid grid-cols-2 rounded-lg bg-white/7 p-1"><button onClick={() => switchMode("applicant")} className={`rounded-md px-2 py-2 text-xs font-semibold ${mode === "applicant" ? "bg-white text-[#182b3a]" : "text-[#b8c6d1]"}`}>Applicant</button><button onClick={() => switchMode("lender")} className={`rounded-md px-2 py-2 text-xs font-semibold ${mode === "lender" ? "bg-white text-[#182b3a]" : "text-[#b8c6d1]"}`}>Lender</button></div>
          <nav aria-label="Primary navigation" className="space-y-1">{nav.map((item) => { const Icon = item.icon; return <button key={item.id} onClick={() => navigate(item.id)} disabled={!selected && item.id !== "queue" && item.id !== "validation" && item.id !== "guide"} className={`flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-35 ${view === item.id ? "bg-white text-[#182b3a]" : "text-[#c5d0d9] hover:bg-white/8 hover:text-white"}`}><Icon className="size-4" />{item.label}</button>; })}</nav>
          <div className="mt-auto rounded-lg border border-white/10 bg-white/5 p-3"><div className="flex items-center gap-2 text-xs font-semibold text-[#dce5eb]"><span className="size-2 rounded-full bg-[#42c8a8]" /> API connected</div></div>
        </div>
      </aside>
      <div className="lg:pl-[236px]"><header className="sticky top-0 z-20 flex min-h-[68px] items-center justify-between border-b border-[#dbe3e9] bg-white/95 px-4 backdrop-blur sm:px-6 lg:px-8"><div className="flex items-center gap-3"><Button size="icon" variant="ghost" className="lg:hidden" onClick={() => setMobileNav(true)}><Menu /></Button><div><p className="text-xs font-semibold uppercase tracking-[0.1em] text-[#8090a4]">Evidence period</p><p className="text-sm font-semibold text-[#34495c]">{evidencePeriod}</p></div></div><div className="flex items-center gap-3"><CreateApplicantDialog compact onCreated={created} />{selected ? <><select aria-label="Selected applicant" className="hidden h-9 max-w-[230px] rounded-md border border-[#d4dde5] bg-white px-3 text-sm sm:block" value={selected.id} onChange={(e) => void loadCase(e.target.value)}>{applicants.map((applicant) => <option key={applicant.id} value={applicant.id}>{applicant.name} · {applicant.id}</option>)}</select><span className="grid size-9 place-items-center rounded-full bg-[#eaf0fb] text-xs font-bold text-[#2f61c5]">{initials(selected.name)}</span></> : null}</div></header>
        <div className="mx-auto max-w-[1380px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{error ? <div className="mb-5 flex items-start justify-between gap-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800"><span>{error}</span><button onClick={() => setError(null)}><X className="size-4" /></button></div> : null}{caseLoading ? <div className="mb-4 flex items-center gap-2 text-sm text-[#617087]"><LoaderCircle className="size-4 animate-spin" /> Refreshing passport…</div> : null}{view === "guide" ? <GuideView applicant={selected} transition={transition} /> : view === "queue" ? <QueueView applicants={applicants} onOpen={(applicant) => { void loadCase(applicant.id); setView("case"); }} /> : view === "validation" ? <ValidationView validation={validation} loading={validationLoading} onLoad={() => void loadValidation()} /> : !selected || !config || !evidence || !score || !transition ? <EmptyWorkspace onCreated={created} /> : view === "home" ? <HomeView applicant={selected} evidence={evidence} score={score} config={config} onNavigate={navigate} onRefresh={() => void refreshCase()} /> : view === "evidence" ? <EvidenceView applicant={selected} evidence={evidence} config={config} onRefresh={() => void refreshCase()} /> : view === "score" ? <ScoreView key={`${score.applicant_id}:${product}`} score={score} product={product} onProductChange={(next) => void changeProduct(next)} /> : view === "transition" ? <TransitionView applicant={selected} transition={transition} onSaved={setTransition} /> : <CaseView applicant={selected} evidence={evidence} score={score} onNavigate={navigate} />}</div>
      </div>
      </main>
    </TooltipProvider>
  );
}
