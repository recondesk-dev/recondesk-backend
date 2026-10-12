import { backendProxyHandlers } from "@/lib/backendProxy";

export const { GET, POST, OPTIONS } = backendProxyHandlers("/api/admin/coupons");
