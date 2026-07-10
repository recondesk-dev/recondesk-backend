const CASES = [
  {
    ref: "CF-01",
    title: "Missed eligible credits",
    statute: "ITC left on the table",
    consequence:
      "2B mein dikha, books mein nahi — aur filing ke baad pata chala. Working capital block, interest ticking.",
  },
  {
    ref: "CF-02",
    title: "Incorrect availment",
    statute: "Claimed what shouldn't be",
    consequence:
      "Sec 17(5) blocked credit still claimed. Notice aaya toh reverse + interest. Excel colour-code se nahi bachta.",
  },
  {
    ref: "CF-03",
    title: "Manual Table 4 mapping",
    statute: "GSTR-3B classification drift",
    consequence:
      "Ek invoice galat bucket mein — Table 4(A) vs 4(B) confusion. Month-end scramble, no clean trail.",
  },
  {
    ref: "CF-04",
    title: "Weak audit trail",
    statute: "No judgment record",
    consequence:
      "Excel mein manually track karte ho? Ek invoice miss, aur working capital block. Partner poochhe — kya jawab?",
  },
] as const;

export function RiskCaseFile() {
  return (
    <div className="border border-[#0B1D33]/20 bg-white">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-[#0B1D33] bg-[#0B1D33] px-4 py-3 sm:px-5">
        <p className="font-mono text-[11px] tracking-[0.16em] text-[#A8B5C4]">CASE FILE · ITC RISK REGISTER</p>
        <p className="font-mono text-[10px] text-[#6B7C8F]">CONFIDENTIAL · FIRM USE</p>
      </div>
      <ul className="divide-y divide-[#D4D9E0]">
        {CASES.map((c) => (
          <li key={c.ref} className="grid gap-3 px-4 py-5 sm:grid-cols-[5.5rem_1fr] sm:gap-6 sm:px-5 sm:py-6">
            <div className="font-mono text-[11px] tracking-wider text-[#6B7C8F]">{c.ref}</div>
            <div>
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h3 className="font-display text-lg text-[#0B1D33] sm:text-xl">{c.title}</h3>
                <span className="font-mono text-[10px] tracking-wide text-[#9AA6B4]">{c.statute}</span>
              </div>
              <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[#3D4F63]">{c.consequence}</p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
