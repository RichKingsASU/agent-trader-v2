from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Mapping, Optional

from .models import EventType, NewsFeatureRecord, get_text_fields, stable_feature_id


# --- Deterministic rule sets (no external dependencies, no randomness) ---

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9']+")

_NEGATIONS = {"not", "no", "never", "without", "n't"}
_INTENSIFIERS = {"very": 1.25, "significantly": 1.35, "materially": 1.35, "strongly": 1.25, "sharply": 1.25}

# Compact lexicon aimed at market-moving corporate news headlines.
# Weights are fixed and deterministic.
_LEXICON: dict[str, float] = {
    # positive
    "beat": 1.6,
    "beats": 1.8,
    "beating": 1.6,
    "surge": 1.5,
    "surges": 1.5,
    "record": 1.2,
    "profit": 1.0,
    "profits": 1.0,
    "growth": 1.1,
    "strong": 0.9,
    "upgrade": 1.2,
    "upgrades": 1.2,
    "raise": 1.2,
    "raises": 1.4,
    "raised": 1.4,
    "guidance": 1.0,  # positive in isolation is mild; used with "raise"
    "wins": 1.1,
    "win": 1.1,
    "approval": 1.2,
    "approved": 1.2,
    "launch": 0.8,
    "launches": 0.8,
    # negative
    "miss": -1.6,
    "misses": -1.8,
    "warning": -1.2,
    "warns": -1.2,
    "cut": -1.3,
    "cuts": -1.3,
    "lower": -0.9,
    "lowers": -1.1,
    "downgrade": -1.2,
    "downgrades": -1.2,
    "plunge": -1.5,
    "plunges": -1.5,
    "loss": -1.0,
    "losses": -1.0,
    "lawsuit": -1.6,
    "sued": -1.6,
    "investigation": -1.8,
    "investigates": -1.8,
    "probe": -1.4,
    "fraud": -2.0,
    "restatement": -1.5,
    "bankruptcy": -2.2,
    "layoffs": -1.3,
    "layoff": -1.3,
    "recall": -1.2,
    "breach": -1.6,
    "hacked": -1.6,
    "antitrust": -1.4,
    "fine": -1.0,
    "fined": -1.0,
}

# Phrase patterns (checked before token scoring).
_PHRASE_SCORES: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\bbeats?\s+earnings\b", re.IGNORECASE), 1.3),
    (re.compile(r"\bmiss(es|ed)?\s+earnings\b", re.IGNORECASE), -1.3),
    (re.compile(r"\brais(es|ed)?\s+guidance\b", re.IGNORECASE), 1.2),
    (re.compile(r"\bcuts?\s+guidance\b", re.IGNORECASE), -1.2),
    (re.compile(r"\b(sec|doj|ftc)\s+(probe|investigation)\b", re.IGNORECASE), -1.4),
    (re.compile(r"\b(class action)\b", re.IGNORECASE), -1.2),
]


def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD_RE.finditer(text or "")]


def sentiment(news_text: str) -> float:
    """
    Deterministic sentiment score in [-1.0, 1.0] using a small rules lexicon.
    """
    text = (news_text or "").strip()
    if not text:
        return 0.0

    phrase_score = 0.0
    for pat, score in _PHRASE_SCORES:
        if pat.search(text):
            phrase_score += score

    tokens = _tokenize(text)
    if not tokens:
        return 0.0

    score = phrase_score
    abs_mass = abs(phrase_score)

    i = 0
    while i < len(tokens):
        tok = tokens[i]

        mult = 1.0
        if tok in _INTENSIFIERS:
            mult *= _INTENSIFIERS[tok]
            # Apply intensifier to the next token if possible.
            if i + 1 < len(tokens):
                next_tok = tokens[i + 1]
                w = _LEXICON.get(next_tok, 0.0)
                if w != 0.0:
                    score += (w * mult)
                    abs_mass += abs(w * mult)
                    i += 2
                    continue

        w = _LEXICON.get(tok, 0.0)
        if w != 0.0:
            # Negation flips the immediate prior context.
            if i > 0 and tokens[i - 1] in _NEGATIONS:
                w = -w
            score += w
            abs_mass += abs(w)
        i += 1

    # Normalize with a smooth saturating function for stability.
    # Using tanh gives bounded, deterministic results without magic thresholds.
    if abs_mass == 0.0:
        return 0.0

    # Scale by token length (prevents tiny headlines from saturating).
    length_scale = 1.0 + (len(tokens) / 12.0)
    scaled = score / length_scale
    out = math.tanh(scaled / 3.0)

    # Clamp hard for safety.
    if out > 1.0:
        return 1.0
    if out < -1.0:
        return -1.0
    return float(out)


def classify_event(news_text: str) -> EventType:
    """
    Deterministic event classification via ordered keyword rules.
    """
    t = (news_text or "").lower()
    if not t.strip():
        return EventType.OTHER

    # M&A
    if any(k in t for k in ["acquire", "acquires", "acquisition", "merge", "merger", "buyout", "takeover"]):
        return EventType.MERGER_ACQUISITION

    # Earnings / guidance (separate so guidance can be captured)
    if any(k in t for k in ["earnings", "eps", "quarter", "q1", "q2", "q3", "q4", "results"]):
        return EventType.EARNINGS
    if any(k in t for k in ["guidance", "outlook", "raises guidance", "cuts guidance", "forecast"]):
        return EventType.GUIDANCE

    # Regulatory
    if any(k in t for k in ["sec", "doj", "ftc", "regulator", "regulatory", "probe", "investigation", "antitrust"]):
        return EventType.REGULATORY

    # Litigation
    if any(k in t for k in ["lawsuit", "sued", "court", "settlement", "class action"]):
        return EventType.LITIGATION

    # Analyst actions
    if any(k in t for k in ["upgrade", "downgrade", "initiates coverage", "price target", "pt raised", "pt cut"]):
        return EventType.ANALYST_RATING

    # Product / operational
    if any(k in t for k in ["launch", "releases", "product", "partnership", "contract", "deal", "recall", "breach"]):
        return EventType.PRODUCT

    # Insider / capital structure
    if any(k in t for k in ["insider", "ceo sells", "cfo sells", "buyback", "repurchase", "dividend"]):
        return EventType.INSIDER

    # Macro
    if any(k in t for k in ["fed", "inflation", "rates", "cpi", "unemployment", "recession", "gdp", "oil"]):
        return EventType.MACRO

    return EventType.OTHER


def _symbol_mentioned(symbol: str, text: str) -> bool:
    sym = (symbol or "").strip().upper()
    if not sym or not text:
        return False
    # Prefer strict uppercase match to reduce false positives for short/common tokens.
    return bool(re.search(rf"(?<![A-Z0-9])(?:\${sym}|{sym})(?![A-Z0-9])", text))


def relevance(symbol: str, news: Mapping[str, Any] | str) -> float:
    """
    Deterministic relevance score in [0.0, 1.0].

    Rules:
    - If the symbol isn't present (or structured symbol mismatches), relevance is 0.
    - Otherwise combine (symbol mention strength) + (event materiality prior).
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return 0.0

    if isinstance(news, str):
        headline = ""
        body = news
        structured_symbol = None
        event_ts = None
    else:
        headline, body = get_text_fields(news)
        structured_symbol = (news.get("symbol") or None)
        event_ts = news.get("event_ts") or news.get("timestamp")

    if structured_symbol and str(structured_symbol).upper() not in (sym,):
        # Explicit mismatch: this item is about another symbol.
        return 0.0

    combined_text = (headline or "") + "\n" + (body or "")
    mention_any = _symbol_mentioned(sym, combined_text) or (structured_symbol is not None)
    mention_headline = _symbol_mentioned(sym, headline or "") or False
    if not mention_any and not mention_headline:
        return 0.0

    et = classify_event(combined_text)
    event_weight: dict[EventType, float] = {
        EventType.EARNINGS: 1.0,
        EventType.GUIDANCE: 0.9,
        EventType.MERGER_ACQUISITION: 1.0,
        EventType.REGULATORY: 0.85,
        EventType.LITIGATION: 0.8,
        EventType.ANALYST_RATING: 0.55,
        EventType.PRODUCT: 0.6,
        EventType.INSIDER: 0.45,
        EventType.MACRO: 0.4,
        EventType.OTHER: 0.3,
    }

    base = 0.4 * (1.0 if mention_any else 0.0) + 0.3 * (1.0 if mention_headline else 0.0) + 0.3 * event_weight[et]

    # Small boost for recency markers if present, but deterministic.
    # (We don't parse actual time deltas; just acknowledge presence of a timestamp.)
    if isinstance(event_ts, datetime):
        base = min(1.0, base + 0.02)

    if base < 0.0:
        return 0.0
    if base > 1.0:
        return 1.0
    return float(base)


def to_feature_records(symbol: str, news: Mapping[str, Any]) -> list[NewsFeatureRecord]:
    """
    Convert a single normalized news payload to a list of feature records:
    - news.sentiment (float)
    - news.event_type (str enum value)
    - news.relevance (float)
    """
    sym = (symbol or news.get("symbol") or "").strip().upper()
    headline, body = get_text_fields(news)
    combined = (headline or "") + ("\n" + body if body else "")
    event_ts = news.get("event_ts") or news.get("timestamp")

    s = sentiment(combined)
    et = classify_event(combined)
    r = relevance(sym, news)

    source = news.get("source")
    url = news.get("url")

    base_id_parts = (sym, str(event_ts or ""), headline or "", str(source or ""))

    return [
        NewsFeatureRecord(
            feature_id=stable_feature_id(*base_id_parts, "news.sentiment"),
            symbol=sym,
            feature_name="news.sentiment",
            feature_value=float(s),
            event_ts=event_ts if isinstance(event_ts, datetime) else None,
            source=str(source) if source else None,
            headline=headline or None,
            url=str(url) if url else None,
            metadata={"method": "lexicon_v1"},
        ),
        NewsFeatureRecord(
            feature_id=stable_feature_id(*base_id_parts, "news.event_type"),
            symbol=sym,
            feature_name="news.event_type",
            feature_value=et.value,
            event_ts=event_ts if isinstance(event_ts, datetime) else None,
            source=str(source) if source else None,
            headline=headline or None,
            url=str(url) if url else None,
            metadata={"method": "rules_v1"},
        ),
        NewsFeatureRecord(
            feature_id=stable_feature_id(*base_id_parts, "news.relevance"),
            symbol=sym,
            feature_name="news.relevance",
            feature_value=float(r),
            event_ts=event_ts if isinstance(event_ts, datetime) else None,
            source=str(source) if source else None,
            headline=headline or None,
            url=str(url) if url else None,
            metadata={"method": "rules_v1"},
        ),
    ]

