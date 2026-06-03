/** Normalize phone to up to 10 national digits for comparison / submit. */
export function normalizeProfilePhone(raw: string): string {
  let digits = raw.replace(/\D/g, "");
  if (digits.startsWith("91") && digits.length > 10) {
    digits = digits.slice(2);
  }
  return digits.slice(0, 10);
}

export function validateIndianPhone(raw: string): string | null {
  const digits = normalizeProfilePhone(raw);
  if (!digits) return null;
  if (!/^[6-9]\d{9}$/.test(digits)) {
    return "Enter a valid 10-digit Indian mobile number";
  }
  return null;
}
