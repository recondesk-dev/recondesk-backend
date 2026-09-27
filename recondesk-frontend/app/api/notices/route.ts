import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/backendProxy";

async function handle(request: NextRequest) {
  return proxyToBackend(request, "/api/notices");
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const PUT = handle;
export const DELETE = handle;
export const OPTIONS = handle;
