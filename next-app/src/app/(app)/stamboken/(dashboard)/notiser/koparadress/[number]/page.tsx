import { notFound } from "next/navigation";
import { Masthead } from "@/components/shell/Masthead";
import { ApiError, fetchApi } from "@/lib/api";
import { BuyerEmailReview, type ReviewBuyer } from "./BuyerEmailReview";
import styles from "../../../inskick/inskick.module.css";

export default async function ReviewPage({
  params,
}: {
  params: Promise<{ number: string }>;
}) {
  const { number } = await params;
  let buyers: ReviewBuyer[];
  try {
    buyers = await fetchApi<ReviewBuyer[]>(
      `/v2/individual/${encodeURIComponent(number)}/buyer-email-reviews`,
    );
  } catch (e) {
    if (e instanceof ApiError && (e.status === 403 || e.status === 404))
      notFound();
    throw e;
  }
  return (
    <>
      <Masthead eyebrow={number} title="Kontrollera köparens e-postadress" />
      <div className={styles.container}>
        {buyers.length === 0 && (
          <p>Det finns ingen köparadress att kontrollera.</p>
        )}
        {buyers.map((buyer) => (
          <BuyerEmailReview key={buyer.id} buyer={buyer} />
        ))}
      </div>
    </>
  );
}
