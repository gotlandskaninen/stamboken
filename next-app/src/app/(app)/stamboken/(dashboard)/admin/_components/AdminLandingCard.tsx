import Link from "next/link";
import { SbIcon, type SbIconName } from "@/components/shell/SbIcon";
import styles from "../admin.module.css";

/**
 * Landningskort (handoff Adminpanel.html:123-128, admin-page.jsx:86-95).
 * Hela kortet är en <Link> — inget CardActionArea, ingen component={Link}.
 * Titeln MÅSTE förbli ett riktigt rubrikelement: landing.test.tsx:78,87,90
 * gör getByRole("heading", { name: title }).
 */
export function AdminLandingCard({
  href,
  title,
  description,
  countLabel,
  icon,
}: {
  href: string;
  title: string;
  description: string;
  countLabel?: string | null;
  icon: SbIconName;
}) {
  return (
    <Link href={href} className={`sb-card ${styles["ad-landing-card"]}`}>
      <span className={styles["ad-landing-icon"]}>
        <SbIcon name={icon} size={20} />
      </span>
      <h2 className={styles["ad-landing-title"]}>{title}</h2>
      <span className={styles["ad-landing-desc"]}>{description}</span>
      {countLabel && <span className="sb-meta">{countLabel}</span>}
    </Link>
  );
}
