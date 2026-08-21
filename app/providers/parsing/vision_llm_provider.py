"""OCR-via-multimodal-LLM parser: for scanned PDFs where every page is a
flat image (no text layer, so Docling/pypdf text extraction both fail),
send each page's embedded page image to a free vision-language model on
OpenRouter and use its transcription as the page's text.

# ponytail: page-level granularity, same as pypdf_provider.py — one block
# per page, bbox = full page rect, no true paragraph bounding boxes. This
# is OCR-via-LLM, not a layout model — it gets you text, not structure.
# Upgrade path: DoclingParserProvider with OCR enabled, once its model
# downloads are approved.
"""

import asyncio
import base64
import io
import logging

import httpx
from pypdf import PdfReader

from app.config import Settings
from app.providers.base import (
    BoundingBox,
    ExtractedBlock,
    ExtractionBlockKind,
    ParsedDocument,
    ParserProvider,
    ProviderError,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "nvidia/nemotron-nano-12b-v2-vl:free"
DEFAULT_CONCURRENCY = 6
OCR_PROMPT = "Transcribe all text visible on this page exactly, preserving structure. Output only the transcribed text, no commentary."


class VisionLLMParserProvider(ParserProvider):
    name = "vision_llm_ocr"

    def __init__(
        self,
        settings: Settings,
        model: str = DEFAULT_MODEL,
        concurrency: int = DEFAULT_CONCURRENCY,
    ):
        if not settings.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is not set")
        self._api_key = settings.openrouter_api_key
        self._model = model
        self._client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1", timeout=90.0
        )
        # ponytail: fixed-size semaphore, not a tuned rate limiter — a free
        # OpenRouter model has no documented RPS limit, so this is a
        # conservative guess. Upgrade path: back off on 429s if they show up.
        self._semaphore = asyncio.Semaphore(concurrency)

    def _largest_page_image(self, page) -> bytes | None:
        """The full-page scan is the largest embedded image on the page —
        smaller images on a scanned page are typically header/footer
        strips or watermarks, not content worth sending to the model.
        """
        images = list(page.images)
        if not images:
            return None
        biggest = max(images, key=lambda im: im.image.size[0] * im.image.size[1])
        buf = io.BytesIO()
        biggest.image.convert("RGB").save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    async def _transcribe_page(self, image_bytes: bytes) -> str:
        b64 = base64.b64encode(image_bytes).decode()
        async with self._semaphore:
            response = await self._post_transcribe(b64)
        payload = response.json()
        # OpenRouter can return HTTP 200 with an error body (rate limits,
        # moderation, upstream provider failure) — raise_for_status() only
        # catches 4xx/5xx, so this has to be checked explicitly or a
        # transient failure silently becomes a KeyError deep in tenacity's
        # retry stack instead of a retryable ProviderError.
        if "error" in payload:
            raise ProviderError(f"{self.name}: {payload['error']}")
        if "choices" not in payload:
            raise ProviderError(f"{self.name}: unexpected response shape: {payload}")
        return payload["choices"][0]["message"]["content"].strip()

    async def _post_transcribe(self, b64: str) -> httpx.Response:
        try:
            response = await self._client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": OCR_PROMPT},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                                },
                            ],
                        }
                    ],
                    "max_tokens": 2000,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name}: {exc}") from exc
        return response

    async def parse(self, file_path: str) -> ParsedDocument:
        try:
            reader = PdfReader(file_path)
        except Exception as exc:
            raise ProviderError(f"{self.name}: failed to open {file_path}: {exc}") from exc

        pages = []
        for page_number, page in enumerate(reader.pages, start=1):
            image_bytes = self._largest_page_image(page)
            if image_bytes is None:
                continue
            pages.append(
                (page_number, float(page.mediabox.width), float(page.mediabox.height), image_bytes)
            )

        async def _transcribe_one(page_number: int, width: float, height: float, image_bytes: bytes):
            try:
                text = await self._transcribe_page(image_bytes)
            except ProviderError as exc:
                # A free-tier vision model timing out on one page out of a
                # few hundred concurrent calls is an expected, recoverable
                # event, not a reason to lose every other page already
                # transcribed — log and move on. The whole-document
                # failure path (ProviderRouter's own retry/circuit-breaker)
                # is still what handles the provider being down entirely.
                logger.warning("%s: page %d failed, skipping: %s", self.name, page_number, exc)
                return page_number, None
            logger.info("%s: transcribed page %d/%d", self.name, page_number, len(reader.pages))
            if not text:
                return page_number, None
            return page_number, ExtractedBlock(
                block_id=f"page-{page_number:04d}",
                page=page_number,
                kind=ExtractionBlockKind.PARAGRAPH,
                text=text,
                bbox=BoundingBox(x0=0.0, y0=0.0, x1=width, y1=height),
                reading_order=page_number,
                confidence=0.5,  # OCR-via-LLM, page-level — see module note
            )

        # Concurrency is bounded by self._semaphore inside _transcribe_page,
        # not here — gather just lets that many requests be in flight
        # instead of waiting for each page's full round trip serially.
        results = await asyncio.gather(*(_transcribe_one(*p) for p in pages))

        blocks: list[ExtractedBlock] = []
        failed_pages: list[int] = []
        for page_number, block in sorted(results, key=lambda r: r[0]):
            if block is None:
                failed_pages.append(page_number)
            else:
                blocks.append(block)

        if failed_pages:
            logger.warning(
                "%s: %d/%d pages failed and were skipped: %s",
                self.name, len(failed_pages), len(reader.pages), failed_pages,
            )
        # Confidence reflects how much of the document actually got
        # transcribed, not just "OCR-via-LLM is inherently 0.5" — a
        # document that lost a third of its pages to timeouts shouldn't
        # report the same confidence as one that lost none.
        completed = len(reader.pages) - len(failed_pages)
        confidence = 0.5 * (completed / len(reader.pages)) if reader.pages else 0.0
        return ParsedDocument(blocks=blocks, parser_confidence=confidence, parser_name=self.name)
