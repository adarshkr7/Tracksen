import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SAMANVAY — Unified Block Plan",
  description:
    "AI-assisted maintenance block planning across Engineering, S&T and Traction on Indian Railways.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
