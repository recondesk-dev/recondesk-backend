const EMAIL_REGEX =
  /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$/;

export const EMAIL_VALIDATION_MESSAGE = "Enter a valid email address";

export function isValidEmail(email: string): boolean {
  const trimmed = email.trim();
  if (!trimmed || trimmed.length > 254) return false;
  return EMAIL_REGEX.test(trimmed);
}

export type PasswordRule = {
  id: string;
  label: string;
  test: (password: string) => boolean;
};

export const PASSWORD_RULES: PasswordRule[] = [
  { id: "minLength", label: "At least 8 characters", test: (p) => p.length >= 8 },
  { id: "uppercase", label: "At least 1 uppercase letter", test: (p) => /[A-Z]/.test(p) },
  { id: "lowercase", label: "At least 1 lowercase letter", test: (p) => /[a-z]/.test(p) },
  { id: "number", label: "At least 1 number", test: (p) => /\d/.test(p) },
  {
    id: "special",
    label: "At least 1 special character (!@#$%^&* etc.)",
    test: (p) => /[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?`~]/.test(p),
  },
];

export function getUnmetPasswordRules(password: string): PasswordRule[] {
  return PASSWORD_RULES.filter((rule) => !rule.test(password));
}

export function isValidPassword(password: string): boolean {
  return getUnmetPasswordRules(password).length === 0;
}

export function getPasswordStrengthScore(password: string): number {
  return PASSWORD_RULES.filter((rule) => rule.test(password)).length;
}

export type PasswordStrengthLabel = "Weak" | "Fair" | "Good" | "Strong";

export function getPasswordStrengthLabel(score: number): PasswordStrengthLabel {
  if (score <= 1) return "Weak";
  if (score <= 3) return "Fair";
  if (score === 4) return "Good";
  return "Strong";
}
