"""
Nabewerking van gegenereerde SPARQL queries.

Verantwoordelijkheden:
- Verplichte prefixen injecteren als ze ontbreken
- LIMIT verwijderen uit lijstqueries
- COUNT detecteren in lijstmodus
- Provincie-filterpad normaliseren naar directe URI match
- LCASE = vervangen door CONTAINS
- heeftProvincie zonder prefLabel-pad corrigeren
"""

import re
import logging

import config
from sparql import executor as sparql_executor
from config import SPARQL_PREFIXES, PROVINCIE_URI

CBS_GRAPH = 'https://linkeddata.cultureelerfgoed.nl/rce/cho/graphs/cbs_woonplaatsen'

logger = logging.getLogger(__name__)


def inject_prefixes(query: str) -> str:
    """Voeg verplichte prefixen toe als ze ontbreken."""
    if "PREFIX ceo:" not in query:
        return SPARQL_PREFIXES + "\n\n" + query
    if "PREFIX rdfs:" not in query and "rdfs:" in query:
        query = "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n" + query
    if "PREFIX cbs:" not in query and "cbs:" in query:
        query = "PREFIX cbs: <https://opendata.cbs.nl/woonplaatsen/>\n" + query
    # Vervang altijd een foutieve rn:-prefix (zonder /2/) door de correcte versie.
    # Het LLM genereert soms PREFIX rn: <.../rn/> (zonder /2/), waarna
    # rn:b2d9a59a-... ongeldige SPARQL-syntax is.
    if "PREFIX rn: <https://data.cultureelerfgoed.nl/term/id/rn/>" in query and        "PREFIX rn: <https://data.cultureelerfgoed.nl/term/id/rn/2/>" not in query:
        query = query.replace(
            "PREFIX rn: <https://data.cultureelerfgoed.nl/term/id/rn/>",
            "PREFIX rn: <https://data.cultureelerfgoed.nl/term/id/rn/2/>"
        )
    if "PREFIX rn:" not in query and "rn:" in query:
        query = "PREFIX rn: <https://data.cultureelerfgoed.nl/term/id/rn/2/>\n" + query
    return query


def remove_limit(query: str) -> str:
    """Verwijder LIMIT uit een query (voor lijstvragen)."""
    return re.sub(r"\s*LIMIT\s+\d+", "", query, flags=re.IGNORECASE).strip()


def has_count(query: str) -> bool:
    """Geeft True als de query een COUNT bevat."""
    return bool(re.search(r"\bCOUNT\b", query, re.IGNORECASE))


def normalize_gezicht_uri(query: str) -> str:
    """
    Als de query een FILTER op een gezichtsnaam bevat, vervang die
    door een directe URI match of een UNION van meerdere URIs als
    er meerdere gezichten met dezelfde naam zijn.

    Van:
      ?gezicht ceo:heeftNaam ?naamObj . ?naamObj ceo:naam ?naam .
      FILTER(CONTAINS(LCASE(?naam), "deventer"))

    Naar (één gezicht):
      FILTER(?gezicht = <https://...gezicht/10134270>)

    Naar (meerdere gezichten):
      FILTER(?gezicht IN (<https://...10134270>, <https://...10134635>))
    """
    if "Gezicht" not in query and "gezicht" not in query.lower():
        return query
    if not config.GEZICHT_URI:
        return query

    # Zoek FILTER op naam variabele
    m = re.search(r'FILTER[^"]*"([^"]+)"', query, re.IGNORECASE)
    if not m:
        return query

    ctx = query[max(0, m.start() - 200) : m.end() + 10]
    if not any(x in ctx.lower() for x in ["gezicht", "naam"]):
        return query

    zoekterm = m.group(1).lower().strip()

    # Zoek exacte match eerst
    uri = config.GEZICHT_URI.get(zoekterm)

    # Als geen exacte match, zoek gedeeltelijke match (bijv. "deventer" -> "Deventer")
    if not uri:
        matches = {k: v for k, v in config.GEZICHT_URI.items() if zoekterm in k}
        if len(matches) == 1:
            uri = list(matches.values())[0]
        elif len(matches) > 1:
            # Meerdere matches — bouw FILTER IN op
            all_uris = []
            for v in matches.values():
                if isinstance(v, list):
                    all_uris.extend(v)
                else:
                    all_uris.append(v)
            uri_list = ", ".join(f"<{u}>" for u in all_uris)
            logger.info("Meerdere gezichten gevonden voor '%s': %d matches", zoekterm, len(all_uris))
            # Vervang de naam FILTER door een URI IN filter
            lines = query.split("\n")
            lines = [l for l in lines if not ("FILTER" in l and "naam" in l.lower() and "CONTAINS" in l)]
            query = "\n".join(lines)
            query = re.sub(
                r'([?]\w+)\s+ceo:heeftNaam\s+[?]\w+\s*\.\s*\n?\s*[?]\w+\s+ceo:naam\s+[?]\w+\s*\.\s*\n?',
                '', query
            )
            # Voeg FILTER IN toe na de gezicht variabele declaratie
            query = re.sub(
                r'([?]\w+)\s+a\s+ceo:Gezicht\s*\.',
                lambda m2: m2.group(0) + f"\n  FILTER({m2.group(1)} IN ({uri_list}))",
                query
            )
            return query

    if not uri:
        logger.debug("Gezicht '%s' niet gevonden in mapping", zoekterm)
        return query

    # Eén URI gevonden
    uris = uri if isinstance(uri, list) else [uri]
    uri_list = ", ".join(f"<{u}>" for u in uris)
    filter_expr = f"FILTER(?gezicht IN ({uri_list}))" if len(uris) > 1 else f"FILTER(?gezicht = <{uris[0]}>)"

    logger.info("Gezicht '%s' genormaliseerd naar %d URI(s)", zoekterm, len(uris))

    # Verwijder naam triple en FILTER
    lines = query.split("\n")
    lines = [l for l in lines if not ("ceo:naam" in l and "naamObj" in l.lower())]
    lines = [l for l in lines if not ("heeftNaam" in l)]
    lines = [l for l in lines if not ("FILTER" in l and "naam" in l.lower() and "CONTAINS" in l)]
    query = "\n".join(lines)

    # Voeg URI filter toe na ceo:Gezicht declaratie
    query = re.sub(
        r'([?]\w+)\s+a\s+ceo:Gezicht\s*\.',
        lambda m2: m2.group(0) + f"\n  {filter_expr}",
        query
    )
    return query



def remove_empty_optional(query: str) -> str:
    """Verwijder lege OPTIONAL {} blokken (kunnen ontstaan na postprocessing)."""
    return re.sub(r'OPTIONAL\s*\{\s*\}', '', query)


def remove_unbound_triples(query: str) -> str:
    """
    Verwijdert triple-patronen waarvan het SUBJECT nooit ECHT gebonden wordt
    door de rest van de query. Dit komt voor wanneer het LLM een relatie
    probeert te volgen die niet bestaat in het datamodel (bijv. de gemeente
    van een Gezicht rechtstreeks proberen op te halen, of een losse
    ?gemeenteUri rdfs:label ?gemeente regel zonder dat ?gemeenteUri ergens
    aan een echte URI of ander triple gekoppeld is). Zo'n patroon maakt de
    variabele in feite vrij over de HELE dataset, wat een ongerichte join
    veroorzaakt en timeouts geeft.

    Een variabele is pas ECHT gebonden als ze elders in de query voorkomt
    als OBJECT van een triple (?iets predicate ?dezeVar), niet alleen als
    subject van willekeurig veel "lookup"-triples (?dezeVar predicate ?iets).
    Simpelweg meerdere keren voorkomen als subject is NIET genoeg -- dat
    betekent alleen dat de variabele meerdere keren wordt gebruikt, niet
    dat ze ooit een waarde krijgt.

    Alleen toegepast op simpele "?subject predicate ?object ." regels
    (één triple per regel, geen OPTIONAL/FILTER-blokken) om veilig te blijven.
    Wordt herhaald tot er niets meer verwijderd wordt, zodat een keten van
    ongebonden variabelen (A hangt af van B, B hangt af van C, ...) volledig
    wordt opgeruimd.
    """
    def is_bound_as_object(var: str, full_query: str) -> bool:
        # Zoek of deze variabele ergens voorkomt als OBJECT (laatste deel)
        # van een triple: "... predicate ?var ." -- dat betekent dat de
        # variabele daar een waarde toegewezen krijgt.
        pattern = r"[?\w<>:/#.\-]+\s+[\w:]+\s+" + re.escape(var) + r"\s*\."
        return bool(re.search(pattern, full_query))

    changed = True
    while changed:
        changed = False
        lines = query.split("\n")
        kept_lines = []

        for line in lines:
            m = re.match(r"^\s*([?]\w+)\s+[\w:]+\s+[?]\w+\s*\.\s*$", line)
            if not m:
                kept_lines.append(line)
                continue

            subject_var = m.group(1)
            rest_of_query = query.replace(line, "", 1)

            if not is_bound_as_object(subject_var, rest_of_query) and subject_var != "?rm" and subject_var != "?gezicht":
                logger.info("Ongebonden triple verwijderd: %s", line.strip())
                changed = True
                continue  # regel overslaan = verwijderen

            kept_lines.append(line)

        query = "\n".join(kept_lines)

    return query


def wrap_risky_gezicht_naam_in_optional(query: str) -> str:
    """
    Een veelvoorkomende LLM-fout: "?gezicht rdfs:label ?gezichtNaam ." als
    VERPLICHTE (niet-OPTIONAL) triple. ceo:Gezicht heeft geen rdfs:label,
    dus dit veroorzaakt 0 resultaten zonder duidelijke foutmelding -- de
    rest van de query kan prima kloppen. Wrap dit patroon altijd in OPTIONAL,
    of verwijder het volledig als de gevonden naam toch nergens gebruikt wordt
    (bijv. niet in de SELECT).
    """
    pattern = r"^(\s*)([?]gezicht)\s+rdfs:label\s+([?]\w+)\s*\.\s*$"
    m = re.search(pattern, query, re.MULTILINE)
    if not m:
        return query

    var_name = m.group(3)
    indent = m.group(1)

    if var_name in re.findall(r"SELECT\s+(?:DISTINCT\s+)?((?:[?]\w+\s*)+)", query, re.IGNORECASE)[0] if re.findall(r"SELECT\s+(?:DISTINCT\s+)?((?:[?]\w+\s*)+)", query, re.IGNORECASE) else False:
        # De naam wordt getoond in de resultaten -- gebruik het juiste pad
        # binnen een OPTIONAL, niet rdfs:label
        replacement = (
            f"{indent}OPTIONAL {{ ?gezicht ceo:heeftNaam ?gezichtNaamObj . "
            f"?gezichtNaamObj ceo:naam {var_name} . }}"
        )
    else:
        # De naam wordt nergens gebruikt -- regel kan gewoon weg
        replacement = ""

    logger.info("Risicovolle ?gezicht rdfs:label triple herschreven/verwijderd")
    query = re.sub(pattern, replacement, query, count=1, flags=re.MULTILINE)
    return query


def add_gemeente_voorfilter_bij_gezicht(query: str) -> str:
    """
    Als een gezicht-URI is opgelost (FILTER ?gezicht = ... of IN (...)) en de
    query een ruimtelijke join (sfWithin/sfIntersects) met Rijksmonument
    bevat, maar nog GEEN gemeente-voorfilter heeft op het rijksmonument
    (?rm heeftBasisregistratieRelatie -> heeftGemeente), leidt dan de
    gemeente automatisch af (via één representatief rijksmonument binnen
    het gezicht) en voeg die toe als voorfilter. Dit voorkomt de timeout
    die ontstaat als sfWithin alle rijksmonumenten in Nederland moet scannen,
    en is robuuster dan vertrouwen op het LLM om de juiste gemeente te raden
    (een gezicht heeft niet altijd dezelfde naam als zijn gemeente, bijv.
    "Riel" hoort niet bij de gemeente "Riel").
    """
    if "Rijksmonument" not in query:
        return query
    if not re.search(r"sfWithin|sfIntersects", query):
        return query

    # Verwijder altijd eerst elk ONGEBONDEN gemeente-patroon waarbij het subject
    # nergens anders in de query gedefinieerd wordt (typisch: het LLM probeert de
    # gemeente van het GEZICHT zelf af te leiden via een niet-bestaande relatie,
    # zoals "?gezichtRelatie ceo:heeftGemeente ?gemeenteUri ." — dit subject komt
    # nergens anders voor en maakt de variabele in feite vrij over de hele dataset,
    # wat een ongerichte join over alle gemeenten veroorzaakt).
    for m in list(re.finditer(r"^\s*([?]\w+)\s+ceo:heeftGemeente\s+([?]\w+)\s*\.\s*$", query, re.MULTILINE)):
        subject_var = m.group(1)
        # Is dit subject ergens ANDERS in de query gedefinieerd (bijv. via
        # heeftBasisregistratieRelatie)? Zo niet, is het een los/ongebonden patroon.
        other_occurrences = re.findall(re.escape(subject_var) + r"\b", query)
        if len(other_occurrences) <= 1:
            query = query.replace(m.group(0), "")

    gezicht_match = re.search(
        r"FILTER\s*\(\s*\?gezicht\s*=\s*<([^>]+)>\s*\)",
        query,
        re.IGNORECASE,
    )
    if not gezicht_match:
        # Probeer ook de IN(...)-vorm en pak de eerste URI als representatief
        gezicht_match = re.search(
            r"FILTER\s*\(\s*\?gezicht\s+IN\s*\(\s*<([^>]+)>",
            query,
            re.IGNORECASE,
        )
    if not gezicht_match:
        return query

    gezicht_uri = gezicht_match.group(1)
    gemeente_uri = sparql_executor.get_gemeente_voor_gezicht(gezicht_uri)
    if not gemeente_uri:
        logger.warning("Kon geen gemeente afleiden voor gezicht %s — query blijft ongewijzigd (mogelijk timeout)", gezicht_uri)
        return query

    logger.info("Gemeente-voorfilter automatisch afgeleid voor gezicht %s: %s", gezicht_uri, gemeente_uri)

    # Verwijder ALLE bestaande heeftGemeente-regels op het rijksmonument, zowel
    # met vaste URI als met variabele. Het LLM kan namelijk zelf ook een
    # (foutieve) gemeente invullen op basis van de gezichtnaam (bijv. "Riel"
    # -> gokt op gemeente Goirle, terwijl dit specifieke gezicht in Eindhoven
    # ligt) — dus elke bestaande filter wordt altijd vervangen door de
    # betrouwbaar afgeleide versie, nooit naast elkaar behouden.
    query = re.sub(
        r"^\s*[?]\w+\s+ceo:heeftGemeente\s+(?:[?]\w+|<[^>]+>)\s*\.\s*$\n?",
        "",
        query,
        flags=re.MULTILINE,
    )
    # Verwijder ook losse heeftBasisregistratieRelatie-regels die uitsluitend
    # voor de (nu verwijderde) gemeente-relatie bedoeld waren en nergens anders
    # meer voor gebruikt worden, om duplicaten te voorkomen.
    query = re.sub(
        r"^\s*[?]rm\s+ceo:heeftBasisregistratieRelatie\s+[?]\w*[Gg]emeente\w*\s*\.\s*$\n?",
        "",
        query,
        flags=re.MULTILINE,
    )

    # Voeg het voorfilter toe direct na de eerste ?rm a ceo:Rijksmonument . regel
    query = re.sub(
        r"([?]rm\s+a\s+ceo:Rijksmonument\s*\.)",
        lambda m: m.group(0) +
                  f"\n  ?rm ceo:heeftBasisregistratieRelatie ?gemeenteVoorfilterBrr .\n"
                  f"  ?gemeenteVoorfilterBrr ceo:heeftGemeente <{gemeente_uri}> .",
        query,
        count=1,
    )

    return query


def normalize_gemeente_uri(query: str) -> str:
    """
    Vervang gemeente-filterpad door een directe URI match.
    Gebruikt de dynamisch geladen config.GEMEENTE_URI mapping.

    Van:
      ?brk ceo:gemeentenaam ?gemeente .
      FILTER(CONTAINS(LCASE(?gemeente), "den bosch"))

    Naar:
      ?brr ceo:heeftGemeente <http://...s-Hertogenbosch_(gemeente)> .
    """
    if "gemeentenaam" not in query and "heeftGemeente" not in query:
        return query

    # Als de gezicht-URI al is opgelost (normalize_gezicht_uri), is de locatie
    # van het GEZICHT al bepaald. ceo:Gezicht heeft geen heeftBasisregistratieRelatie,
    # dus een eventuele (foutieve) gemeentefilter DIRECT OP ?gezicht moet verwijderd worden.
    # De query loopt daarna gewoon door, want het rijksmonument heeft nog steeds
    # een eigen gemeente-voorfilter nodig (performance) dat WEL genormaliseerd moet worden.
    if re.search(r'FILTER\s*\(\s*\?gezicht\s*(=|IN\b)', query, re.IGNORECASE):
        lines = query.split("\n")
        cleaned = []
        for l in lines:
            # Alleen regels waar ?gezicht zelf het subject is van de gemeente-relatie
            if re.match(r'^\s*\?gezicht\s+ceo:(heeftBasisregistratieRelatie|heeftGemeente)\b', l):
                continue
            cleaned.append(l)
        query = "\n".join(cleaned)
        # GEEN return hier — ga door naar de normale ?rm gemeentenormalisatie hieronder

    if not config.GEMEENTE_URI:
        return query  # mapping nog niet geladen, laat query ongewijzigd

    # Zoek de volledige FILTER regel die over gemeente gaat
    filter_match = None
    for fm in re.finditer(r'FILTER\s*\([^\n]*\)', query, re.IGNORECASE):
        if any(x in fm.group(0).lower() for x in ["gemeente", "woonplaats"]):
            filter_match = fm
            break
    if not filter_match:
        return query

    # Probeer elke quoted string in deze FILTER op de mapping
    zoektermen = re.findall(r'"([^"]+)"', filter_match.group(0))
    uri = None
    zoekterm = None
    for term in zoektermen:
        candidate = term.lower().strip()
        if candidate in config.GEMEENTE_URI:
            uri = config.GEMEENTE_URI[candidate]
            zoekterm = candidate
            break

    if not uri:
        logger.debug("Geen van de zoektermen %s gevonden in gemeentemapping", zoektermen)
        return query

    logger.info("Gemeente '%s' genormaliseerd naar URI: %s", zoekterm, uri)

    # Verwijder de gemeentenaam triple en de gevonden FILTER regel
    lines = query.split("\n")
    lines = [l for l in lines if not ("gemeentenaam" in l.lower() and "filter" not in l.lower())]
    lines = [l for l in lines if filter_match.group(0) not in l]
    query = "\n".join(lines)

    # Vervang heeftBRKRelatie pad door heeftGemeente met directe URI
    # Verwijder: ?brr ceo:heeftBRKRelatie ?brk .
    query = re.sub(
        r'[?]\w+\s+ceo:heeftBRKRelatie\s+[?]\w+\s*\.\s*\n?',
        '', query
    )
    # Voeg heeftGemeente toe aan de BasisregistratieRelatie
    query = re.sub(
        r'([?]\w+)\s+ceo:heeftBasisregistratieRelatie\s+([?]\w+)\s*\.',
        lambda m2: m2.group(1) + ' ceo:heeftBasisregistratieRelatie ' + m2.group(2) + ' .\n  ' +
                   m2.group(2) + ' ceo:heeftGemeente <' + uri + '> .',
        query,
        count=1
    )
    return query


JURIDISCHE_STATUS_RM = "rn:b2d9a59a-fe1e-4552-9a05-3c2acddff864"


def add_juridische_status_filter(query: str, question: str = "") -> str:
    """
    Voeg automatisch de standaard juridische status filter (rijksmonument) toe
    als de query ?rm a ceo:Rijksmonument gebruikt maar de filter ontbreekt.

    Wordt overgeslagen als de vraag expliciet om alle statussen vraagt
    (bijv. "ongeacht status", "alle statussen", "afgevoerd", "voorbeschermd").
    """
    if "Rijksmonument" not in query:
        return query
    if "heeftJuridischeStatus" in query:
        return query

    # Als de vraag expliciet over status gaat, niet automatisch invullen
    status_keywords = [
        "status", "voorbescherm", "afgevoerd", "voormalig",
        "geen rijksmonument", "ongeacht"
    ]
    if any(kw in question.lower() for kw in status_keywords):
        logger.debug("Status-gerelateerde vraag — geen automatische filter toegevoegd")
        return query

    return re.sub(
        r"([?]\w+)\s+a\s+ceo:Rijksmonument\s*\.",
        lambda m: m.group(0) + "\n  " + m.group(1) +
                  " ceo:heeftJuridischeStatus " + JURIDISCHE_STATUS_RM + " .",
        query,
        count=1,
    )


def add_geometry_optional(query: str) -> str:
    """
    Voeg automatisch OPTIONAL geometrie toe als de hoofdklasse geometrie kan hebben
    maar ?wkt nog niet in de query zit. Zo toont de kaart altijd resultaten als
    geometrie beschikbaar is, ook als het LLM dit vergeet.
    """
    if "asWKT" in query:
        return query

    # Welke hoofdklasse wordt bevraagd en welke variabele hoort erbij
    klasse_var = None
    for klasse in ["Rijksmonument", "Gezicht", "ArcheologischOnderzoeksgebied", "Werelderfgoed"]:
        m = re.search(r"([?]\w+)\s+a\s+ceo:" + klasse + r"\s*\.", query)
        if m:
            klasse_var = m.group(1)
            break

    if not klasse_var:
        return query

    # Voeg PREFIX geo: toe als die ontbreekt
    if "PREFIX geo:" not in query:
        query = "PREFIX geo: <http://www.opengis.net/ont/geosparql#>\n" + query

    # Voeg ?wkt toe aan SELECT
    query = re.sub(
        r"(SELECT\s+(?:DISTINCT\s+)?)((?:\?\w+\s*)+)",
        lambda m: m.group(1) + m.group(2).rstrip() + " ?wkt ",
        query,
        count=1,
    )

    # Voeg OPTIONAL geometrie toe na de klasse-declaratie
    query = re.sub(
        r"(" + re.escape(klasse_var) + r"\s+a\s+ceo:\w+\s*\.)",
        lambda m: m.group(0) + "\n  OPTIONAL { " + klasse_var +
                  " ceo:heeftGeometrie ?geom . ?geom geo:asWKT ?wkt . }",
        query,
        count=1,
    )

    return query


def fix_rijksmonument_woonplaats_pad(query: str) -> str:
    """
    Als de query ceo:woonplaatsnaam gebruikt voor een Rijksmonument (geeft de
    GEMEENTENAAM terug, niet de kern), en de zoekterm matcht NIET op de
    GEMEENTE_URI mapping, dan is het waarschijnlijk een kernnaam (zoals
    "Werkhoven" binnen gemeente Bunnik). Herschrijf dan naar het
    heeftLocatieAanduiding -> locatienaam pad, dat wel kernnamen bevat.
    """
    if "Rijksmonument" not in query:
        return query
    if "ArcheologischOnderzoeksgebied" in query:
        return query
    if "woonplaatsnaam" not in query:
        return query

    filter_match = None
    for fm in re.finditer(r'FILTER\s*\([^\n]*\)', query, re.IGNORECASE):
        if "woonplaats" in fm.group(0).lower():
            filter_match = fm
            break
    if not filter_match:
        return query

    zoektermen = re.findall(r'"([^"]+)"', filter_match.group(0))
    if not zoektermen:
        return query
    zoekterm = zoektermen[0]

    # Als de zoekterm WEL een bekende gemeentenaam is, laat de query ongewijzigd
    # (normalize_gemeente_uri handelt dat geval al af)
    if zoekterm.lower().strip() in config.GEMEENTE_URI:
        return query

    logger.info(
        "Woonplaatsnaam '%s' is geen bekende gemeente — herschrijf naar locatienaam-pad",
        zoekterm,
    )

    # Verwijder de oude heeftBAGRelatie/woonplaatsnaam regels en de FILTER
    lines = query.split("\n")
    cleaned = []
    bag_var = None
    for l in lines:
        m = re.match(r'^\s*[?]\w+\s+ceo:heeftBAGRelatie\s+([?]\w+)\s*\.', l)
        if m:
            bag_var = m.group(1)
            continue
        if bag_var and f"{bag_var} ceo:woonplaatsnaam" in l:
            continue
        if filter_match.group(0) in l:
            continue
        cleaned.append(l)
    query = "\n".join(cleaned)

    # Voeg het locatienaam-pad toe na heeftBasisregistratieRelatie
    query = re.sub(
        r"([?]\w+\s+ceo:heeftBasisregistratieRelatie\s+[?]\w+\s*\.)",
        lambda m: m.group(1) +
                  f'\n  ?rm ceo:heeftLocatieAanduiding ?locatie . ?locatie ceo:locatienaam ?locatienaam .'
                  f'\n  FILTER(CONTAINS(LCASE(?locatienaam), "{zoekterm.lower()}"))',
        query,
        count=1,
    )

    return query


def add_gemeente_context_bij_locatienaam(query: str) -> str:
    """
    Als de query ceo:locatienaam gebruikt (kernnaam-zoekopdracht) maar nog geen
    gemeente bevat, voeg de gemeentenaam toe als extra context zodat de gebruiker
    ziet in welke gemeente de kern ligt. Gebruikt de OFFICIËLE heeftGemeente-URI
    (via rdfs:label), NIET ceo:gemeentenaam via BRK (die kan afwijkende waarden geven).
    """
    if "locatienaam" not in query:
        return query

    # Zorg dat ?locatienaam zelf altijd in de SELECT staat, ook als het LLM
    # die alleen in de FILTER gebruikte
    select_match = re.search(r"SELECT\s+(?:DISTINCT\s+)?(?:\?\w+\s*)+", query, re.IGNORECASE)
    if select_match and "?locatienaam" not in select_match.group(0):
        query = re.sub(
            r"(SELECT\s+(?:DISTINCT\s+)?)((?:\?\w+\s*)+)",
            lambda m: m.group(1) + m.group(2).rstrip() + " ?locatienaam ",
            query,
            count=1,
        )

    if "heeftGemeente" in query:
        return query

    if "PREFIX rdfs:" not in query:
        query = "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n" + query

    # Voeg ?gemeente toe aan de SELECT
    query = re.sub(
        r"(SELECT\s+(?:DISTINCT\s+)?)((?:\?\w+\s*)+)",
        lambda m: m.group(1) + m.group(2).rstrip() + " ?gemeente ",
        query,
        count=1,
    )

    # Voeg de OPTIONAL toe na de locatienaam-FILTER regel.
    # FILTER(!CONTAINS(?gemeente, "'")) sluit de archaïsche apostrof-variant uit
    # (zoals "'s-Gravenhage" naast "Den Haag") zodat er geen duplicaatrij ontstaat
    # voor hetzelfde monument met twee verschillende gemeentelabels.
    query = re.sub(
        r'(FILTER\s*\(\s*CONTAINS\s*\(\s*LCASE\s*\(\s*\?locatienaam\s*\)[^)]*\)\s*\))',
        lambda m: m.group(0) +
                  "\n  OPTIONAL {\n"
                  "    ?rm ceo:heeftBasisregistratieRelatie ?relatieGemeente .\n"
                  "    ?relatieGemeente ceo:heeftGemeente ?gemeenteUri .\n"
                  "    ?gemeenteUri rdfs:label ?gemeente .\n"
                  "    FILTER(!CONTAINS(?gemeente, \"'\"))\n"
                  "  }",
        query,
        count=1,
    )

    return query


def fix_optional_geometry_in_spatial_filter(query: str) -> str:
    """
    Als een geometrievariabele (bijv. ?wkt) binnen een OPTIONAL staat maar WEL
    gebruikt wordt in een geof:sfWithin/sfIntersects FILTER, maak die regel dan
    verplicht. Een ruimtelijke FILTER op een ongebonden variabele faalt altijd,
    wat tot 0 resultaten leidt ook als er wel matches zouden moeten zijn.
    """
    spatial_match = re.search(
        r"geof:(?:sfWithin|sfIntersects|sfContains|sfOverlaps)\s*\(\s*(\?\w+)\s*,\s*(\?\w+)\s*\)",
        query,
    )
    if not spatial_match:
        return query

    geo_vars = {spatial_match.group(1), spatial_match.group(2)}

    # Zoek elke OPTIONAL { ... } blok dat een van deze variabelen bindt
    def maak_verplicht(m):
        block = m.group(0)
        binnenkant = m.group(1)
        # Bevat dit OPTIONAL-blok een binding voor een van de ruimtelijke variabelen?
        if any(re.search(re.escape(v) + r"\b", binnenkant) for v in geo_vars):
            logger.info("OPTIONAL rond ruimtelijke geometrie verplicht gemaakt: %s", binnenkant.strip())
            return binnenkant.strip()
        return block

    query = re.sub(
        r"OPTIONAL\s*\{([^{}]*)\}",
        maak_verplicht,
        query,
    )

    return query


def fix_provincie_pad(query: str) -> str:
    """
    Zorg dat heeftProvincie altijd via rdfs:label loopt.

    Als het LLM alleen ?brr ceo:heeftProvincie ?prov . genereert
    zonder rdfs:label stap, voeg die dan toe.
    """
    if "heeftProvincie" not in query:
        return query
    if "provURI" in query or "rdfs:label" in query:
        return query
    query = re.sub(
        r"([?]\w+)\s+ceo:heeftProvincie\s+([?]\w+)\s*\.",
        lambda m: (
            m.group(1) + " ceo:heeftProvincie ?provURI . "
            "?provURI rdfs:label " + m.group(2) + " ."
        ),
        query,
    )
    return query


def normalize_provincie_uri(query: str) -> str:
    """
    Vervang het provincie-filterpad door een directe URI match.

    Van:
      ?provURI rdfs:label ?provincie .
      FILTER(CONTAINS(LCASE(STR(?provincie)), "utrecht"))

    Naar:
      ceo:heeftProvincie <http://...Utrecht_(provincie)> .
    """
    if "heeftProvincie" not in query:
        return query

    m = re.search(r'FILTER[^"]*"([^"]+)"', query, re.IGNORECASE)
    if not m:
        return query

    ctx = query[max(0, m.start() - 100) : m.end() + 10]
    if not any(x in ctx.lower() for x in ["provinci", "provlabel"]):
        return query

    zoekterm = m.group(1).lower().strip()
    uri = PROVINCIE_URI.get(zoekterm)
    if not uri:
        logger.warning("Onbekende provincie: '%s' — filter niet genormaliseerd", zoekterm)
        return query

    logger.info("Provincie '%s' genormaliseerd naar URI: %s", zoekterm, uri)
    lines = query.split("\n")
    lines = [l for l in lines if not ("rdfs:label" in l and "provinci" in l.lower())]
    lines = [l for l in lines if not ("FILTER" in l and "provinci" in l.lower())]
    query = "\n".join(lines)
    query = re.sub(
        r"ceo:heeftProvincie\s+[?]\w+\s*\.",
        "ceo:heeftProvincie <" + uri + "> .",
        query,
    )
    return query


def add_gezicht_wkt(query: str) -> str:
    """
    Als de query sfWithin gebruikt met een gezichtgeometrie maar ?gezichtWkt
    niet in de SELECT staat, voeg die dan automatisch toe.
    Zo wordt het gezichtspolygoon altijd op de kaart getoond.
    """
    if "sfWithin" not in query:
        return query
    if "gezichtWkt" in query and "SELECT" in query:
        # Check of gezichtWkt al in SELECT staat
        select_match = re.search(r'SELECT.*?WHERE', query, re.IGNORECASE | re.DOTALL)
        if select_match and "gezichtWkt" in select_match.group(0):
            return query
    # Voeg ?gezichtWkt toe aan SELECT en aan WHERE als die er al in zit
    if "gezichtWkt" not in query:
        # Voeg toe aan WHERE: haal WKT op van het gezicht
        query = re.sub(
            r'(\?gezichtGeom\s+\w+:asWKT\s+\?gezichtWkt\s*\.)',
            r'',
            query
        )
        # Als gezichtGeom wel bestaat maar gezichtWkt niet
        query = re.sub(
            r'(\?\w+Geom\s+(?:geo|gsp):asWKT\s+\?\w+Wkt\s*\.)',
            r'',
            query
        )
    # Voeg ?gezichtWkt toe aan SELECT als die er nog niet in zit
    if "gezichtWkt" in query and not re.search(r'SELECT[^{]*gezichtWkt', query, re.IGNORECASE | re.DOTALL):
        query = re.sub(
            r'(SELECT\s+(?:DISTINCT\s+)?)',
            r'?gezichtWkt ',
            query,
            count=1,
            flags=re.IGNORECASE
        )
    return query


def fix_label_filter(query: str) -> str:
    """
    Vervang FILTER(LCASE(?x) = "waarde") door FILTER(CONTAINS(LCASE(?x), "waarde")).
    Taalgelabelde strings kunnen niet met = vergeleken worden.
    """
    return re.sub(
        r"FILTER\s*\(\s*LCASE\s*\((\?\w+)\)\s*=\s*(\"[\w\s]+\")\s*\)",
        lambda m: "FILTER(CONTAINS(LCASE(" + m.group(1) + "), " + m.group(2) + "))",
        query,
        flags=re.IGNORECASE,
    )


def add_safety_limit(query: str, max_rows: int = 10000) -> str:
    """Zet LIMIT altijd op 10000 (Virtuoso maximum).
    Vervangt ook lagere LIMITs die het LLM genereert.
    """
    existing = re.search(r"\bLIMIT\s+(\d+)", query, re.IGNORECASE)
    if existing:
        current = int(existing.group(1))
        if current < max_rows:
            query = re.sub(r"\bLIMIT\s+\d+", f"LIMIT {max_rows}", query, flags=re.IGNORECASE)
    else:
        query = query.strip() + f"\nLIMIT {max_rows}"
    return query


def postprocess(query: str, mode: str, question: str = "") -> str:
    """
    Pas alle nabewerking toe op een gegenereerde SPARQL query.

    Volgorde is belangrijk:
    1. Strip backticks
    2. Inject prefixen
    3. Fix provincie pad
    4. Normaliseer provincie naar URI
    5. Fix label filters
    6. Verwijder LIMIT (als lijst-modus) — altijd als laatste
    """
    query = query.replace("```sparql", "").replace("```", "").strip()
    query = remove_unbound_triples(query)
    query = wrap_risky_gezicht_naam_in_optional(query)
    query = inject_prefixes(query)
    query = add_juridische_status_filter(query, question)
    query = add_geometry_optional(query)
    query = fix_optional_geometry_in_spatial_filter(query)
    query = fix_rijksmonument_woonplaats_pad(query)
    query = add_gemeente_context_bij_locatienaam(query)
    query = normalize_gezicht_uri(query)
    query = add_gemeente_voorfilter_bij_gezicht(query)
    query = normalize_gemeente_uri(query)
    query = remove_empty_optional(query)
    query = fix_provincie_pad(query)
    query = normalize_provincie_uri(query)
    query = add_gezicht_wkt(query)
    query = fix_label_filter(query)
    query = remove_unbound_triples(query)
    query = remove_empty_optional(query)

    if mode == "lijst":
        query = remove_limit(query)
    # Tellingsvragen krijgen geen LIMIT — die geven sowieso weinig rijen terug
    if mode != "telling":
        query = add_safety_limit(query, max_rows=10000)

    return query
