"use client";

import type { FilingExternalInputGap } from "@/lib/api";
import {
  SectionHeader,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";
import { tableLabel } from "@/components/filing/filingHelpers";

export function ExternalInputGapsPanel({
  gaps,
}: {
  gaps: FilingExternalInputGap[];
}) {
  if (!gaps.length) return null;

  const blockers = gaps.filter((g) => g.blocks_file);
  const advisory = gaps.filter((g) => !g.blocks_file);

  return (
    <section
      className={sectionContainerClass}
      aria-label="External input needed"
    >
      <SectionHeader title="Schedules GSTN needs from you" dotColor="#111111" />
      <p className="mt-1 text-[13px] text-gray-500">
        These are period-level gaps the Sales Register cannot fill. Upload or
        prepare the missing schedule before File — they are not fixed by
        changing a single invoice type.
      </p>

      {blockers.length > 0 ? (
        <GapGroup
          title="Required for File"
          items={blockers}
          emphasize
        />
      ) : null}
      {advisory.length > 0 ? (
        <GapGroup title="Advisory / if applicable" items={advisory} />
      ) : null}
    </section>
  );
}

function GapGroup({
  title,
  items,
  emphasize,
}: {
  title: string;
  items: FilingExternalInputGap[];
  emphasize?: boolean;
}) {
  return (
    <div className="mt-5">
      <h3 className="text-[12px] font-semibold uppercase tracking-wide text-gray-500">
        {title}
      </h3>
      <ul className="mt-2 space-y-2">
        {items.map((g) => (
          <li
            key={`${g.table}-${g.reason}`}
            className={`rounded-xl px-4 py-3 ring-1 ${
              emphasize
                ? "bg-[#F7F7F8] ring-[#E8E8EA]"
                : "bg-white ring-[#F0F0F0]"
            }`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[13px] font-semibold text-[var(--ink)]">
                {tableLabel(g.table)}
              </span>
              {emphasize ? (
                <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-semibold text-gray-600 ring-1 ring-[#E5E5E7]">
                  Blocks File
                </span>
              ) : null}
            </div>
            <p className="mt-1.5 text-[13px] text-gray-700">{g.message}</p>
            {g.missing_fields.length > 0 ? (
              <p className="mt-1 text-[12px] text-gray-500">
                Missing: {g.missing_fields.join(", ")}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
