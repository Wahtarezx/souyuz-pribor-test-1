import re

from app.schemas import GeneratedContent, Product


class ContentError(ValueError):
    pass


def source_fields(product: Product) -> dict[str, str]:
    return {
        "name": product.name,
        "manufacturer": product.manufacturer or "",
        "description": product.description,
        **{f"specs.{key}": value or "" for key, value in product.specs.items()},
    }


def validate_content(product: Product, content: GeneratedContent) -> None:
    """Reject invalid evidence and new numeric tokens; not a semantic truth oracle."""
    fields = source_fields(product)
    for evidence in content.evidence:
        if evidence.field not in fields or evidence.quote not in fields[evidence.field]:
            raise ContentError(f"Цитата не найдена в исходном поле {evidence.field}")

    prose = "\n".join(
        [
            content.seo_title,
            content.seo_description,
            content.commercial_block,
            *content.search_queries,
        ]
    )
    # Preserve signs, decimal separators and leading zeros. No numeric conversions.
    pattern = r"[+−-]?\d+(?:[.,]\d+)?"
    allowed = set(re.findall(pattern, "\n".join(fields.values())))
    unexpected = set(re.findall(pattern, prose)) - allowed
    if unexpected:
        raise ContentError("Новые числовые значения: " + ", ".join(sorted(unexpected)))

    # A known number attached to a new unit is still an unsupported measurement.
    measurement = (
        r"[+−-]?\d+(?:[.,]\d+)?(?:\s*[–—-]\s*[+−-]?\d+(?:[.,]\d+)?)?"
        r"\s*(?:МПа|кПа|мПа|Па|мбар|бар|кВ|мВ|В|мА|А|мВт|кВт|Вт|мм|см|м|"
        r"кГц|МГц|Гц|°C|°С|%)(?![а-яА-Яa-zA-Z])"
    )

    def normalize(value: str) -> str:
        return re.sub(r"\s+", "", value)

    known = {normalize(value) for value in re.findall(measurement, "\n".join(fields.values()))}
    added = {normalize(value) for value in re.findall(measurement, prose)} - known
    if added:
        raise ContentError("Неподтверждённые значения с единицами: " + ", ".join(sorted(added)))


def build_card(product: Product, content: GeneratedContent) -> dict:
    characteristics = [{"name": "производитель", "value": product.manufacturer or "данных нет"}]
    characteristics.extend(
        {"name": name, "value": value or "данных нет"} for name, value in product.specs.items()
    )
    provided = {key.casefold(): value for key, value in product.specs.items()}
    missing = []
    if not product.manufacturer:
        missing.append("производитель")
    if not product.description:
        missing.append("описание или фрагмент паспорта")
    for name in product.expected_specs:
        if not provided.get(name.casefold()):
            missing.append(name)
        if name.casefold() not in provided:
            characteristics.append({"name": name, "value": "данных нет"})
    missing.extend(name for name, value in product.specs.items() if not value)
    return {
        **content.model_dump(),
        "characteristics": characteristics,
        "missing_fields": list(dict.fromkeys(missing)),
        "review_required": True,
        "warnings": [
            "Черновик: перед публикацией требуется проверка контент-менеджером.",
            *(["Исходные данные неполные; запросите паспорт прибора."] if missing else []),
        ],
    }
