"""The colour atlas (Färgatlas 2022): each colour's id is its atlas number."""

from utils.database import DATABASE, Color

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
                "its ids must be the atlas numbers. Recreate the database: docker compose down -v"
            )
        colors[(code, name)] = stored or Color.create(id=id_, name=name, comment=comment, genebank=genebank)
    DATABASE.execute_sql(
        "SELECT setval(pg_get_serial_sequence('color', 'color_id'), (SELECT max(color_id) FROM color))"
    )
    return colors
