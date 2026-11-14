"""
The intake queue's image reading (docs/inkorg.md, "Tolkning"): a photo of a paper certificate in, the fields the
model reads on it out. Nothing here decides what is right: utils/inbox_proposal.py checks the reading against the
registry, and only a human saves. INLASNING_TOLKARE picks the interpreter; "av", the default, reads nothing.
"""

import base64
import json

import requests

import utils.settings as settings

TIMEOUT = 900  # seconds: a model on CPU takes minutes per photo, and longer while it loads

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
