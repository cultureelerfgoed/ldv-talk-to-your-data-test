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

from config import SPARQL_PREFIXES, PROVINCIE_URI

logger = logging.getLogger(__name__)


def inject_prefixes(query: str) -> str:
    """Voeg verplichte prefixen toe als ze ontbreken."""
    if "PREFIX ceo:" not in query:
        return SPARQL_PREFIXES + "\n\n" + query
    if "PREFIX rdfs:" not in query and "rdfs:" in query:
        return "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n" + query
    return query


def remove_limit(query: str) -> str:
    """Verwijder LIMIT uit een query (voor lijstvragen)."""
    return re.sub(r"\s*LIMIT\s+\d+", "", query, flags=re.IGNORECASE).strip()


def has_count(query: str) -> bool:
    """Geeft True als de query een COUNT bevat."""
    return bool(re.search(r"\bCOUNT\b", query, re.IGNORECASE))


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


def postprocess(query: str, mode: str) -> str:
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
    query = inject_prefixes(query)
    query = fix_provincie_pad(query)
    query = normalize_provincie_uri(query)
    query = fix_label_filter(query)

    if mode == "lijst":
        query = remove_limit(query)

    return query
