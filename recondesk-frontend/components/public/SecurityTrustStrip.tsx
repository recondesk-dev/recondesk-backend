import {
  Ban,
  Building2,
  ClipboardList,
  Lock,
  Shield,
  Trash2,
  Users,
  type LucideIcon,
} from "lucide-react";

type SecurityBadge = {
  icon: LucideIcon;
  label: string;
  subtitle: string;
};

const SECURITY_BADGES: SecurityBadge[] = [
  { icon: Lock, label: "AES-256 Encrypted", subtitle: "Data at rest" },
  { icon: Shield, label: "TLS 1.2+ in Transit", subtitle: "All connections encrypted" },
  { icon: Users, label: "Full Data Isolation", subtitle: "Per CA, per client" },
  { icon: Trash2, label: "Delete Your Data", subtitle: "Anytime, on request" },
  { icon: Building2, label: "SOC 2 Infrastructure", subtitle: "Certified cloud providers" },
  { icon: ClipboardList, label: "Full Audit Logs", subtitle: "Every action recorded" },
  { icon: Ban, label: "Never Sold", subtitle: "Data never shared" },
];

function SecurityBadgeCard({ icon: Icon, label, subtitle }: SecurityBadge) {
  return (
    <div className="landing-trust-badge mx-[3px] flex shrink-0 items-center gap-2 rounded-2xl bg-white px-5 py-2.5 shadow-[var(--shadow-soft)]">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#F3F4F6] text-gray-700">
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <div className="whitespace-nowrap">
        <p className="text-[13px] font-medium leading-tight text-[var(--ink)]">{label}</p>
        <p className="text-[11px] leading-tight text-gray-500">{subtitle}</p>
      </div>
    </div>
  );
}

export function SecurityTrustStrip() {
  const badges = [...SECURITY_BADGES, ...SECURITY_BADGES];

  return (
    <section className="landing-trust-strip py-6" aria-label="Security and data protection">
      <p className="text-center text-[11px] font-medium uppercase tracking-[0.08em] text-gray-500">
        YOUR CLIENTS&apos; DATA IS PROTECTED
      </p>
      <div className="landing-trust-marquee relative mt-4 overflow-hidden">
        <div className="landing-trust-track flex w-max">
          {badges.map((badge, index) => (
            <SecurityBadgeCard key={`${badge.label}-${index}`} {...badge} />
          ))}
        </div>
      </div>
    </section>
  );
}
