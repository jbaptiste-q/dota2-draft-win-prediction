import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Dota 2 Draft Lab — Radiant vs Dire",
  description:
    "Build two completed Dota 2 lineups and reveal an explainable battle forecast.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
