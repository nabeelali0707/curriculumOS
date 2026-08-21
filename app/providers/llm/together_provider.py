from app.config import Settings
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider

BASE_URL = "https://api.together.xyz/v1"
# NOTE: verify against Together's current model catalog before relying on
# this — see the same caveat in openai_provider.py.
DEFAULT_MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo"


class TogetherLLMProvider(OpenAICompatibleLLMProvider):
    def __init__(self, settings: Settings, model: str = DEFAULT_MODEL):
        super().__init__(
            name="together",
            model=model,
            base_url=BASE_URL,
            api_key=settings.together_api_key,
        )
