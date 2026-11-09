import pytest
from pydantic import ValidationError

from app.export import to_markdown
from app.prompts import input_hash
from app.schemas import GeneratedContent, Product
from app.validation import ContentError, build_card, validate_content


@pytest.mark.parametrize(
    "field,value",
    [
        ("seo_title", "т" * 71),
        ("seo_description", "т" * 799),
        ("seo_description", "т" * 1201),
        ("search_queries", ["а", "б"]),
        ("search_queries", ["а", "б", "в", "г", "д", "е"]),
        ("search_queries", ["Testo", "testo", "манометр"]),
        ("evidence", []),
    ],
)
def test_output_constraints(content, field, value):
    with pytest.raises(ValidationError):
        GeneratedContent(**{**content, field: value})


@pytest.mark.parametrize("length", [800, 1200])
def test_description_boundaries(content, length):
    assert (
        len(GeneratedContent(**{**content, "seo_description": "т" * length}).seo_description)
        == length
    )


@pytest.mark.parametrize("text", ["Питание 999 В", "Давление 510 МПа"])
def test_unknown_numbers_or_units_are_rejected(product, content, text):
    content["commercial_block"] = text
    with pytest.raises(ContentError):
        validate_content(Product(**product), GeneratedContent(**content))


def test_false_evidence_rejected(product, content):
    content["evidence"][0]["quote"] = "Несуществующее описание"
    with pytest.raises(ContentError):
        validate_content(Product(**product), GeneratedContent(**content))


def test_known_measurement_and_exact_characteristics(product, content):
    product["specs"]["диапазон измерений"] = "0–1,6 МПа"
    content["commercial_block"] = "Диапазон измерений: 0–1,6 МПа."
    product = Product(**product)
    content = GeneratedContent(**content)
    validate_content(product, content)
    card = build_card(product, content)
    assert {"name": "диапазон измерений", "value": "0–1,6 МПа"} in card["characteristics"]
    assert "диапазон измерений" not in card["missing_fields"]


def test_empty_values_marked_missing(product, content):
    product["manufacturer"] = " "
    product["specs"]["точность"] = " "
    product["specs"]["интерфейсы"] = None
    card = build_card(Product(**product), GeneratedContent(**content))
    assert {"производитель", "точность", "интерфейсы"} <= set(card["missing_fields"])
    assert {"name": "точность", "value": "данных нет"} in card["characteristics"]


def test_hash_ignores_object_key_order_but_detects_changes(product):
    first = Product(**product)
    reordered = Product(**dict(reversed(list(product.items()))))
    assert input_hash(first) == input_hash(reordered)
    product["specs"]["артикул"] = "другой"
    assert input_hash(first) != input_hash(Product(**product))


def test_markdown_escapes_user_html_and_table_delimiters(product, content):
    product["specs"]["<script>"] = "one|two\nthree"
    markdown = to_markdown(build_card(Product(**product), GeneratedContent(**content)))
    assert "<script>" not in markdown
    assert r"one\|two three" in markdown
