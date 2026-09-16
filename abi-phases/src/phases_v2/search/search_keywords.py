"""Keyword syntax: bare words and exact words/phrases inside double quotes."""

import re


def tokenize(query: str) -> list[str]:
    query = query.lower().translate(str.maketrans({"\u201c": '"', "\u201d": '"'}))
    terms = []
    for match in re.finditer(r'"([^"]*)"|(\w+)', query):
        phrase, word = match.groups()
        term = f'"{phrase.strip()}"' if phrase and phrase.strip() else word
        if term and term not in terms:
            terms.append(term)
    return terms


def is_exact(term: str) -> bool:
    return term.startswith('"') and term.endswith('"')


def exact_pattern(term: str, word_chars: str = r"\w") -> str:
    phrase = r"\s+".join(re.escape(word) for word in term[1:-1].split())
    return rf"(^|[^{word_chars}]){phrase}($|[^{word_chars}])"


def matches_term(text: str, term: str) -> bool:
    if is_exact(term):
        return re.search(exact_pattern(term), text.lower()) is not None
    return term in text.lower()
