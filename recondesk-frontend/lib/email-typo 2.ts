/**
 * Typo-domain detection for signup email field.
 * Compares email domain against known common providers using Levenshtein distance (1-2 edits).
 */

export const COMMON_EMAIL_DOMAINS = [
  "gmail.com",
  "yahoo.com",
  "outlook.com",
  "hotmail.com",
  "icloud.com",
  "rediffmail.com",
] as const;

/**
 * Calculates the Levenshtein edit distance between two strings.
 */
export function levenshteinDistance(a: string, b: string): number {
  const m = a.length;
  const n = b.length;
  if (m === 0) return n;
  if (n === 0) return m;

  const prevRow: number[] = new Array(n + 1);
  for (let j = 0; j <= n; j++) {
    prevRow[j] = j;
  }

  for (let i = 1; i <= m; i++) {
    const currRow: number[] = new Array(n + 1);
    currRow[0] = i;
    for (let j = 1; j <= n; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      currRow[j] = Math.min(
        currRow[j - 1] + 1, // insertion
        prevRow[j] + 1, // deletion
        prevRow[j - 1] + cost // substitution
      );
    }
    for (let j = 0; j <= n; j++) {
      prevRow[j] = currRow[j];
    }
  }

  return prevRow[n];
}

/**
 * Checks if the domain part of an email matches a known provider with an edit distance of 1 to maxDistance (default 2).
 * Returns the suggested corrected email string if a close match is found, or null if:
 * - Domain is an exact match (distance = 0)
 * - Domain is too different (distance > maxDistance)
 * - Email format is invalid (no @ or missing local/domain part)
 */
export function suggestEmailCorrection(
  email: string,
  commonDomains: readonly string[] = COMMON_EMAIL_DOMAINS,
  maxDistance = 2
): string | null {
  if (!email || typeof email !== "string") {
    return null;
  }

  const trimmed = email.trim();
  const atIndex = trimmed.lastIndexOf("@");
  if (atIndex <= 0 || atIndex === trimmed.length - 1) {
    return null;
  }

  const localPart = trimmed.slice(0, atIndex);
  const domainPart = trimmed.slice(atIndex + 1).toLowerCase();

  let bestMatch: string | null = null;
  let bestDistance = Infinity;

  for (const provider of commonDomains) {
    const target = provider.toLowerCase();
    if (domainPart === target) {
      // Exact match — no suggestion needed
      return null;
    }
    const dist = levenshteinDistance(domainPart, target);
    if (dist <= maxDistance && dist < bestDistance) {
      bestDistance = dist;
      bestMatch = provider;
    }
  }

  if (bestMatch && bestDistance >= 1 && bestDistance <= maxDistance) {
    return `${localPart}@${bestMatch}`;
  }

  return null;
}
