"""Small HTTP client: no direct database writes, same validation as the web UI."""

import argparse
import json
import sys
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description="Обмен заданиями с ChatGPT")
    parser.add_argument("--url", default="http://localhost:8080")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("file", type=Path)
    create.add_argument("--provider", choices=["manual", "openai"], default="manual")
    export = commands.add_parser("export")
    export.add_argument("id")
    export.add_argument("--output", type=Path, required=True)
    complete = commands.add_parser("complete")
    complete.add_argument("file", type=Path)
    commands.add_parser("list")
    args = parser.parse_args()
    try:
        with httpx.Client(base_url=args.url, timeout=120) as client:
            if args.command == "create":
                response = client.post(
                    "/api/drafts",
                    json={
                        "product": json.loads(args.file.read_text()),
                        "provider": args.provider,
                    },
                )
            elif args.command == "export":
                response = client.get(f"/api/drafts/{args.id}/request")
            elif args.command == "complete":
                payload = json.loads(args.file.read_text())
                response = client.post(f"/api/drafts/{payload['draft_id']}/result", json=payload)
            else:
                response = client.get("/api/drafts")
            response.raise_for_status()
            result = json.dumps(response.json(), ensure_ascii=False, indent=2)
            if args.command == "export":
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(result + "\n")
                print(args.output)
            else:
                print(result)
    except httpx.HTTPStatusError as exc:
        print(f"HTTP {exc.response.status_code}: {exc.response.text}", file=sys.stderr)
        sys.exit(1)
    except (httpx.RequestError, OSError, ValueError, KeyError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
