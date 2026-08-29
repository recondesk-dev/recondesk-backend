"use client";

import type { ReactNode } from "react";

import { ToastProvider } from "@/components/providers/ToastProvider";
import { AuthRecoveryListener } from "@/components/providers/AuthRecoveryListener";

export function RootProviders({ children }: { children: ReactNode }) {
  return (
    <ToastProvider>
      <AuthRecoveryListener />
      {children}
    </ToastProvider>
  );
}
