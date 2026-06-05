# RCE Erfgoed Assistent

Een webapplicatie waarmee je in gewone taal vragen kunt stellen aan de linked data van de Rijksdienst voor het Cultureel Erfgoed (RCE). De app vertaalt je vraag automatisch naar SPARQL, bevraagt het RCE endpoint, en geeft een leesbaar antwoord terug.

## Wat het doet

- Stel vragen in Nederlands, zoals *"Welke rijksmonumenten staan er in Zeist?"* of *"Hoeveel kerken zijn er in Utrecht?"*
- Kies tussen **Lijst** (alle monumenten als rijen) of **Telling** (een aantal)
- Bekijk de gegenereerde SPARQL query
- Exporteer resultaten als CSV, direct te openen in Excel
- Resultaten uit vrije tekstvelden worden als **onzeker** gemarkeerd

## Architectuur

```
frontend/index.html     — gebruikersinterface (browser)
app.py                  — Flask backend (localhost:5000)
config.py               — instellingen en provincie URI mapping
sparql/
  sparql_generator.py   — genereert SPARQL via Claude
  executor.py           — voert query uit op RCE endpoint
  postprocess.py        — prefix-injectie, provincie-normalisatie, LIMIT-verwijdering
  prompts/
    lijst.txt           — system prompt voor lijstvragen
    telling.txt         — system prompt voor tellingsvragen
answer/
  answer_generator.py   — vertaalt resultaten naar Nederlands antwoord
```

## Vereisten

- Python 3.10+
- Anthropic API key ([console.anthropic.com](https://console.anthropic.com))

## Installatie

```powershell
pip install -r requirements.txt
copy .env.example .env
```

Open `.env` en vul je Anthropic API key in:
```
ANTHROPIC_API_KEY=sk-ant-...
```

## Opstarten

```powershell
powershell -ExecutionPolicy Bypass -File start.ps1
```

Of handmatig:
```powershell
python app.py
```
Open daarna `frontend/index.html` in je browser.

## Datamodel

De app gebruikt de [Cultureel Erfgoed Ontologie (CEO)](https://linkeddata.cultureelerfgoed.nl/def/ceo) van de RCE en bevraagt het SPARQL endpoint op:

```
https://api.linkeddata.cultureelerfgoed.nl/datasets/rce/cho/services/cho/sparql
```

## Configuratie

Alle instellingen staan in `.env`:

| Variabele | Standaard | Omschrijving |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Verplicht |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5` | Te gebruiken model |
| `SPARQL_ENDPOINT` | RCE endpoint | SPARQL endpoint URL |
| `FLASK_PORT` | `5000` | Poort voor de backend |
| `FLASK_DEBUG` | `false` | Debug modus |

## Bekende beperkingen

- Zoeken op functie/type gebruikt string-matching op thesaurusconcepten — synoniemen worden niet automatisch herkend
- Provincienamen worden genormaliseerd naar OWMS URIs; onbekende spelwijzen vallen terug op de originele zoekterm
- De app is bedoeld als lokale tool, niet als productie-webapplicatie (API key zit in `.env` op de server)

## Licentie

MIT
