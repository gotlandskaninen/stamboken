"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMode } from "@/lib/mode-context";
import { enhancePencil, moveRect, resizeRect } from "../image";
import type { InboxDocument, Rect } from "../lib";
import styles from "../inkorg.module.css";

// shortcut: originals (up to 40 MP) are drawn at most 2400 px a side, which
// keeps "Förstärk blyerts" fast; raise it if pencil detail is lost on big scans.
const MAX_SIDE = 2400;
const ZOOMS = [1, 1.5, 2, 3, 4, 6];
const STEP = 0.01;
const KEYS: Record<string, [number, number]> = {
  ArrowLeft: [-STEP, 0],
  ArrowRight: [STEP, 0],
  ArrowUp: [0, -STEP],
  ArrowDown: [0, STEP],
};

export type MaskLayer = {
  rects: Rect[];
  /** An open frame around a part of the photo ("Bifoga utsnitt") instead of black boxes. */
  frame?: boolean;
  selected: number | null;
  onSelect: (i: number) => void;
  onChange: (i: number, r: Rect) => void;
  onRemove: (i: number) => void;
};

/**
 * The original, drawn on a canvas: turned by `rotation`, with zoom, pan,
 * contrast and "Förstärk blyerts". Only the rotation is saved (by the
 * caller); the rest is for reading. With `mask`, the masking rectangles lie
 * on top in fractions of the turned image.
 */
export function PhotoViewer({
  src,
  rotation,
  onRotate,
  mask,
}: {
  src: string;
  rotation: number;
  onRotate?: (quarterTurns: number) => void;
  mask?: MaskLayer;
}) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const pan = useRef<{
    x: number;
    y: number;
    left: number;
    top: number;
  } | null>(null);
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const [failed, setFailed] = useState(false);
  const [zoom, setZoom] = useState(0);
  const [contrast, setContrast] = useState(100);
  const [pencil, setPencil] = useState(false);

  // One fetch per document: every fetch of an original is logged by the API.
  useEffect(() => {
    const img = new Image();
    img.onload = () => setImage(img);
    img.onerror = () => setFailed(true);
    img.src = src;
  }, [src]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!image || !canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const scale = Math.min(
      1,
      MAX_SIDE / Math.max(image.naturalWidth, image.naturalHeight),
    );
    const w = Math.round(image.naturalWidth * scale);
    const h = Math.round(image.naturalHeight * scale);
    const sideways = rotation % 180 !== 0;
    canvas.width = sideways ? h : w;
    canvas.height = sideways ? w : h;
    ctx.translate(canvas.width / 2, canvas.height / 2);
    ctx.rotate((rotation * Math.PI) / 180);
    ctx.drawImage(image, -w / 2, -h / 2, w, h);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    if (pencil) {
      const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height);
      enhancePencil(pixels.data);
      ctx.putImageData(pixels, 0, 0);
    }
  }, [image, rotation, pencil]);

  // Mouse drag pans; touch scrolls natively and the keyboard scrolls the focused viewport.
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const vp = viewportRef.current;
    if (e.pointerType !== "mouse" || e.target !== canvasRef.current || !vp)
      return;
    pan.current = {
      x: e.clientX,
      y: e.clientY,
      left: vp.scrollLeft,
      top: vp.scrollTop,
    };
    vp.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const vp = viewportRef.current;
    if (!pan.current || !vp) return;
    vp.scrollLeft = pan.current.left - (e.clientX - pan.current.x);
    vp.scrollTop = pan.current.top - (e.clientY - pan.current.y);
  };

  const drag = (e: React.PointerEvent, i: number, kind: "move" | "resize") => {
    const stage = stageRef.current;
    if (!mask || !stage) return;
    e.preventDefault();
    e.stopPropagation();
    mask.onSelect(i);
    const { width, height } = stage.getBoundingClientRect();
    const start = { x: e.clientX, y: e.clientY, rect: mask.rects[i] };
    const target = e.currentTarget as HTMLElement;
    target.setPointerCapture(e.pointerId);
    const move = (ev: PointerEvent) => {
      const dx = (ev.clientX - start.x) / width;
      const dy = (ev.clientY - start.y) / height;
      mask.onChange(
        i,
        kind === "move"
          ? moveRect(start.rect, dx, dy)
          : resizeRect(start.rect, dx, dy),
      );
    };
    const end = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", end);
      target.removeEventListener("pointercancel", end);
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", end);
    target.addEventListener("pointercancel", end);
  };

  const onRectKey = (e: React.KeyboardEvent, i: number) => {
    if (!mask) return;
    const d = KEYS[e.key];
    if (d) {
      e.preventDefault();
      const r = mask.rects[i];
      mask.onChange(
        i,
        e.shiftKey ? resizeRect(r, d[0], d[1]) : moveRect(r, d[0], d[1]),
      );
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      mask.onRemove(i);
    }
  };

  const canvas = (
    <canvas
      ref={canvasRef}
      style={{ filter: `contrast(${contrast}%)` }}
      role="img"
      aria-label={
        onRotate
          ? image
            ? "Originalet"
            : "Fotot hämtas"
          : t(image ? "queueDetail.original" : "queueDetail.loading")
      }
    />
  );

  if (!onRotate)
    return (
      <div className={styles.caseViewport}>
        {failed ? (
          <p role="status" className={styles.error}>
            {t("queueDetail.failed")}
          </p>
        ) : (
          <button
            type="button"
            className={styles.casePhoto}
            aria-label={t(zoom ? "queueDetail.zoomOut" : "queueDetail.zoomIn")}
            aria-pressed={Boolean(zoom)}
            onClick={() => setZoom(zoom ? 0 : 1)}
          >
            {canvas}
          </button>
        )}
      </div>
    );

  return (
    <>
      <div className={styles.toolbar}>
        <button
          type="button"
          className="sb-btn sb-btn-secondary sb-btn-sm"
          onClick={() => onRotate(-1)}
        >
          ⟲ Vrid vänster
        </button>
        <button
          type="button"
          className="sb-btn sb-btn-secondary sb-btn-sm"
          onClick={() => onRotate(1)}
        >
          ⟳ Vrid höger
        </button>
        <button
          type="button"
          className="sb-btn sb-btn-secondary sb-btn-sm"
          aria-label="Zooma ut"
          disabled={zoom === 0}
          onClick={() => setZoom((z) => z - 1)}
        >
          −
        </button>
        <output aria-live="polite">{ZOOMS[zoom] * 100} %</output>
        <button
          type="button"
          className="sb-btn sb-btn-secondary sb-btn-sm"
          aria-label="Zooma in"
          disabled={zoom === ZOOMS.length - 1}
          onClick={() => setZoom((z) => z + 1)}
        >
          +
        </button>
        <label>
          Kontrast
          <input
            type="range"
            min={50}
            max={300}
            step={10}
            value={contrast}
            onChange={(e) => setContrast(Number(e.target.value))}
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={pencil}
            onChange={(e) => setPencil(e.target.checked)}
          />
          Förstärk blyerts
        </label>
      </div>
      <div
        ref={viewportRef}
        className={styles.viewport}
        tabIndex={0}
        role="region"
        aria-label="Fotot. Piltangenterna flyttar bilden när den är inzoomad."
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={() => (pan.current = null)}
        onPointerCancel={() => (pan.current = null)}
      >
        {failed ? (
          <p className={styles.error}>Fotot kunde inte hämtas.</p>
        ) : (
          <div
            ref={stageRef}
            className={styles.stage}
            style={{ width: `${ZOOMS[zoom] * 100}%` }}
          >
            {canvas}
            {image &&
              mask?.rects.map((r, i) => (
                <button
                  key={i}
                  type="button"
                  className={`${styles.rect} ${mask.frame ? styles.frame : ""}`}
                  aria-pressed={mask.selected === i}
                  aria-label={`${mask.frame ? "Ramen runt utsnittet" : `Svart ruta ${i + 1} av ${mask.rects.length}`}. Piltangenterna flyttar, Skift och piltangenterna ändrar storleken, Delete tar bort.`}
                  style={{
                    left: `${r.x * 100}%`,
                    top: `${r.y * 100}%`,
                    width: `${r.w * 100}%`,
                    height: `${r.h * 100}%`,
                  }}
                  onFocus={() => mask.onSelect(i)}
                  onPointerDown={(e) => drag(e, i, "move")}
                  onKeyDown={(e) => onRectKey(e, i)}
                >
                  <span
                    className={styles.handle}
                    onPointerDown={(e) => drag(e, i, "resize")}
                  />
                </button>
              ))}
          </div>
        )}
      </div>
    </>
  );
}

export function CasePhotos({
  itemId,
  documents,
}: {
  itemId: number;
  documents: InboxDocument[];
}) {
  const mode = useMode();
  const { t } = useTranslation();
  const [selected, setSelected] = useState(0);
  const index = Math.min(selected, documents.length - 1);
  const photo = documents[index];
  if (!photo) return null;
  const apiBase =
    mode === "demo" && process.env.NEXT_PUBLIC_API_TEST_URL
      ? process.env.NEXT_PUBLIC_API_TEST_URL
      : "/api";

  return (
    <section
      className={styles.caseSection}
      aria-label={t("queueDetail.photos")}
    >
      <h3>{t("queueDetail.photos")}</h3>
      {photo.has_original === false ? (
        <p>{t("queueDetail.erased")}</p>
      ) : (
        <PhotoViewer
          key={photo.id}
          src={`${apiBase}/v2/inkorg/${itemId}/dokument/${photo.id}/original`}
          rotation={photo.rotation}
        />
      )}
      <div className={styles.photoNav}>
        <span aria-live="polite">
          {t("queueDetail.photoCount", {
            index: index + 1,
            total: documents.length,
          })}
        </span>
        {documents.length > 1 && (
          <div role="group" aria-label={t("queueDetail.selectPhoto")}>
            {documents.map((d, i) => (
              <button
                type="button"
                key={d.id}
                aria-current={i === index}
                aria-label={t("queueDetail.photo", { index: i + 1 })}
                onClick={() => setSelected(i)}
              >
                {i + 1}
              </button>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
