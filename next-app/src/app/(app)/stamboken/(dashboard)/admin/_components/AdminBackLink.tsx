import Link from "next/link";
import ds from "@/styles/ds-admin.module.css";

/**
 * 13px tillbakalänk (handoff Adminpanel.html:41-42, README "Breadcrumbs are
 * removed; detail pages use a '← Alla användare' back link"). Ersätter
 * <Breadcrumbs> på alla sidor som inte är en flikdestination.
 */
export function AdminBackLink({
  href,
  label,
}: {
  href: string;
  label: string;
}) {
  return (
    <Link href={href} className={ds["ad-back"]}>
      ← {label}
    </Link>
  );
}
