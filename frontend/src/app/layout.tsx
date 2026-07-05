import type { Metadata } from "next";
import { AuthProviderWrapper } from "./AuthProviderWrapper";
import { Providers } from "@/providers/Providers";
import OrchestratorBanner from "./OrchestratorBanner";
import NavUserMenu from "@/components/NavUserMenu";
import "./globals.css";

export const metadata: Metadata = {
  title: "Prometheus Swarm",
  description: "You describe the task. The swarm does the rest.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet" />

        <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
      </head>
      <body>
        <Providers>
        <AuthProviderWrapper>
          <nav className="fixed top-0 left-0 right-0 z-50 bg-[var(--color-surface-elevated)]/80 backdrop-blur-xl border-b border-[var(--color-border)]">
            <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="w-2 h-2 rounded-full bg-[var(--color-primary)]" />
                <a href="/" className="text-sm font-semibold text-[var(--color-text-primary)] tracking-tight">
                  Prometheus
                </a>
              </div>
              <div className="flex items-center gap-1">
                <a href="/feed" className="nav-link px-3 py-1.5 rounded-lg">
                  Feed
                </a>
                <a href="/jobs" className="nav-link px-3 py-1.5 rounded-lg">
                  Jobs
                </a>
                <a href="/drift" className="nav-link px-3 py-1.5 rounded-lg">
                  Drift
                </a>
                <div className="w-px h-5 bg-[var(--color-border)] mx-2" />
                <NavUserMenu />
              </div>
            </div>
          </nav>
          <OrchestratorBanner />
          <main className="pt-14 min-h-screen">{children}</main>
        </AuthProviderWrapper>
        </Providers>
      </body>
    </html>
  );
}
