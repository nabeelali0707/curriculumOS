from app.config import Settings
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider

BASE_URL = "https://api.fireworks.ai/inference/v1"
# NOTE: verify against Fireworks' current model catalog before relying on
# this — see the same caveat in openai_provider.py.
DEFAULT_MODEL = "accounts/fireworks/models/llama-v3p3-70b-instruct"


class FireworksLLMProvider(OpenAICompatibleLLMProvider):
    def __init__(self, settings: Settings, model: str = DEFAULT_MODEL):
        super().__init__(
            name="fireworks",
            model=model,
            base_url=BASE_URL,
            api_key=settings.fireworks_api_key,
        )
