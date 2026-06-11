"""
Configuratie — laadt .env en exporteert alle constanten.
Kopieer .env.example naar .env en vul je waarden in.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(
            f"Omgevingsvariabele '{key}' is niet ingesteld. "
            f"Kopieer .env.example naar .env en vul hem in."
        )
    return value


# LLM provider: 'anthropic' of 'google'
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "google")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

SPARQL_ENDPOINT = os.getenv(
    "SPARQL_ENDPOINT",
    "https://api.linkeddata.cultureelerfgoed.nl/datasets/rce/cho/services/cho/sparql",
)
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-1.5-pro")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

SPARQL_PREFIXES = """\
PREFIX ceo: <https://linkeddata.cultureelerfgoed.nl/def/ceo#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>"""

# Exacte provincie URIs uit de OWMS thesaurus
# Alle gangbare spelwijzen mappen naar één URI per provincie
_BASE = "http://standaarden.overheid.nl/owms/terms/"
# Omgekeerde mapping: URI → leesbare naam
PROVINCIE_NAAM = {
    "http://standaarden.overheid.nl/owms/terms/Drenthe":              "Drenthe",
    "http://standaarden.overheid.nl/owms/terms/Flevoland":            "Flevoland",
    "http://standaarden.overheid.nl/owms/terms/Fryslan":              "Fryslân",
    "http://standaarden.overheid.nl/owms/terms/Gelderland":           "Gelderland",
    "http://standaarden.overheid.nl/owms/terms/Groningen_(provincie)":"Groningen",
    "http://standaarden.overheid.nl/owms/terms/Limburg":              "Limburg",
    "http://standaarden.overheid.nl/owms/terms/Noord-Brabant":        "Noord-Brabant",
    "http://standaarden.overheid.nl/owms/terms/Noord-Holland":        "Noord-Holland",
    "http://standaarden.overheid.nl/owms/terms/Overijssel":           "Overijssel",
    "http://standaarden.overheid.nl/owms/terms/Utrecht_(provincie)":  "Utrecht",
    "http://standaarden.overheid.nl/owms/terms/Zeeland_(provincie)":  "Zeeland",
    "http://standaarden.overheid.nl/owms/terms/Zuid-Holland":         "Zuid-Holland",
}

# Gezichtmapping — wordt dynamisch geladen bij opstarten via executor.load_gezicht_mapping()
# Bevat naam (lowercase) -> URI of lijst van URIs bij meerdere gezichten met zelfde naam
GEZICHT_URI: dict = {}

# Gemeentemapping — wordt dynamisch geladen bij opstarten via executor.load_gemeente_mapping()
# Bevat alle labels (inclusief alternatieve namen zoals "Den Bosch") → OWMS URI
GEMEENTE_URI: dict = {}

PROVINCIE_URI = {
    "drenthe":              _BASE + "Drenthe",
    "flevoland":            _BASE + "Flevoland",
    "friesland":            _BASE + "Fryslan",
    "fryslan":              _BASE + "Fryslan",
    "fryslân":              _BASE + "Fryslan",
    "frysland":             _BASE + "Fryslan",
    "gelderland":           _BASE + "Gelderland",
    "groningen":            _BASE + "Groningen_(provincie)",
    "provincie groningen":  _BASE + "Groningen_(provincie)",
    "limburg":              _BASE + "Limburg",
    "noord-brabant":        _BASE + "Noord-Brabant",
    "noord brabant":        _BASE + "Noord-Brabant",
    "noordbrabant":         _BASE + "Noord-Brabant",
    "n-brabant":            _BASE + "Noord-Brabant",
    "brabant":              _BASE + "Noord-Brabant",
    "noord-holland":        _BASE + "Noord-Holland",
    "noord holland":        _BASE + "Noord-Holland",
    "noordholland":         _BASE + "Noord-Holland",
    "n-holland":            _BASE + "Noord-Holland",
    "overijssel":           _BASE + "Overijssel",
    "utrecht":              _BASE + "Utrecht_(provincie)",
    "provincie utrecht":    _BASE + "Utrecht_(provincie)",
    "provincie zeeland":    _BASE + "Zeeland_(provincie)",
    "zeeland":              _BASE + "Zeeland_(provincie)",
    "zuid-holland":         _BASE + "Zuid-Holland",
    "zuid holland":         _BASE + "Zuid-Holland",
    "zuidholland":          _BASE + "Zuid-Holland",
    "z-holland":            _BASE + "Zuid-Holland",
}
