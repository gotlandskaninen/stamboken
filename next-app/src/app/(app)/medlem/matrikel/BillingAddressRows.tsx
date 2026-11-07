import type { BillingAddress } from "./types";

/**
 * Read-only billing address as rows of an .ad-kv list: the membership detail
 * for those who may read but not edit the matrikel, and the application
 * review. Empty fields show "–".
 */
export function BillingAddressRows({ billing }: { billing: BillingAddress }) {
  const rows: [string, string | null][] = [
    ["Fakturamottagare", billing.billing_name],
    ["Fakturaadress", billing.billing_address],
    ["Fakturapostnummer", billing.billing_postal_code],
    ["Fakturapostort", billing.billing_city],
    ["E-post för faktura", billing.billing_email],
    ["Fakturareferens", billing.billing_reference],
  ];
  return (
    <>
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value || "–"}</dd>
        </div>
      ))}
    </>
  );
}
