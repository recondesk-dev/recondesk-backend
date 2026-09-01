"use client";

import { useLocaleSwitcher } from "@/components/providers/LocaleProvider";

export function LanguageToggle() {
  const { locale, setLocale } = useLocaleSwitcher();

  return (
    <div
      role="group"
      aria-label="Language selection"
      className="inline-flex items-center rounded-full border border-[#E2E8F0] bg-white p-1 shadow-sm select-none"
    >
      <button
        type="button"
        onClick={() => setLocale("en")}
        aria-pressed={locale === "en"}
        className={`rounded-full px-2.5 py-1 text-xs transition-all duration-150 ${
          locale === "en"
            ? "bg-[var(--ink)] font-bold text-white shadow-xs"
            : "font-medium text-gray-500 hover:text-gray-900"
        }`}
      >
        EN
      </button>
      <button
        type="button"
        onClick={() => setLocale("hi")}
        aria-pressed={locale === "hi"}
        className={`rounded-full px-2.5 py-1 text-xs transition-all duration-150 ${
          locale === "hi"
            ? "bg-[var(--ink)] font-bold text-white shadow-xs"
            : "font-medium text-gray-500 hover:text-gray-900"
        }`}
      >
        हिं
      </button>
    </div>
  );
}
