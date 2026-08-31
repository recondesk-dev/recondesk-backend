"use client";

import { useEffect } from "react";

import { startKeepalive } from "@/lib/keepalive";

/**
 * Invisible component that starts the backend keep-alive ping once
 * the app is mounted in the browser. Renders nothing.
 */
export function KeepAlive() {
  useEffect(() => {
    startKeepalive();
  }, []);

  return null;
}
