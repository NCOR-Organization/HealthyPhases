from phases_v2.sql import in_list, literal


def test_literal_quotes_a_plain_value():
    assert literal("abc") == "'abc'"


def test_literal_escapes_embedded_quotes():
    assert literal("O'Brien") == "'O''Brien'"


def test_literal_neutralises_an_injection_attempt():
    hostile = "x' OR '1'='1"

    assert literal(hostile) == "'x'' OR ''1''=''1'"


def test_in_list_builds_a_parenthesised_list():
    assert in_list(["a", "b"]) == "('a', 'b')"


def test_an_empty_in_list_matches_nothing_rather_than_being_a_syntax_error():
    assert in_list([]) == "(NULL)"
