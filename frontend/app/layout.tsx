import type { Metadata } from "next";

import { Inter } from "next/font/google";
import { AppShell } from "@/components/app-shell";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "ScalistAI",
  description: "Cómputo métrico automatizado para preconstrucción",
};

const themeInitScript = `
(function() {
  try {
    var t = localStorage.getItem('scalistai_theme');
    var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (t === 'dark' || (!t && prefersDark)) {
      document.documentElement.classList.add('dark');
    }
  } catch (e) {}
})();
`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className={`${inter.variable} font-sans`}>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
