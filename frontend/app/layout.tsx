import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/sonner";
import Sidebar from "@/components/Sidebar";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AgentFromScratch — Runtime Console",
  description: "AI Agent Runtime Monitoring & Control Interface",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} dark h-full`}>
      <body className="antialiased bg-background text-foreground h-full">
        <div className="flex h-full overflow-hidden">
          <Sidebar />
          <main className="flex-1 overflow-auto grid-bg">
            {children}
          </main>
        </div>
        <Toaster theme="dark" position="bottom-right" />
      </body>
    </html>
  );
}
