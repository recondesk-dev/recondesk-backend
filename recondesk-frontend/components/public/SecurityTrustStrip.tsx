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
  { icon: Trash2, label: "Files Auto-Deleted", subtitle: "After processing" },
  { icon: Building2, label: "SOC 2 Infrastructure", subtitle: "Certified cloud providers" },
  { icon: ClipboardList, label: "Full Audit Logs", subtitle: "Every action recorded" },
  { icon: Ban, label: "Never Sold", subtitle: "Data never shared" },
];

function SecurityBadgeCard({ icon: Icon, label, subtitle }: SecurityBadge) {
  return (
    <div className="landing-trust-badge mx-[3px] flex shrink-0 items-center gap-2 rounded-xl border border-[#E8E8E8] bg-white px-5 py-2">
      <Icon className="h-4 w-4 shrink-0 text-brand" aria-hidden />
      <div className="whitespace-nowrap">
        <p className="text-[13px] font-medium leading-tight text-[#0A0A0A]">{label}</p>
        <p className="text-[11px] leading-tight text-[#6B6B6B]">{subtitle}</p>
      </div>
    </div>
  );
}

export function SecurityTrustStrip() {
  const badges = [...SECURITY_BADGES, ...SECURITY_BADGES];

  return (
    <section className="landing-trust-strip border-y border-[#E8E8E8] bg-white py-5" aria-label="Security and data protection">
      <p className="text-center text-[11px] font-medium uppercase tracking-[0.08em] text-[#0A0A0A]">
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
