"use client";

// Replaces the root layout when it fails; renders its own document without
// global styles, so it uses inline styles and follows the OS colour scheme.
export default function GlobalError({ retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <html lang="en">
      <body
        style={{
          fontFamily: "system-ui, sans-serif",
          display: "grid",
          placeItems: "center",
          minHeight: "100vh",
          margin: 0,
          colorScheme: "light dark",
        }}
      >
        <title>Amber — Rare Disease Atlas</title>
        <main style={{ maxWidth: 420, padding: 24, textAlign: "center" }}>
          <h1 style={{ fontSize: 20 }}>Amber could not load</h1>
          <p style={{ opacity: 0.7, fontSize: 14 }}>Please try again in a moment.</p>
          <button type="button" onClick={() => retry()} style={{ padding: "8px 14px", borderRadius: 8, cursor: "pointer" }}>
            Try again
          </button>
        </main>
      </body>
    </html>
  );
}
