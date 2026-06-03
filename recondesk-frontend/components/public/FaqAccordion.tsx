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
      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-[#E5E5E5] text-sm font-medium text-[#3A3A3A]"
      aria-hidden
    >
      {open ? "−" : "+"}
    </span>
  );
}

export function FaqAccordion() {
  const [openIndex, setOpenIndex] = useState(0);

  return (
    <div className="landing-card mx-auto mt-10 max-w-3xl divide-y divide-[#E5E5E5] rounded-xl border border-[#E5E5E5] bg-[#F5F5F5]">
      {FAQ_ITEMS.map(({ q, a }, index) => {
        const open = openIndex === index;
        return (
          <div key={q}>
            <button
              type="button"
              className="flex w-full items-start justify-between gap-3 px-4 py-3.5 text-left transition-colors hover:bg-[#EBEBEB] sm:items-center sm:gap-4 sm:px-5 sm:py-4"
              aria-expanded={open}
              onClick={() => setOpenIndex(open ? -1 : index)}
            >
              <span className="min-w-0 flex-1 pr-1 text-sm font-semibold leading-snug text-[#0A0A0A] sm:text-base">
                {q}
              </span>
              <ToggleIcon open={open} />
            </button>
            <div
              className={`grid transition-[grid-template-rows] duration-300 ease-in-out ${
                open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
              }`}
            >
              <div className="overflow-hidden">
                <p className="px-4 pb-4 text-sm leading-relaxed text-[#3A3A3A] sm:px-5">{a}</p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
