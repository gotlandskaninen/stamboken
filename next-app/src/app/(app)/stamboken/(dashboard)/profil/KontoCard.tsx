"use client";

import { useRef, useState, useTransition } from "react";
import { Switch } from "@mui/material";
import { useSnackbar } from "@/components/SnackbarProvider";
import { useNotifications } from "@/contexts/NotificationContext";
import type { UserContext } from "@/lib/user-context";
import { updateProfilePicture, updateSettings } from "./actions";
import styles from "./profil.module.css";

const COURSE_URL =
  "https://classroom.google.com/c/NjE3MDI1MzY2OTAz?cjc=27x3zpg";

export function KontoCard({ user }: { user: UserContext }) {
  const { showSnackbar } = useSnackbar();
  const { addNotification } = useNotifications();
  const [isPending, startTransition] = useTransition();
  const [selectedImage, setSelectedImage] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [useGooglePicture, setUseGooglePicture] = useState(
    user.use_google_picture || false,
  );
  const fileInputRef = useRef<HTMLInputElement>(null);

  const displayName =
    user.google_name || user.fullname || user.username || "Användare";
  const profilePicture =
    (user.use_google_picture && user.google_picture) ||
    (user.profile_picture
      ? `/uppladdningar/profiler/${user.profile_picture}`
      : null);
  const initials = displayName
    .split(/\s+/)
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const dirty =
    selectedImage !== null ||
    useGooglePicture !== (user.use_google_picture || false);

  const handleImageSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/"))
      return showSnackbar("Vänligen välj en bildfil", "error");
    if (file.size > 5 * 1024 * 1024)
      return showSnackbar("Bilden är för stor. Max 5MB tillåten.", "error");
    setSelectedImage(file);
    const reader = new FileReader();
    reader.onload = (e) => setImagePreview(e.target?.result as string);
    reader.readAsDataURL(file);
  };

  const save = () =>
    startTransition(async () => {
      try {
        if (selectedImage) {
          const formData = new FormData();
          formData.append("profile_picture", selectedImage);
          const img = await updateProfilePicture(formData);
          if (!img.success)
            throw new Error(img.error || "Kunde inte ladda upp profilbild");
        }
        const settings = await updateSettings({
          use_google_picture: useGooglePicture,
        });
        if (!settings.success)
          throw new Error(settings.error || "Kunde inte uppdatera profilen");
        showSnackbar("Profil uppdaterad!", "success");
        addNotification({
          type: "success",
          title: "Profil uppdaterad",
          message: selectedImage
            ? "Din profilbild och inställningar har sparats."
            : "Dina profilinställningar har sparats.",
        });
        setSelectedImage(null);
        setImagePreview(null);
        if (fileInputRef.current) fileInputRef.current.value = "";
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : "Ett fel uppstod vid uppdatering av profilen";
        showSnackbar(message, "error");
        addNotification({
          type: "error",
          title: "Fel vid uppdatering",
          message,
        });
      }
    });

  return (
    <section className="sb-card">
      <div className={styles.cardHead}>
        <h3 className={`sb-h6 ${styles.cardTitle}`}>Konto</h3>
      </div>
      <div className={styles.cardBody}>
        <div className={styles.avatarRow}>
          {imagePreview || profilePicture ? (
            // eslint-disable-next-line @next/next/no-img-element -- data: preview / uploaded file, not an optimizable asset
            <img
              className={styles.avatar}
              src={imagePreview || profilePicture || undefined}
              alt=""
            />
          ) : (
            <span className={styles.avatar} aria-hidden="true">
              {initials}
            </span>
          )}
          <div>
            <div className="sb-h5">{displayName}</div>
            <div className="sb-meta">{user.email}</div>
          </div>
        </div>
        <div className={styles.badgeRow} style={{ marginTop: 12 }}>
          {user.is_admin && (
            <span className="sb-badge sb-badge-lera">Administratör</span>
          )}
          {user.is_manager && (
            <span className="sb-badge sb-badge-himmel">Genbanksansvarig</span>
          )}
          {(user.is_owner ?? []).map((herd) => (
            <span key={herd} className="sb-badge sb-badge-mossa">
              Ägare {herd}
            </span>
          ))}
          {user.validated ? (
            <span className="sb-badge sb-badge-skog">Validerad</span>
          ) : (
            <span className={`sb-badge ${styles.badgeWarning}`}>
              Inte validerad
            </span>
          )}
        </div>
        {!user.validated && (
          <div
            className={`${styles.banner} ${styles.bannerWarning}`}
            style={{ marginTop: 16 }}
          >
            <strong>För att bli validerad:</strong> Du måste genomgå kursen för
            att få full åtkomst till systemet.{" "}
            <a
              className="sb-link"
              href={COURSE_URL}
              target="_blank"
              rel="noopener noreferrer"
            >
              Gå kursen nu
            </a>
          </div>
        )}
        <hr className={`sb-rule ${styles.rule}`} />
        {user.google_picture && (
          <>
            <label className={styles.switchRow}>
              <span>Använd Google-profilbild</span>
              <Switch
                checked={useGooglePicture}
                onChange={(e) => setUseGooglePicture(e.target.checked)}
              />
            </label>
            <p className={styles.switchHint}>
              Om aktiverat används din Google-profilbild i stället för en
              uppladdad bild.
            </p>
          </>
        )}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          style={{ display: "none" }}
          onChange={handleImageSelect}
        />
        <div className={styles.actions}>
          <button
            type="button"
            className="sb-btn sb-btn-secondary sb-btn-sm"
            onClick={() => fileInputRef.current?.click()}
          >
            Ladda upp bild
          </button>
          <button
            type="button"
            className="sb-btn sb-btn-sm"
            disabled={isPending || !dirty}
            onClick={save}
          >
            {isPending ? "Sparar..." : "Spara"}
          </button>
        </div>
        <p className={styles.hint}>
          Rekommenderat: minst 128×128 px i JPG-format.
          {selectedImage ? ` Ny profilbild vald: ${selectedImage.name}` : ""}
        </p>
        <hr className={`sb-rule ${styles.rule}`} />
        <dl className={styles.kv}>
          <div>
            <dt>Fullständigt namn</dt>
            <dd>{displayName}</dd>
          </div>
          <div>
            <dt>Inloggning</dt>
            <dd className={styles.mono}>{user.email}</dd>
          </div>
          {user.google_email && user.google_email !== user.email && (
            <div>
              <dt>Google</dt>
              <dd className={styles.mono}>{user.google_email}</dd>
            </div>
          )}
        </dl>
        <p className={styles.hint}>
          Hanteras via Google Workspace. Kontakta admin för ändringar.
        </p>
      </div>
    </section>
  );
}
