"""
SPARQL query executor.

Verantwoordelijkheden:
- Query uitvoeren op het RCE SPARQL endpoint
- Resultaten dedupliceren op ?rm (monument URI)
- Foutafhandeling voor timeouts en HTTP-fouten
"""

import logging
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

    response = requests.get(
        SPARQL_ENDPOINT,
        params={"query": query, "format": "json"},
        headers={"Accept": "application/sparql-results+json"},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    data = _translate_provincie_uris(data)

    # Voeg waarschuwing toe als query ceo:woonplaatsnaam gebruikt
    if "woonplaatsnaam" in query and "ArcheologischOnderzoeksgebied" in query:
        data["_warning_woonplaats"] = (
            "Let op: de woonplaatsnamen bij archeologische onderzoeksgebieden zijn "
            "handmatig ingevoerd en kunnen afwijken van officiële BAG-namen. "
            "Resultaten kunnen onvolledig of onjuist zijn door spellingsverschillen "
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


GG_ENDPOINT = "https://api.druid.datalegend.net/datasets/nlgis/gemeentegeschiedenis/sparql"

# Mapping van provincie-URI in gemeentegeschiedenis naar OWMS provincie URI
GG_PROVINCIE_MAP = {
    "province:Drenthe":       "http://standaarden.overheid.nl/owms/terms/Drenthe",
    "province:Flevoland":     "http://standaarden.overheid.nl/owms/terms/Flevoland",
    "province:Friesland":     "http://standaarden.overheid.nl/owms/terms/Fryslan",
    "province:Gelderland":    "http://standaarden.overheid.nl/owms/terms/Gelderland",
    "province:Groningen":     "http://standaarden.overheid.nl/owms/terms/Groningen_(provincie)",
    "province:Limburg":       "http://standaarden.overheid.nl/owms/terms/Limburg",
    "province:Noord-Brabant": "http://standaarden.overheid.nl/owms/terms/Noord-Brabant",
    "province:Noord-Holland": "http://standaarden.overheid.nl/owms/terms/Noord-Holland",
    "province:Overijssel":    "http://standaarden.overheid.nl/owms/terms/Overijssel",
    "province:Utrecht":       "http://standaarden.overheid.nl/owms/terms/Utrecht_(provincie)",
    "province:Zeeland":       "http://standaarden.overheid.nl/owms/terms/Zeeland",
    "province:Zuid-Holland":  "http://standaarden.overheid.nl/owms/terms/Zuid-Holland",
}


def load_woonplaats_provincie_mapping() -> dict:
    """
    Laad woonplaats → OWMS provincie URI mapping via gemeentegeschiedenis.nl.
    Matcht gemeentenamen op woonplaatsnamen (huidige gemeenten zonder einddatum).
    Geeft dict terug van lowercase woonplaatsnaam -> OWMS provincie URI.
    """
    query = """
PREFIX gg: <http://www.gemeentegeschiedenis.nl/gg-schema#>
SELECT DISTINCT ?naam ?provURI WHERE {
  ?gem a gg:Municipality .
  ?gem gg:name ?naam .
  ?gem gg:inProvince ?provURI .
  FILTER NOT EXISTS { ?gem gg:endDate ?end }
}
"""
    try:
        response = requests.get(
            GG_ENDPOINT,
            params={"query": query, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        mapping = {}
        for row in data.get("results", {}).get("bindings", []):
            naam = row["naam"]["value"].lower().strip()
            prov_raw = row["provURI"]["value"]
            # Normaliseer province: prefix naar OWMS URI
            prov_key = "province:" + prov_raw.split("/")[-1]
            owms_uri = GG_PROVINCIE_MAP.get(prov_key)
            if owms_uri:
                mapping[naam] = owms_uri
        logger.info("Woonplaats-provincie mapping geladen: %d woonplaatsen", len(mapping))
        return mapping
    except Exception as e:
        logger.warning("Woonplaats-provincie mapping kon niet worden geladen: %s", e)
        return {}


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


def _deduplicate(data: dict[str, Any]) -> dict[str, Any]:
    """
    Dedupliceert resultaten op ?rm (monument URI).

    Als ?rm aanwezig is in de resultaten, bewaar dan alleen de eerste
    rij per monument URI. Bij queries zonder ?rm (bijv. COUNT) wordt
    niets aangepast.
    """
    bindings = data.get("results", {}).get("bindings", [])
    vars_ = data.get("head", {}).get("vars", [])

    if "rm" not in vars_ or not bindings:
        return data

    seen: set[str] = set()
    deduped = []

    for row in bindings:
        rm_val = row.get("rm", {}).get("value", "")
        if rm_val and rm_val not in seen:
            seen.add(rm_val)
            deduped.append(row)
        elif not rm_val:
            deduped.append(row)

    data["results"]["bindings"] = deduped
    return data
