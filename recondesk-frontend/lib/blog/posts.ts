import { BlogPost } from "./types";

export const BLOG_POSTS: BlogPost[] = [
  {
    slug: "what-is-gst-reconciliation",
    title: "What Is GST Reconciliation and Why It Matters for CAs in India",
    excerpt:
      "GST reconciliation matches your purchase register with GSTR-2B so you claim only valid ITC. Learn what it is, why it matters, and how CAs avoid notices.",
    publishedAt: "Oct 5, 2026",
    readTime: "6 min read",
    category: "GST Compliance",
    author: {
      name: "ReconDesk Team",
      role: "GST Compliance & Technology Group",
    },
    tags: [
      "GST Reconciliation",
      "GSTR-2B Reconciliation",
      "ITC Reconciliation",
      "Rule 37",
      "Rule 88D",
      "DRC-01C",
      "Section 17(5)",
    ],
    keywords: [
      "GST reconciliation",
      "GSTR-2B reconciliation",
      "GSTR-2B vs purchase register",
      "ITC reconciliation",
      "Rule 37",
      "Section 17(5)",
      "DRC-01C",
      "Rule 88D",
      "ITC mismatch",
      "GST reconciliation software for CAs",
    ],
    metaTitle: "What Is GST Reconciliation and Why It Matters for CAs in India",
    metaDescription:
      "GST reconciliation matches your purchase register with GSTR-2B so you claim only valid ITC. Learn what it is, why it matters, and how CAs avoid notices.",
    coverGradient: "from-blue-600 via-indigo-600 to-purple-700",
    featured: true,
    faqs: [
      {
        question: "What is the difference between GSTR-2A and GSTR-2B?",
        answer:
          "GSTR-2A is a dynamic statement that keeps changing as suppliers file or amend their returns. GSTR-2B is a static statement generated once for each month, and it is the basis for claiming ITC in GSTR-3B.",
      },
      {
        question: "How often should GST reconciliation be done?",
        answer:
          "Monthly, before filing GSTR-3B. A full-year check before GSTR-9 is also important, since some differences only become visible over a longer period.",
      },
      {
        question: "What happens if ITC is claimed that does not appear in GSTR-2B?",
        answer:
          "It can lead to a DRC-01C intimation, a demand for reversal with interest, and exposure during audit or assessment. Claiming only what 2B supports, and tracking the rest, avoids this.",
      },
      {
        question: "Can reconciliation be done in Excel?",
        answer:
          "Yes, for small volumes. As invoice counts and client numbers grow, Excel becomes slow, error-prone and hard to defend. Dedicated reconciliation software handles format differences, fuzzy matching and documentation far more reliably.",
      },
      {
        question: "Is GST reconciliation mandatory?",
        answer:
          "The law does not use the word 'reconciliation' as a standalone obligation, but ITC conditions, reporting requirements and notice exposure make it a practical necessity for every registered taxpayer who claims ITC.",
      },
    ],
    content: `
If you run a CA practice in India, you already know the feeling. The 20th is close, thirty clients are waiting, and somewhere in an Excel sheet there is a purchase register that refuses to agree with GSTR-2B. This is GST reconciliation, and it is one of the most time-consuming and highest-risk parts of GST compliance.

This guide explains what GST reconciliation is, why it matters, where manual methods fail, and what a reliable process looks like.

---

### What is GST reconciliation?

GST reconciliation is the process of matching the data in your books of accounts with the data available on the GST portal, so that every return you file is backed by records that agree with each other.

The most important form for most businesses is **GSTR-2B vs. Purchase Register**:

- **GSTR-2B** is an auto-generated, static monthly statement of input tax credit (ITC) available to the taxpayer. It is built from the GSTR-1, GSTR-5 and other returns filed by suppliers.
- **Purchase Register** is what the business has recorded in Tally, Busy, Zoho, or Excel.

Reconciliation means checking, invoice by invoice, whether the two sides agree on supplier GSTIN, invoice number, invoice date, taxable value and tax amounts. Wherever they do not, someone has to find out why.

Other common reconciliations include:

- **GSTR-1 vs. GSTR-3B**, to confirm that outward supplies declared in the monthly return match the tax paid.
- **GSTR-3B vs. books**, to confirm that liability and ITC reported agree with the ledgers.
- **Annual reconciliation (GSTR-9 and GSTR-9C)**, to tie the full financial year together.

---

### Why GST reconciliation matters

#### 1. ITC is only safe when it is supported

Input tax credit is the largest lever in GST. Under **Section 16 of the CGST Act**, ITC can be claimed only when conditions are met, including that the invoice is reflected in GSTR-2B and that tax on it has actually been paid by the supplier. An invoice sitting in your books but missing from 2B is credit you cannot safely claim.

{{TAX_CALLOUT_RULE_36_4}}

#### 2. Mismatches invite notices

If the ITC claimed in GSTR-3B is materially higher than what GSTR-2B shows, the system can flag it. Under **Rule 88D**, a significant difference can trigger an intimation in **Form GST DRC-01C**, requiring the taxpayer to explain the difference or pay the excess with interest. Replying means accounting for every rupee of the gap, usually under a deadline. Firms that reconcile every month can answer quickly. Firms that do not end up rebuilding the analysis from scratch.

{{TAX_CALLOUT_RULE_88D}}

#### 3. Rule 37 can quietly create liabilities

Under **Rule 37**, if a recipient has not paid the supplier within 180 days from the date of the invoice, the ITC availed must be reversed and interest paid. The credit can be re-availed once payment is made. The problem is that this obligation lives in the payment data, not in the GSTR-2B. Without tracking, it builds up silently until an audit or notice brings it out.

{{TAX_CALLOUT_RULE_37}}

#### 4. Blocked credits slip through

**Section 17(5)** lists supplies on which ITC is blocked, such as certain motor vehicles, food and beverages, club memberships, and works contract services for construction of immovable property in specified cases. In a purchase register with thousands of lines, these items are easy to miss, and a wrongly claimed blocked credit is a future demand.

#### 5. A supplier's default becomes your client's problem

When a supplier does not file GSTR-1 on time, their invoices do not appear in your client's 2B. The credit is delayed, or lost if the time limit under **Section 16(4)** passes. Spotting non-filers early gives you time to follow up with the supplier before it affects the client.

{{TAX_CALLOUT_SECTION_16_4}}

---

### Why manual reconciliation breaks down

Most CA firms still reconcile with Excel, VLOOKUP, and filters. That works for a few hundred invoices. It fails at scale, for predictable reasons:

- **Inconsistent invoice numbers**. INV/001, INV-1, 001 and INV001 are the same invoice to a human and four different values to a formula.
- **Small data errors**. A single wrong digit in a GSTIN, or a rounding difference of a rupee, creates false mismatches that waste time.
- **No memory between months**. Every client and every period starts from zero.
- **No documentation**. When a notice arrives, there is no workpaper showing what was checked and why a difference exists.
- **Review burden**. The senior reviewing the file has to trust the sheet or redo it.

During return-filing weeks, this is exactly where hours disappear.

---

### What good GST reconciliation looks like

A reliable process does more than label rows as matched or unmatched. It should:

1. **Match in layers**. Start with exact matches, then move to progressively looser ones (format differences, small amount differences, probable typos), and show how confident each match is.
2. **Categorise every difference**. Matched, missing in 2B, missing in books, amount mismatch, and each with a stated reason rather than just a flag.
3. **Recommend an action**. For every invoice, the CA should see whether to claim, hold, or follow up with the supplier, and why.
4. **Build compliance checks into the match**. Rule 37 deadlines and Section 17(5) screening should run alongside reconciliation, not as a separate exercise.
5. **Leave a defensible trail**. Every decision should be traceable, so a notice reply starts from a ready workpaper.
6. **Keep the CA in control**. Automation should prepare and explain. The professional should decide.

---

### How ReconDesk helps

ReconDesk is built for CAs who want decisions, not just a mismatch list. You upload the Purchase Register and GSTR-2B, and ReconDesk matches them in layers, explains each difference, and flags Rule 37 and Section 17(5) exposure. It also helps with supplier follow-ups and supports notice defence preparation, so the work you do each month becomes the evidence you need later.

There is a free plan covering 2 GSTINs, with no card required, so you can test it on real client data before deciding anything.

👉 [Try ReconDesk free at recondesk.in](https://recondesk.in)

---

### Frequently asked questions

**What is the difference between GSTR-2A and GSTR-2B?**  
GSTR-2A is a dynamic statement that keeps changing as suppliers file or amend their returns. GSTR-2B is a static statement generated once for each month, and it is the basis for claiming ITC in GSTR-3B.

{{GSTR_2A_VS_2B_VAULT}}

**How often should GST reconciliation be done?**  
Monthly, before filing GSTR-3B. A full-year check before GSTR-9 is also important, since some differences only become visible over a longer period.

**What happens if ITC is claimed that does not appear in GSTR-2B?**  
It can lead to a DRC-01C intimation, a demand for reversal with interest, and exposure during audit or assessment. Claiming only what 2B supports, and tracking the rest, avoids this.

**Can reconciliation be done in Excel?**  
Yes, for small volumes. As invoice counts and client numbers grow, Excel becomes slow, error-prone and hard to defend. Dedicated reconciliation software handles format differences, fuzzy matching and documentation far more reliably.

**Is GST reconciliation mandatory?**  
The law does not use the word "reconciliation" as a standalone obligation, but ITC conditions, reporting requirements and notice exposure make it a practical necessity for every registered taxpayer who claims ITC.

---

### Conclusion

GST reconciliation is not a clerical chore. It protects your clients' ITC, keeps returns defensible, and prevents surprises from Rule 37, Section 17(5) and notices. The firms that treat it as a monthly discipline, supported by the right tooling, spend less time firefighting and more time advising.

*Disclaimer: This article is for general information and is not legal or tax advice. Provisions, thresholds and notified limits under the CGST Act and Rules change from time to time. Please verify against the latest notifications.*
`,
  },
  {
    slug: "what-is-gstr-2b-itc-claims-guide",
    title: "What is GSTR-2B and Why Does It Matter for ITC Claims?",
    excerpt:
      "It's the 20th of the month. Your client's ITC is short by ₹1.8 lakhs. The supplier says they filed. The portal says otherwise. Here is why GSTR-2B rules your ITC.",
    publishedAt: "Sep 27, 2026",
    readTime: "4 min read",
    category: "ITC Optimization",
    author: {
      name: "ReconDesk Tax Research",
      role: "GST Compliance & Analytics Group",
    },
    tags: ["GSTR-2B", "ITC Claims", "Rule 36(4)", "Reconciliation"],
    coverGradient: "from-purple-600 to-indigo-700",
    featured: true,
    content: `
It's the 20th of the month. Your client's ITC is short by ₹1.8 lakhs. The supplier says they filed. The portal says otherwise. You've been staring at Excel for 3 hours.

This is a GSTR-2B problem.

---

### What is GSTR-2B?

GSTR-2B is an auto-drafted, static Input Tax Credit (ITC) statement generated by the GST portal every month.

It shows exactly which suppliers filed their GSTR-1 or IFF and reported invoices in your name — for a fixed period. It does not change after generation. That's what makes it different from GSTR-2A.

- **Generated on**: 14th of every month (for the previous month)
- **Based on**: Supplier's GSTR-1 / IFF / GSTR-5 / GSTR-6 filings
- **Type**: Static — does not update after cut-off

---

### Forensic Inspection: What the GST Department Sees Underneath

Hover or move your cursor across the client's books below to switch between the client view, the GST Department X-Ray, and the ReconDesk algorithmic resolution:

{{FORENSIC_AUDIT_LOUPE}}

---

### GSTR-2B vs GSTR-2A — What's the Difference?

{{GSTR_2A_VS_2B_VAULT}}

**Bottom line:** Use GSTR-2A to track. Use GSTR-2B to claim.

---

### Why Does GSTR-2B Matter for ITC Claims?

As per **Rule 36(4) of the CGST Rules**, you can claim ITC only on invoices reflecting in GSTR-2B.

{{TAX_CALLOUT_RULE_36_4}}

**No GSTR-2B entry = No ITC legally.**

This means:
- **Supplier didn't file GSTR-1** → invoice won't appear → you lose ITC that month
- **Supplier filed late** → it shifts to next month's GSTR-2B
- **Wrong GSTIN by supplier** → it won't show up at all

Every rupee of ITC your client claims must be backed by GSTR-2B.

---

### What is GSTR-2B Reconciliation?

Reconciliation = matching your purchase register (books) against GSTR-2B (portal).

Three outcomes come out of this:

1. **Matched** — Invoice in books + in GSTR-2B → Claim ITC ✅
2. **In GSTR-2B but not in books** — Supplier filed but you haven't recorded it → Update books
3. **In books but not in GSTR-2B** — You recorded it but supplier didn't file → Chase supplier, hold ITC

This reconciliation is what CAs spend 3 to 6 hours on per client, per month — manually.

---

### Common Reasons GSTR-2B Doesn't Match

- Supplier filed GSTR-1 after the 14th cut-off
- Wrong GSTIN or invoice number entered by supplier
- Supplier is under QRMP scheme — filed quarterly, not monthly
- Invoice period mismatch (supplier reported in wrong month)
- Credit notes not accounted for

---

### CA Catch 🎯

Most CAs claim ITC based on what's in their books — not what's in GSTR-2B. That's a severe compliance risk. During scrutiny, the department will match your GSTR-3B ITC with GSTR-2B. Any excess claim = demand notice + interest + penalty.

{{CA_CATCH_RADAR}}

---

### What Happens if You Ignore GSTR-2B Reconciliation?

- **Excess ITC claimed** → Section 73/74 notice
- **Interest @ 24%** on wrongly availed ITC
- **Penalty up to 100%** of tax amount
- **Cascading issues** during annual return (GSTR-9)

One month of skipped reconciliation can undo a year of clean filings.

---

### How to Do GSTR-2B Reconciliation (Quick Steps)

1. Download GSTR-2B JSON from GST portal
2. Export your purchase register from Tally / ERP
3. Match invoice by invoice — GSTIN, invoice number, amount, tax
4. Flag mismatches
5. Chase suppliers for unmatched entries
6. Claim only what's matched

Doing this manually for 50+ clients every month is where hours disappear.

---

### Frequently Asked Questions

**Can I claim ITC if invoice is not in GSTR-2B?**  
No. As per current rules, ITC is restricted strictly to what reflects in GSTR-2B.

**What if supplier files after the 14th?**  
The invoice will appear in next month's GSTR-2B. ITC can be claimed then.

**Is GSTR-2B available for composition dealers?**  
No. Composition dealers cannot claim ITC.

**How many months can I carry forward unclaimed ITC?**  
Up to 30th November of the next financial year or date of annual return filing, whichever is earlier.

---

### Key Takeaway

GSTR-2B is not just a report. It is the legal basis for every ITC rupee your client claims.

- **Get the reconciliation wrong** → your client pays interest and penalty.
- **Skip it entirely** → audit risk that can surface months later.

The CAs who stay clean are the ones reconciling every month, without exception.
`,
  },
];

export function getAllPosts(): BlogPost[] {
  return [...BLOG_POSTS].sort(
    (a, b) => new Date(b.publishedAt).getTime() - new Date(a.publishedAt).getTime()
  );
}

export function getRecentPosts(limit = 3): BlogPost[] {
  return getAllPosts().slice(0, limit);
}

export function getPostBySlug(slug: string): BlogPost | undefined {
  return BLOG_POSTS.find((p) => p.slug === slug);
}

export function getAllCategories(): string[] {
  const set = new Set(BLOG_POSTS.map((p) => p.category));
  return Array.from(set);
}
