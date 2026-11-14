/**
 * GitHub's heading anchors, so the manual's own table of contents works both
 * on the website and on GitHub: lower case, punctuation dropped, spaces to
 * hyphens, "-1", "-2" on repeats. One slugger per rendered document.
 */
export function headingSlugger() {
  const seen = new Map<string, number>();
  return (text: string) => {
    const base = text
      .toLowerCase()
      .replace(/[^\p{L}\p{M}\p{N}\p{Pc} -]/gu, "")
      .replace(/ /g, "-");
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return n ? `${base}-${n}` : base;
  };
}
