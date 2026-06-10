"""
RCE Erfgoed Assistent — Flask applicatie

Start:
    pip install -r requirements.txt
    cp .env.example .env  # en vul ANTHROPIC_API_KEY in
    python app.py
"""

import logging

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

import os
import config
from answer import answer_generator
from sparql import executor as sparql_executor
from sparql import sparql_generator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), "frontend"),
    static_url_path="",
)
CORS(app)

# Laad mappings bij opstarten
config.GEZICHT_URI = sparql_executor.load_gezicht_mapping()
config.GEMEENTE_URI = sparql_executor.load_gemeente_mapping()


@app.route("/api/generate-sparql", methods=["POST"])
def generate_sparql():
    """Stap 1: vertaal natuurlijke vraag naar SPARQL via Claude."""
    data = request.get_json()
    question = (data.get("question") or "").strip()
    mode = data.get("mode", "lijst")

    if not question:
        return jsonify({"error": "Geen vraag opgegeven"}), 400
    if mode not in ("lijst", "telling"):
        return jsonify({"error": "Ongeldige modus — gebruik 'lijst' of 'telling'"}), 400

    try:
        query = sparql_generator.generate(question, mode)
        return jsonify({"query": query})
    except Exception as e:
        logger.exception("Fout bij SPARQL generatie")
        return jsonify({"error": str(e)}), 500


@app.route("/api/execute-sparql", methods=["POST"])
def execute_sparql():
    """Stap 2: voer SPARQL query uit op het RCE endpoint."""
    data = request.get_json()
    query = (data.get("query") or "").strip()

    if not query:
        return jsonify({"error": "Geen query opgegeven"}), 400

    try:
        results = sparql_executor.execute(query)
        return jsonify(results)
    except requests.exceptions.Timeout:
        return jsonify({"error": "Endpoint timeout (>30s)"}), 504
    except requests.exceptions.HTTPError as e:
        return jsonify({
            "error": f"Endpoint fout: {e.response.status_code} — {e.response.text[:300]}"
        }), 502
    except Exception as e:
        logger.exception("Fout bij SPARQL uitvoering")
        return jsonify({"error": str(e)}), 500


@app.route("/api/generate-answer", methods=["POST"])
def generate_answer():
    """Stap 3: vertaal SPARQL resultaten naar leesbaar antwoord."""
    data = request.get_json()
    question = data.get("question", "")
    results = data.get("results", {})

    try:
        answer = answer_generator.generate(question, results)
        return jsonify({"answer": answer})
    except Exception as e:
        logger.exception("Fout bij antwoord generatie")
        return jsonify({"error": str(e)}), 500


@app.route("/")
def index():
    """Serveer de frontend."""
    return app.send_static_file("index_with_map.html")


@app.route("/api/health", methods=["GET"])
def health():
    """Health check — controleer of de backend en API key beschikbaar zijn."""
    try:
        config.ANTHROPIC_API_KEY
        api_key_set = True
    except EnvironmentError:
        api_key_set = False

    model = config.GOOGLE_MODEL if config.LLM_PROVIDER == "google" else config.ANTHROPIC_MODEL

    return jsonify({
        "status": "ok",
        "api_key_set": api_key_set,
        "provider": config.LLM_PROVIDER,
        "model": model,
        "endpoint": config.SPARQL_ENDPOINT,
    })


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", config.FLASK_PORT))
    logger.info("SPARQL endpoint: %s", config.SPARQL_ENDPOINT)
    logger.info("Model: %s", config.ANTHROPIC_MODEL)
    logger.info("Server start op poort %d", port)
    app.run(host="0.0.0.0", debug=config.FLASK_DEBUG, port=port)
