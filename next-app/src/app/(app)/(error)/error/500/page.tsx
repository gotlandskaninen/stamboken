import Link from "next/link";

export const metadata = { title: "500 – Internt serverfel" };

export default function Page500() {
  return (
    <main style={{ maxWidth: 520, textAlign: "center" }}>
      <p className="sb-eyebrow">Fel 500</p>
      <h1 className="sb-h3" style={{ margin: "12px 0" }}>
        Internt serverfel
      </h1>
      <p className="sb-lede" style={{ marginBottom: 24 }}>
        Servern stötte på ett oväntat fel. Försök igen om en stund.
      </p>
      <Link href="/" className="sb-btn">
        Till startsidan
      </Link>
    </main>
  );
}
