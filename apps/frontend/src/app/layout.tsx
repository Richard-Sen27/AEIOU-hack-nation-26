import type { Metadata, Viewport } from "next";
import { Archivo, JetBrains_Mono } from "next/font/google";

import { Providers } from "@/components/providers";
import { SiteFooter } from "@/components/shell/site-footer";
import { SiteHeader } from "@/components/shell/site-header";

import "./globals.css";

const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Amber",
    template: "%s · Amber",
  },
  description:
    "A sourced knowledge graph of rare diseases: find who shares your disease's mechanism or symptoms, what research, registries and trials already exist, and what to do together next. Every connection is cited and rated for confidence.",
  applicationName: "Amber",
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#e9ebee" },
    { media: "(prefers-color-scheme: dark)", color: "#151c1a" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${archivo.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col has-[[data-fit-viewport]]:h-dvh">
        <Providers>
          <a
            href="#main"
            className="sr-only z-[100] rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
          >
            Skip to content
          </a>
          <SiteHeader />
          <main id="main" tabIndex={-1} className="flex flex-1 flex-col outline-none has-[[data-fit-viewport]]:min-h-0">
            {children}
          </main>
          <SiteFooter />
        </Providers>
      </body>
    </html>
  );
}
