from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.database import Base, Draft, make_database
from app.export import to_markdown
from app.prompts import PROMPT_VERSION, export_request, input_hash
from app.providers import ProviderError, generate_openai
from app.schemas import Completion, CreateDraft, Product
from app.validation import ContentError, build_card, validate_content

ROOT = Path(__file__).resolve().parent


def serialize(draft: Draft) -> dict:
    return {
        "id": draft.id,
        "product": draft.product,
        "provider": draft.provider,
        "model": draft.model,
        "prompt_version": draft.prompt_version,
        "input_hash": draft.input_hash,
        "status": draft.status,
        "result": draft.result,
        "error": draft.error,
        "created_at": draft.created_at.isoformat(),
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine, sessions = make_database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        # Deliberate MVP choice: one table, one application worker, no schema upgrades.
        Base.metadata.create_all(engine)
        yield
        engine.dispose()

    app = FastAPI(title="Прибор / Контент", version="0.1.0", lifespan=lifespan)
    app.state.sessions = sessions
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Do not reflect full input (or potentially secret values) in errors.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"field": ".".join(map(str, item["loc"])), "message": item["msg"]}
                    for item in exc.errors()
                ]
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        return JSONResponse(status_code=503, content={"detail": "База данных недоступна"})

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/health")
    def health():
        with sessions() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/api/config")
    def config():
        return {
            "default_provider": settings.default_provider,
            "openai_available": bool(settings.openai_api_key.get_secret_value()),
        }

    @app.get("/api/examples")
    def examples():
        import json

        return [
            {
                "product": json.loads(path.read_text()),
                "content": json.loads(
                    path.with_name(path.name.replace(".input.json", ".content.json")).read_text()
                ),
            }
            for path in sorted((ROOT.parent / "examples").glob("*.input.json"))
        ]

    def get_draft(session, draft_id: UUID) -> Draft:
        draft = session.get(Draft, str(draft_id))
        if draft is None:
            raise HTTPException(404, "Задание не найдено")
        return draft

    @app.post("/api/drafts", status_code=201)
    def create_draft(body: CreateDraft):
        provider = body.provider or settings.default_provider
        if provider == "openai" and not settings.openai_api_key.get_secret_value():
            raise HTTPException(503, "Задайте OPENAI_API_KEY или выберите режим ChatGPT")
        with sessions() as session:
            draft = Draft(
                product=body.product.model_dump(),
                provider=provider,
                model=settings.openai_model if provider == "openai" else "ChatGPT (manual)",
                input_hash=input_hash(body.product),
                prompt_version=PROMPT_VERSION,
            )
            session.add(draft)
            session.commit()
            if provider == "manual":
                return serialize(draft)
            # Release the connection during the provider request.
            draft_id = draft.id
        try:
            content = generate_openai(body.product, settings)
            validate_content(body.product, content)
            card = build_card(body.product, content)
        except (ProviderError, ContentError) as exc:
            with sessions() as session:
                session.execute(
                    update(Draft)
                    .where(Draft.id == draft_id)
                    .values(status="failed", error=str(exc)[:1000])
                )
                session.commit()
            code = exc.status_code if isinstance(exc, ProviderError) else 502
            raise HTTPException(code, {"message": str(exc), "draft_id": draft_id}) from exc
        with sessions() as session:
            draft = session.get(Draft, draft_id)
            draft.result, draft.status = card, "completed"
            session.commit()
            return serialize(draft)

    @app.get("/api/drafts")
    def list_drafts(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        with sessions() as session:
            drafts = session.scalars(
                select(Draft)
                .order_by(Draft.created_at.desc(), Draft.id)
                .limit(limit)
                .offset(offset)
            )
            return [
                {
                    "id": d.id,
                    "name": d.product["name"],
                    "status": d.status,
                    "provider": d.provider,
                    "created_at": d.created_at.isoformat(),
                }
                for d in drafts
            ]

    @app.get("/api/drafts/{draft_id}")
    def read_draft(draft_id: UUID):
        with sessions() as session:
            return serialize(get_draft(session, draft_id))

    @app.get("/api/drafts/{draft_id}/request")
    def request_bundle(draft_id: UUID):
        with sessions() as session:
            draft = get_draft(session, draft_id)
            return export_request(draft.id, Product.model_validate(draft.product))

    @app.post("/api/drafts/{draft_id}/result")
    def complete_draft(draft_id: UUID, body: Completion):
        with sessions() as session:
            draft = get_draft(session, draft_id)
            if body.draft_id != draft_id or body.input_hash != draft.input_hash:
                raise HTTPException(409, "Ответ относится к другому заданию или исходным данным")
            if draft.provider != "manual" or draft.status != "pending":
                raise HTTPException(409, "Импорт доступен только для ожидающего ответа ChatGPT")
            product = Product.model_validate(draft.product)
            try:
                validate_content(product, body.content)
            except ContentError as exc:
                raise HTTPException(422, str(exc)) from exc
            card = build_card(product, body.content)
            # Compare-and-set prevents concurrent imports from overwriting a completed draft.
            result = session.execute(
                update(Draft)
                .where(
                    Draft.id == str(draft_id), Draft.status == "pending", Draft.provider == "manual"
                )
                .values(result=card, status="completed")
            )
            if result.rowcount != 1:
                session.rollback()
                raise HTTPException(409, "Задание уже обработано")
            session.commit()
            session.refresh(draft)
            return serialize(draft)

    @app.get("/api/drafts/{draft_id}/markdown", response_class=PlainTextResponse)
    def markdown(draft_id: UUID):
        with sessions() as session:
            draft = get_draft(session, draft_id)
            if draft.status != "completed":
                raise HTTPException(409, "Карточка ещё не готова")
            return to_markdown(draft.result)

    return app
