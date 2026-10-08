"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { clearOnboardingDoneCookie } from "@/lib/onboarding-cookie";
import { Bell, ChevronDown, LogOut, User, Menu } from "lucide-react";

interface UserProfile {
  full_name?: string;
  firm_name?: string;
  role?: "Admin" | "Staff";
  email?: string;
}

interface HeaderProps {
  user: UserProfile;
  onMenuToggle?: () => void;
}

const ROLE_BADGE = {
  Admin: "bg-brand-dim text-brand border-brand/20",
  Staff: "bg-amber-100 text-amber-700 border-amber-200",
};

export default function Header({ user, onMenuToggle }: HeaderProps) {
  const router = useRouter();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const role = (user.role ?? "Staff") as "Admin" | "Staff";

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleLogout = () => {
    clearOnboardingDoneCookie();
    window.location.href = "/api/auth/cognito-logout";
  };

  const initials = user.full_name
    ? user.full_name.split(" ").map((n) => n[0]).join("").toUpperCase().slice(0, 2)
    : "U";

  return (
    <header className="h-16 bg-white border-b border-gray-200 flex items-center justify-between px-6 flex-shrink-0">
      {/* Left: mobile menu + breadcrumb */}
      <div className="flex items-center gap-3">
        {onMenuToggle && (
          <button
            onClick={onMenuToggle}
            className="md:hidden text-gray-500 hover:text-gray-700 p-1"
          >
            <Menu size={20} />
          </button>
        )}
        <div className="hidden md:block">
          <p className="text-xs text-gray-400">{user.firm_name ?? "ReconDesk"}</p>
        </div>
      </div>

      {/* Right: notifications + avatar */}
      <div className="flex items-center gap-3">
        {/* Notifications */}
        <button className="relative p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors">
          <Bell size={18} />
          <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-brand rounded-full" />
        </button>

        {/* Avatar dropdown */}
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="flex items-center gap-2.5 p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
          >
            {/* Avatar circle */}
            <div className="w-8 h-8 rounded-full bg-brand flex items-center justify-center text-white text-xs font-semibold flex-shrink-0">
              {initials}
            </div>
            <div className="hidden sm:block text-left">
              <p className="text-sm font-medium text-gray-800 leading-tight">
                {user.full_name ?? "User"}
              </p>
              <span
                className={`inline-flex items-center text-[10px] font-semibold px-1.5 py-0.5 rounded border ${ROLE_BADGE[role]}`}
              >
                {role}
              </span>
            </div>
            <ChevronDown
              size={14}
              className={`text-gray-400 transition-transform ${dropdownOpen ? "rotate-180" : ""}`}
            />
          </button>

          {/* Dropdown menu */}
          {dropdownOpen && (
            <div className="absolute right-0 mt-1 w-56 bg-white rounded-xl shadow-lg border border-gray-200 py-1.5 z-50">
              <div className="px-4 py-2.5 border-b border-gray-100">
                <p className="text-sm font-medium text-gray-800">{user.full_name}</p>
                <p className="text-xs text-gray-500 truncate">{user.email}</p>
                <span
                  className={`inline-flex items-center text-[10px] font-semibold px-1.5 py-0.5 rounded border mt-1 ${ROLE_BADGE[role]}`}
                >
                  {role}
                  {role === "Staff" && (
                    <span className="ml-1 text-[9px] opacity-70">· Limited access</span>
                  )}
                </span>
              </div>
              <button
                onClick={() => {
                  setDropdownOpen(false);
                  router.push("/settings/profile");
                }}
                className="flex items-center gap-2.5 w-full px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
              >
                <User size={14} className="text-gray-400" />
                Profile settings
              </button>
              <div className="border-t border-gray-100 mt-1 pt-1">
                <button
                  onClick={handleLogout}
                  className="flex items-center gap-2.5 w-full px-4 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
                >
                  <LogOut size={14} />
                  Sign out
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
