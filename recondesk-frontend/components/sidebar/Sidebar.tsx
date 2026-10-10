"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Logo } from "@/components/ui/Logo";
import {
  LayoutDashboard,
  Users,
  RefreshCcw,
  Layers,
  CreditCard,
  UsersRound,
  Settings,
  ChevronLeft,
  FileText,
  FileCheck,
  Truck,
} from "lucide-react";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/clients", label: "Clients", icon: Users },
  { href: "/reconciliation", label: "Reconciliation", icon: RefreshCcw },
  { href: "/filing", label: "GST Filing", icon: FileCheck },
  { href: "/einvoicing", label: "E-Invoicing", icon: FileText },
  { href: "/einvoicing/ewaybill", label: "E-Way Bill", icon: Truck },
  { href: "/billing", label: "Billing", icon: CreditCard },
  { href: "/team", label: "Team", icon: UsersRound },
  { href: "/settings", label: "Settings", icon: Settings },
];



interface SidebarProps {
  collapsed?: boolean;
  onToggle?: () => void;
}

export default function Sidebar({ collapsed = false, onToggle }: SidebarProps) {
  const pathname = usePathname();

  const isActive = (href: string) => {
    if (href === "/dashboard") return pathname === "/dashboard";
    if (href === "/einvoicing") {
      return pathname === "/einvoicing" || (pathname.startsWith("/einvoicing/") && !pathname.startsWith("/einvoicing/ewaybill"));
    }
    return pathname.startsWith(href);
  };

  return (
    <aside
      className="flex flex-col h-full transition-all duration-300"
      style={{ background: "#0F1117" }}
    >
      {/* Logo */}
      <div className="flex items-center justify-between px-4 h-16 border-b border-white/10 flex-shrink-0">
        {!collapsed && (
          <Link href="/dashboard" className="flex items-center text-white">
            <Logo height={24} className="text-white" />
          </Link>
        )}
        {collapsed && (
          <Link href="/dashboard" className="flex items-center justify-center mx-auto text-white">
            <Logo height={20} className="text-white" />
          </Link>
        )}
        {onToggle && !collapsed && (
          <button
            onClick={onToggle}
            className="text-gray-500 hover:text-gray-300 transition-colors p-1 rounded"
          >
            <ChevronLeft size={16} />
          </button>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {!collapsed && (
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider px-3 mb-3">
            Menu
          </p>
        )}
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={`sidebar-link ${isActive(href) ? "active" : ""} ${
              collapsed ? "justify-center px-2" : ""
            }`}
            title={collapsed ? label : undefined}
          >
            <Icon size={18} className="flex-shrink-0" />
            {!collapsed && <span>{label}</span>}
          </Link>
        ))}
      </nav>

      {/* Bottom separator */}
      <div className="border-t border-white/10 p-3">
        <Link
          href="/settings"
          className={`sidebar-link ${isActive("/settings") ? "active" : ""} ${
            collapsed ? "justify-center px-2" : ""
          }`}
          title={collapsed ? "Settings" : undefined}
        >
          <Settings size={18} className="flex-shrink-0" />
          {!collapsed && <span>Settings</span>}
        </Link>
      </div>
    </aside>
  );
}
