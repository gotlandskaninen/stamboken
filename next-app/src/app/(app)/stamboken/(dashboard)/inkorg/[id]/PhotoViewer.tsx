"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMode } from "@/lib/mode-context";
import {
  degrees,
  enhancePencil,
  MIN_FRAME,
  moveRect,
  resizeRect,
  turnedSize,
} from "../image";
import type { InboxDocument, Rect } from "../lib";
import styles from "../inkorg.module.css";

// shortcut: originals (up to 40 MP) are drawn at most 2400 px a side, which
// keeps "Förstärk blyerts" fast; raise it if pencil detail is lost on big scans.
const MAX_SIDE = 2400;
const ZOOMS = [1, 1.5, 2, 3, 4, 6];
const STEP = 0.01;
const WHEEL_STEP = 50; // px of wheel per zoom step: one notch of a mouse wheel, several flicks of a trackpad
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
  /** The index of the rectangle that is the frame around the copy: the photo outside it is left out. */
  frameAt?: number;
  selected: number | null;
  onSelect: (i: number) => void;
  onChange: (i: number, r: Rect) => void;
  onRemove: (i: number) => void;
};

/** "Svart ruta 2 av 3", counting the black boxes only, not the frame around the copy. */
function boxLabel(i: number, { rects, frameAt }: MaskLayer) {
  const framed = frameAt === undefined ? 0 : 1;
  const after = frameAt !== undefined && i > frameAt ? 1 : 0;
  return `Svart ruta ${i + 1 - after} av ${rects.length - framed}`;
}

/**
 * The original, drawn on a canvas: turned by `rotation` and `straighten`
 * (frame F: the bounding box of the turned photo, white in the corners), with
 * zoom, pan, contrast and "Förstärk blyerts". Only the turn is saved (by the
 * caller); the rest is for reading. With `mask`, the masking rectangles lie
 * on top in fractions of the turned image.
 */
export function PhotoViewer({
  src,
  rotation,
  straighten = 0,
  onRotate,
  onStraighten,
  straightenLocked = false,
  onFindPaper,
  busy = false,
  mask,
}: {
  src: string;
  rotation: number;
  straighten?: number;
  onRotate?: (quarterTurns: number) => void;
  /** "Räta upp": the angle in degrees, -15 to 15. */
  onStraighten?: (degrees: number) => void;
  /** The angle cannot change (the masking step). */
  straightenLocked?: boolean;
  /** "Hitta pappret", for the item's handler. */
  onFindPaper?: () => void;
  busy?: boolean;
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
  // A wheel zoom's aim: the pointer on screen, and the photo's point under it as fractions of the photo.
  const anchor = useRef<{
    cx: number;
    cy: number;
    fx: number;
    fy: number;
  } | null>(null);
  const shown = useRef(0); // the zoom last laid out, for the wheel's listener
  const spun = useRef(0); // wheel travel not yet a whole step
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
    // F's size, from the original's: the overlays are fractions of it.
    const size = turnedSize(
      image.naturalWidth,
      image.naturalHeight,
      rotation + straighten,
    );
    canvas.width = Math.round(size.width * scale);
    canvas.height = Math.round(size.height * scale);
    ctx.fillStyle = "white";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.translate(canvas.width / 2, canvas.height / 2);
    ctx.rotate(((rotation + straighten) * Math.PI) / 180);
    ctx.drawImage(image, -w / 2, -h / 2, w, h);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    if (pencil) {
      const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height);
      enhancePencil(pixels.data);
      ctx.putImageData(pixels, 0, 0);
    }
  }, [image, rotation, straighten, pencil]);

  // The wheel zooms a step at a time. A wheel past the last step (down at 100 %, up at 600 %),
  // a sideways swipe and a pinch (ctrlKey) are the page's. Our own listener: React's onWheel is passive.
  const viewer = Boolean(onRotate);
  useEffect(() => {
    const vp = viewportRef.current;
    if (!vp) return;
    // Presses in the photo until each ends anywhere: a masking rectangle or the photo is being dragged, and its
    // maths needs the photo still. Safari's wheel events say no button is down, and Delete can remove the rectangle.
    const held = new Set<number>();
    const press = (e: PointerEvent) => held.add(e.pointerId);
    const release = (e: PointerEvent) => held.delete(e.pointerId);
    const onWheel = (e: WheelEvent) => {
      const mode = e.deltaMode; // first: Firefox turns lines into pixels once a delta is read
      if (e.ctrlKey) return;
      if (held.size || e.buttons) return e.preventDefault();
      const stage = stageRef.current;
      const sideways = Math.abs(e.deltaX) > Math.abs(e.deltaY);
      const last = e.deltaY > 0 ? 0 : ZOOMS.length - 1;
      if (sideways || !stage || shown.current === last) return;
      e.preventDefault();
      // A line or a page (deltaMode 1, 2) is a notch.
      spun.current += mode ? Math.sign(e.deltaY) * WHEEL_STEP : e.deltaY;
      if (Math.abs(spun.current) < WHEEL_STEP) return;
      // One step per event: a mouse notch is one step whatever its size; a trackpad's flicks add up.
      const step = spun.current < 0 ? 1 : -1;
      spun.current %= WHEEL_STEP;
      const photo = stage.getBoundingClientRect();
      if (!photo.width || !photo.height) return;
      anchor.current = {
        cx: e.clientX,
        cy: e.clientY,
        fx: (e.clientX - photo.left) / photo.width,
        fy: (e.clientY - photo.top) / photo.height,
      };
      setZoom((z) => Math.min(ZOOMS.length - 1, Math.max(0, z + step)));
    };
    vp.addEventListener("wheel", onWheel, { passive: false });
    vp.addEventListener("pointerdown", press, true);
    window.addEventListener("pointerup", release);
    window.addEventListener("pointercancel", release);
    return () => {
      vp.removeEventListener("wheel", onWheel);
      vp.removeEventListener("pointerdown", press, true);
      window.removeEventListener("pointerup", release);
      window.removeEventListener("pointercancel", release);
    };
  }, [viewer]);

  // After the stage is laid out at the new size: the same point of the photo back under the pointer.
  useLayoutEffect(() => {
    shown.current = zoom;
    const vp = viewportRef.current;
    const stage = stageRef.current;
    const at = anchor.current;
    anchor.current = null;
    if (!vp || !stage || !at) return;
    // Measured now, so a scroll the browser already cut back at the edge counts.
    const photo = stage.getBoundingClientRect();
    vp.scrollLeft += photo.left + at.fx * photo.width - at.cx;
    vp.scrollTop += photo.top + at.fy * photo.height - at.cy;
  }, [zoom]);

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

  // The frame around the copy keeps a tenth each way (the API refuses less); boxes the default minimum.
  const smallest = (i: number) => (i === mask?.frameAt ? MIN_FRAME : undefined);

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
          : resizeRect(start.rect, dx, dy, smallest(i)),
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
        e.shiftKey
          ? resizeRect(r, d[0], d[1], smallest(i))
          : moveRect(r, d[0], d[1]),
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
        {onStraighten && (
          <>
            <label>
              Räta upp
              <input
                type="range"
                min={-15}
                max={15}
                step={0.1}
                value={straighten}
                disabled={straightenLocked}
                aria-valuetext={`${degrees(straighten)} medurs`}
                onChange={(e) => onStraighten(Number(e.target.value))}
              />
              <output>{degrees(straighten)}</output>
            </label>
            <button
              type="button"
              className="sb-btn sb-btn-secondary sb-btn-sm"
              disabled={straightenLocked || straighten === 0}
              onClick={() => onStraighten(0)}
            >
              Nollställ
            </button>
          </>
        )}
        {onFindPaper && (
          <button
            type="button"
            className="sb-btn sb-btn-secondary sb-btn-sm"
            disabled={busy}
            onClick={onFindPaper}
          >
            Hitta pappret
          </button>
        )}
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
                  // The frame keeps its own key: when it is removed, focus does not land on a box Delete would take.
                  key={
                    i === mask.frameAt
                      ? "frame"
                      : i -
                        (mask.frameAt !== undefined && i > mask.frameAt ? 1 : 0)
                  }
                  type="button"
                  className={`${styles.rect} ${mask.frame ? styles.frame : ""} ${i === mask.frameAt ? styles.copyFrame : ""}`}
                  aria-pressed={mask.selected === i}
                  aria-label={`${mask.frame ? "Ramen runt utsnittet" : i === mask.frameAt ? "Ramen runt kopian" : boxLabel(i, mask)}. Piltangenterna flyttar, Skift och piltangenterna ändrar storleken, Delete tar bort.`}
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
          straighten={photo.straighten}
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
