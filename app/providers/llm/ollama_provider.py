from app.config import Settings
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider

# Local, self-hosted — no vendor to verify a model catalog against. The
# model must actually be pulled on the target Ollama instance
# (`ollama pull <model>`) or every call fails.
DEFAULT_MODEL = "llama3.3"


class OllamaLLMProvider(OpenAICompatibleLLMProvider):
    def __init__(self, settings: Settings, model: str | None = None):
        super().__init__(
            name="ollama",
            model=model or settings.ollama_model,
            base_url=settings.ollama_base_url,
            api_key=None,
            requires_api_key=False,
        )


class OllamaVerifyLLMProvider(OpenAICompatibleLLMProvider):
    """Same Ollama instance, a deliberately different model from
    OllamaLLMProvider — registered under a distinct provider name
    ("ollama_verify") so app/providers/llm/__init__.py's "verification
    must not start with generation's provider" check treats it as a real
    independent option, not a self-grading loop, when Ollama ends up the
    only actually-reachable provider (see config/providers.yaml).
    """

    def __init__(self, settings: Settings, model: str | None = None):
        super().__init__(
            name="ollama_verify",
            model=model or settings.ollama_verify_model,
            base_url=settings.ollama_base_url,
            api_key=None,
            requires_api_key=False,
        )
