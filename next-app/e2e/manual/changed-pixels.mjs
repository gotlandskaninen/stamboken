// The changed manual pictures with how many pixels differ from the committed
// ones, largest first, as Markdown for the job summary of
// manual-screenshots.yml. Run from the repository root:
//   node next-app/e2e/manual/changed-pixels.mjs <png path>...
import { execFileSync } from "node:child_process";
import sharp from "sharp";

const raw = (src) =>
  sharp(src).ensureAlpha().raw().toBuffer({ resolveWithObject: true });

const rows = [];
for (const file of process.argv.slice(2)) {
  let committed;
  try {
    committed = execFileSync("git", ["show", `HEAD:${file}`], {
      maxBuffer: 1 << 28,
      stdio: ["ignore", "pipe", "ignore"],
    });
  } catch {
    rows.push({ file, note: "ny bild", pixels: Infinity });
    continue;
  }
  const [a, b] = await Promise.all([raw(committed), raw(file)]);
  if (a.info.width !== b.info.width || a.info.height !== b.info.height) {
    const size = (i) => `${i.width}×${i.height}`;
    rows.push({
      file,
      note: `ny storlek, ${size(a.info)} → ${size(b.info)}`,
      pixels: Infinity,
    });
    continue;
  }
  let pixels = 0;
  for (let i = 0; i < a.data.length; i += 4)
    if (a.data.readUInt32BE(i) !== b.data.readUInt32BE(i)) pixels++;
  rows.push({ file, note: `${pixels.toLocaleString("sv-SE")} pixlar`, pixels });
}
rows.sort((x, y) => y.pixels - x.pixels);
for (const { file, note } of rows) console.log(`- \`${file}\`: ${note}`);
