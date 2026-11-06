import Link from "next/link";

export default function NotFound() {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
      }}
    >
      <main style={{ maxWidth: 520, textAlign: "center" }}>
        <p className="sb-eyebrow">Fel 404</p>
        <h1 className="sb-h3" style={{ margin: "12px 0" }}>
          Sidan kunde inte hittas
        </h1>
        <p className="sb-lede" style={{ marginBottom: 24 }}>
          Sidan du letar efter kan ha flyttats eller tagits bort.
        </p>
        <Link href="/" className="sb-btn">
          Till startsidan
        </Link>
      </main>
    </div>
  );
}
