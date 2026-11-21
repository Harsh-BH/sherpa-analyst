import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AppSidebar } from "@/components/shell/app-sidebar";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SherpaProvider } from "@/lib/store";
import { THEME_SCRIPT } from "@/lib/theme";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Sherpa",
  description: "Governed AI business analyst: every number traces to an executed query.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // the head script sets class="dark" before React hydrates
    <html lang="en" suppressHydrationWarning className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
      <head>
        <script>{THEME_SCRIPT}</script>
      </head>
      <body>
        <SherpaProvider>
          <TooltipProvider>
            <SidebarProvider>
              <AppSidebar />
              <SidebarInset className="h-svh min-w-0 overflow-hidden">
                <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3 md:hidden">
                  <SidebarTrigger />
                  <span className="font-semibold">Sherpa</span>
                </header>
                {children}
              </SidebarInset>
            </SidebarProvider>
          </TooltipProvider>
        </SherpaProvider>
      </body>
    </html>
  );
}
