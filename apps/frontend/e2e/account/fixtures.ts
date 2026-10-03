import { expect, type Page } from "@playwright/test";

/**
 * Assert that nothing health-related ended up in the URL or browser storage
 * (docs/compliance.md). `terms` are the health strings the test typed or
 * received from mocks.
 */
export async function expectNoHealthDataInBrowser(page: Page, terms: string[]) {
  const url = decodeURIComponent(page.url());
  const storage = await page.evaluate(() => {
    const dump = (s: Storage) => {
      const out: string[] = [];
      for (let i = 0; i < s.length; i++) {
        const k = s.key(i)!;
        out.push(`${k}=${s.getItem(k)}`);
      }
      return out.join("\n");
    };
    return `${dump(window.localStorage)}\n${dump(window.sessionStorage)}`;
  });
  for (const t of terms) {
    expect(url, `URL contains "${t}"`).not.toContain(t);
    expect(storage, `browser storage contains "${t}"`).not.toContain(t);
  }
}

export const consentRecord = (type: "upload" | "contribute", extra: Record<string, unknown> = {}) => ({
  id: `c-${type}`,
  consent_type: type,
  version: `${type}-2026-10-04`,
  granted_at: "2026-10-01T10:00:00Z",
  revoked_at: null,
  about_child: false,
  parental_responsibility_confirmed: false,
  active: true,
  ...extra,
});
