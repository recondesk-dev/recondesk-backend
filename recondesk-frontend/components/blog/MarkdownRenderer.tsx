import React from "react";
import { ScrollyInvoiceStory } from "./ScrollyInvoiceStory";
import { ItcLossCalculator } from "./ItcLossCalculator";
import { TaxCallout } from "./TaxCallout";
import { TemporalScrubberStory } from "./TemporalScrubberStory";
import { Gstr2aVs2bCard } from "./Gstr2aVs2bCard";
import { CaCatchRadar } from "./CaCatchRadar";
import { ForensicAuditLoupe } from "./ForensicAuditLoupe";

export function MarkdownRenderer({ content }: { content: string }) {
  // Split into paragraphs / blocks
  const blocks = content.trim().split(/\n\s*\n/);

  return (
    <div className="space-y-5 text-sm sm:text-base leading-relaxed text-[#2A2A2A]">
      {blocks.map((block, i) => {
        const trimmed = block.trim();

        // 1. Dynamic Widget Tags
        if (trimmed === "{{FORENSIC_AUDIT_LOUPE}}") {
          return <ForensicAuditLoupe key={i} />;
        }
        if (trimmed === "{{TEMPORAL_SCRUBBER}}") {
          return <TemporalScrubberStory key={i} />;
        }
        if (trimmed === "{{GSTR_2A_VS_2B_VAULT}}") {
          return <Gstr2aVs2bCard key={i} />;
        }
        if (trimmed === "{{CA_CATCH_RADAR}}") {
          return <CaCatchRadar key={i} />;
        }
        if (trimmed === "{{SCROLLY_STORY}}") {
          return <ScrollyInvoiceStory key={i} />;
        }
        if (trimmed === "{{CALCULATOR}}") {
          return <ItcLossCalculator key={i} />;
        }
        if (trimmed === "{{TAX_CALLOUT_RULE_36_4}}") {
          return (
            <TaxCallout
              key={i}
              type="law"
              title="Rule 36(4) of CGST Rules: Statutory ITC Restriction"
            >
              No input tax credit shall be availed by a registered person in respect of invoices or debit notes the details of which are required to be furnished under sub-section (1) of section 37 unless the details of such invoices or debit notes have been furnished by the supplier in the statement of outward supplies and communicated to the recipient in Form GSTR-2B.
            </TaxCallout>
          );
        }
        if (trimmed === "{{TAX_CALLOUT_SECTION_16_4}}") {
          return (
            <TaxCallout
              key={i}
              type="warning"
              title="Statutory Warning: Section 16(4) CGST Act"
            >
              A registered person shall not be entitled to take input tax credit in respect of any invoice or debit note for supply of goods or services or both after the 30th day of November following the end of the financial year to which such invoice pertains.
            </TaxCallout>
          );
        }
        if (trimmed === "{{TAX_CALLOUT_RULE_37A}}") {
          return (
            <TaxCallout
              key={i}
              type="law"
              title="Rule 37A of CGST Rules: Mandatory Reversal of ITC"
            >
              Where input tax credit has been availed by a registered person in GSTR-3B for a tax period in respect of an invoice or debit note, the details of which have been furnished by the supplier in GSTR-1, but the return in GSTR-3B for the said tax period has not been furnished by such supplier till the 30th day of November following the end of financial year, the said amount of input tax credit shall be reversed.
            </TaxCallout>
          );
        }

        // 2. Horizontal divider
        if (trimmed === "---") {
          return <hr key={i} className="my-8 border-[#E5E5E2]" />;
        }

        // 3. Headings
        if (trimmed.startsWith("### ")) {
          return (
            <h3
              key={i}
              className="mt-8 mb-3 text-xl font-bold tracking-tight text-[#0A0A0A] sm:text-2xl"
            >
              {renderInline(trimmed.replace(/^###\s+/, ""))}
            </h3>
          );
        }
        if (trimmed.startsWith("## ")) {
          return (
            <h2
              key={i}
              className="mt-10 mb-4 text-2xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-3xl"
            >
              {renderInline(trimmed.replace(/^##\s+/, ""))}
            </h2>
          );
        }

        // 4. Markdown Tables
        if (trimmed.includes("|") && trimmed.includes("\n")) {
          const rows = trimmed
            .split("\n")
            .filter((r) => r.trim().startsWith("|") && !r.includes("---"));
          if (rows.length > 0) {
            const headerCells = rows[0]
              .split("|")
              .map((c) => c.trim())
              .filter(Boolean);
            const dataRows = rows.slice(1).map((r) =>
              r
                .split("|")
                .map((c) => c.trim())
                .filter(Boolean)
            );

            return (
              <div key={i} className="my-6 overflow-x-auto rounded-xl border border-[#E5E5E2] shadow-sm">
                <table className="w-full text-left text-xs sm:text-sm">
                  <thead className="bg-[#FAF9F5] border-b border-[#E5E5E2] font-bold text-[#0A0A0A]">
                    <tr>
                      {headerCells.map((cell, cIdx) => (
                        <th key={cIdx} className="px-4 py-3">
                          {renderInline(cell)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#E5E5E2] bg-white">
                    {dataRows.map((row, rIdx) => (
                      <tr key={rIdx} className="hover:bg-[#FAF9F5]/60 transition-colors">
                        {row.map((cell, cIdx) => (
                          <td key={cIdx} className="px-4 py-3 text-[#4A4A4A]">
                            {renderInline(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          }
        }

        // 5. Unordered List
        if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
          const items = trimmed
            .split("\n")
            .filter((line) => line.trim().startsWith("- ") || line.trim().startsWith("* "));
          return (
            <ul key={i} className="my-4 list-disc space-y-2 pl-5 text-[#4A4A4A]">
              {items.map((item, itemIdx) => (
                <li key={itemIdx}>
                  {renderInline(item.replace(/^[-*]\s+/, ""))}
                </li>
              ))}
            </ul>
          );
        }

        // 6. Ordered List
        if (/^\d+\.\s/.test(trimmed)) {
          const items = trimmed
            .split("\n")
            .filter((line) => /^\d+\.\s/.test(line.trim()));
          return (
            <ol key={i} className="my-4 list-decimal space-y-2 pl-5 text-[#4A4A4A]">
              {items.map((item, itemIdx) => (
                <li key={itemIdx}>
                  {renderInline(item.replace(/^\d+\.\s+/, ""))}
                </li>
              ))}
            </ol>
          );
        }

        // 7. Regular paragraph
        return (
          <p key={i} className="text-[#3A3A3A] leading-relaxed">
            {renderInline(trimmed)}
          </p>
        );
      })}
    </div>
  );
}

/**
 * Basic inline parser for bold, code, and links
 */
function renderInline(text: string): React.ReactNode {
  // Split on bold (**text**)
  const parts = text.split(/(\*\*.*?\*\*|`.*?`)/g);

  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={index} className="font-bold text-[#0A0A0A]">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code
          key={index}
          className="rounded bg-[#FAF9F5] border border-[#E5E5E2] px-1.5 py-0.5 font-mono text-xs text-[#7B5CFA]"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return part;
  });
}
