import { backendProxyHandlers } from "@/lib/backendProxy";

export const maxDuration = 60;

export const { GET, POST, PATCH, PUT, DELETE, OPTIONS } =
  backendProxyHandlers("/api/filing");
