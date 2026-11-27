"""
The intake queue's photo of a paper certificate turned as the handler sees it (frame F).
"""

from PIL import Image

MAX_STRAIGHTEN = 15  # degrees either way


def turned(image, rotation, straighten=0):
    """
    F, the photo as the handler sees it: turned `rotation` + `straighten` degrees clockwise, as RGB. Without
    straighten it is the quarter turn the copy and the reading always had, pixel for pixel; with it the photo is
    resampled into its new bounding box and the corners filled white. Fractions of the photo are fractions of F.
    """
    image = image.convert("RGB")
    if not straighten:
        return image.rotate(-rotation, expand=True)
    return image.rotate(-(rotation + straighten), expand=True, resample=Image.Resampling.BICUBIC, fillcolor="white")
