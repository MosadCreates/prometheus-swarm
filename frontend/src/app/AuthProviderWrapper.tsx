"use client";

import { AuthProvider } from "@/components/AuthProvider";

export function AuthProviderWrapper({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}
