import { NextRequest } from "next/server";

import { proxyToBackend } from "@/lib/backendProxy";

type RouteContext = { params: { path: string[] } };

async function handle(request: NextRequest, context: RouteContext) {
  const segments = context.params.path ?? [];
  const targetPath = `/api/gstr2a-delta/${segments.map(encodeURIComponent).join("/")}`;
  return proxyToBackend(request, targetPath);
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const PUT = handle;
export const DELETE = handle;
export const OPTIONS = handle;
