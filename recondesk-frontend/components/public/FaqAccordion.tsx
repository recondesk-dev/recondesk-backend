"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";

type FaqCategory = "all" | "pricing" | "statutory" | "privacy";

interface FaqItem {
  id: string;
  category: "pricing" | "statutory" | "privacy";
  categoryLabel: string;
  q: string;
  a: string;
}

const FAQ_ITEMS: FaqItem[] = [
  {
    id: "free-tier",
    category: "pricing",
    categoryLabel: "60-Day Trial",
    q: "How does the 60-day free trial work?",
    a: "You get 100% full product access for up to 2 client GSTINs completely free for 60 days (covering 2 complete monthly return filing cycles) with zero feature gating. You get access to the full 5-level matching engine, Rule 37 tracking, Section 17(5) scanner, and Excel audit export. No credit card is required. After 60 days, you can choose a plan like Solo or Firm to keep running new reconciliations, while all your past data remains accessible.",
  },
  {
    id: "pricing-structure",
    category: "pricing",
    categoryLabel: "Pricing & Capacity",
    q: "How is pricing structured for CA firms?",
    a: "Plans are based strictly on active client GSTIN capacity with unlimited staff seats and unlimited reconciliation runs — 60-Day Free Trial up to 2 GSTINs (₹0), Solo up to 25 GSTINs (₹799/mo · ₹5,999/yr), Firm up to 75 GSTINs (₹1,199/mo · ₹8,999/yr), and Large Firm up to 150 GSTINs (₹1,899/mo · ₹11,999/yr). Every plan includes 100% full product access with zero feature gating.",
  },
  {
    id: "rule-88d-notice",
    category: "statutory",
    categoryLabel: "Notice Shield",
    q: "How does ReconDesk prevent Rule 88D & DRC-01C notices?",
    a: "ReconDesk automatically pre-checks your GSTR-3B ITC claim against GSTR-2B before you file. If the variance exceeds 20% and ₹25 Lakhs (the statutory notice trigger threshold), it alerts you immediately and generates a pre-formatted explanatory reply statement citing Section 16(4) carry-forwards, timing differences, and supplier filing delays.",
  },
  {
    id: "rule-37-tracker",
    category: "statutory",
    categoryLabel: "Rule 37 Tracking",
    q: "How does the Rule 37 180-day unpaid supplier tracker work?",
    a: "ReconDesk automatically scans invoice dates against payment status to identify supplier invoices approaching or exceeding the mandatory 180-day deadline. It computes the exact 18% p.a. interest liability under Section 50(1) and automatically calculates proportionate reversals for partial payments.",
  },
  {
    id: "5-level-matching",
    category: "statutory",
    categoryLabel: "Matching Engine",
    q: "How does the 5-level matching engine handle invoice number typos?",
    a: "The engine uses deterministic multi-tier logic to bridge format drifts (such as INV/2026/0941 vs 941, leading zeros, or date swaps) while ensuring ₹0 financial delta. This eliminates over 95% of manual spreadsheet review rows without compromising audit rigor.",
  },
  {
    id: "accounting-software",
    category: "privacy",
    categoryLabel: "Integrations",
    q: "Which accounting software and file formats work?",
    a: "Tally Prime, Tally ERP 9, Busy, Zoho Books, SAP, Oracle, and any custom Excel/CSV purchase registers. ReconDesk automatically detects column headers on upload with zero manual mapping required. You can also fetch GSTR-2B directly from the GST portal via 1-click OTP.",
  },
  {
    id: "data-privacy",
    category: "privacy",
    categoryLabel: "Data Governance",
    q: "How is my clients' financial data protected from AI training?",
    a: "Each CA firm operates in an isolated tenant database schema with AES-256 at-rest and TLS 1.3 in-transit encryption. We have a strict zero-AI model training policy — your client turnovers, ledgers, and supplier lists are never shared, sold, or used to train machine learning models.",
  },
  {
    id: "team-access",
    category: "privacy",
    categoryLabel: "Team Collaboration",
    q: "Can my article assistants and team members work on client files together?",
    a: "Yes. All plans include unlimited team member seats. Article assistants can upload files and run reconciliations; senior associates and partners can review match reasons, leave notes on disputed invoices, and lock finalized runs for audit sign-off.",
  },
];

export function FaqAccordion() {
  const [selectedCategory, setSelectedCategory] = useState<FaqCategory>("all");
  const [openId, setOpenId] = useState<string | null>("free-tier");

  const filteredFaqs =
    selectedCategory === "all"
      ? FAQ_ITEMS
      : FAQ_ITEMS.filter((item) => item.category === selectedCategory);

  const categories: { key: FaqCategory; label: string }[] = [
    { key: "all", label: "All Questions" },
    { key: "pricing", label: "Free Tier & Pricing" },
    { key: "statutory", label: "Statutory & Notices" },
    { key: "privacy", label: "Privacy & Software" },
  ];

  const toggleItem = (id: string) => {
    setOpenId((prev) => (prev === id ? null : id));
  };

  return (
    <div className="mx-auto mt-10 max-w-4xl">
      {/* Category Filter Pills */}
      <div className="flex flex-wrap items-center justify-center gap-2">
        {categories.map((cat) => (
          <button
            key={cat.key}
            type="button"
            onClick={() => setSelectedCategory(cat.key)}
            className={`rounded-full px-4 py-1.5 text-xs font-semibold transition-all ${
              selectedCategory === cat.key
                ? "bg-[#0A0A0A] text-white shadow-xs"
                : "bg-white text-[#6B6B6B] border border-[#E5E5E2] hover:bg-[#F5F5F3] hover:text-[#0A0A0A]"
            }`}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* Sleek Minimal Divider List (No boxy cards) */}
      <div className="mt-8 divide-y divide-[#E5E5E2] border-t border-b border-[#E5E5E2]">
        {filteredFaqs.map((item) => {
          const isOpen = openId === item.id;

          return (
            <div key={item.id} className="py-4 sm:py-5 transition-colors">
              <button
                type="button"
                onClick={() => toggleItem(item.id)}
                className="flex w-full items-start justify-between gap-4 text-left group"
                aria-expanded={isOpen}
              >
                <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 flex-1 min-w-0">
                  <span className="text-base font-bold text-[#0A0A0A] group-hover:text-[#7B5CFA] transition-colors leading-snug">
                    {item.q}
                  </span>
                  <span className="inline-block w-fit rounded bg-[#F1F5F9] px-2 py-0.5 text-[10px] font-semibold text-[#64748B]">
                    {item.categoryLabel}
                  </span>
                </div>

                <div
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[#E5E5E2] bg-white text-[#6B6B6B] transition-transform duration-200 ${
                    isOpen ? "rotate-180 bg-[#7B5CFA] text-white border-[#7B5CFA]" : "group-hover:border-[#0A0A0A]"
                  }`}
                >
                  <ChevronDown className="h-4 w-4" />
                </div>
              </button>

              {/* Smooth Inline Answer Dropdown */}
              <div
                className={`grid transition-[grid-template-rows] duration-200 ease-out ${
                  isOpen ? "grid-rows-[1fr] opacity-100 mt-3" : "grid-rows-[0fr] opacity-0"
                }`}
              >
                <div className="overflow-hidden">
                  <p className="text-sm leading-relaxed text-[#555555] sm:pr-12">
                    {item.a}
                  </p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
