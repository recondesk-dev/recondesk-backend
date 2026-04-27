export function formatInrCompact(amount: number): string {
  if (amount >= 1e7) {
    return `₹${(amount / 1e7).toFixed(2)}Cr`;
  }
  return `₹${(amount / 1e5).toFixed(2)}L`;
}

export function formatInrFull(n: number): string {
  return `₹${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(n)}`;
}

export function formatInrAxis(n: number): string {
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(1)}Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(1)}L`;
  if (n >= 1e3) return `₹${(n / 1e3).toFixed(0)}K`;
  return `₹${n}`;
}

export function truncateGstin(gstin: string): string {
  if (gstin.length <= 12) return gstin;
  return `${gstin.slice(0, 7)}…${gstin.slice(-4)}`;
}
