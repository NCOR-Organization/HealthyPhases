"""Helpers for building the module's SQL.

The dataset service takes SQL as a string with no parameter binding, so every
value this module puts into a query goes through :func:`literal` first. Ids are
hex or slugs by construction, but caller-supplied paper ids are not, and a
query builder that is only safe for well-behaved input is not safe.
"""

from __future__ import annotations


def literal(value: str) -> str:
    """A single-quoted SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def in_list(values: list[str]) -> str:
    """A parenthesised list for ``IN (...)``; never empty."""
    if not values:
        # An empty IN () is a syntax error, and IN (NULL) matches nothing,
        # which is the intended meaning of "restricted to no ids".
        return "(NULL)"
    return "(" + ", ".join(literal(value) for value in values) + ")"
