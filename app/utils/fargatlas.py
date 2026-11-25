"""The colour atlas (Färgatlas 2022): each colour's id is its atlas number."""

import json
import logging
import os
import re

import utils.inbox as inbox
from utils.database import DATABASE, Color, Genebank

logger = logging.getLogger(__name__)

# The package ops put under PRIVATE_UPLOAD_FOLDER: the atlas's texts and photos (fargatlas.json, <id>.jpg and
# <id>-480.jpg), behind login and never in the repo.
MANIFEST = "fargatlas/fargatlas.json"
FOTO_ID = re.compile(r"[0-9]{2,3}-[a-z]")
FOTO_FIL = {"1600": "fargatlas/{}.jpg", "480": "fargatlas/{}-480.jpg"}

# (id, "G" gotlandskanin or "M" mellerudskanin, name, comment), as in production.
ATLAS_FARGER: tuple[tuple[int, str, str, str], ...] = (
    (11, "G", "Svart", "Kaninen ska vara helsvart"),
    (12, "G", "Albino", "Vit med röda ögon"),
    (13, "G", "Brun", "Kan ha svarta inslag. Kallas ibland för havanna eller havana"),
    (14, "G", "Blå", "Även buken ska vara blå"),
    (15, "G", "Isabella", "Gulbrun med blågrå mask"),
    (16, "G", "Madagaskar", "Brun med mörk mask"),
    (17, "G", "Sallander", "Vit med mörk mask. Kan vara aningen ljusbeige"),
    (18, "G", "Vit ej albino", "Vit med blå eller bruna ögon. Öronen kan vara svagt färgade"),
    (21, "G", "Järngrå", "Även grafitgrå och järnbrun räknas hit"),
    (22, "G", "Viltgrå", "Varierar, kan vara ljus till mörk, kallas även hargrå"),
    (23, "G", "Snöhare", "Vit/ljus päls med svarta toppar"),
    (24, "G", "Rödgul", "Inte klart åtskild från 25, även orange"),
    (25, "G", "Viltgul", "Inte klart åtskild från 24, även gul (med gul mage)"),
    (26, "G", "Viltblå", "Blå med ljus mage. Gråbrun med blått skimmer. Kallad ibland för pearl egern"),
    (27, "G", "Chinchilla", "Gråmelerad, även grå och blå chinchilla räknas hit"),
    (28, "G", "Järnblå", "Blå med inslag av beiga hårstrån"),
    (31, "G", "Svartbrokig", "Vit med svarta tecken, även med järngrå tecken räknas hit"),
    (32, "G", "Blåbrokig", "Vit med blå tecken"),
    (33, "G", "Viltgråbrokig", "Vit med viltgrå (hargrå) tecken"),
    (34, "G", "Gulbrokig", "Vit med gula tecken, även orange eller röda tecken"),
    (35, "G", "Madagaskarbrokig", "Vit med madagaskarteckning, alltså madagaskartecknad bottenfärg"),
    (36, "G", "Trefärgad", "Oftast vit med svarta och gula tecken, även kallad Tricolor och japanbrokig"),
    (37, "G", "Chinchillabrokig", "Vit med chinchillatecken, även blå chinchilla eller grå färg"),
    (38, "G", "Brunbrokig", "Vit med (mörk)bruna tecken"),
    (39, "G", "Brokad på annat sätt", "Vit med färgade tecken på annat sätt"),
    (41, "G", "Gul-blå japantecknad", "Tigrerad, mer eller mindre tydligt randig"),
    (42, "G", "Gul-svart japantecknad", "Tigrerad, mer eller mindre tydligt randig"),
    (43, "G", "Vit-svart japantecknad", "Tigrerad, mer eller mindre tydligt randig"),
    (46, "G", "Vit-blå japantecknad", "Tigrerad, mer eller mindre tydligt randig"),
    (49, "G", "Annan japanteckning", "Även Japanteckning av okänt slag"),
    (51, "G", "White blå och Otter blå", "Blå med ljus buk på särskilt sätt"),
    (52, "G", "White svart och Otter svart", "Svart med ljus buk på särskilt sätt"),
    (54, "G", "Svart med vita stickelhår", "Även med grå eller ljusbruna stickelhår. Kallas svensk päls"),
    (71, "G", "Wienertecknad", "Färgad (alla färger) med enstaka vita tecken. Ofta vit bläs eller vit tass"),
    (99, "G", "Allt annat", "Kaniner som inte passar in i någon av grupperna 11-54"),
    (100, "M", "Holländarteckning", "Svartbrokig med stora sammanhängande fält"),
    (101, "M", "Albino", "Vit med röda ögon"),
)


def seed_colors(gotland, mellerud):
    """Creates the atlas colours with their numbers as ids; returns {("G" | "M", name): Color}.

    Idempotent. A colour that exists with another name, genebank or id than the atlas gives would end up
    with a number that is not the atlas's, so the seed stops: the database needs `docker compose down -v`.
    """
    genebanks = {"G": gotland, "M": mellerud}
    colors = {}
    for id_, code, name, comment in ATLAS_FARGER:
        genebank = genebanks[code]
        stored = Color.get_or_none(Color.id == id_)
        other = Color.select().where(Color.name == name, Color.genebank == genebank, Color.id != id_).first()
        if other or (stored and (stored.name, stored.genebank_id) != (name, genebank.id)):
            raise ValueError(
                f"Colour {id_} {name!r} does not match the colours already in the database; "
                "its ids must be the atlas numbers. Recreate the database: docker compose down -v and remove "
                "postgres-data/ (a bind mount that down -v leaves alone; see README)"
            )
        colors[(code, name)] = stored or Color.create(id=id_, name=name, comment=comment, genebank=genebank)
    DATABASE.execute_sql(
        "SELECT setval(pg_get_serial_sequence('color', 'color_id'), (SELECT max(color_id) FROM color))"
    )
    return colors


def las_atlaspaket(logga_poster=True):
    """
    The package's manifest; {} when there is none, and an error in the log when it cannot be read. A colour entry
    that is not an object is left out, so one bad entry does not take the other colours with it, and logged unless
    `logga_poster` is off (the photo route: once per page is enough, not once per photo).
    """
    try:
        with open(inbox.private_path(MANIFEST), encoding="utf-8") as f:
            paket = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        logger.error("The colour atlas manifest cannot be read: %s", error)
        return {}
    if not isinstance(paket, dict) or not isinstance(paket.get("farger"), dict):
        logger.error("The colour atlas manifest has no farger object")
        return {}
    bad = [id_ for id_, farg in paket["farger"].items() if farg is not None and not isinstance(farg, dict)]
    if bad and logga_poster:
        logger.error("The colour atlas manifest has colour entries that are not objects: %s", ", ".join(bad))
    paket["farger"] = {id_: farg for id_, farg in paket["farger"].items() if isinstance(farg, dict)}
    return paket


def _text(value):
    """A text from the manifest, or None for anything that is not a string."""
    return value if isinstance(value, str) else None


def _foton(farg):
    """A colour's photos, with only the fields the page shows and only ids the photo endpoint serves."""
    foton = farg.get("foton")
    return [
        {"id": f["id"], "fotograf": _text(f.get("fotograf")), "bildtext": _text(f.get("bildtext"))}
        for f in (foton if isinstance(foton, list) else [])
        if isinstance(f, dict) and isinstance(f.get("id"), str) and FOTO_ID.fullmatch(f["id"])
    ]


def _nyckel(paket):
    """
    The determination key from the manifest, passed on as it is (ops checks it before every build), or None. A key
    of the wrong shape is logged and left out, and the page then shows the colours by genebank without the guide.
    """
    nyckel = paket.get("nyckel")
    if nyckel is None:
        return None
    if (
        isinstance(nyckel, dict)
        and isinstance(nyckel.get("start"), str)
        and isinstance(nyckel.get("fragor"), dict)
        and isinstance(nyckel.get("grupper"), list)
    ):
        return nyckel
    logger.error("The colour atlas manifest's key has the wrong shape")
    return None


def fargatlas_data():
    """Every colour from the database, by number, with the package's description, contrast, photos and key."""
    paket = las_atlaspaket()
    farger = paket.get("farger", {})
    grupper = paket.get("grupper")
    with DATABASE.atomic():
        colors = list(Color.select(Color, Genebank).join(Genebank).order_by(Color.id))
    rows = []
    for color in colors:
        farg = farger.get(str(color.id), {})
        rows.append(
            {
                "id": color.id,
                "name": color.name,
                "comment": color.comment,
                "genebank": color.genebank.name,
                "beskrivning": _text(farg.get("beskrivning")),
                "skiljs_fran": _text(farg.get("skiljs_fran")),
                # Only photos with both sizes on disk: a copy that stopped halfway gives "Foto saknas", not a broken image.
                "foton": [f for f in _foton(farg) if all(_finns(f["id"], storlek) for storlek in FOTO_FIL)],
            }
        )
    return {
        "version": _text(paket.get("version")),
        "grupper": {
            id_: {"beskrivning": _text(grupp.get("beskrivning"))}
            for id_, grupp in (grupper.items() if isinstance(grupper, dict) else [])
            if isinstance(grupp, dict)
        },
        "farger": rows,
        "nyckel": _nyckel(paket),
    }


def _finns(foto_id, storlek):
    return os.path.isfile(inbox.private_path(FOTO_FIL[storlek].format(foto_id)))


def foto_sokvag(foto_id, storlek):
    """The photo's file, built from the id and size alone; None unless the manifest lists it and the file exists."""
    if storlek not in FOTO_FIL or not FOTO_ID.fullmatch(foto_id):
        return None
    listed = {f["id"] for farg in las_atlaspaket(logga_poster=False).get("farger", {}).values() for f in _foton(farg)}
    return inbox.private_path(FOTO_FIL[storlek].format(foto_id)) if foto_id in listed and _finns(foto_id, storlek) else None
