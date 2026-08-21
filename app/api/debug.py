"""Live-demo endpoint: prove the LLM provider chain actually answers, from
the browser, without needing a seeded database. Not part of the product
API surface — kept separate so it's obvious this is a demo utility.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.providers.base import LLMMessage, ProviderError

router = APIRouter(prefix="/debug", tags=["debug"])


class PromptRequest(BaseModel):
    prompt: str


class PromptResponse(BaseModel):
    provider: str
    model: str
    text: str


@router.post("/llm", response_model=PromptResponse)
async def ask_llm(body: PromptRequest) -> PromptResponse:
    from app.providers.llm import get_generation_chain

    chain = get_generation_chain()
    try:
        response = await chain.call(
            lambda p: p.complete([LLMMessage(role="user", content=body.prompt)], max_tokens=300)
        )
    except ProviderError as exc:
        return PromptResponse(provider="none", model="none", text=f"error: {exc}")
    return PromptResponse(provider=response.provider, model=response.model, text=response.text)
