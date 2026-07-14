/** Client-side aggregation of reconcile bucket rows by supplier GSTIN. */

export type SupplierGroupableRow = {
  id: string;
  supplier_gstin: string;
  trade_name?: string | null;
  amount: number;
};

export type SupplierGroup<T extends SupplierGroupableRow = SupplierGroupableRow> = {
  gstin: string;
  tradeName: string;
  invoiceCount: number;
  totalAmount: number;
  invoices: T[];
};

/**
 * Aggregate invoices by supplier GSTIN.
 * Sorted by total amount descending (stable by GSTIN for ties).
 */
export function groupRowsBySupplier<T extends SupplierGroupableRow>(
  rows: T[]
): SupplierGroup<T>[] {
  const map = new Map<string, SupplierGroup<T>>();

  for (const row of rows) {
    const gstin = (row.supplier_gstin || "").trim().toUpperCase();
    if (!gstin) continue;

    const existing = map.get(gstin);
    const tradeName =
      (row.trade_name && String(row.trade_name).trim()) || "";

    if (!existing) {
      map.set(gstin, {
        gstin,
        tradeName,
        invoiceCount: 1,
        totalAmount: Number(row.amount) || 0,
        invoices: [row],
      });
      continue;
    }

    if (!existing.tradeName && tradeName) {
      existing.tradeName = tradeName;
    }
    existing.invoiceCount += 1;
    existing.totalAmount += Number(row.amount) || 0;
    existing.invoices.push(row);
  }

  return Array.from(map.values()).sort(
    (a, b) =>
      b.totalAmount - a.totalAmount || a.gstin.localeCompare(b.gstin)
  );
}

/** Fetch every page of a paginated reconcile bucket (max 250/page). */
export async function fetchAllBucketPages<T>(
  fetchPage: (page: number, limit: number) => Promise<{
    data: T[];
    total_pages: number;
  }>,
  limit = 250
): Promise<T[]> {
  const all: T[] = [];
  let page = 1;
  let totalPages = 1;
  do {
    const res = await fetchPage(page, limit);
    all.push(...(res.data ?? []));
    totalPages = res.total_pages ?? 1;
    page += 1;
  } while (page <= totalPages);
  return all;
}
