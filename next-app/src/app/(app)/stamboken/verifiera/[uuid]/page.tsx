import Link from "next/link";

import { fetchApi } from "@/lib/api";

interface VerificationResponse {
  verified: boolean;
  certificate_type: string;
  individual_name: string;
  individual_number: string;
  genebank: string;
  // null once a paper certificate has replaced the digital one, or the number was lost (ADR-0019)
  digital_certificate: number | null;
  issued_at: string;
  is_current: boolean;
  replaced_by_date: string | null;
}

function svDate(iso: string): string {
  return new Date(iso).toLocaleDateString("sv-SE");
}

export default async function VerifieraPage({
  params,
}: {
  params: Promise<{ uuid: string }>;
}) {
  const { uuid } = await params;
  let data: VerificationResponse | null = null;
  try {
    data = await fetchApi<VerificationResponse>(
      `/v2/certificates/verify/${uuid}`,
      // Certificates are issued in prod; the demo copy lags a day.
      { forceProd: true },
    );
  } catch {
    data = null;
  }

  if (!data || !data.verified) {
    return (
      <>
        <main className="vf-body">
          <span className="badge badge-err">
            <span className="dot" />
            Kunde inte verifieras
          </span>
          <h1>Intyget hittades inte</h1>
          <p className="sub">
            Länken eller QR-koden matchar inget intyg i Stamboken.
          </p>
          <div className="hint">
            Det kan bero på att:
            <ul>
              <li>QR-koden lästes av fel — prova att skanna igen</li>
              <li>länken skrevs av för hand och blev fel</li>
              <li>intyget inte är utfärdat digitalt via Stamboken</li>
            </ul>
          </div>
          <div className="actions">
            <a
              className="btn btn-secondary"
              href="mailto:admin@gotlandskaninen.se"
            >
              Kontakta Föreningen Gotlandskaninen
            </a>
          </div>
        </main>
        <footer className="vf-foot">
          Ett äkta digitalt intyg har alltid en QR-kod som leder till
          gotlandskaninen.se.
        </footer>
      </>
    );
  }

  const isIdCard = data.certificate_type === "id_card";
  const superseded = !data.is_current;
  // No date: no newer digital certificate, a paper certificate replaced it.
  const replaced = data.replaced_by_date !== null;

  if (superseded) {
    return (
      <>
        <main className="vf-body">
          <span className="badge badge-warn">
            <span className="dot" />
            {replaced ? "Ersatt intyg" : "Gäller inte längre"}
          </span>
          <h1>
            {replaced ? "Äkta, men ersatt" : "Äkta, men gäller inte längre"}
          </h1>
          <p className="sub">
            {data.replaced_by_date ? (
              <>
                Intyget är äkta och utfärdat i Stamboken, men ett{" "}
                <strong>nyare intyg</strong> har utfärdats för denna kanin{" "}
                <strong>{svDate(data.replaced_by_date)}</strong>.
              </>
            ) : (
              <>
                Intyget är äkta och utfärdat i Stamboken, men det{" "}
                <strong>gäller inte längre</strong> för denna kanin.
              </>
            )}{" "}
            Det här dokumentet är inte längre den aktuella versionen.
          </p>
          <div className="ind-card">
            <div className="num">{data.individual_number}</div>
            <div className="nm">{data.individual_name}</div>
            <div className="frow">
              <span className="l">Ras</span>
              <span className="v">{data.genebank}</span>
            </div>
            {data.digital_certificate !== null && (
              <div className="frow">
                <span className="l">Intygsnummer</span>
                <span className="v">{data.digital_certificate}</span>
              </div>
            )}
            <div className="frow">
              <span className="l">Detta intyg</span>
              <span className="v">{svDate(data.issued_at)}</span>
            </div>
            {data.replaced_by_date && (
              <div className="frow">
                <span className="l">Nyaste intyg</span>
                <span className="v">{svDate(data.replaced_by_date)}</span>
              </div>
            )}
          </div>
          <div className="actions">
            <Link
              className="btn btn-primary"
              href={`/stamboken/individ/${data.individual_number}`}
            >
              Visa kaninens sida i Stamboken →
            </Link>
          </div>
        </main>
        <footer className="vf-foot">
          {replaced
            ? "Be säljaren om den senaste versionen av intyget."
            : "Be säljaren om kaninens gällande intyg."}
          <span className="tok">token {uuid}</span>
        </footer>
      </>
    );
  }

  return (
    <>
      <main className="vf-body">
        <span className="badge badge-ok">
          <span className="dot" />
          Verifierat intyg
        </span>
        <h1>{isIdCard ? "Äkta ID-kort" : "Äkta genbanksintyg"}</h1>
        <p className="sub">
          Intyg nr <strong>{data.digital_certificate}</strong> är utfärdat i
          Stamboken och digitalt signerat av Föreningen Gotlandskaninen.
        </p>
        <div className="ind-card">
          <div className="num">{data.individual_number}</div>
          <div className="nm">{data.individual_name}</div>
          <div className="frow">
            <span className="l">Ras</span>
            <span className="v">{data.genebank}</span>
          </div>
          <div className="frow">
            <span className="l">Intygsnummer</span>
            <span className="v">{data.digital_certificate}</span>
          </div>
          <div className="frow">
            <span className="l">Datum</span>
            <span className="v">{svDate(data.issued_at)}</span>
          </div>
        </div>
        <div className="actions">
          <Link
            className="btn btn-primary"
            href={`/stamboken/individ/${data.individual_number}`}
          >
            Visa kaninens sida i Stamboken →
          </Link>
          <Link className="btn btn-secondary" href="/stamboken-online">
            Om genbanksintyg
          </Link>
        </div>
      </main>
      <footer className="vf-foot">
        Verifieringen gäller detta intygs äkthet vid skanningstillfället.
        <span className="tok">token {uuid}</span>
      </footer>
    </>
  );
}
