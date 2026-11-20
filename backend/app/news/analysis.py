"""Event fingerprints complement embeddings with independent lexical guards."""

import hashlib
import math
import os
import re
from collections import Counter
from functools import lru_cache

DIMENSION = 384
STOP = set(
    "the and a an at in of to for by as on is was has were en de het een voor op met van die der das dem den des und im am für mit zu zur ein eine its new latest news über after said".split()
)
CONCEPTS = {
    "launch": "launch launches launched opens opened opening start starts started eröffnet eröffnete eröffnen opent opende lanceert lanceerde startet startete beginn begann",
    "cut": "cut cuts lowered reduced senkt senkte verlaagt verlaagde",
    "rate": "rate rates policy zinssatz leitzins rente beleidsrente",
    "benchmark": "benchmark benchmarks benchmarktest",
    "speech": "speech spraak sprach",
    "model": "model models modell modellen",
    "language": "language languages sprachen talen",
    "pilot": "pilot pilots pilotprojekt proefproject",
    "solar": "solar solaranlage zonnepark",
    "market": "market markets markets markt markten",
    "grid": "grid netz stroomnet",
    "approval": "approval approved approves genehmigt goedgekeurd",
    "warning": "warning warnings alert warns warnt waarschuwt",
    "flood": "flood floods flooding hochwasser overstroming",
    "library": "libraries library bibliotheken bibliotheek bibliothek",
    "transit": "bus buses transit transport vervoer",
    "publish": "publication publishes published veröffentlicht publiceert publiceerde veröffentlichte releases released",
    "report": "report reports reported meldet meldete meldt",
    "profit": "earnings profit profits gewinn winst",
    "quarterly": "quarterly quartalsgewinn quartalsgewinne kwartaalwinst",
    "fund": "fund funds funded funding finanzierung financiering",
    "chip": "chip chips processor processors",
}
ALIASES = {v: k for k, values in CONCEPTS.items() for v in values.split()}
ACTIONS = {
    "launch",
    "cut",
    "approval",
    "warning",
    "publish",
    "fund",
    "report",
    "acquire",
    "approve",
    "sell",
    "raise",
    "close",
    "expand",
}
DESCRIPTORS = {k for k in CONCEPTS if k not in ACTIONS}
TOPICS = {
    "artificial_intelligence": {
        "model",
        "benchmark",
        "speech",
        "ai",
        "ki",
        "llm",
        "inference",
        "robotics",
    },
    "finance": {
        "rate",
        "profit",
        "market",
        "inflation",
        "bond",
        "bank",
        "treasury",
        "banking",
        "bonds",
    },
    "energy": {"solar", "grid", "energy", "battery", "megawatts", "electricity"},
    "climate": {"flood", "climate", "storm", "drought"},
    "transport": {"transit", "train", "rail", "station", "departures"},
    "technology": {"chip", "software", "computer", "processor", "quantum", "hardware"},
    "science": {"telescope", "observatory", "space", "astronomy", "research"},
}
ACTIONS_EXTRA = {
    "raises": "raise",
    "raised": "raise",
    "acquires": "acquire",
    "acquired": "acquire",
    "closed": "close",
    "expands": "expand",
    "expanded": "expand",
}
ALIASES.update(ACTIONS_EXTRA)
COMMON_CAPS = {
    "the",
    "a",
    "an",
    "this",
    "der",
    "die",
    "das",
    "het",
    "de",
    "new",
    "according",
    "during",
    "researchers",
    "officials",
    "early",
    "more",
}


def tokens(text: str) -> list[str]:
    words = re.findall(r"[^\W_]+", text.casefold())
    return [ALIASES.get(w, w) for w in words if w not in STOP and len(w) > 1]


def anchors(title: str, lead: str) -> tuple[set[str], set[str], set[str]]:
    def names(value):
        return {
            w.casefold()
            for w in re.findall(r"\b[A-ZÀ-Þ][\w-]+\b", value)
            if w.casefold() not in COMMON_CAPS | STOP and w.casefold() not in ALIASES
        }

    # Title carries event identity. Source boilerplate or later events in the body do not.
    identity = names(title)
    words = set(tokens(title))
    return identity, words & ACTIONS, words - identity - ACTIONS


def same_event(left, right, similarity: float, threshold: float) -> bool:
    le, la, ld = left
    re_, ra, rd = right
    if not le.intersection(re_) or similarity < threshold:
        return False
    if (le - re_) and (re_ - le):
        return False
    if la and ra and la.isdisjoint(ra):
        return False
    return (
        bool(la.intersection(ra) and ld.intersection(rd))
        or len(ld.intersection(rd)) >= 2
    )


def classify(title: str, body: str) -> list[str]:
    weights = Counter(tokens(title) * 4 + tokens(body[:900]))
    scores = sorted(
        ((sum(weights[w] for w in words), key) for key, words in TOPICS.items()),
        reverse=True,
    )
    topics = [key for score, key in scores if score > 0][:3] or ["general"]
    if "artificial_intelligence" in topics and "technology" not in topics:
        topics.append("technology")
    if "finance" in topics:
        topics.append("economy")
    return topics


def scores(topics: list[str], sources: int, content: str) -> tuple[float, float]:
    words = set(tokens(content))
    warning = bool({"warning", "flood"} <= words or {"emergency", "evacuation"} & words)
    impact = 0.23 if set(topics) & {"finance", "energy", "climate"} else 0.12
    importance = min(0.99, 0.38 + impact + 0.065 * min(sources, 4) + 0.27 * warning)
    urgency = min(0.99, 0.3 + 0.59 * warning + 0.09 * bool({"cut", "warning"} & words))
    return round(importance, 3), round(urgency, 3)


def model_name() -> str:
    provider = os.environ.get("EMBEDDING_PROVIDER", "local_hash")
    if provider == "local_hash":
        return "lexical-multilingual-hash-v1"
    if provider == "sentence_transformers":
        return os.environ.get(
            "EMBEDDING_MODEL",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        )
    raise ValueError("Unsupported EMBEDDING_PROVIDER")


@lru_cache(maxsize=1)
def transformer(name):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(name, trust_remote_code=False)


def embed(title: str, body: str) -> list[float]:
    name = model_name()
    if name != "lexical-multilingual-hash-v1":
        vector = transformer(name).encode(
            title + ". " + body[:1500], normalize_embeddings=True
        )
        if len(vector) != DIMENSION:
            raise ValueError(
                "The vector index requires a 384-dimensional embedding model"
            )
        return vector.tolist()
    bins = [0.0] * DIMENSION
    for word, count in Counter(tokens(title) * 5 + tokens(body[:650])).items():
        raw = hashlib.blake2s(word.encode(), digest_size=4).digest()
        index = int.from_bytes(raw, "big") % DIMENSION
        bins[index] += math.log1p(count) * (1 if raw[0] & 1 else -1)
    norm = math.sqrt(sum(x * x for x in bins)) or 1
    return [x / norm for x in bins]


def cosine(left, right) -> float:
    return sum(float(a) * float(b) for a, b in zip(left, right, strict=True))
