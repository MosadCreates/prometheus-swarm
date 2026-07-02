import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Prometheus Swarm",
  description: "Autonomous multi-agent ML system live feed",
};

const NAV_STYLE: React.CSSProperties = {
  display: "flex",
  gap: 4,
  padding: "8px 16px",
  borderBottom: "1px solid #1e1e2e",
  background: "#0f0f18",
};

const LINK_STYLE: React.CSSProperties = {
  padding: "6px 14px",
  borderRadius: 4,
  fontSize: 13,
  fontWeight: 500,
  color: "#94a3b8",
  textDecoration: "none",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif", background: "#0a0a0f", color: "#e0e0e0" }}>
        <nav style={NAV_STYLE}>
          <a href="/submit" style={{ ...LINK_STYLE, background: "#3b82f6", color: "#fff" }}>+ New Problem</a>
          <a href="/feed" style={LINK_STYLE}>Feed</a>
          <a href="/jobs" style={LINK_STYLE}>Jobs</a>
          <a href="/drift" style={LINK_STYLE}>Drift Monitor</a>
        </nav>
        {children}
      </body>
    </html>
  );
}
