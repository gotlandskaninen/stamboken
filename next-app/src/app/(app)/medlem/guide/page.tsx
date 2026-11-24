import { readFile } from "node:fs/promises";
import path from "node:path";
import { notFound } from "next/navigation";
import { getUser } from "@/lib/auth";
import { Masthead } from "@/components/shell/Masthead";
import { ManualArticle } from "@/components/manual/ManualArticle";
import styles from "../medlem.module.css";
import { GUIDE_DIR, GUIDE_IMAGE_URL, canReadGuide } from "./guide";

export const dynamic = "force-dynamic";

export default async function MatrikelGuidePage() {
  // Not a 403: everyone else should not learn the page exists.
  if (!canReadGuide(await getUser())) notFound();
  const markdown = await readFile(path.join(GUIDE_DIR, "GUIDE.md"), "utf8");

  return (
    <>
      <Masthead
        eyebrow="Matrikel"
        title="Guide för matrikeln"
        meta="Ansökningar, medlemskap, adresser, avgifter och export"
      />
      <div className={styles.container}>
        <ManualArticle
          markdown={markdown}
          imageDir={GUIDE_DIR}
          imageUrl={GUIDE_IMAGE_URL}
          partsLabel="Guidens delar"
        />
      </div>
    </>
  );
}
