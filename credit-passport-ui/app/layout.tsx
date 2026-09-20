import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Credit Passport",
  description: "Build and review a portable record of cross-border financial evidence.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en-IN">
      <body className="antialiased">{children}</body>
    </html>
  );
}
