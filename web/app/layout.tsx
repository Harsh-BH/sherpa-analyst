import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AppSidebar } from "@/components/shell/app-sidebar";
import { PaletteProvider } from "@/components/shell/command-palette";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
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
              <PaletteProvider>
                <AppSidebar />
                {/* the compact top bar on phones (menu, palette, Inspector) is Workspace's, so pages own it */}
                <SidebarInset className="h-svh min-w-0 overflow-hidden">{children}</SidebarInset>
              </PaletteProvider>
            </SidebarProvider>
          </TooltipProvider>
        </SherpaProvider>
      </body>
    </html>
  );
}
