const ROWS = [
  {
    gstin: "27AB•••1Z5",
    inv: "1847",
    books: "2,48,000",
    gstr: "2,48,000",
    excelNote: "?? match?",
    excelTone: "guess" as const,
    recon: "MATCHED",
    reconTone: "matched" as const,
  },
  {
    gstin: "29CD•••2Z3",
    inv: "9021",
    books: "85,400",
    gstr: "85,400",
    excelNote: "yellow?",
    excelTone: "warn" as const,
    recon: "REVIEW",
    reconTone: "review" as const,
  },
  {
    gstin: "24EF•••9Z1",
    inv: "441",
    books: "—",
    gstr: "1,12,000",
    excelNote: "missed??",
    excelTone: "miss" as const,
    recon: "MISSED ITC",
    reconTone: "missed" as const,
  },
  {
    gstin: "27GH•••4Z8",
    inv: "3302",
    books: "56,200",
    gstr: "56,000",
    excelNote: "₹200??",
    excelTone: "guess" as const,
    recon: "MATCHED ±",
    reconTone: "matched" as const,
  },
  {
    gstin: "09IJ•••7Z2",
    inv: "778",
    books: "3,40,000",
    gstr: "3,40,000",
    excelNote: "OK?",
    excelTone: "ok" as const,
    recon: "MATCHED",
    reconTone: "matched" as const,
  },
  {
    gstin: "27KL•••3Z6",
    inv: "1205",
    books: "19,800",
    gstr: "19,800",
    excelNote: "17(5)?",
    excelTone: "warn" as const,
    recon: "HOLD",
    reconTone: "review" as const,
  },
];

const excelBg = {
  guess: "bg-[#FFF3B0]",
  warn: "bg-[#FFD6A5]",
  miss: "bg-[#FFADAD]",
  ok: "bg-[#CAFFBF]",
} as const;

const reconColor = {
  matched: "text-[#1A6B52]",
  review: "text-[#D97706]",
  missed: "text-[#9B2C2C]",
} as const;

export function ExcelVsRecon() {
  return (
    <div className="grid gap-6 lg:grid-cols-2 lg:gap-8">
      {/* Excel mess */}
      <div className="min-w-0">
        <div className="mb-3 flex items-baseline justify-between gap-2">
          <h3 className="font-display text-lg text-[#0B1D33]">Manual Excel</h3>
          <span className="font-mono text-[10px] tracking-wider text-[#9B2C2C]">HIGHLIGHT & GUESS</span>
        </div>
        <div className="overflow-x-auto border border-[#B8A99A] bg-[#E8E0D4] shadow-[inset_0_1px_0_rgba(255,255,255,0.4)]">
          {/* Fake Excel chrome */}
          <div className="flex items-center gap-1.5 border-b border-[#C4B8A8] bg-[#D4CBBE] px-2 py-1.5">
            <span className="h-2 w-2 rounded-full bg-[#C45C4A]" aria-hidden />
            <span className="h-2 w-2 rounded-full bg-[#D4A017]" aria-hidden />
            <span className="h-2 w-2 rounded-full bg-[#5A9A5A]" aria-hidden />
            <span className="ml-2 font-mono text-[10px] text-[#5C5346]">recon_may26_FINAL_v7.xlsx</span>
          </div>
          <table className="w-full min-w-[420px] border-collapse font-mono text-[10px] sm:text-[11px]">
            <thead>
              <tr className="bg-[#C8BFAF] text-left text-[#3D3428]">
                <th className="border border-[#B8A99A] px-2 py-1.5 font-medium">A · GSTIN</th>
                <th className="border border-[#B8A99A] px-2 py-1.5 font-medium">B · Inv</th>
                <th className="border border-[#B8A99A] px-2 py-1.5 text-right font-medium">C · Books</th>
                <th className="border border-[#B8A99A] px-2 py-1.5 text-right font-medium">D · 2B</th>
                <th className="border border-[#B8A99A] px-2 py-1.5 font-medium">E · Notes</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row, i) => (
                <tr key={row.inv}>
                  <td className="border border-[#C4B8A8] bg-[#F5F0E8] px-2 py-1.5 text-[#3D3428]">
                    <span className="mr-1 text-[#9A8F80]">{i + 2}</span>
                    {row.gstin}
                  </td>
                  <td className="border border-[#C4B8A8] bg-[#F5F0E8] px-2 py-1.5">{row.inv}</td>
                  <td className="border border-[#C4B8A8] bg-[#F5F0E8] px-2 py-1.5 text-right tabular-nums">
                    {row.books}
                  </td>
                  <td className="border border-[#C4B8A8] bg-[#F5F0E8] px-2 py-1.5 text-right tabular-nums">
                    {row.gstr}
                  </td>
                  <td
                    className={`border border-[#C4B8A8] px-2 py-1.5 font-medium text-[#3D3428] ${excelBg[row.excelTone]}`}
                  >
                    {row.excelNote}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="border-t border-[#C4B8A8] bg-[#DDD4C6] px-2 py-1.5 font-mono text-[9px] text-[#6B5E4E]">
            Conditional formatting · 14 named ranges · last edited 2:41 AM
          </p>
        </div>
      </div>

      {/* ReconDesk clean */}
      <div className="min-w-0">
        <div className="mb-3 flex items-baseline justify-between gap-2">
          <h3 className="font-display text-lg text-[#0B1D33]">ReconDesk</h3>
          <span className="font-mono text-[10px] tracking-wider text-[#1A6B52]">DECISION LAYER</span>
        </div>
        <div className="overflow-x-auto border border-[#0B1D33]/25 bg-white">
          <div className="flex items-center justify-between border-b border-[#D4D9E0] bg-[#0B1D33] px-3 py-1.5">
            <span className="font-mono text-[10px] tracking-wider text-[#A8B5C4]">RUN · MAY 2026</span>
            <span className="font-mono text-[10px] text-[#1A6B52]">6 / 6 RESOLVED</span>
          </div>
          <table className="w-full min-w-[420px] border-collapse font-mono text-[10px] sm:text-[11px]">
            <thead>
              <tr className="border-b border-[#D4D9E0] bg-[#F7F8FA] text-left text-[10px] tracking-wider text-[#6B7C8F]">
                <th className="px-3 py-2 font-medium">GSTIN</th>
                <th className="px-3 py-2 font-medium">INV</th>
                <th className="px-3 py-2 text-right font-medium">BOOKS</th>
                <th className="px-3 py-2 text-right font-medium">2B</th>
                <th className="px-3 py-2 font-medium">VERDICT</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row) => (
                <tr key={`rd-${row.inv}`} className="border-b border-[#EEF1F4] last:border-0">
                  <td className="px-3 py-2.5 text-[#0B1D33]">{row.gstin}</td>
                  <td className="px-3 py-2.5 text-[#4A5C6E]">{row.inv}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-[#0B1D33]">{row.books}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-[#0B1D33]">{row.gstr}</td>
                  <td className={`px-3 py-2.5 font-medium tracking-wide ${reconColor[row.reconTone]}`}>
                    {row.recon}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="grid grid-cols-3 border-t border-[#D4D9E0] bg-[#F7F8FA] font-mono text-[10px]">
            <div className="border-r border-[#D4D9E0] px-3 py-2 text-[#1A6B52]">CLAIM · 3</div>
            <div className="border-r border-[#D4D9E0] px-3 py-2 text-[#D97706]">HOLD · 2</div>
            <div className="px-3 py-2 text-[#9B2C2C]">DISPUTE · 1</div>
          </div>
        </div>
      </div>
    </div>
  );
}
