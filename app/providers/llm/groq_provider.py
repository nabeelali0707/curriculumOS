from app.config import Settings
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider

BASE_URL = "https://api.groq.com/openai/v1"
# NOTE: verify against Groq's current model catalog before relying on this
# — see the same caveat in openai_provider.py.
DEFAULT_MODEL = "llama-3.3-70b-versatile"


class GroqLLMProvider(OpenAICompatibleLLMProvider):
    def __init__(self, settings: Settings, model: str = DEFAULT_MODEL):
        super().__init__(
            name="groq",
            model=model,
            base_url=BASE_URL,
            api_key=settings.groq_api_key,
        )
