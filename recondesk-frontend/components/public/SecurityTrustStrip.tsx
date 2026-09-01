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
    <div className="landing-trust-badge mx-2 flex shrink-0 items-center gap-3 rounded-[10px] border border-[#E5E5E2] bg-white px-4 py-2.5 shadow-xs">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] bg-[#F5F5F3] text-[#0A0A0A]">
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <div className="whitespace-nowrap">
        <p className="text-xs font-semibold leading-tight text-[#0A0A0A]">{label}</p>
        <p className="text-[11px] leading-tight text-[#6B6B6B]">{subtitle}</p>
      </div>
    </div>
  );
}

export function SecurityTrustStrip() {
  const badges = [...SECURITY_BADGES, ...SECURITY_BADGES];

  return (
    <section className="landing-trust-strip py-10" aria-label="Security and data protection">
      <p className="text-center text-xs font-bold uppercase tracking-widest text-[#6B6B6B]">
        YOUR CLIENTS&apos; DATA IS PROTECTED
      </p>
      <div className="landing-trust-marquee relative mt-5 overflow-hidden">
        <div className="landing-trust-track flex w-max">
          {badges.map((badge, index) => (
            <SecurityBadgeCard key={`${badge.label}-${index}`} {...badge} />
          ))}
        </div>
      </div>
    </section>
  );
}
