"""Fast, explainable editorial priority. Scores are relevance signals, not truth ratings."""
import re
import unicodedata

VERSION = 'editorial-v2'


def _has(text, pattern):
    return bool(re.search(r'(?<!\w)(?:' + pattern + r')(?!\w)', text))


def assess(title, content, publishers=1):
    # Keep footer disclaimers, related links and repeated keywords out of priority.
    headline = unicodedata.normalize('NFKC', title).casefold()
    lead = unicodedata.normalize('NFKC', content[:1400]).casefold()
    text = headline + ' ' + lead
    importance, urgency = 0.25, 0.12
    reasons = []
    signals = []

    def add(reason, impact, time):
        nonlocal importance, urgency
        importance += impact
        urgency = max(urgency, time)
        reasons.append(reason)
        signals.append({"reason": reason, "importance_delta": impact, "urgency_floor": time})

    safety = _has(text, r'evacuat\w*|evaku\w*|evacu\w*|state of emergency|notstand|noodtoestand|flood\w*|hochwasser|overstrom\w*|tsunami|earthquake|erdbeben|aardbeving')
    if safety:
        add('Public safety or evacuation event', 0.43, 0.92)
    bank = _has(text, r'central bank|federal reserve|ecb|ezb|bce|bank of england|zentralbank|notenbank|centrale bank')
    rate = _has(text, r'rates?|(?:leit)?zins\w*|(?:beleids)?rente\w*|monetary policy|geldpolitik')
    decision = _has(text, r'cut\w*|rais\w*|hik\w*|hold\w*|held|senk\w*|erhöh\w*|belässt|verlaag\w*|verhoog\w*|handhaaf\w*|decision|beschluss|besluit')
    if bank and rate and decision:
        add('Central bank policy decision', 0.34, 0.65)
    macro = _has(text, r'inflation|inflatie|gdp|bip|bbp|gross domestic product|bruttoinlandsprodukt|unemployment|arbeitslos\w*|werkloos\w*|payrolls|consumer prices|verbraucherpreise|consumentenprijzen')
    release = _has(text, r'report\w*|data|release\w*|rose|fell|rises|falls|stijg\w*|daal\w*|stieg|sank|daten|bericht\w*|cijfers|percent|prozent|procent') or '%' in text
    if macro and release:
        add('Macroeconomic data affecting households and businesses', 0.25, 0.48)
    shock = _has(text, r'bank fail\w*|bank collapse\w*|bankrupt\w*|insolven\w*|faill\w*|sovereign default|trading halt\w*|handelsstopp|handel stilgelegd|market crash|börsencrash')
    if shock:
        add('Financial failure or market disruption', 0.36, 0.82)
    public = _has(text, r'ceasefire|waffenstillstand|staakt.het.vuren|invasion|invasie|election results?|wahlergebnis\w*|verkiezingsuitslag|sanctions|sanktionen|sancties|power outage|stromausfall|stroomstoring')
    if public:
        add('Major public or geopolitical development', 0.30, 0.70)
    corporate = _has(text, r'earnings|quarterly profit|quartalsgewinn|kwartaalwinst|acquir\w*|übernahme|overname|merger|fusion|fusie|layoffs|entlass\w*|ontslag\w*|recall|rückruf|terugroep\w*')
    if corporate:
        add('Material company results or corporate event', 0.15, 0.36)
    scale = _has(text, r'(?:million\w*|billion\w*|milliard\w*|miljoen\w*|thousand\w*|tausend\w*|duizend\w*) (?:people|residents|workers|jobs|menschen|beschäftigte|mensen|banen)|nationwide|landesweit|landelijk')
    if scale and (safety or shock or public or corporate):
        add('Large reported impact on people or services', 0.12, urgency)
    # Independent coverage is capped so popularity cannot outweigh major events.
    independent = max(0, min(4, publishers) - 1)
    if independent:
        add('Covered by multiple independent publishers', 0.04 * independent, urgency)
    speculative = _has(headline, r'opinion|commentary|kommentar|meinung|opinie|could|might|may|könnte\w*|zou|forecast\w*|prognose\w*|voorspelling\w*')
    promotional = _has(headline, r'stocks? to buy|buy now|top stocks?|best stocks?|aktien kaufen|aandelen kopen|sponsored|advertorial')
    if speculative or promotional:
        penalty = 0.16 if promotional else 0.08
        importance -= penalty
        signals.append({'reason': 'Opinion, forecast or promotion', 'importance_delta': -penalty, 'urgency_cap': 0.35})
        urgency = min(urgency, 0.35)
        reasons.append('Opinion, forecast or promotion has reduced priority')
    return {
        'version': VERSION,
        'baseline': {'importance': 0.25, 'urgency': 0.12},
        'signals': signals,
        'bounds': {'minimum': 0.05, 'maximum': 0.99},
        'importance': round(max(0.05, min(0.99, importance)), 3),
        'urgency': round(max(0.05, min(0.99, urgency)), 3),
        'reasons': reasons or ['Routine report; ranked using freshness and listener interests'],
        'independent_publishers': max(0, publishers),
        'method': 'Local multilingual editorial rules; no model call. Source coverage does not prove a claim true.',
    }


def assess_story(db, story):
    from sqlalchemy import select
    from .models import Source
    from .service import story_articles
    from .coverage import publisher_family
    articles = story_articles(db, story.id)
    if not articles:
        return assess(story.title, '', 0)
    lead = next((a for a in articles if a.language == 'en'), articles[0])
    names = dict(db.execute(select(Source.id, Source.name).where(
        Source.id.in_({a.source_id for a in articles})
    )).all())
    publishers = {publisher_family(names[a.source_id]) for a in articles if not a.near_duplicate_of}
    return assess(lead.title, lead.content, len(publishers))


def main():
    import argparse
    import json
    from sqlalchemy import select
    from app.db import SessionLocal, load_models
    from .models import Story
    parser = argparse.ArgumentParser(description='Recalculate priority without reimporting articles or calling AI providers')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    load_models()
    changed = 0
    with SessionLocal() as db:
        stories = db.scalars(select(Story).where(Story.archived.is_(False))).all()
        for story in stories:
            result = assess_story(db, story)
            if (story.importance, story.urgency) != (result['importance'], result['urgency']):
                changed += 1
                if args.apply:
                    story.importance, story.urgency = result['importance'], result['urgency']
        if args.apply:
            db.commit()
        print(json.dumps({'version': VERSION, 'stories': len(stories), 'changed': changed, 'applied': args.apply, 'model_calls': 0}))


if __name__ == '__main__':
    main()
