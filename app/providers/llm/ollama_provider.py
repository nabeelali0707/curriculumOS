from app.config import Settings
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider

# Local, self-hosted — no vendor to verify a model catalog against. The
# model must actually be pulled on the target Ollama instance
# (`ollama pull <model>`) or every call fails.
DEFAULT_MODEL = "llama3.3"


class OllamaLLMProvider(OpenAICompatibleLLMProvider):
    def __init__(self, settings: Settings, model: str = DEFAULT_MODEL):
        super().__init__(
            name="ollama",
            model=model,
            base_url=settings.ollama_base_url,
            api_key=None,
            requires_api_key=False,
        )
