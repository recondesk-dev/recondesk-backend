import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/backendProxy";

export async function POST(request: NextRequest) {
  return proxyToBackend(request, "/api/coupons/validate");
}
