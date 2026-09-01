"use client";

import type { ReactNode } from "react";

import { ToastProvider } from "@/components/providers/ToastProvider";
import { AuthRecoveryListener } from "@/components/providers/AuthRecoveryListener";
import { LocaleProvider } from "@/components/providers/LocaleProvider";

export function RootProviders({ children }: { children: ReactNode }) {
  return (
    <LocaleProvider>
      <ToastProvider>
        <AuthRecoveryListener />
        {children}
      </ToastProvider>
    </LocaleProvider>
  );
}
