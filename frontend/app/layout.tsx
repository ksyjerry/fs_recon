import type { Metadata } from "next";
import "./globals.css";
import Header from "./components/Header";

export const metadata: Metadata = {
  title: "국영문 보고서 대사 | Samil PwC",
  description: "국영문 보고서 대사 시스템",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="bg-pwc-grey-5 min-h-screen flex flex-col">
        <Header />
        <main className="flex-1">{children}</main>
        <footer className="bg-pwc-grey-90 py-4 text-center text-xs text-pwc-grey-20">
          © 2025 Samil PricewaterhouseCoopers. All rights reserved.
        </footer>
      </body>
    </html>
  );
}
