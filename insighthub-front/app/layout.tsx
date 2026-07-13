import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Sidebar from "./components/Sidebar";
import AppFooter from "./components/AppFooter";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "InsightHub — Plateforme de connaissance unifiee",
  description:
    "InsightHub connecte vos outils (Jira, ServiceNow, SharePoint, SQL…) et vous permet d'interroger l'ensemble de vos donnees en langage naturel.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" className={inter.variable}>
      <body>
        <div className="app-shell">
          <Sidebar />
          <div className="main-area">
            {children}
            <AppFooter />
          </div>
        </div>
      </body>
    </html>
  );
}
