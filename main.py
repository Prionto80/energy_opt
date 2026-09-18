"""
GridWise LLM Energy Optimizer - FastAPI entrypoint.

Pipeline:

    Operator notes
        -> LLM interpretation (interpreter)
        -> deterministic guardrails (guardrails)
        -> linear-programming optimizer (optimizer)
        -> final validation / replay (validator)
        -> JSON response
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates

from app.interpreter import InterpretationError, interpret_notes
from app.guardrails import validate_directives
from app.optimizer import optimize_energy
from app.schemas import OptimizeRequest, OptimizeResponse
from app.validator import validate_plan


app = FastAPI(
    title="GridWise LLM Energy Optimizer",
    version="0.1.0",
    description="BUP CSE Fest 2026 Hackathon API",
)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/", include_in_schema=False)
def index(request: Request):
    """Render the lightweight operator dashboard."""
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post(
    "/optimize-energy",
    response_model=OptimizeResponse,
)
def optimize_energy_api(
    request: OptimizeRequest,
):
    try:
        # --------------------------------------------------
        # STEP 1: notes -> structured directives
        # --------------------------------------------------
        directives = interpret_notes(
            request.operator_notes,
            request.battery.capacity_kwh,
        )

        # --------------------------------------------------
        # STEP 2: validate interpreter output
        # --------------------------------------------------
        validate_directives(
            directives,
            request.operator_notes,
            request.battery.capacity_kwh,
        )

        # --------------------------------------------------
        # STEP 3: apply directives + optimize
        # --------------------------------------------------
        result = optimize_energy(
            request,
            directives,
        )

        # --------------------------------------------------
        # STEP 4: final validation / replay
        # --------------------------------------------------
        validate_plan(
            request,
            directives,
            result,
        )

        return result

    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=str(e),
        )

    except InterpretationError as e:
        detail = str(e)
        if not detail.startswith(("OpenAI ", "Google ")):
            detail = "Operator-note interpretation unavailable"
        raise HTTPException(
            status_code=500,
            detail=detail,
        )

    except Exception:
        # Do not expose internal stack traces.
        raise HTTPException(
            status_code=500,
            detail="Optimization failed",
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="localhost", port=8000)
