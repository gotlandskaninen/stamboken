import Link from "next/link";

/** "Guide" in the masthead of the member pages, for those who may read it. */
export function GuideLink() {
  return (
    <Link href="/medlem/guide" className="sb-btn sb-btn-ghost sb-btn-sm">
      Guide
    </Link>
  );
}
