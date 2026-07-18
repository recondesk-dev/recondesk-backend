import { backendProxyHandlers } from "@/lib/backendProxy";

export const { GET, POST, PATCH, PUT, DELETE, OPTIONS } =
  backendProxyHandlers("/api/notes");
