import type { Metadata, Viewport } from "next";
import "./globals.css";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  themeColor: "#FBF1E3",
};

export const metadata: Metadata = {
  title: "Media Monitoring",
  description: "Dashboard Operasional & Pemantauan Berita Ditjen Industri Agro, Kementerian Perindustrian RI",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="id">
      <body>{children}</body>
    </html>
  );
}
