"""
The intake queue's photo of a paper certificate turned as the handler sees it (frame F), and "Hitta pappret": how
far the paper is tilted and where it lies once straightened. numpy and Pillow only, on a small grey copy, so it
runs within the request. Nothing here changes a document: the handler applies what it finds and saves the angle.
"""

import math

import numpy as np
from PIL import Image, ImageFilter

MAX_STRAIGHTEN = 15  # degrees either way
WORK_SIDE = 800  # pixels, the longest side of the copy the paper is looked for on
# The best angle's score must beat the score at 0 by this much to count as a tilt. On synthetic photos a tilt of
# 0.5° or more scored 2 to 70 times its score at 0, and pure noise at most 1.28 times.
CLEAR_GAIN = 1.5
MIN_TILT = 0.3  # degrees: a smaller tilt is noise
PAPER_SHARE = 0.5  # of the largest share of light pixels in a row (or column): a row through the paper
PAPER_MARGIN = 0.015  # added to each side of the paper found
CLOSING = 9  # pixels: writing up to this size is closed over before the light rows and columns are counted
PAPER_AREA = (0.2, 0.97)  # the paper found covers this share of the photo, or it is no paper
EDGE_STRIP = 0.02  # of the photo's side: the strip outside the paper where the table must show
MAX_PIXELS = 40_000_000  # F never has more pixels than an upload may (blueprints/uploads.MAX_PIXELS)


def turned(image, rotation, straighten=0):
    """
    F, the photo as the handler sees it: turned `rotation` + `straighten` degrees clockwise, as RGB. Without
    straighten it is the quarter turn the copy and the reading always had, pixel for pixel; with it the photo is
    resampled into its new bounding box and the corners filled white. Fractions of the photo are fractions of F.
    """
    image = image.convert("RGB")
    if not straighten:
        return image.rotate(-rotation, expand=True)
    size = fitted(*image.size, rotation + straighten)
    if size != image.size:  # a long, thin photo turned would grow past MAX_PIXELS: smaller first
        image = image.resize(size, Image.Resampling.BICUBIC)
    return image.rotate(-(rotation + straighten), expand=True, resample=Image.Resampling.BICUBIC, fillcolor="white")


def turned_size(width, height, degrees):
    """The size of a width x height image turned `degrees` clockwise with expand: Pillow's own sum (Image.rotate)."""
    angle = -degrees % 360.0
    if angle in (0, 180):
        return width, height
    if angle in (90, 270):
        return height, width
    angle = -math.radians(angle)
    matrix = [round(math.cos(angle), 15), round(math.sin(angle), 15), 0.0]
    matrix += [round(-math.sin(angle), 15), round(math.cos(angle), 15), 0.0]

    def transform(x, y):
        a, b, c, d, e, f = matrix
        return a * x + b * y + c, d * x + e * y + f

    matrix[2], matrix[5] = transform(-width / 2, -height / 2)
    matrix[2] += width / 2
    matrix[5] += height / 2
    xs, ys = zip(*(transform(x, y) for x, y in ((0, 0), (width, 0), (width, height), (0, height))), strict=True)
    return math.ceil(max(xs)) - math.floor(min(xs)), math.ceil(max(ys)) - math.floor(min(ys))


def fitted(width, height, degrees):
    """The size a width x height photo is shrunk to before it is turned `degrees`, so that F has at most MAX_PIXELS."""
    turned_width, turned_height = turned_size(width, height, degrees)
    if turned_width * turned_height <= MAX_PIXELS:
        return width, height
    scale = math.sqrt(MAX_PIXELS / (turned_width * turned_height)) * 0.99  # the bounding box rounds outwards
    return max(1, math.floor(width * scale)), max(1, math.floor(height * scale))


def _otsu(grey):
    """The level that best splits the grey values (0-255) in two (Otsu)."""
    counts = np.bincount(grey.ravel(), minlength=256).astype(np.float64)
    levels = np.arange(256)
    below, total = np.cumsum(counts), counts.sum()
    mass = np.cumsum(counts * levels)
    above = total - below
    with np.errstate(divide="ignore", invalid="ignore"):
        between = np.nan_to_num((mass[-1] * below / total - mass) ** 2 / (below * above))
    return int(between.argmax())


def _row_score(dark, angle):
    """
    How sharply the dark pixels line up in rows with the photo turned `angle` degrees clockwise: the sum of squared
    differences between neighbouring rows' shares of dark pixels. A line of writing that lies straight starts and
    ends within a row or two. The variance of the rows was tried and dropped: on a dark background the edges of the
    paper outweigh the writing, a 2° tilt beat 0° by 3 % and pure noise by up to 19 %. The shares are counted over
    the photo only: the corners the turn adds would otherwise score by the angle alone.
    """
    rows = np.asarray(dark.rotate(-angle, expand=True), np.float32).sum(axis=1)
    inside = np.asarray(Image.new("L", dark.size, 255).rotate(-angle, expand=True), np.float32).sum(axis=1)
    kept = inside >= inside.max() / 2  # rows cut short by a corner say little
    return float((np.diff(rows[kept] / inside[kept]) ** 2).sum())


def _tilt(grey):
    """
    The straighten that lines the writing up in rows, in steps of 0.1 degrees, or 0.0 when no angle clearly beats
    leaving the photo as it is: the best score must beat the score at 0 by CLEAR_GAIN, and the angle must be at
    least MIN_TILT.
    """
    dark = Image.fromarray(((grey < _otsu(grey)) * 255).astype(np.uint8))
    straight = _row_score(dark, 0)

    def best(angles):
        return max((_row_score(dark, a), a) for a in angles)

    _, coarse = best(np.arange(-MAX_STRAIGHTEN, MAX_STRAIGHTEN + 0.25, 0.5))
    fine = np.clip(np.arange(coarse - 0.5, coarse + 0.55, 0.1), -MAX_STRAIGHTEN, MAX_STRAIGHTEN)
    score, angle = best(fine)
    angle = round(float(angle), 1) + 0.0  # never -0.0
    if not score > straight * CLEAR_GAIN or abs(angle) < MIN_TILT:
        return 0.0
    return angle


def _run(shares):
    """The longest run of rows (or columns) through the paper: (first, last + 1)."""
    inside = shares >= PAPER_SHARE * shares.max()
    best, start = (0, 0), None
    for i, on in enumerate([*inside, False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            best = max(best, (start, i), key=lambda run: run[1] - run[0])
            start = None
    return best


def _shares(light, inside, axis):
    """Each row's (axis 1) or column's (axis 0) share of light pixels, of the photo's own pixels in it."""
    counts = inside.sum(axis=axis)
    return np.divide(light.sum(axis=axis), counts, out=np.zeros(counts.shape), where=counts > 0)


def _edge(light, inside):
    """A strip just outside the paper shows the table: mostly the photo's own pixels, and mostly not light."""
    seen = inside.sum()
    return bool(seen >= inside.size / 2 and light.sum() < seen / 2)


def _paper(grey, inside):
    """
    The light area (the paper) on the straightened copy, as fractions {x, y, w, h}, or None. `inside` marks the
    photo's own pixels: the corners the turn adds count neither as paper nor as table. The paper must show an edge
    against the table on at least two sides: on a light table the light area is the table, and runs to the photo's
    edges.
    """
    if not inside.any():
        return None
    light = Image.fromarray((((grey > _otsu(grey[inside])) & inside) * 255).astype(np.uint8))
    light = np.asarray(light.filter(ImageFilter.MaxFilter(CLOSING)).filter(ImageFilter.MinFilter(CLOSING)), bool)
    light &= inside
    if not light.any():
        return None
    height, width = light.shape
    top, bottom = _run(_shares(light, inside, 1))
    left, right = _run(_shares(light, inside, 0))
    strip_x, strip_y = max(3, round(EDGE_STRIP * width)), max(3, round(EDGE_STRIP * height))
    strips = (
        np.s_[max(0, top - strip_y) : top, left:right],
        np.s_[bottom : bottom + strip_y, left:right],
        np.s_[top:bottom, max(0, left - strip_x) : left],
        np.s_[top:bottom, right : right + strip_x],
    )
    if sum(_edge(light[strip], inside[strip]) for strip in strips if inside[strip].size) < 2:
        return None
    x0, y0 = max(0.0, left / width - PAPER_MARGIN), max(0.0, top / height - PAPER_MARGIN)
    x1, y1 = min(1.0, right / width + PAPER_MARGIN), min(1.0, bottom / height + PAPER_MARGIN)
    if not PAPER_AREA[0] <= (x1 - x0) * (y1 - y0) <= PAPER_AREA[1]:
        return None
    return {"x": round(x0, 4), "y": round(y0, 4), "w": round(x1 - x0, 4), "h": round(y1 - y0, 4)}


def find_paper(source, rotation, straighten=None):
    """
    "Hitta pappret" on the photo (a path or a file) turned `rotation` degrees: the straighten that lines up its
    writing (0.0 when there is no clear tilt, see _tilt), or the `straighten` given, which is never looked for; and
    the paper as fractions of F turned `rotation` plus that angle, or None when no light area of a believable size
    stands out (a light background, a photo of only paper). Found on a grey copy about WORK_SIDE pixels long.
    """
    with Image.open(source) as original:
        original.draft("L", (WORK_SIDE, WORK_SIDE))  # a JPEG is decoded at a fraction of its size
        grey = original.convert("L")
    grey.thumbnail((WORK_SIDE, WORK_SIDE))
    grey = grey.rotate(-rotation, expand=True)
    angle = _tilt(np.asarray(grey)) if straighten is None else straighten
    straightened = grey.rotate(-angle, expand=True, resample=Image.Resampling.BILINEAR)
    # The photo's own pixels, less the edge the resampling blends with the corners the turn adds.
    inside = Image.new("L", grey.size, 255).rotate(-angle, expand=True).filter(ImageFilter.MinFilter(3))
    return {"angle": angle, "paper": _paper(np.asarray(straightened), np.asarray(inside, bool))}
