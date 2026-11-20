"""Conservative, order-sensitive claim/evidence equivalence.

The accepted paraphrases deliberately form a small, inspectable vocabulary.
Whitespace, punctuation and these substitutions are the only transformations.
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

NUMBER = re.compile(r"(?<!\w)[+−-]?\d+(?:[.,]\d+)*(?!\w)")
WORDS = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+(?:['’][^\W\d_]+)?|[^\s]", re.UNICODE)
REWRITES = (
    (r"\bper cent\b|\bpercent\b", "%"),
    (r"\bincreased\b|\bgrew\b|\bclimbed\b", "rose"),
    (r"\bdecreased\b|\bdeclined\b|\bdropped\b", "fell"),
    (r"\bannounced that\b", "announced"),
)
UNSAFE = re.compile(
    r"\b(ignore|disregard|bypass)\b.{0,45}\b(instructions?|prompt|rules?)\b|"
    r"\b(system prompt|developer message|buy now|strong buy|should (?:buy|sell|invest)|"
    r"we recommend (?:buying|selling)|kaufen sie|koop nu|sell your shares)\b",
    re.I,
)


# Distinguish currency marks, units, dates, direction, negation and argument order.
def canonical(text: str) -> tuple[str, ...]:
    text = unicodedata.normalize("NFKC", text).casefold()
    for pattern, replacement in REWRITES:
        text = re.sub(pattern, replacement, text)
    return tuple(WORDS.findall(text.strip().removesuffix(".")))


def verify_claim(text: str, evidence_excerpts: list[str]) -> bool:
    if not text.strip() or UNSAFE.search(text):
        return False
    signature = canonical(text)
    return bool(signature) and any(
        signature == canonical(excerpt) for excerpt in evidence_excerpts
    )


@dataclass(frozen=True)
class Excerpt:
    text: str
    start: int
    end: int


def extract_claims(content: str) -> list[Excerpt]:
    """Use complete source sentences with offsets into stored normalized text."""
    output = []
    for match in re.finditer(r".+?(?:[.!?](?=\s|$)|$)", content):
        sentence = match.group().strip()
        if len(sentence.split()) < 3 or len(sentence) > 450 or sentence.endswith("?"):
            continue
        if UNSAFE.search(sentence):
            continue
        # Leave coordinated propositions, editorial fragments and calls to action out.
        if re.search(r";|\b(and|but|while|und|aber|maar|terwijl)\b", sentence, re.I):
            continue
        if not re.search(
            r"\b(announc\w*|report\w*|rose|fell|grew|increas\w*|decreas\w*|"
            r"open\w*|release\w*|launch\w*|held|kept|cut|set|has|was|is|are|said|"
            r"approved|issued|recorded|closed|tested|counts?|includes?|covers?|starts?|ends?|"
            r"raised|publish\w*|reached|bekannt|begann|beträgt|meld\w*|öffne\w*|hielt|"
            r"senkte|erreichte|veröffentlichte|stieg|beschloss|startete|is|opende|blijft|"
            r"steeg|lanceerde|publiceerde|testte|telt|begint|bevat|verlaagde)\b",
            sentence,
            re.I,
        ):
            continue
        start = match.start() + len(match.group()) - len(match.group().lstrip())
        output.append(Excerpt(sentence, start, start + len(sentence)))
    return output


def comparison_key(
    text: str, language: str = "en"
) -> tuple[str, tuple[str, ...]] | None:
    """Compare one reported quantity only when its full non-numeric context matches.

    Keep dates, periods, units and other context in the comparison key. Exclude
    single dates/identifiers from unsupported conflict inferences.
    """
    # Prefer matched metric values over other numbers such as dates or product IDs.
    pattern = re.compile(
        r"(?:[$€£]\s*(?P<money>\d+(?:[.,]\d+)*))|"
        r"(?P<amount>\d+(?:[.,]\d+)*)\s*(?=%|percent\b|per cent\b|prozent\b|procent\b|"
        r"basis points?\b|million\b|billion\b|megawatts?\b|stations?\b|sites?\b|"
        r"departures?\b|libraries\b|days?\b)",
        re.I,
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    group = "money" if match.group("money") else "amount"
    start, end = match.span(group)
    templated = text[:start] + " VALUEMARKER " + text[end:]
    value = text[start:end]
    if language in {"nl", "de"}:
        value = value.replace(".", "").replace(",", ".")
    else:
        value = value.replace(",", "")
    return " ".join(canonical(templated)), (str(Decimal(value).normalize()),)
