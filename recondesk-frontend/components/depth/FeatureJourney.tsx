"use client";
import { ArrowRight, Check, Database, FileSpreadsheet, Layers, Lock, ScanLine, ShieldCheck, Users } from "lucide-react";
import { useAutoplay } from "../motion/useAutoplay";
import { useDepthMotion, DepthMotionToggle } from "./DepthExperience";

type Chapter = "overview" | "ingestion" | "engine" | "rules" | "outward" | "shield" | "audit" | "governance";
const chapters: Record<Chapter, { title: string; steps: [string, string, string][] }> = {
  overview: { title: "Follow an invoice through the desk", steps: [
    ["Bring your files", "Start with your books and portal records. The ingestion layer brings their fields into a common structure.", "Books + portal"],
    ["Find the connection", "The matching layers compare invoice details, then separate matches from items that need attention.", "Matching engine"],
    ["Understand the decision", "Rule checks add context to the result, so you can see what needs review and why.", "Rules + review"],
    ["Keep the evidence", "Workpapers and review controls carry the explanation into your audit workflow.", "Audit trail"],
  ] },
  ingestion: { title: "From different files to one working set", steps: [
    ["Start with your register", "Bring a Tally, Busy, or Excel export. Header detection identifies the columns in your file.", "Register fields"],
    ["Read the portal records", "GSTR-2B JSON and Excel records enter the same workspace, with tax components kept separate.", "Portal records"],
    ["Connect through OTP", "The portal-fetch option uses client GSTIN and OTP verification to retrieve official records.", "Verified fetch"],
    ["Review invoice signals", "IMS recommendations and IRN checks add the next layer of information for your review.", "IMS + IRN"],
  ] },
  engine: { title: "Watch the matching ladder", steps: [
    ["L1 · Exact identity", "Compare the GSTIN, invoice number, and tax value. Identical details are the first checkpoint.", "Exact"],
    ["L2 · Normalize the format", "Different invoice formats can describe the same record. Normalization checks the underlying details.", "Normalized"],
    ["L3 · Inspect differences", "Small rounding and date differences are surfaced as tolerance matches, with the difference visible.", "Tolerance"],
    ["L4 · Follow the PAN", "Compare the entity PAN across state registrations to examine cross-branch invoice pairs.", "PAN match"],
    ["L6 · Separate unmatched items", "Distinguish portal-only records from books-only records. They need different follow-up actions.", "Unilateral"],
  ] },
  rules: { title: "Every rule has an explanation", steps: [
    ["Read the condition", "Begin with the rule’s trigger. The codex below keeps the exact condition and statutory reference together.", "Condition"],
    ["Trace the action", "See what the engine does when the condition applies, rather than treating the result as a black box.", "Action"],
    ["Keep the audit output", "The rule’s output explains how the observation appears in the workpapers. Search below for a specific rule.", "Audit output"],
  ] },
  outward: { title: "Bring sales and filing into alignment", steps: [
    ["Compare both sides", "Place the sales register alongside GSTR-1 to identify records present on only one side.", "Books ↔ GSTR-1"],
    ["Inspect the diagnostics", "The diagnostic matrix checks categories, values, and document sequences across outward supplies.", "G1M1–G1M10"],
    ["Review before filing", "Use the differences and their explanations to work through issues before the filing is locked.", "Review queue"],
  ] },
  shield: { title: "See the difference before the notice", steps: [
    ["Compare claimed and available ITC", "Bring the two values together so the excess claim is visible. The simulator below lets you explore an example.", "Compare"],
    ["Inspect both thresholds", "The original simulator evaluates the percentage and amount conditions together. Move its slider to see the result.", "Two checks"],
    ["Prepare the explanation", "Review the supporting records and the draft response. The example below shows how the explanation is organized.", "Draft + evidence"],
  ] },
  audit: { title: "A year of records, organized for review", steps: [
    ["Sheet 1 · Tie out the totals", "Bring the annual figures into the Table 8A versus 8B/8C view.", "Annual tie-out"],
    ["Sheet 2 · Group by supplier", "Roll transactions up by supplier PAN to see the entity-level picture.", "PAN rollup"],
    ["Sheet 3 · Read the observations", "Keep audit observations together with their supporting explanation.", "Observations"],
    ["Sheet 4 · Review reversals", "Keep Rule 37 and Section 17(5) reversal workpapers in a dedicated sheet.", "Reversals"],
  ] },
  governance: { title: "Give every decision an owner", steps: [
    ["Assign the work", "Assistants, managers, and partners work within role-based review permissions.", "Team roles"],
    ["Finalize and lock", "Once reviewed and filed, lock the run to protect the audit record from accidental edits.", "Locked record"],
    ["Follow up with suppliers", "Prepare itemized notices for vendor follow-up through PDF letters and WhatsApp text.", "Supplier notice"],
    ["Close the engagement", "Export the archive and use the existing purge workflow when the engagement is complete.", "Archive + purge"],
  ] },
};
const icons = { overview: Layers, ingestion: Database, engine: ScanLine, rules: ShieldCheck, outward: FileSpreadsheet, shield: ShieldCheck, audit: Layers, governance: Users };
export function FeatureJourney({ chapter }: { chapter: Chapter }) {
  const content = chapters[chapter];
  const { paused } = useDepthMotion();
  const { ref, step, setStep, running, reduced, setInteracting } = useAutoplay(content.steps.length, paused);
  const Icon = icons[chapter];
  return <div ref={ref} className={`depth-journey depth-journey-${chapter}`} data-running={running} data-step={step}
    onMouseEnter={() => setInteracting(true)} onMouseLeave={() => setInteracting(false)}
    onFocusCapture={() => setInteracting(true)} onBlurCapture={event => { if (!event.currentTarget.contains(event.relatedTarget)) setInteracting(false); }}>
    <div className="depth-journey-top"><span><i /> ANIMATED EXPLAINER · ILLUSTRATIVE</span><DepthMotionToggle /></div>
    <div className="depth-journey-body">
      <div className="depth-stage" aria-hidden="true">
        <div className="depth-stage-grid" />
        <div className="depth-orbit" /><div className="depth-orbit depth-orbit-inner" />
        <div className="depth-core"><Icon size={34} strokeWidth={1.3} /><span>{chapter === "overview" ? "ReconDesk" : "ReconDepth"}</span></div>
        <div className="depth-flow"><span /><span /><span /></div>
        <div className="depth-node depth-node-input"><FileSpreadsheet size={20} /><span>{chapter === "governance" ? "TEAM" : chapter === "audit" ? "12 MONTHS" : "SOURCE"}</span><div className="depth-mini-lines"><i /><i /><i /></div></div>
        <div className="depth-node depth-node-output" key={step}><Check size={20} /><span>{content.steps[step][2]}</span><div className="depth-mini-lines"><i /><i /><i /></div></div>
        <div className="depth-stage-label"><Lock size={12} /> Example walkthrough · no client data</div>
        <div className="depth-ledger">{content.steps.map((item,index)=><div key={item[0]} data-current={step===index}><span>{String(index+1).padStart(2,"0")}</span><strong>{item[2]}</strong><Check size={12} /></div>)}</div>
      </div>
      <div className="depth-story"><span className="depth-story-eyebrow">{content.title}</span>
        <div className="depth-story-copy" key={step}><span className="depth-step-number">{String(step+1).padStart(2,"0")} / {String(content.steps.length).padStart(2,"0")}</span><h3>{content.steps[step][0]}</h3><p>{content.steps[step][1]}</p></div>
        <div className="depth-steps" aria-label={`${content.title} steps`}>{content.steps.map((item,index)=><button type="button" key={item[0]} aria-label={item[0]} aria-pressed={step===index} onClick={()=>setStep(index)}><span>{String(index+1).padStart(2,"0")}</span><i key={step} /></button>)}</div>
        <div className="depth-playback-note">{reduced ? "Reduced motion · choose a step to explore" : paused ? "Paused · choose any step" : "Plays automatically · pauses while you explore"}<ArrowRight size={13}/></div>
      </div>
    </div>
  </div>;
}
