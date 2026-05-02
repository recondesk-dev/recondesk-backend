"use client";

import type { ReactNode } from "react";

import { ToastProvider } from "@/components/providers/ToastProvider";

export function RootProviders({ children }: { children: ReactNode }) {
  return <ToastProvider>{children}</ToastProvider>;
}
