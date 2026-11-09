from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
SpecValue = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Product(StrictModel):
    name: ShortText
    manufacturer: Annotated[str, Field(max_length=200)] | None = None
    specs: dict[ShortText, SpecValue | None] = Field(default_factory=dict, max_length=40)
    description: str = Field(default="", max_length=15000)
    expected_specs: list[ShortText] = Field(
        default_factory=lambda: [
            "диапазон измерений",
            "точность",
            "питание",
            "тип корпуса",
            "интерфейсы",
        ],
        max_length=30,
    )

    @field_validator("specs")
    @classmethod
    def unique_spec_names(cls, value):
        if len({key.casefold() for key in value}) != len(value):
            raise ValueError("Названия характеристик не должны повторяться")
        return value

    @field_validator("expected_specs")
    @classmethod
    def unique_expected_specs(cls, value):
        return list(dict.fromkeys(value))


class Evidence(StrictModel):
    field: ShortText = Field(description="name, manufacturer, description или specs.<ключ>")
    quote: str = Field(min_length=1, max_length=1000, description="Точная цитата из поля")


class GeneratedContent(StrictModel):
    seo_title: str = Field(min_length=1, max_length=70)
    seo_description: str = Field(min_length=800, max_length=1200)
    search_queries: list[ShortText] = Field(min_length=3, max_length=5)
    commercial_block: str = Field(min_length=1, max_length=700)
    evidence: list[Evidence] = Field(min_length=1, max_length=40)

    @field_validator("search_queries")
    @classmethod
    def unique_queries(cls, value):
        if len({query.casefold() for query in value}) != len(value):
            raise ValueError("Поисковые запросы должны быть разными")
        return value


class CreateDraft(StrictModel):
    product: Product
    provider: Literal["manual", "openai"] | None = None


class Completion(StrictModel):
    draft_id: UUID
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    content: GeneratedContent
