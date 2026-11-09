"""Replay saved ChatGPT responses through the public API, never pretend to generate."""

import argparse
import json
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description="Загрузить два сохранённых примера ChatGPT")
    parser.add_argument("--url", default="http://localhost:8080")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent / "examples"
    try:
        with httpx.Client(base_url=args.url, timeout=30) as client:
            for path in sorted(root.glob("*.input.json")):
                created = client.post(
                    "/api/drafts",
                    json={
                        "product": json.loads(path.read_text()),
                        "provider": "manual",
                    },
                )
                created.raise_for_status()
                draft = created.json()
                content = json.loads(
                    path.with_name(path.name.replace(".input.json", ".content.json")).read_text()
                )
                completed = client.post(
                    f"/api/drafts/{draft['id']}/result",
                    json={
                        "draft_id": draft["id"],
                        "input_hash": draft["input_hash"],
                        "content": content,
                    },
                )
                completed.raise_for_status()
                print(f"Сохранён пример: {draft['product']['name']} → {draft['id']}")
    except httpx.HTTPStatusError as exc:
        parser.exit(1, f"Ошибка API: {exc.response.status_code} {exc.response.text}\n")
    except (httpx.RequestError, OSError, ValueError) as exc:
        parser.exit(1, f"Не удалось загрузить примеры: {exc}\n")


if __name__ == "__main__":
    main()
