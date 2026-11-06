import { test, expect } from "@playwright/test";

// ADR-0010, 375-px-kravet on a 375px touch screen: field text at least 16px
// (iOS zooms in on focus below that), tap targets at least 44 × 44px with 8px
// between targets side by side, and no horizontal scroll. The touch rules
// live behind `@media (pointer: coarse)`, which hasTouch turns on.
test.use({
  viewport: { width: 375, height: 812 },
  hasTouch: true,
  isMobile: true,
});

const PAGES = [
  "/stamboken/min-besattning?tab=overview",
  "/stamboken/min-besattning?tab=individuals",
  "/stamboken/min-besattning?tab=breeding",
  "/stamboken/min-besattning?tab=pedigree",
  "/stamboken/profil",
  "/stamboken/individ/G1274-2112",
  "/stamboken/provparning",
  "/stamboken/alla-kaniner",
];

const PASS = { text: [], small: [], tight: [], overflow: false };

function measure() {
  const visible = (el: Element) => {
    const r = el.getBoundingClientRect();
    return (
      r.width > 0 &&
      r.height > 0 &&
      getComputedStyle(el).visibility !== "hidden" &&
      !el.closest("[aria-hidden=true]")
    );
  };
  const label = (el: Element) => {
    const r = el.getBoundingClientRect();
    const name = (
      el.getAttribute("aria-label") || (el as HTMLElement).innerText
    )
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 30);
    return `${el.tagName.toLowerCase()} "${name}" ${r.width.toFixed(1)}×${r.height.toFixed(1)}`;
  };

  const fields = document.querySelectorAll(
    "input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=file]), select, textarea",
  );
  const text = [...fields]
    .filter(
      (el) => visible(el) && parseFloat(getComputedStyle(el).fontSize) < 16,
    )
    .map(label);

  const small = new Set<string>();
  const boxes: [Element, DOMRect][] = [];
  const targets = document.querySelectorAll(
    "button, a[href], [role=button], [role=tab], [role=switch], [role=combobox], summary, input[type=checkbox], input[type=radio], select",
  );
  for (const el of targets) {
    if (!visible(el)) continue;
    // Links in running text are exempt, as in WCAG 2.5.8.
    if (el.tagName === "A" && getComputedStyle(el).display === "inline")
      continue;
    // The whole Autocomplete field opens the list.
    if (
      el.matches(
        ".MuiAutocomplete-popupIndicator, .MuiAutocomplete-clearIndicator",
      )
    )
      continue;
    // A field's input is reached through the whole field; a hidden switch or
    // checkbox input through its label or MUI wrapper.
    const box =
      el.closest(".MuiInputBase-root") ??
      (el.matches("input[type=checkbox], input[type=radio]")
        ? (el.closest("label") ?? el.parentElement ?? el)
        : el);
    const r = box.getBoundingClientRect();
    if (r.width < 43.5 || r.height < 43.5) small.add(label(box));
    boxes.push([box, r]);
  }

  const tight = new Set<string>();
  boxes.forEach(([a, ra], i) => {
    for (const [b, rb] of boxes.slice(i + 1)) {
      if (a.contains(b) || b.contains(a)) continue;
      // The sticky topbar and tab bar overlap scrolled content, not neighbours.
      if (
        a.closest("header, [role=tablist]") !==
        b.closest("header, [role=tablist]")
      )
        continue;
      // Tabs, segmented buttons, list rows and cards sit edge to edge.
      const parent = a.parentElement;
      if (
        parent &&
        parent === b.parentElement &&
        parent.matches("[role=tablist], [role=group]")
      )
        continue;
      if (ra.height > 56 && rb.height > 56) continue;
      const overlapY =
        Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
      if (overlapY < Math.min(ra.height, rb.height) / 2) continue;
      const gapX = Math.max(ra.left, rb.left) - Math.min(ra.right, rb.right);
      if (gapX < 7.5) tight.add(`${label(a)} | ${label(b)}`);
    }
  });

  return {
    text,
    small: [...small],
    tight: [...tight],
    overflow: document.documentElement.scrollWidth > window.innerWidth,
  };
}

test.describe("ADR-0010 375-px-kravet on touch", () => {
  for (const url of PAGES) {
    test(url, async ({ page }) => {
      await page.goto(url, { waitUntil: "networkidle" });
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      expect(await page.evaluate(measure)).toEqual(PASS);
    });
  }

  test("an open litter card with its roster", async ({ page }) => {
    await page.goto("/stamboken/min-besattning?tab=breeding", {
      waitUntil: "networkidle",
    });
    await page
      .locator('[data-testid="breeding-card"]')
      .filter({ hasText: /Visby Stamfar|Visby Stammor/ })
      .first()
      .getByRole("button", { name: "Detaljer" })
      .click();
    await expect(page.getByText(/Kullista/).first()).toBeVisible();
    expect(await page.evaluate(measure)).toEqual(PASS);
  });
});
