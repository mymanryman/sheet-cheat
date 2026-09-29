// Nudge each note sideways onto the note head that is actually printed on
// the page. Audiveris gets the pitch (and so the height) right, but the
// horizontal positions we rebuild from its MusicXML can drift, so we look
// along the note's own line/space for the darkest head-shaped blob nearby.

const TARGET_SPACE_PX = 12; // render so one staff space is about this many pixels
const SEARCH_SPACES = 5; // how far left/right of the estimate to look
const HEAD_HALF_W = 0.6; // head is about 1.2 spaces wide
const HEAD_HALF_H = 0.4; // look at the middle of the head only

export async function snapToHeads(page, result) {
  if (!result?.notes?.length || !result.space) return result;
  const base = page.getViewport({ scale: 1 });
  const pageHeightPx = TARGET_SPACE_PX / result.space;
  const scale = Math.min(Math.max(pageHeightPx / base.height, 1), 5);
  const viewport = page.getViewport({ scale });
  const W = Math.round(viewport.width);
  const H = Math.round(viewport.height);
  const c = document.createElement("canvas");
  c.width = W;
  c.height = H;
  const ctx = c.getContext("2d", { willReadFrequently: true });
  ctx.fillStyle = "white";
  ctx.fillRect(0, 0, W, H);
  await page.render({ canvasContext: ctx, viewport }).promise;
  const rgba = ctx.getImageData(0, 0, W, H).data;
  const dark = new Uint8Array(W * H);
  for (let i = 0, j = 0; j < dark.length; i += 4, j++) {
    dark[j] = rgba[i] * 0.3 + rgba[i + 1] * 0.59 + rgba[i + 2] * 0.11 < 140 ? 1 : 0;
  }

  const space = result.space * H;
  for (const note of result.notes) {
    const found = findHead(dark, W, H, space, (note.x + note.w / 2) * W, note.y * H);
    if (found !== null) {
      note.x = found / W - note.w / 2;
      note.snapped = true;
    }
  }
  return result;
}

function findHead(dark, W, H, space, ex, cy) {
  const x0 = Math.max(0, Math.floor(ex - SEARCH_SPACES * space - HEAD_HALF_W * space));
  const x1 = Math.min(W - 1, Math.ceil(ex + SEARCH_SPACES * space + HEAD_HALF_W * space));
  const y0 = Math.max(0, Math.round(cy - HEAD_HALF_H * space));
  const y1 = Math.min(H - 1, Math.round(cy + HEAD_HALF_H * space));
  if (x1 - x0 < space * 2 || y1 <= y0) return null;

  // Skip staff lines and ledger lines: rows that are dark almost everywhere
  // in the search window would make every column look like a note head.
  const rows = [];
  for (let y = y0; y <= y1; y++) {
    let n = 0;
    for (let x = x0; x <= x1; x++) n += dark[y * W + x];
    if (n / (x1 - x0 + 1) < 0.6) rows.push(y);
  }
  if (rows.length < 2) return null;

  // prefix sums of dark pixels per column over the remaining rows
  const prefix = new Float64Array(x1 - x0 + 2);
  for (let x = x0; x <= x1; x++) {
    let n = 0;
    for (const y of rows) n += dark[y * W + x];
    prefix[x - x0 + 1] = prefix[x - x0] + n;
  }
  const half = Math.max(1, Math.round(HEAD_HALF_W * space));
  const area = (2 * half + 1) * rows.length;
  const fill = (cx) => (prefix[cx + half - x0 + 1] - prefix[cx - half - x0]) / area;

  let best = null;
  let bestScore = -Infinity;
  const from = Math.max(x0 + half, Math.round(ex - SEARCH_SPACES * space));
  const to = Math.min(x1 - half, Math.round(ex + SEARCH_SPACES * space));
  let prev = fill(from);
  let cur = from + 1 <= to ? fill(from + 1) : 0;
  for (let cx = from + 1; cx < to; cx++) {
    const next = fill(cx + 1);
    // a local maximum that is solid enough to be a head (hollow heads included)
    if (cur >= 0.35 && cur >= prev && cur >= next) {
      const score = cur - 0.06 * Math.abs(cx - ex) / space;
      if (score > bestScore) {
        bestScore = score;
        best = cx;
      }
    }
    prev = cur;
    cur = next;
  }
  return best;
}
