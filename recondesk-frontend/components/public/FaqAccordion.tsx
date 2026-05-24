"use client";

import { useState } from "react";

const FAQ_ITEMS = [
  {
    q: "Is my client's data safe?",
    a: "Files are deleted after processing. All data is encrypted at rest and in transit. We never share your data with third parties.",
  },
  {
    q: "Which accounting software works?",
    a: "Tally, Busy, or any Excel format — source software is auto-detected on upload.",
  },
  {
    q: "How long does reconciliation take?",
    a: "Under 60 seconds for 1,000 invoices.",
  },
  {
    q: "Can I try before paying?",
    a: "Yes. Your first 2 reconciliations are completely free. No credit card required.",
  },
  {
    q: "Can my staff use it?",
    a: "Yes. Invite team members. Staff can run reconciliations; you review and finalize results.",
  },
  {
    q: "What happens to unused runs?",
    a: "Solo plans: runs expire monthly. Firm Growth and Pro plans: unused runs carry over for up to 2 months.",
  },
  {
    q: "How does billing work?",
    a: "Manual monthly payment via Razorpay. No auto-debit. You choose when to renew.",
  },
] as const;

function ToggleIcon({ open }: { open: boolean }) {
  return (
    <span
      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-white/15 text-sm font-medium text-slate-300"
      aria-hidden
    >
      {open ? "−" : "+"}
    </span>
  );
}

export function FaqAccordion() {
  const [openIndex, setOpenIndex] = useState(0);

  return (
    <div className="mx-auto mt-10 max-w-3xl divide-y divide-white/10 rounded-xl border border-white/10 bg-[#13161f]">
      {FAQ_ITEMS.map(({ q, a }, index) => {
        const open = openIndex === index;
        return (
          <div key={q}>
            <button
              type="button"
              className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left transition-colors hover:bg-white/[0.03]"
              aria-expanded={open}
              onClick={() => setOpenIndex(open ? -1 : index)}
            >
              <span className="font-semibold text-white">{q}</span>
              <ToggleIcon open={open} />
            </button>
            <div
              className={`grid transition-[grid-template-rows] duration-300 ease-in-out ${
                open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
              }`}
            >
              <div className="overflow-hidden">
                <p className="px-5 pb-4 text-sm leading-relaxed text-slate-400">{a}</p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
