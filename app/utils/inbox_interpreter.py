"""
The intake queue's image reading (docs/inkorg.md, "Tolkning"): a photo of a paper certificate in, the fields the
model reads on it out, one document a minute in the scheduler's inbox_interpret. Nothing here decides what is
right: utils/inbox_proposal.py checks the reading against the registry, and only a human saves. INLASNING_TOLKARE
picks the interpreter; "av", the default, reads nothing.
"""

import base64
import io
import json
import logging
import os
from datetime import datetime, timezone

import numpy as np
import requests
from peewee import fn
from PIL import Image, ImageFilter

import utils.settings as settings
from utils.database import DB_PROXY, InboxDocument, InboxItem
from utils.inbox_proposal import build_proposal

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # then the document is "misslyckad" and the handler types it
TIMEOUT = 900  # seconds: a model on CPU takes minutes per photo, and longer while it loads
MAX_SIDE = 2000  # pixels, the longest side of the photo the interpreter gets
_BACKGROUND_SCALE = 4  # the paper's background is estimated on a copy this many times smaller

_ANCESTOR = {
    "type": "object",
    "properties": {"genbanksnr": {"type": "string"}, "ar_kull_individ": {"type": "string"}, "namn": {"type": "string"}},
    "required": ["genbanksnr", "ar_kull_individ", "namn"],
}
ANCESTORS = ("far", "mor", "farfar", "farmor", "morfar", "mormor")
_OWN = (
    "genbanksnr",
    "ar_kull_individ",
    "intygsnummer",
    "fodelsedatum",
    "kon",
    "namn",
    "farg",
    "fodda_i_kullen",
    "levande_efter_6_veckor",
)
# The trial's schema, plus the certificate number and the fields the model saw struck through or corrected.
SCHEMA = {
    "type": "object",
    "properties": {
        **{key: {"type": "string"} for key in _OWN},
        **{key: _ANCESTOR for key in ANCESTORS},
        "overstruket": {"type": "array", "items": {"type": "string", "enum": [*_OWN, *ANCESTORS]}},
    },
    "required": [*_OWN, *ANCESTORS, "overstruket"],
}
PROMPT = (
    "Fotot visar ett svenskt genbanksintyg för en kanin, gotlandskanin eller mellerudskanin. Skriv av fälten "
    "precis som de står, handskrivna eller tryckta. Kaninen: genbanksnr (besättningsnumret, en bokstav och "
    "siffror, till exempel G1274), år/kull/individ (fyra eller fem siffror), intygsnummer (uppe till höger), "
    "födelsedatum, kön (Hona eller Hane), namn, färg, antal födda i kullen och antal levande efter 6 veckor. "
    "Härstamningen: far och mor, farfar och farmor (fars föräldrar, till vänster), morfar och mormor (mors "
    "föräldrar, till höger), var och en med genbanksnr, år/kull/individ och namn. Är något överstruket eller "
    "rättat: skriv det som gäller och lägg fältets namn i overstruket. Gissa aldrig: lämna en tom sträng när "
    "fältet är tomt eller oläsligt. Säljarens och köparens uppgifter ska inte skrivas av."
)


class InterpretationError(Exception):
    """The interpreter gave no usable answer: the server is down, timed out, or answered something else."""


def prepare_image(source, rotation):
    """
    The photo (a path or a file) as the interpreter gets it, a greyscale JPEG: turned `rotation` degrees
    clockwise as the handler set it, at most MAX_SIDE pixels on its longest side, and enhanced as in the trial.
    The green channel fades the form, which is printed in green, and keeps the writing; dividing by the
    paper's background takes away shadows and uneven light; the stretch darkens the midtones so that faint
    pencil shows.
    """
    with Image.open(source) as original:
        image = original.convert("RGB").rotate(-rotation, expand=True)
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    green = image.getchannel("G")
    # A closing (max, then min) wipes out the writing and a median smooths what is left. On a smaller copy,
    # since Pillow's rank filters at full size take minutes; the sizes match the trial's at full size.
    background = (
        green.reduce(_BACKGROUND_SCALE)
        .filter(ImageFilter.MaxFilter(7))
        .filter(ImageFilter.MinFilter(7))
        .filter(ImageFilter.MedianFilter(7))
        .resize(green.size, Image.Resampling.BILINEAR)
    )
    level = np.clip(np.asarray(green, np.float32) / np.maximum(np.asarray(background, np.float32), 1) * 255, 0, 255)
    low = np.percentile(level, 0.5)
    level = np.clip((level - low) / max(255 - low, 1), 0, 1)
    buffer = io.BytesIO()
    Image.fromarray((255 * level**2).astype(np.uint8)).save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def _gemma(image, schema):
    """Gemma on the Ollama server at OLLAMA_URL, answering in JSON against `schema` (structured output)."""
    body = {
        "model": settings.interpretation.model,
        "stream": False,
        "think": False,
        "format": schema,
        # num_thread matches the ollama service's 6 CPUs in the compose files.
        "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 1500, "num_thread": 6},
        "messages": [{"role": "user", "content": PROMPT, "images": [base64.b64encode(image).decode()]}],
    }
    url = f"{settings.interpretation.ollama_url}/api/chat"
    response = requests.post(url, json=body, timeout=TIMEOUT)
    if response.status_code == 400 and "think" in response.text:  # a model or an Ollama without the option
        del body["think"]
        response = requests.post(url, json=body, timeout=TIMEOUT)
    response.raise_for_status()
    return json.loads(response.json()["message"]["content"])


# The interpreters INLASNING_TOLKARE can name. Extension point: a second interpreter is one more entry, a
# function (JPEG bytes, JSON schema) -> dict. One that sends photos off the server needs the board's decision
# and an agreement with the provider first (docs/inkorg.md, "Tolkning").
INTERPRETERS = {"gemma": _gemma}


def enabled():
    """The image reading is on: INLASNING_TOLKARE names an interpreter (anything else, "av" too, is off)."""
    return settings.interpretation.interpreter in INTERPRETERS


def interpret(image, schema=SCHEMA):
    """What the configured interpreter reads on the photo (JPEG bytes), as a dict in the shape of `schema`."""
    if not enabled():
        raise InterpretationError("Tolkningen är avstängd.")
    try:
        answer = INTERPRETERS[settings.interpretation.interpreter](image, schema)
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        raise InterpretationError(f"{type(exc).__name__}: {exc}") from exc
    if not isinstance(answer, dict):
        raise InterpretationError("Svaret är inget JSON-objekt.")
    return answer


def initial_status():
    """A certificate's interpretation_status when it comes in or becomes a certificate: waiting, or off."""
    return "vantar" if enabled() else "av"


def _waiting():
    """A certificate waiting to be read, in an open item, with nothing saved from it yet."""
    return (
        (InboxDocument.interpretation_status == "vantar")
        & (InboxDocument.doc_type == "intyg")
        & InboxDocument.done_at.is_null()
        & InboxDocument.individual.is_null()
        & InboxItem.closed_at.is_null()
    )


def _locked(document_id, item_id):
    """The document, its item locked first: the order of every write through the queue (utils/inbox.py)."""
    InboxItem.select().where(InboxItem.id == item_id).for_update().first()
    return InboxDocument.get_or_none(InboxDocument.id == document_id)


def _finish(document, status, **values):
    document.interpretation_status, document.interpreted_at = status, datetime.now(timezone.utc)
    document.interpreter = settings.interpretation.interpreter
    for name, value in values.items():
        setattr(document, name, value)
    document.save()


def interpret_next():
    """
    The scheduler's inbox_interpret: the oldest certificate waiting is read and checked into a proposal, one per
    run. The attempt is counted before the model runs, so a run that dies counts too; after MAX_ATTEMPTS the
    document is "misslyckad". No transaction and no connection is held while the model reads, which takes
    minutes: the claim and the result are short transactions of their own, and a document turned, requeued or
    changed meanwhile keeps waiting and the stale reading is dropped. Returns the document's id, or None.
    """
    if not enabled():
        return None
    with DB_PROXY.atomic():
        oldest = InboxDocument.select(InboxDocument.id, InboxDocument.item).join(InboxItem).where(_waiting())
        oldest = oldest.order_by(InboxDocument.id).first()
        if oldest is None:
            return None
        document = _locked(oldest.id, oldest.item_id)
        item = InboxItem.get_by_id(oldest.item_id)
        if document is None or document.interpretation_status != "vantar":
            return None
        if document.attempts >= MAX_ATTEMPTS:  # the runs that tried it died
            _finish(document, "misslyckad")
            return document.id
        document.attempts += 1
        document.save()
    document_id, claimed = document.id, ("vantar", document.attempts, document.rotation, document.doc_type)
    DB_PROXY.close()
    try:
        image = prepare_image(os.path.join(settings.service.private_upload_folder, document.original_path), claimed[2])
        raw = interpret(image)
    except Exception as exc:  # pylint: disable=broad-except  # whatever failed, it was an attempt
        logger.warning("Interpreting inbox document %s failed (attempt %s): %s", document_id, claimed[1], exc)
        raw = None
    with DB_PROXY.atomic():
        document = _locked(document_id, item.id)
        if document is None or (
            (document.interpretation_status, document.attempts, document.rotation, document.doc_type) != claimed
        ):
            return document_id
        if raw is not None:
            proposal = build_proposal(raw, item.genebank_id, item.herd_id)
            _finish(document, "klar", interpretation=raw, proposal=proposal)
        elif document.attempts >= MAX_ATTEMPTS:
            _finish(document, "misslyckad")
    return document_id


def status():
    """For the queue's header: documents waiting, the last one read, and an alarm when the last three failed."""
    recent = (
        InboxDocument.select(InboxDocument.interpretation_status)
        .where(InboxDocument.interpreted_at.is_null(False))
        .order_by(InboxDocument.interpreted_at.desc())
        .limit(3)
    )
    last = [state for (state,) in recent.tuples()]
    done = InboxDocument.select(fn.MAX(InboxDocument.interpreted_at)).where(
        InboxDocument.interpretation_status == "klar"
    )
    last_done = done.scalar()
    return {
        "interpreter": settings.interpretation.interpreter if enabled() else "av",
        "waiting": InboxDocument.select().join(InboxItem).where(_waiting()).count(),
        "last_done_at": last_done.isoformat() if last_done else None,
        "alarm": enabled() and last == ["misslyckad"] * 3,
    }
