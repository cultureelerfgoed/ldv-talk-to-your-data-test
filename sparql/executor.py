"""
SPARQL query executor.

Verantwoordelijkheden:
- Query uitvoeren op het RCE SPARQL endpoint
- Resultaten dedupliceren op ?rm (monument URI)
- Foutafhandeling voor timeouts en HTTP-fouten
"""

import logging
import math
import re
from typing import Any

import requests

from config import SPARQL_ENDPOINT, PROVINCIE_NAAM, PROVINCIE_URI

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30


def execute(query: str) -> dict[str, Any]:
    """
    Voer een SPARQL query uit op het RCE endpoint.

    Returns:
        SPARQL JSON resultaat als dict, gededupliceerd op ?rm.

    Raises:
        requests.exceptions.Timeout: Bij timeout.
        requests.exceptions.HTTPError: Bij HTTP-fouten.
    """
    logger.info("Query uitvoeren op %s", SPARQL_ENDPOINT)

    # Lees en verwijder de OPPERVLAKTE_FILTER marker (indien aanwezig) — dit is
    # een gewone SPARQL-comment (#) die Virtuoso al negeert, maar we lezen hem
    # hier uit om na ontvangst zelf op berekende oppervlakte te filteren.
    oppervlakte_filter = None
    filter_match = re.search(
        r"#\s*OPPERVLAKTE_FILTER:\s*operator=(\w+)\s+waarde=([\d.]+)\s+eenheid=(\w+)",
        query,
        re.IGNORECASE,
    )
    if filter_match:
        oppervlakte_filter = {
            "operator": filter_match.group(1).upper(),
            "waarde": float(filter_match.group(2)),
            "eenheid": filter_match.group(3).lower(),
        }
        logger.info("Oppervlaktefilter gedetecteerd: %s", oppervlakte_filter)

    response = requests.get(
        SPARQL_ENDPOINT,
        params={"query": query, "format": "json"},
        headers={"Accept": "application/sparql-results+json"},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    data = _translate_provincie_uris(data)

    # Voeg waarschuwing toe als de query leunt op een handmatig ingevoerde
    # plaatsnaam zonder officiële URI-koppeling (woonplaatsnaam of locatienaam).
    # Dit geldt voor archeologische onderzoeksgebieden (altijd via woonplaatsnaam)
    # EN voor rijksmonumenten die via het locatienaam-pad gezocht zijn (kernnamen
    # zoals "Werkhoven" die geen eigen gemeente-URI hebben).
    if "woonplaatsnaam" in query or "locatienaam" in query:
        data["_warning_woonplaats"] = (
            "Let op: deze resultaten zijn gefilterd op een handmatig ingevoerde "
            "plaatsnaam (geen officiële gemeente-koppeling). Spellingsverschillen "
            "kunnen resultaten missen of onjuist groeperen "
            "(bijv. 'Alphen' i.p.v. 'Alphen aan den Rijn')."
        )

    # Voeg waarschuwing toe als resultaat gelijk is aan de LIMIT
    # (Virtuoso heeft een max van 10000 rijen)
    bindings = data.get("results", {}).get("bindings", [])
    limit_match = None
    import re as _re
    limit_match = _re.search(r"\bLIMIT\s+(\d+)", query, _re.IGNORECASE)
    if limit_match:
        limit_val = int(limit_match.group(1))
        if len(bindings) >= limit_val:
            data["_warning"] = (
                f"De resultaten zijn beperkt tot {limit_val} rijen (maximumlimiet bereikt). "
                f"Er kunnen meer resultaten bestaan. Verfijn je zoekvraag voor volledigere resultaten."
            )

    original = len(data.get("results", {}).get("bindings", []))
    data = add_computed_oppervlakte(data, oppervlakte_filter)
    data = _deduplicate(data)
    deduped = len(data.get("results", {}).get("bindings", []))

    if original != deduped:
        logger.info("Deduplicatie: %d → %d rijen", original, deduped)

    return data


def _translate_provincie_uris(data: dict) -> dict:
    """Vertaal ?provURI waarden naar leesbare provincienamen."""
    bindings = data.get("results", {}).get("bindings", [])
    for row in bindings:
        if "provURI" in row:
            uri = row["provURI"].get("value", "")
            naam = PROVINCIE_NAAM.get(uri)
            if naam:
                row["provincie"] = {"type": "literal", "value": naam}
            else:
                # Gebruik het laatste deel van de URI als fallback
                row["provincie"] = {"type": "literal", "value": uri.split("/")[-1]}
    # Voeg provincie toe aan vars als provURI aanwezig is
    vars_ = data.get("head", {}).get("vars", [])
    if "provURI" in vars_ and "provincie" not in vars_:
        idx = vars_.index("provURI")
        vars_.insert(idx, "provincie")
    return data



# Cache voor gezicht -> gemeente-URI afleiding (on-demand, in-memory voor de sessie)
_GEZICHT_GEMEENTE_CACHE: dict[str, str | None] = {}


def get_gemeente_voor_gezicht(gezicht_uri: str) -> str | None:
    """
    Leidt de gemeente-URI af voor een gezicht, via één rijksmonument dat
    ruimtelijk binnen dat gezicht ligt (gezichten hebben geen eigen
    gemeente-relatie). Resultaat wordt in-memory gecached zodat dezelfde
    gezicht-URI niet herhaaldelijk bevraagd wordt.

    Geeft None terug als er geen rijksmonument binnen het gezicht ligt
    of bij een fout (bijv. timeout) -- de aanroeper moet hiermee om kunnen gaan.
    """
    if gezicht_uri in _GEZICHT_GEMEENTE_CACHE:
        return _GEZICHT_GEMEENTE_CACHE[gezicht_uri]

    query = f"""
PREFIX ceo: <https://linkeddata.cultureelerfgoed.nl/def/ceo#>
PREFIX geo: <http://www.opengis.net/ont/geosparql#>
PREFIX geof: <http://www.opengis.net/def/function/geosparql/>

SELECT ?gemeenteUri WHERE {{
  <{gezicht_uri}> ceo:heeftGeometrie ?gGeom .
  ?gGeom geo:asWKT ?gWkt .

  ?rm a ceo:Rijksmonument .
  ?rm ceo:heeftGeometrie ?rmGeom .
  ?rmGeom geo:asWKT ?rmWkt .
  FILTER(geof:sfWithin(?rmWkt, ?gWkt))

  ?rm ceo:heeftBasisregistratieRelatie ?brr .
  ?brr ceo:heeftGemeente ?gemeenteUri .
}}
LIMIT 1
"""
    try:
        response = requests.get(
            SPARQL_ENDPOINT,
            params={"query": query, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        bindings = data.get("results", {}).get("bindings", [])
        gemeente_uri = bindings[0]["gemeenteUri"]["value"] if bindings else None
        _GEZICHT_GEMEENTE_CACHE[gezicht_uri] = gemeente_uri
        logger.info("Gezicht %s -> gemeente %s afgeleid", gezicht_uri, gemeente_uri)
        return gemeente_uri
    except Exception as e:
        logger.warning("Kon gemeente niet afleiden voor gezicht %s: %s", gezicht_uri, e)
        _GEZICHT_GEMEENTE_CACHE[gezicht_uri] = None
        return None


def load_gezicht_mapping() -> dict:
    """
    Haal alle gezicht URIs en namen op uit het endpoint bij opstarten.
    Geeft een dict terug van lowercase naam -> URI.
    Meerdere gezichten kunnen dezelfde plaatsnaam hebben (bijv. meerdere in Amsterdam).
    In dat geval worden alle URIs opgeslagen als lijst.
    """
    query = """
PREFIX ceo: <https://linkeddata.cultureelerfgoed.nl/def/ceo#>
SELECT DISTINCT ?gezicht ?naam WHERE {
  ?gezicht a ceo:Gezicht .
  ?gezicht ceo:heeftNaam ?naamObj .
  ?naamObj ceo:naam ?naam .
}
"""
    try:
        response = requests.get(
            SPARQL_ENDPOINT,
            params={"query": query, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        mapping = {}
        for row in data.get("results", {}).get("bindings", []):
            naam = row["naam"]["value"].lower().strip()
            uri = row["gezicht"]["value"]
            if naam in mapping:
                # Meerdere gezichten met zelfde naam — sla beide op als lijst
                existing = mapping[naam]
                if isinstance(existing, list):
                    existing.append(uri)
                else:
                    mapping[naam] = [existing, uri]
            else:
                mapping[naam] = uri
        logger.info("Gezichtmapping geladen: %d namen", len(mapping))
        return mapping
    except Exception as e:
        logger.warning("Gezichtmapping kon niet worden geladen: %s", e)
        return {}


def load_gemeente_mapping() -> dict:
    """
    Haal alle gemeente URIs en labels op uit het endpoint bij opstarten.
    Geeft een dict terug van lowercase label -> URI.
    Meerdere labels per gemeente (bijv. Den Bosch / 's-Hertogenbosch) worden
    allemaal gemapt naar dezelfde URI.
    """
    query = """
PREFIX ceo: <https://linkeddata.cultureelerfgoed.nl/def/ceo#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?gemeente ?label WHERE {
  ?rm a ceo:Rijksmonument .
  ?rm ceo:heeftBasisregistratieRelatie ?brr .
  ?brr ceo:heeftGemeente ?gemeente .
  ?gemeente rdfs:label ?label .
}
"""
    try:
        response = requests.get(
            SPARQL_ENDPOINT,
            params={"query": query, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        mapping = {}
        for row in data.get("results", {}).get("bindings", []):
            label = row["label"]["value"].lower().strip()
            uri = row["gemeente"]["value"]
            mapping[label] = uri
        logger.info("Gemeentemapping geladen: %d labels voor gemeenten", len(mapping))
        return mapping
    except Exception as e:
        logger.warning("Gemeentemapping kon niet worden geladen: %s", e)
        return {}


def _polygon_area_m2(wkt: str) -> float | None:
    """
    Berekent de oppervlakte van een POLYGON of MULTIPOLYGON WKT-string in
    vierkante meters, via de schoenveterformule met een equirectangular
    projectie. Geschikt voor gebieden tot provincie-grootte in Nederland;
    niet bedoeld voor zeer grote of poolnabije gebieden.
    """
    if not wkt:
        return None

    wkt = re.sub(r'^<[^>]+>\s*', '', wkt).strip()

    if wkt.upper().startswith("MULTIPOLYGON"):
        # Elke losse polygoon-ring optellen
        rings = re.findall(r'\(\(([^()]+)\)\)', wkt)
    elif wkt.upper().startswith("POLYGON"):
        rings = re.findall(r'\(\(([^()]+)\)\)', wkt)
    else:
        return None  # geen vlak (POINT/LINESTRING) heeft geen oppervlakte

    if not rings:
        return None

    total_area = 0.0
    R = 6371000  # aardradius in meters

    for ring in rings:
        points = []
        for pair in ring.split(','):
            parts = pair.strip().split()
            if len(parts) < 2:
                continue
            lon, lat = float(parts[0]), float(parts[1])
            points.append((lon, lat))

        if len(points) < 3:
            continue

        lat0 = points[0][1]
        xy = [
            (
                math.radians(lon) * R * math.cos(math.radians(lat0)),
                math.radians(lat) * R,
            )
            for lon, lat in points
        ]

        area = 0.0
        n = len(xy)
        for i in range(n):
            x1, y1 = xy[i]
            x2, y2 = xy[(i + 1) % n]
            area += x1 * y2 - x2 * y1
        total_area += abs(area) / 2

    return total_area


def add_computed_oppervlakte(
    data: dict[str, Any], oppervlakte_filter: dict | None = None
) -> dict[str, Any]:
    """
    Berekent oppervlakte (m2 en hectare) uit elke WKT-waarde in de resultaten
    en voegt die toe als extra velden ?oppervlakte_m2 / ?oppervlakte_ha.
    Alleen relevant voor klassen zonder kant-en-klare oppervlakte-attributen
    (Werelderfgoed/Gezicht hebben die al via ceo:oppervlakteInHectare).

    Als oppervlakte_filter is meegegeven (operator/waarde/eenheid), worden
    rijen die niet aan de drempelwaarde voldoen verwijderd uit het resultaat.
    """
    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        return data

    # Skip volledig als de kant-en-klare attributen al aanwezig zijn
    # (Werelderfgoed/Gezicht) — die zijn altijd correcter en sneller dan een
    # eigen Python-berekening, en mogen nooit overschreven worden.
    existing_vars = set(data.get("head", {}).get("vars", []))
    if existing_vars & {"oppervlakteHa", "oppervlakteKm2", "oppervlakte_ha", "oppervlakte_m2"}:
        return data

    wkt_vars = [v for v in data.get("head", {}).get("vars", []) if "wkt" in v.lower()]
    if not wkt_vars:
        return data

    added_var = False
    gefilterde_bindings = []
    for row in bindings:
        area_m2 = None
        for wkt_var in wkt_vars:
            if wkt_var not in row or not row[wkt_var].get("value"):
                continue
            berekend = _polygon_area_m2(row[wkt_var]["value"])
            if berekend is not None:
                area_m2 = berekend
                break

        if area_m2 is not None:
            row["oppervlakte_m2"] = {"type": "literal", "value": f"{area_m2:.1f}"}
            row["oppervlakte_ha"] = {"type": "literal", "value": f"{area_m2 / 10000:.4f}"}
            added_var = True

        # Pas de drempelwaarde-filter toe, indien meegegeven
        if oppervlakte_filter and area_m2 is not None:
            eenheid = oppervlakte_filter["eenheid"]
            waarde_m2 = (
                oppervlakte_filter["waarde"] * 1_000_000
                if eenheid == "km2"
                else oppervlakte_filter["waarde"] * 10_000
            )
            if oppervlakte_filter["operator"] == "GROTER" and not (area_m2 > waarde_m2):
                continue
            if oppervlakte_filter["operator"] == "KLEINER" and not (area_m2 < waarde_m2):
                continue

        gefilterde_bindings.append(row)

    if oppervlakte_filter:
        logger.info(
            "Oppervlaktefilter toegepast: %d van %d rijen behouden",
            len(gefilterde_bindings),
            len(bindings),
        )
        data["results"]["bindings"] = gefilterde_bindings

    if added_var:
        existing_vars = set(data["head"]["vars"])
        for extra in ["oppervlakte_m2", "oppervlakte_ha"]:
            if extra not in existing_vars:
                data["head"]["vars"].append(extra)

    return data


def _is_polygon_wkt(value: str) -> bool:
    """Check of een WKT-waarde een vlak-vormige geometrie is (geen punt/lijn)."""
    v = (value or "").strip().upper()
    return v.startswith("POLYGON") or v.startswith("MULTIPOLYGON")


def _row_geometry_score(row: dict, vars_: list[str]) -> int:
    """
    Geeft een score voor hoe "informatief" de geometrie in deze rij is.
    Hoger is beter: een rij met een POLYGON/MULTIPOLYGON krijgt voorrang
    boven een rij met alleen een POINT, omdat sommige geometrie-objecten
    in deze dataset zowel een representatief punt als een exacte contour
    hebben opgeslagen onder hetzelfde geometrie-object.
    """
    score = 0
    for v in vars_:
        val = row.get(v, {}).get("value", "")
        if _is_polygon_wkt(val):
            score += 1
    return score


def _deduplicate(data: dict[str, Any]) -> dict[str, Any]:
    """
    Dedupliceert resultaten op ?rm (monument URI).

    Als ?rm aanwezig is in de resultaten, bewaar dan de rij met de meest
    informatieve geometrie per monument URI (POLYGON/MULTIPOLYGON heeft
    voorrang boven POINT, want sommige geometrie-objecten in deze dataset
    hebben beide varianten onder hetzelfde object opgeslagen). Bij queries
    zonder ?rm (bijv. COUNT) wordt niets aangepast.
    """
    bindings = data.get("results", {}).get("bindings", [])
    vars_ = data.get("head", {}).get("vars", [])

    if "rm" not in vars_ or not bindings:
        return data

    best_per_rm: dict[str, dict] = {}
    no_rm_rows = []
    order: list[str] = []

    for row in bindings:
        rm_val = row.get("rm", {}).get("value", "")
        if not rm_val:
            no_rm_rows.append(row)
            continue

        if rm_val not in best_per_rm:
            best_per_rm[rm_val] = row
            order.append(rm_val)
        else:
            current_score = _row_geometry_score(best_per_rm[rm_val], vars_)
            new_score = _row_geometry_score(row, vars_)
            if new_score > current_score:
                best_per_rm[rm_val] = row

    deduped = [best_per_rm[rm_val] for rm_val in order] + no_rm_rows
    data["results"]["bindings"] = deduped
    return data
