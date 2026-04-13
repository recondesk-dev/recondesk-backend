export const dynamic = "force-dynamic";

import { createClient } from "@/lib/supabase/server";
import {
  Users,
  RefreshCcw,
  CheckCircle2,
  AlertCircle,
  TrendingUp,
  Clock,
  ArrowUpRight,
  ArrowDownRight,
} from "lucide-react";

const STAT_CARDS = [
  {
    label: "Total Clients",
    value: "—",
    change: null,
    icon: Users,
    iconBg: "bg-blue-100",
    iconColor: "text-blue-600",
  },
  {
    label: "Reconciliations",
    value: "—",
    change: null,
    icon: RefreshCcw,
    iconBg: "bg-purple-100",
    iconColor: "text-purple-600",
  },
  {
    label: "Completed",
    value: "—",
    change: null,
    icon: CheckCircle2,
    iconBg: "bg-green-100",
    iconColor: "text-green-600",
  },
  {
    label: "Pending Review",
    value: "—",
    change: null,
    icon: Clock,
    iconBg: "bg-amber-100",
    iconColor: "text-amber-600",
  },
];

const RECENT_ACTIVITY = [
  { id: 1, title: "Bank reconciliation completed", client: "Acme Corp", time: "2 hours ago", status: "completed" },
  { id: 2, title: "Discrepancy flagged", client: "Beta Industries", time: "5 hours ago", status: "alert" },
  { id: 3, title: "Monthly report generated", client: "Gamma LLC", time: "Yesterday", status: "completed" },
  { id: 4, title: "Reconciliation started", client: "Delta Partners", time: "Yesterday", status: "in-progress" },
];

const STATUS_STYLES = {
  completed: "bg-green-100 text-green-700",
  alert: "bg-red-100 text-red-700",
  "in-progress": "bg-blue-100 text-blue-700",
};

const STATUS_LABELS = {
  completed: "Completed",
  alert: "Alert",
  "in-progress": "In Progress",
};

export default async function DashboardPage() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const userName =
    user?.user_metadata?.full_name?.split(" ")[0] ?? "there";

  return (
    <div className="space-y-8">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">
          Good morning, {userName} 👋
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Here&apos;s what&apos;s happening with your reconciliations today.
        </p>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {STAT_CARDS.map(({ label, value, change, icon: Icon, iconBg, iconColor }) => (
          <div
            key={label}
            className="bg-white rounded-xl border border-gray-200 p-5 hover:shadow-sm transition-shadow"
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
                <p className="text-2xl font-bold text-gray-900 mt-1.5">{value}</p>
                {change !== null && (
                  <p
                    className={`text-xs mt-1 flex items-center gap-0.5 ${
                      Number(change) >= 0 ? "text-green-600" : "text-red-600"
                    }`}
                  >
                    {Number(change) >= 0 ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                    {Math.abs(Number(change))}% vs last month
                  </p>
                )}
              </div>
              <div className={`p-2.5 rounded-lg ${iconBg}`}>
                <Icon size={18} className={iconColor} />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Content grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent activity */}
        <div className="lg:col-span-2 bg-white rounded-xl border border-gray-200">
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900">Recent Activity</h2>
            <button className="text-xs text-purple-600 hover:text-purple-700 font-medium">
              View all
            </button>
          </div>
          <div className="divide-y divide-gray-100">
            {RECENT_ACTIVITY.map((item) => (
              <div key={item.id} className="flex items-start gap-4 px-6 py-4">
                <div
                  className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${
                    item.status === "completed"
                      ? "bg-green-500"
                      : item.status === "alert"
                      ? "bg-red-500"
                      : "bg-blue-500"
                  }`}
                />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800">{item.title}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{item.client}</p>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <span
                    className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${
                      STATUS_STYLES[item.status as keyof typeof STATUS_STYLES]
                    }`}
                  >
                    {STATUS_LABELS[item.status as keyof typeof STATUS_LABELS]}
                  </span>
                  <span className="text-xs text-gray-400">{item.time}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Quick actions */}
        <div className="bg-white rounded-xl border border-gray-200">
          <div className="px-6 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900">Quick Actions</h2>
          </div>
          <div className="p-4 space-y-2">
            {[
              { label: "New Reconciliation", icon: RefreshCcw, color: "text-purple-600 bg-purple-50 hover:bg-purple-100" },
              { label: "Add Client", icon: Users, color: "text-blue-600 bg-blue-50 hover:bg-blue-100" },
              { label: "View Reports", icon: TrendingUp, color: "text-green-600 bg-green-50 hover:bg-green-100" },
              { label: "Review Alerts", icon: AlertCircle, color: "text-amber-600 bg-amber-50 hover:bg-amber-100" },
            ].map(({ label, icon: Icon, color }) => (
              <button
                key={label}
                className={`flex items-center gap-3 w-full px-4 py-3 rounded-lg text-sm font-medium transition-colors ${color}`}
              >
                <Icon size={16} />
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
