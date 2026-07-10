const TICKER_ITEMS = [
  { status: "MATCHED", detail: "INV-2847 · Rule 37 clear", tone: "matched" as const },
  { status: "REVIEW REQUIRED", detail: "INV-2912 · Sec 17(5) risk", tone: "review" as const },
  { status: "MATCHED", detail: "INV-2901 · L1 exact GSTIN", tone: "matched" as const },
  { status: "MISSED ITC", detail: "INV-2888 · in 2B, not in books", tone: "missed" as const },
  { status: "MATCHED", detail: "INV-2855 · amount ±₹2", tone: "matched" as const },
  { status: "REVIEW REQUIRED", detail: "INV-2933 · vendor name drift", tone: "review" as const },
  { status: "MATCHED", detail: "INV-2860 · L3 fuzzy invoice#", tone: "matched" as const },
  { status: "MISSED ITC", detail: "INV-2871 · claim window closing", tone: "missed" as const },
  { status: "MATCHED", detail: "INV-2940 · Rule 36(4) ok", tone: "matched" as const },
  { status: "REVIEW REQUIRED", detail: "INV-2951 · hold pending docs", tone: "review" as const },
];

const toneClass = {
  matched: "text-[#1A6B52]",
  review: "text-[#D97706]",
  missed: "text-[#9B2C2C]",
} as const;

function TickerRow() {
  return (
    <>
      {TICKER_ITEMS.map((item, i) => (
        <span key={`${item.status}-${i}`} className="inline-flex items-center gap-3 whitespace-nowrap px-6">
          <span className={`font-mono text-[11px] font-medium tracking-wide ${toneClass[item.tone]}`}>
            {item.status}
          </span>
          <span className="font-mono text-[11px] text-[#6B7C8F]">{item.detail}</span>
          <span className="text-[#C5CDD6]" aria-hidden>
            ·
          </span>
        </span>
      ))}
    </>
  );
}

/** Continuous CSS-only status ticker — no JS animation loop. */
export function StatusTicker() {
  return (
    <div
      className="ledger-ticker relative overflow-hidden border-y border-[#D4D9E0] bg-[#0B1D33]"
      aria-label="Live invoice status feed"
      role="img"
    >
      <div className="ledger-ticker-track flex w-max py-3">
        <TickerRow />
        <TickerRow />
      </div>
    </div>
  );
}
