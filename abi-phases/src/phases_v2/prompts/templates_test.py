"""The declared templates must be valid, stable, and literally what is sent."""

from phases_v2.prompts.domain import CHUNK_PLACEHOLDER, validate
from phases_v2.prompts.templates import declared_prompts


def test_every_declared_template_is_valid():
    validate(list(declared_prompts()))


def test_all_eight_ported_prompts_are_declared():
    assert {template.name for template in declared_prompts()} == {
        "solitude_what",
        "solitude_causes",
        "solitude_how",
        "solitude_when",
        "solitude_where",
        "solitude_effects",
        "conditional_statement",
        "probabilistic_processes",
    }


def test_template_ids_are_stable_across_reloads():
    first = {t.name: t.prompt_id for t in declared_prompts()}

    declared_prompts.cache_clear()
    second = {t.name: t.prompt_id for t in declared_prompts()}

    assert first == second


def test_no_template_carries_doubled_braces():
    # These were written for str.format, where "{{" meant a literal "{". This
    # module substitutes rather than formats, so a surviving "{{" would reach
    # the model verbatim and corrupt the JSON example it is being shown.
    for template in declared_prompts():
        assert "{{" not in template.template, template.name
        assert "}}" not in template.template, template.name


def test_rendering_substitutes_the_chunk_and_leaves_the_json_example_intact():
    template = next(
        t for t in declared_prompts() if t.name == "probabilistic_processes"
    )

    rendered = template.rendered_for("A causes B.")

    assert "A causes B." in rendered
    assert CHUNK_PLACEHOLDER not in rendered
    assert '"relations"' in rendered
    assert "{{" not in rendered


def test_rendering_is_unfazed_by_braces_in_the_chunk_text():
    # Substitution rather than formatting: a chunk quoting JSON or LaTeX must
    # not be able to raise or reformat the prompt around it.
    template = declared_prompts()[0]

    rendered = template.rendered_for('a chunk with {braces} and {"json": 1}')

    assert '{"json": 1}' in rendered


def test_output_keys_match_what_each_prompt_asks_the_model_for():
    for template in declared_prompts():
        assert f'"{template.output_key}"' in template.template, template.name
