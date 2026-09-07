import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Accountant - Intelligent ERP",
  description: "AI-native accounting and financial ERP for small businesses",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="h-full">{children}</body>
    </html>
  );
}
