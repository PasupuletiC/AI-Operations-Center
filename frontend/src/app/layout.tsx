import type { Metadata, Viewport } from "next";
import { Inter, Outfit, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
  weight: ["300", "400", "500", "600", "700", "800", "900"],
});

const outfit = Outfit({
  subsets: ["latin"],
  variable: "--font-outfit",
  display: "swap",
  weight: ["300", "400", "500", "600", "700", "800"],
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "AI Operations Center — Enterprise Command",
  description: "Real-time multi-agent AI system for enterprise incident response, intelligent email triage, and automated operations management.",
  keywords: ["AI Operations", "Incident Management", "LangGraph", "Enterprise AI", "SLA Tracker"],
  authors: [{ name: "AI Ops Team" }],
  robots: "noindex, nofollow",
  openGraph: {
    title: "AI Operations Center",
    description: "Enterprise multi-agent AI dashboard",
    type: "website",
  },
};

export const viewport: Viewport = {
  themeColor: "#050810",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body
        className={`${inter.variable} ${outfit.variable} ${jetbrainsMono.variable} antialiased selection:bg-indigo-500/25 selection:text-indigo-200`}
      >
        {/* Aurora glow orbs */}
        <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden" aria-hidden="true">
          <div className="absolute -top-40 -left-40 w-[700px] h-[700px] rounded-full bg-indigo-600/8 blur-[120px] animate-pulse" style={{ animationDuration: "8s" }} />
          <div className="absolute top-1/2 -right-40 w-[500px] h-[500px] rounded-full bg-violet-600/6 blur-[100px] animate-pulse" style={{ animationDuration: "12s", animationDelay: "3s" }} />
          <div className="absolute -bottom-40 left-1/3 w-[600px] h-[400px] rounded-full bg-cyan-600/5 blur-[100px] animate-pulse" style={{ animationDuration: "10s", animationDelay: "6s" }} />
        </div>
        <main className="relative z-10 min-h-screen text-slate-200">
          {children}
        </main>
      </body>
    </html>
  );
}
