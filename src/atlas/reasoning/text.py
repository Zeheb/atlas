"""Shared lexical primitives for the reasoning subsystem (M1.7 commit 1).

Extracted from ``retrieval.py`` (M1/M1.5) so ``planner.py`` (M1.7) can tokenize
a question with the exact same rules the retriever uses to score windows —
one tokenizer, not two definitions that could silently drift apart. Pure
refactor: behavior is unchanged, only the module boundary moved.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:\.\d+)?")

_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "has",
        "have",
        "had",
        "this",
        "that",
        "these",
        "those",
        "with",
        "as",
        "by",
        "from",
        "it",
        "its",
        "their",
        "they",
        "which",
        "what",
        "how",
        "does",
        "do",
        "did",
        "will",
        "would",
        "can",
        "could",
        "about",
        "over",
        "under",
        "than",
        "then",
        "if",
        "not",
        "no",
        "yes",
        "you",
        "your",
        "we",
        "our",
        "i",
        "he",
        "she",
        "them",
        "his",
        "her",
        "there",
        "here",
        "such",
        "any",
        "all",
        "so",
        "but",
        "also",
    }
)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def keywords(text: str) -> tuple[set[str], set[str]]:
    """Return (word_keywords, numeric_keywords) from *text*, stopwords dropped."""
    words: set[str] = set()
    numbers: set[str] = set()
    for tok in tokenize(text):
        if tok[0].isdigit():
            numbers.add(tok)
        elif tok not in _STOPWORDS and len(tok) >= 3:
            words.add(tok)
    return words, numbers
