import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="border-t bg-background">
      <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-3 px-4 py-6 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <p className="max-w-xl leading-relaxed">
          <span className="font-medium text-foreground">Amber provides information, not medical advice.</span>{" "}
          It never gives a diagnosis. Talk to your doctor or a genetic counselor about decisions.
        </p>
        <nav aria-label="Footer">
          <ul className="flex flex-wrap items-center gap-x-5 gap-y-2">
            <li>
              <Link href="/privacy" className="hover:text-foreground hover:underline underline-offset-2">
                Privacy
              </Link>
            </li>
            <li>
              <Link href="/about-data" className="hover:text-foreground hover:underline underline-offset-2">
                About this data
              </Link>
            </li>
            <li className="font-mono text-[10.5px] uppercase tracking-[0.14em]">Amber — Rare Disease Atlas</li>
          </ul>
        </nav>
      </div>
    </footer>
  );
}
