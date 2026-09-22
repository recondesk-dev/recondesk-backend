"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import { Fragment, useRef, type ReactNode } from "react";

export interface VirtualizedTableProps<T> {
  rows: T[];
  renderHeader: () => ReactNode;
  renderRow: (row: T, index: number, measureRef?: (el: HTMLElement | null) => void) => ReactNode;
  getRowKey?: (row: T, index: number) => string | number;
  colSpan: number;
  estimateRowHeight?: number;
  maxHeight?: string;
  overscan?: number;
  threshold?: number;
  tableClassName?: string;
  containerClassName?: string;
}

/**
 * High-performance virtualized container for standard HTML tables (e.g. Matched Invoices).
 *
 * Keeps table headers sticky at the top while virtualizing rows when row count exceeds threshold.
 * Uses spacer rows in tbody for accurate scrollbar dimensions and 60 FPS scrolling.
 */
export function VirtualizedTable<T>({
  rows,
  renderHeader,
  renderRow,
  getRowKey,
  colSpan,
  estimateRowHeight = 44,
  maxHeight = "72vh",
  overscan = 5,
  threshold = 50,
  tableClassName = "w-full text-left text-xs",
  containerClassName = "w-full min-w-0 max-w-full overflow-x-auto",
}: VirtualizedTableProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null);

  const shouldVirtualize = rows.length > threshold;

  const rowVirtualizer = useVirtualizer({
    count: shouldVirtualize ? rows.length : 0,
    getScrollElement: () => containerRef.current,
    estimateSize: () => estimateRowHeight,
    overscan,
  });

  const virtualRows = shouldVirtualize ? rowVirtualizer.getVirtualItems() : [];
  const totalSize = shouldVirtualize ? rowVirtualizer.getTotalSize() : 0;

  const paddingTop = virtualRows.length > 0 ? virtualRows[0]?.start ?? 0 : 0;
  const paddingBottom =
    virtualRows.length > 0
      ? totalSize - (virtualRows[virtualRows.length - 1]?.end ?? 0)
      : 0;

  return (
    <div
      ref={containerRef}
      className={`${containerClassName} ${shouldVirtualize ? "overflow-y-auto rounded-[8px] border border-[#E2E8F0]" : ""}`}
      style={shouldVirtualize ? { maxHeight } : undefined}
    >
      <table className={tableClassName}>
        {renderHeader()}
        <tbody>
          {!shouldVirtualize ? (
            rows.map((row, index) => (
              <Fragment key={getRowKey ? getRowKey(row, index) : index}>
                {renderRow(row, index)}
              </Fragment>
            ))
          ) : (
            <>
              {paddingTop > 0 && (
                <tr style={{ height: `${paddingTop}px` }}>
                  <td colSpan={colSpan} className="p-0 border-0" />
                </tr>
              )}
              {virtualRows.map((virtualRow) => {
                const row = rows[virtualRow.index];
                const key = getRowKey
                  ? getRowKey(row, virtualRow.index)
                  : virtualRow.key;
                return (
                  <Fragment key={key}>
                    {renderRow(row, virtualRow.index, (el) => {
                      if (el) {
                        el.setAttribute("data-index", String(virtualRow.index));
                        rowVirtualizer.measureElement(el);
                      }
                    })}
                  </Fragment>
                );
              })}
              {paddingBottom > 0 && (
                <tr style={{ height: `${paddingBottom}px` }}>
                  <td colSpan={colSpan} className="p-0 border-0" />
                </tr>
              )}
            </>
          )}
        </tbody>
      </table>
    </div>
  );
}
