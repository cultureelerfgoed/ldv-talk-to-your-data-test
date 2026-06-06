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

---

# Voorbeeldvragen

## Rijksmonumenten

- Welke rijksmonumenten staan er in Zeist?
- Hoeveel kerken zijn er in Utrecht?
- Welke archeologische rijksmonumenten zijn er in Utrecht?
- Welke kastelen staan er in Gelderland?

## Architectuur

- Wie is de architect van het Rijksmuseum?
- Welke monumenten zijn ontworpen door Cuypers?
- Welke monumenten hebben een neogotische stijl?

## Archeologie

- Welke archeologische complexen zijn er?
- Welke archeologische terreinen zijn er in Limburg?
- Welke vondsten bevatten aardewerk?
- Welke grondsporen horen bij een vondstlocatie?

---

# Architectuur

```text
frontend/
  index.html                 — gebruikersinterface

answer/
  answer_generator.py        — genereert leesbare antwoorden

sparql/
  executor.py                — voert SPARQL queries uit
  postprocess.py             — normalisatie en correcties
  sparql_generator.py        — genereert SPARQL via LLM

  prompts/
    lijst.txt                — prompt voor lijstvragen
    telling.txt              — prompt voor tellingen
    datamodel_rules.txt      — CEO datamodelregels en querypatronen

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
git clone https://github.com/jolietjakeblues/ldv-talk-to-your-data-test.git
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

# Datamodelregels

De applicatie gebruikt aanvullende regels in:

```text
sparql/prompts/datamodel_rules.txt
```

Deze regels helpen de LLM om:

- geldige CEO classes te gebruiken
- correcte property-paden te kiezen
- hallucinaties te voorkomen
- betere SPARQL queries te genereren

---

# Bekende beperkingen

- Niet alle CEO-relaties zijn volledig gedocumenteerd
- Sommige architectgegevens zijn literals
- Sommige locatiepaden verschillen per objecttype
- Archeologische objecten gebruiken andere structuurpatronen dan rijksmonumenten
- Synoniemenherkenning blijft beperkt
- Grote queries kunnen traag zijn

---

# Licentie

MIT
