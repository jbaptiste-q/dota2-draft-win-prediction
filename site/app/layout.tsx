import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Draft Lab — Completed Draft Analysis",
  description:
    "Experimental, explainable completed-draft probability analysis for professional Dota 2.",
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
