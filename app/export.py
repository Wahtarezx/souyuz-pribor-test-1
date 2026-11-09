import re


def escape(value: str) -> str:
    value = value.replace("\n", " ").replace("\r", " ")
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", value)


def to_markdown(card: dict) -> str:
    lines = [
        f"# {escape(card['seo_title'])}",
        "",
        "_Черновик · требуется проверка_",
        "",
        escape(card["seo_description"]),
        "",
        "## Характеристики",
        "",
        "| Характеристика | Значение |",
        "| --- | --- |",
    ]
    lines.extend(
        f"| {escape(item['name'])} | {escape(item['value'])} |" for item in card["characteristics"]
    )
    lines.extend(["", "## Поисковые запросы", ""])
    lines.extend(f"- {escape(query)}" for query in card["search_queries"])
    lines.extend(["", "## Для менеджера", "", escape(card["commercial_block"])])
    if card["missing_fields"]:
        lines.extend(["", "## Нужно уточнить", ""])
        lines.extend(f"- {escape(field)}: данных нет" for field in card["missing_fields"])
    lines.extend(["", "## Основания", ""])
    lines.extend(f"- {escape(e['field'])}: {escape(e['quote'])}" for e in card["evidence"])
    return "\n".join(lines) + "\n"
