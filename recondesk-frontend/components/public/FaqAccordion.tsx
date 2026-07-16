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
    q: "How is pricing structured?",
    a: "Plans are priced by GSTIN capacity — Starter ₹999/month (25 GSTINs), Growth ₹7,999/year (50), Pro ₹11,999/year (75). Every plan includes the full product.",
  },
  {
    q: "How does billing work?",
    a: "Manual payment via Razorpay. Starter is monthly; Growth and Pro are yearly. No auto-debit — you choose when to renew.",
  },
] as const;

function ToggleIcon({ open }: { open: boolean }) {
  return (
    <span
      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-medium transition-colors ${
        open ? "bg-[var(--ink)] text-white" : "bg-[#F5F5F6] text-gray-600"
      }`}
      aria-hidden
    >
      {open ? "−" : "+"}
    </span>
  );
}

export function FaqAccordion() {
  const [openIndex, setOpenIndex] = useState(0);

  return (
    <div className="mx-auto mt-10 max-w-3xl divide-y divide-[#F0F0F0] overflow-hidden rounded-[1.5rem] bg-white shadow-[var(--shadow-soft)]">
      {FAQ_ITEMS.map(({ q, a }, index) => {
        const open = openIndex === index;
        return (
          <div key={q}>
            <button
              type="button"
              className="flex w-full items-start justify-between gap-3 px-4 py-3.5 text-left transition-colors hover:bg-[#F7F7F8] sm:items-center sm:gap-4 sm:px-5 sm:py-4"
              aria-expanded={open}
              onClick={() => setOpenIndex(open ? -1 : index)}
            >
              <span className="min-w-0 flex-1 pr-1 text-sm font-semibold leading-snug text-[var(--ink)] sm:text-base">
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
                <p className="px-4 pb-4 text-sm leading-relaxed text-gray-500 sm:px-5">{a}</p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
