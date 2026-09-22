"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import { useRef, type ReactNode } from "react";

export interface VirtualizedDecisionInvoiceListProps<T> {
  items: T[];
  renderItem: (item: T, index: number) => ReactNode;
  getItemKey?: (item: T, index: number) => string | number;
  selectAll?: ReactNode;
  estimateSize?: number;
  maxHeight?: string;
  overscan?: number;
  threshold?: number;
  className?: string;
}

/**
 * High-performance virtualized container for DecisionInvoiceCard items.
 *
 * Automatically falls back to lightweight native DOM rendering when items <= threshold
 * (e.g. 50 items on page sizes 25 & 50). Activates windowed virtualization when page size
 * is 100 or 250 rows, keeping active DOM nodes under 800 and ensuring smooth 60 FPS scrolling.
 */
export function VirtualizedDecisionInvoiceList<T>({
  items,
  renderItem,
  getItemKey,
  selectAll,
  estimateSize = 190,
  maxHeight = "72vh",
  overscan = 5,
  threshold = 50,
  className = "",
}: VirtualizedDecisionInvoiceListProps<T>) {
  const parentRef = useRef<HTMLDivElement>(null);

  const shouldVirtualize = items.length > threshold;

  const rowVirtualizer = useVirtualizer({
    count: shouldVirtualize ? items.length : 0,
    getScrollElement: () => parentRef.current,
    estimateSize: () => estimateSize,
    overscan,
  });

  const virtualItems = shouldVirtualize ? rowVirtualizer.getVirtualItems() : [];
  const totalSize = shouldVirtualize ? rowVirtualizer.getTotalSize() : 0;

  // Unvirtualized path for light page sizes (<= 50 rows)
  if (!shouldVirtualize) {
    return (
      <div className={`space-y-3 ${className}`}>
        {selectAll ? (
          <div className="flex items-center gap-3 rounded-[10px] border border-[#E2E8F0] bg-[#FAFAFA] px-4 py-2.5 shadow-sm">
            {selectAll}
          </div>
        ) : null}
        <div className="space-y-3">
          {items.map((item, index) => (
            <div key={getItemKey ? getItemKey(item, index) : index}>
              {renderItem(item, index)}
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Virtualized path for large page sizes (> 50 rows, e.g. 100 or 250)
  return (
    <div className={`space-y-3 ${className}`}>
      {selectAll ? (
        <div className="flex items-center gap-3 rounded-[10px] border border-[#E2E8F0] bg-[#FAFAFA] px-4 py-2.5 shadow-sm">
          {selectAll}
        </div>
      ) : null}

      <div
        ref={parentRef}
        className="overflow-y-auto rounded-[10px] border border-[#E2E8F0] bg-[#FAFAFA]/40 p-2 shadow-inner"
        style={{ maxHeight }}
      >
        <div
          style={{
            height: `${totalSize}px`,
            width: "100%",
            position: "relative",
          }}
        >
          {virtualItems.map((virtualRow) => {
            const item = items[virtualRow.index];
            const itemKey = getItemKey
              ? getItemKey(item, virtualRow.index)
              : virtualRow.key;

            return (
              <div
                key={itemKey}
                data-index={virtualRow.index}
                ref={rowVirtualizer.measureElement}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  transform: `translateY(${virtualRow.start}px)`,
                  paddingBottom: "12px",
                }}
              >
                {renderItem(item, virtualRow.index)}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
