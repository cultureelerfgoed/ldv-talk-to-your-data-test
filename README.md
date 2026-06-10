# RCE Erfgoed Assistent

Een lokale webapplicatie waarmee je in gewone taal vragen kunt stellen aan de linked data van de Rijksdienst voor het Cultureel Erfgoed (RCE).

De applicatie vertaalt Nederlandse vragen automatisch naar SPARQL, bevraagt het RCE endpoint en geeft een leesbaar antwoord terug.

De app ondersteunt meerdere LLM-providers:

- Ollama (lokaal)
- Anthropic Claude
- Google Gemini

De applicatie is geoptimaliseerd voor de Cultureel Erfgoed Ontologie (CEO) en bevat extra datamodelregels om betere SPARQL queries te genereren.

---

# Functionaliteit

- Stel vragen in natuurlijke taal
- Genereer automatisch SPARQL queries
- Bekijk en bewerk SPARQL queries
- Voer SPARQL direct uit op het RCE endpoint
- Krijg een leesbaar Nederlands antwoord
- Exporteer resultaten als CSV
- Interactieve kaartweergave via Leaflet met marker clustering
- Automatische herkenning van WKT-geometrie
- Ondersteuning voor ruimtelijke queries (geof:sfWithin, geof:sfIntersects)
- Automatische detectie van lijst- of tellingvragen
- Waarschuwing bij bereiken van Virtuoso maximumlimiet (10.000 rijen)

Ondersteunde objecttypen:

- Rijksmonumenten
- Complexen
- Archeologische complexen
- Archeologische terreinen
- Archeologische onderzoeksgebieden
- Vondsten
- Grondsporen
- Functies
- Actoren
- Materialen
- Stijlen
- Beschermde gezichten
- Werelderfgoed
- Vondstlocaties

---

# Voorbeeldvragen

## Rijksmonumenten

- Welke rijksmonumenten staan er in Zeist?
- Hoeveel kerken zijn er in Utrecht?
- Welke archeologische rijksmonumenten zijn er in Utrecht?
- Welke kastelen staan er in Gelderland?
- Welke rijksmonumenten liggen binnen beschermd gezicht Dordrecht?
- Welke kerken liggen binnen een beschermd gezicht?
- Welke werelderfgoedlocaties zijn er?

## Architectuur

- Wie is de architect van het Rijksmuseum?
- Welke monumenten zijn ontworpen door Cuypers?
- Welke monumenten hebben een neogotische stijl?

## Archeologie

- Welke archeologische complexen zijn er?
- Welke archeologische terreinen zijn er in Limburg?
- Welke vondsten bevatten aardewerk?
- Welke grondsporen horen bij een vondstlocatie?
- Toon archeologische terreinen op de kaart
- Welke Romeinse vondsten liggen in Nuth?

---

# Architectuur

```text
frontend/
  index.html                 — basisinterface
  index_with_map.html        — interface met Leaflet kaart

answer/
  answer_generator.py        — genereert leesbare antwoorden

sparql/
  executor.py                — voert SPARQL queries uit
  postprocess.py             — normalisatie en correcties
  sparql_generator.py        — genereert SPARQL via LLM

  prompts/
    lijst.txt                — regels voor lijstqueries
    telling.txt              — regels voor tellingqueries
    datamodel_rules.txt      — centrale CEO kennisbasis

config.py                    — configuratie
app.py                       — Flask backend
requirements.txt             — Python dependencies
.env.example                 — voorbeeldconfiguratie
```

---

# Vereisten

- Python 3.10+
- Git
- Ollama (optioneel voor lokaal gebruik)

---

# Installatie

## Repository clonen

```powershell
git clone https://github.com/cultureelerfgoed/ldv-talk-to-your-data-test.git
cd ldv-talk-to-your-data-test
```

## Virtual environment aanmaken

```powershell
python -m venv .venv
```

## Virtual environment activeren

### Windows PowerShell

```powershell
.venv\Scripts\activate
```

### Linux/macOS

```bash
source .venv/bin/activate
```

## Dependencies installeren

```powershell
pip install -r requirements.txt
```

---

# Ollama installeren

Download Ollama:

https://ollama.com/download

Controleer daarna:

```powershell
ollama list
```

Installeer bijvoorbeeld:

```powershell
ollama pull qwen2.5-coder:14b
```

---

# Configuratie

Kopieer eerst:

```powershell
copy .env.example .env
```

## Voorbeeld `.env`

```env
LLM_PROVIDER=ollama

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5-coder:14b

SPARQL_ENDPOINT=https://api.linkeddata.cultureelerfgoed.nl/datasets/rce/cho/services/cho/sparql

FLASK_PORT=5000
FLASK_DEBUG=true
```

---

# Applicatie starten

```powershell
python app.py
```

Open daarna:

http://127.0.0.1:5000

---

# Postprocessing

Na het genereren van een SPARQL query past `postprocess.py` automatisch een reeks correcties toe voordat de query naar het endpoint wordt gestuurd. Dit compenseert voor veelvoorkomende fouten die LLMs maken bij het bevragen van de CEO-ontologie.

## Stappen in volgorde

### 1. Prefix injectie

Ontbrekende standaardprefixen worden automatisch toegevoegd als ze in de query worden gebruikt maar niet gedeclareerd zijn:

```sparql
PREFIX ceo: <https://linkeddata.cultureelerfgoed.nl/def/ceo#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
```

### 2. Gezicht URI normalisatie

Bij vragen over beschermde gezichten (stads- en dorpsgezichten) wordt de naam automatisch opgezocht in een dynamisch geladen mapping van alle gezichten in de dataset. De string-gebaseerde FILTER wordt vervangen door een directe URI-vergelijking.

Van:
```sparql
FILTER(CONTAINS(LCASE(?naam), "deventer"))
```

Naar:
```sparql
FILTER(?gezicht = <https://linkeddata.cultureelerfgoed.nl/cho-kennis/id/gezicht/10134270>)
```

Als meerdere gezichten de zoekterm bevatten (bijv. "amsterdam"), worden alle overeenkomende URIs opgenomen via `FILTER(?gezicht IN (...))`.

### 3. Gemeente URI normalisatie

Gemeentenamen worden opgezocht in een dynamisch geladen mapping van alle gemeenten uit de dataset, inclusief alle alternatieve namen. De string-gebaseerde FILTER via `ceo:gemeentenaam` wordt vervangen door een directe `ceo:heeftGemeente` vergelijking met de OWMS URI.

Dit voorkomt ambiguïteit bij gemeenten met meerdere namen, zoals:

| Invoer | URI |
|---|---|
| `den bosch` | `owms:terms/'s-Hertogenbosch_(gemeente)` |
| `den haag` | `owms:terms/'s-Gravenhage_(gemeente)` |
| `ferwerderadiel` | `owms:terms/Ferwerderadeel_(gemeente)` |

De mapping wordt bij elke herstart van de applicatie automatisch opgehaald uit het SPARQL endpoint.

### 4. Provincie URI normalisatie

Provincienamen worden genormaliseerd naar OWMS URIs via een hardgecodeerde mapping die alle gangbare spelwijzen afdekt:

| Invoer | URI |
|---|---|
| `friesland` | `owms:terms/Fryslan` |
| `fryslân` | `owms:terms/Fryslan` |
| `utrecht` | `owms:terms/Utrecht_(provincie)` |
| `noord-holland` | `owms:terms/Noord-Holland` |

De rdfs:label stap en FILTER worden verwijderd. De provincie-URI wordt direct in de query opgenomen.

### 5. Provincie pad correctie

Als het LLM `ceo:heeftProvincie` gebruikt zonder de verplichte `rdfs:label` stap, wordt het pad automatisch aangevuld.

### 6. Label filter correctie

`FILTER(LCASE(?x) = "waarde")` werkt niet betrouwbaar voor taalgelabelde strings. Dit wordt automatisch vervangen door `FILTER(CONTAINS(LCASE(?x), "waarde"))`.

### 7. Gezicht WKT toevoeging

Bij ruimtelijke queries met `geof:sfWithin` op een gezicht wordt `?gezichtWkt` automatisch toegevoegd aan de SELECT als die ontbreekt. Zo wordt het gezichtspolygoon altijd op de kaart getoond naast de gevonden monumenten.

### 8. LIMIT instelling

Voor lijstqueries wordt de LIMIT altijd ingesteld op 10.000 (het Virtuoso maximum). Lagere LIMITs die het LLM genereert worden automatisch vervangen. Tellingqueries krijgen geen LIMIT.

### 9. LIMIT waarschuwing

Als het aantal teruggegeven rijen gelijk is aan de ingestelde LIMIT, wordt een waarschuwing toegevoegd aan de response. De frontend toont deze als gele balk boven de resultaten.

### 10. Deduplicatie

Als `?rm` aanwezig is in de resultaten, wordt op die variabele gededupliceerd. Meerdere kadastrale percelen of naam-instanties per monument geven anders dubbele rijen.

---

# Dynamische mappings

Bij het opstarten van de applicatie worden twee mappings automatisch geladen uit het SPARQL endpoint:

**Gemeentemapping** — alle gemeente-URIs met bijbehorende labels (inclusief alternatieve namen zoals "Den Bosch" en "'s-Hertogenbosch"). Wordt opgeslagen in `config.GEMEENTE_URI`.

**Gezichtmapping** — alle gezicht-URIs met bijbehorende namen. Bij meerdere gezichten met dezelfde naam worden alle URIs opgeslagen. Wordt opgeslagen in `config.GEZICHT_URI`.

Deze mappings zorgen ervoor dat de applicatie altijd up-to-date is met de actuele data, zonder handmatige aanpassingen bij gemeentelijke herindelingen of nieuwe gezichten.

---

# Kaartfunctionaliteit

De applicatie ondersteunt automatische kaartweergave via Leaflet.

Wanneer een query WKT-geometrie teruggeeft, toont de frontend automatisch:

- punten
- lijnen
- polygonen
- multipolygonen

Markers worden automatisch geclusterd bij uitzoomen via Leaflet.markercluster. Polygonen (zoals beschermde gezichten) worden als vlakken getoond in een aparte laag zonder clustering.

Ondersteunde WKT-velden:

- `?wkt`
- `?rmWkt`
- `?gezichtWkt`
- `?gebiedWkt`

Bij ruimtelijke queries kunnen meerdere geometrieën tegelijk worden weergegeven, bijvoorbeeld een beschermd gezicht als vlak met rijksmonumenten als geclusterde punten.

---

# Datamodelregels

De applicatie gebruikt een centrale kennisbasis in:

```
sparql/prompts/datamodel_rules.txt
```

Dit bestand bevat:

- CEO klassen en property paths
- archeologische patronen
- geometrische relaties
- BAG/BRK-structuren
- gezichten en werelderfgoed
- ActorEnRol patronen
- functie- en typepaden

`lijst.txt` en `telling.txt` bevatten alleen gedragsregels voor respectievelijk lijst- en tellingqueries.

---

# Bekende beperkingen

- Grote geometrische queries kunnen timeouts veroorzaken
- Ruimtelijke queries via `geof:sfWithin` zijn zwaar — de postprocessor vereist altijd een voorfilter op gemeente of gezicht
- Sommige geometrieën ontbreken in de brondata
- Sommige objecttypen gebruiken inconsistente CEO-structuren
- Grote prompts kunnen bij kleinere LLM's incomplete SPARQL opleveren
- De Virtuoso limiet van 10.000 rijen kan niet worden overschreden — bij grote resultaatsets verschijnt een waarschuwing

---

# Licentie

MIT
