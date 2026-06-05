"""
SPARQL query generator — ondersteunt Anthropic en Google Gemini.
Provider wordt bepaald via LLM_PROVIDER in config/environment.
"""

import logging
from pathlib import Path

import config
from sparql.postprocess import postprocess, has_count

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def _generate_anthropic(question: str, system_prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=1000,
        system=system_prompt,
        messages=[{"role": "user", "content": question}],
    )
    return message.content[0].text


def _generate_google(question: str, system_prompt: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=config.GOOGLE_API_KEY)
    model = genai.GenerativeModel(
        model_name=config.GOOGLE_MODEL,
        system_instruction=system_prompt,
    )
    response = model.generate_content(question)
    return response.text


def _generate(question: str, system_prompt: str) -> str:
    if config.LLM_PROVIDER == "google":
        return _generate_google(question, system_prompt)
    return _generate_anthropic(question, system_prompt)


def generate(question: str, mode: str) -> str:
    """
    Genereer een SPARQL query op basis van een natuurlijke vraag.

    Args:
        question: De vraag in natuurlijke taal.
        mode:     'lijst' of 'telling'.

    Returns:
        Een nabewerkte SPARQL query als string.
    """
    system_prompt = _load_prompt(mode)
    logger.info("Query genereren via %s (modus: %s)", config.LLM_PROVIDER, mode)

    query = _generate(question, system_prompt)
    query = postprocess(query, mode)

    if mode == "lijst" and has_count(query):
        logger.warning("LLM genereerde COUNT in lijstmodus — correctie-aanroep")
        corrected = question + " (geef een lijst van individuele monumenten, geen telling)"
        query = _generate(corrected, system_prompt)
        query = postprocess(query, mode)

    logger.info("Query gegenereerd (%d tekens)", len(query))
    return query
