/** Simple line-art illustration: document + magnifying glass (monochrome). */
export function EmptyStateIllustration({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="120"
      height="88"
      viewBox="0 0 120 88"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
    >
      <rect
        x="12"
        y="16"
        width="76"
        height="56"
        rx="4"
        stroke="currentColor"
        strokeWidth="1.5"
        className="text-gray-400"
      />
      <path
        d="M22 28h24M22 38h56M22 48h40"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        className="text-gray-300"
      />
      <circle
        cx="90"
        cy="36"
        r="11"
        stroke="currentColor"
        strokeWidth="1.5"
        className="text-gray-500"
      />
      <path
        d="M99 44l10 10"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        className="text-gray-500"
      />
    </svg>
  );
}
