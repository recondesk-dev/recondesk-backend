"use client";
import type { ReactNode } from "react";
import { ToastProvider } from "@/components/providers/ToastProvider";
import { AuthRecoveryListener } from "@/components/providers/AuthRecoveryListener";
import { LocaleProvider } from "@/components/providers/LocaleProvider";
import { PostHogProvider } from "@/components/providers/PostHogProvider";

export function RootProviders({ children }: { children: ReactNode }) {
  return (
    <PostHogProvider>
      <LocaleProvider>
        <ToastProvider>
          <AuthRecoveryListener />
          {children}
        </ToastProvider>
      </LocaleProvider>
    </PostHogProvider>
  );
}
