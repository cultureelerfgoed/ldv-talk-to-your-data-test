"""
Antwoord generator — ondersteunt Anthropic en Google Gemini.
"""

import json
import logging
from typing import Any

import config

logger = logging.getLogger(__name__)


def _generate_anthropic(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _generate_google(prompt: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=config.GOOGLE_API_KEY)
    model = genai.GenerativeModel(model_name=config.GOOGLE_MODEL)
    response = model.generate_content(prompt)
    return response.text


def generate(question: str, results: dict[str, Any]) -> str:
    """
    Genereer een leesbaar antwoord op basis van SPARQL resultaten.
    """
    bindings = results.get("results", {}).get("bindings", [])
    vars_ = results.get("head", {}).get("vars", [])
    total = len(bindings)
    sample = bindings[:15]

    summary = json.dumps(
        {"vars": vars_, "sample": sample},
        ensure_ascii=False,
        indent=1,
    )

    prompt = (
        f'Vraag: "{question}"\n\n'
        f"SPARQL resultaten ({total} rijen totaal, eerste 15 getoond):\n{summary}\n\n"
        f"Geef een beknopt, informatief antwoord in het Nederlands op de originele vraag. "
        f"Als de vraag om een telling gaat, gebruik dan het totaal aantal rijen ({total}) als het antwoord. "
        f"Gebruik de data. Geen technische termen. Max 3-4 zinnen."
    )

    logger.info("Antwoord genereren via %s voor %d resultaten", config.LLM_PROVIDER, total)

    if config.LLM_PROVIDER == "google":
        return _generate_google(prompt)
    return _generate_anthropic(prompt)
