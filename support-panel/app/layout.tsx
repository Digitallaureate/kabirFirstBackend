import type { Metadata } from "next";
import "./styles.css";
import { AppShell } from "@/components/app-shell";

export const metadata: Metadata = {
  title: "Traviz Support Panel",
  description: "Customer support operations panel for Traviz"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
