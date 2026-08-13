import os
import json
import logging
from typing import List, Optional
import httpx
import time

from src.config import (
    embedding_batch_size,
    embedding_dim_override,
    embedding_model_override,
    llm_api_key,
    openai_api_base,
    openai_api_key,
    v98_api_key,
)

logger = logging.getLogger(__name__)

# Số chiều phải khớp giữa model nhúng và bảng vec0, nếu không mọi lần ghi vector
# đều fail. Bảng cũ khai float[768] trong khi nhánh mặc định dùng
# text-embedding-3-small (1536 chiều) — đó là lý do tầng vector chưa từng chạy.
EMBEDDING_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "text-embedding-004": 768,
}

DEFAULT_OPENAI_MODEL = "text-embedding-3-small"
DEFAULT_GEMINI_MODEL = "text-embedding-004"


def active_embedding_model() -> str:
    """Model nhúng đang dùng, theo đúng nhánh mà embed_texts sẽ chọn."""
    override = embedding_model_override()
    if override:
        return override
    api_base = openai_api_base()
    uses_openai = (
        v98_api_key()
        or openai_api_key()
        or "v98store" in api_base
        or "openai" in api_base
    )
    return DEFAULT_OPENAI_MODEL if uses_openai else DEFAULT_GEMINI_MODEL


def embedding_dimension() -> int:
    """Số chiều của model đang dùng; cho phép ép bằng EMBEDDING_DIM."""
    forced = embedding_dim_override()
    if forced:
        return int(forced)
    model = active_embedding_model()
    if model not in EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Chưa biết số chiều của model nhúng {model!r}. "
            f"Bổ sung vào EMBEDDING_DIMENSIONS hoặc đặt biến EMBEDDING_DIM."
        )
    return EMBEDDING_DIMENSIONS[model]


class EmbeddingAPI:
    def __init__(self, api_key: str = None, api_base: str = None):
        self.api_key = api_key or llm_api_key()
        self.api_base = api_base or openai_api_base()
        
        if not self.api_key:
            logger.warning("No API key (V98_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY) configured. Embeddings disabled.")
        else:
            logger.info(f"EmbeddingAPI initialized with base URL: {self.api_base}")

    def prepare_legal_text(self, content: str, doc_num: str, heading: str) -> str:
        """Strip frontmatter and prepend doc_num + heading."""
        clean_content = content.strip()
        # Truncate content to safe token size (~1500 words)
        words = clean_content.split()
        if len(words) > 1500:
            clean_content = " ".join(words[:1500])
        return f"[{doc_num}] {heading}\n{clean_content}"

    def embed_single(self, text: str) -> Optional[List[float]]:
        results = self.embed_texts([text])
        return results[0] if results else None

    def embed_texts(self, texts: List[str]) -> List[Optional[List[float]]]:
        if not self.api_key:
            return [None] * len(texts)

        # Check if using OpenAI-compatible V98 API vs Gemini API
        if v98_api_key() or openai_api_key() or "v98store" in self.api_base or "openai" in self.api_base:
            return self._embed_openai_batch(texts)
        else:
            return self._embed_gemini_batch(texts)

    def _embed_openai_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        url = f"{self.api_base.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        results = []
        # text-embedding-3-small nhận tối đa 2048 input và ~300k token mỗi lượt.
        # Đoạn văn bản pháp luật trung bình ~1300 ký tự (~400 token) nên 64 đoạn
        # ≈ 26k token, còn rất xa hạn mức. Mức cũ là 10 → gấp 6 lần số round-trip.
        batch_size = embedding_batch_size()

        model = active_embedding_model()

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            payload = {
                "model": model,
                "input": batch
            }

            retries = 3
            success = False
            for attempt in range(retries):
                try:
                    response = httpx.post(url, headers=headers, json=payload, timeout=60.0)
                    response.raise_for_status()
                    data = response.json()

                    if "data" in data and isinstance(data["data"], list):
                        sorted_data = sorted(data["data"], key=lambda x: x.get("index", 0))
                        # API trả thiếu phần tử mà cứ append tuần tự thì vector
                        # bị gán lệch sang chunk khác — sai thầm lặng, về sau
                        # không có cách nào phát hiện.
                        if len(sorted_data) != len(batch):
                            logger.error(
                                "API trả %d embedding cho %d văn bản — bỏ cả lô để "
                                "tránh gán lệch", len(sorted_data), len(batch)
                            )
                            break
                        for item in sorted_data:
                            results.append(item["embedding"])
                        success = True
                        break
                    else:
                        logger.error(f"Unexpected response format: {data}")
                except Exception as e:
                    logger.error(f"Error embedding batch via OpenAI API (attempt {attempt+1}): {e}")
                    time.sleep(2 ** attempt)

            if not success:
                results.extend([None] * len(batch))

        return results

    def _embed_gemini_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        base_url = "https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:batchEmbedContents"
        results = []
        batch_size = 20
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            requests = [
                {
                    "model": "models/text-embedding-004",
                    "content": {"parts": [{"text": t}]}
                }
                for t in batch
            ]
            
            retries = 3
            success = False
            for attempt in range(retries):
                try:
                    response = httpx.post(
                        f"{base_url}?key={self.api_key}",
                        json={"requests": requests},
                        timeout=60.0
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    if "embeddings" in data:
                        embs = data["embeddings"]
                        # Cùng cạm bẫy như nhánh OpenAI: trả thiếu phần tử mà cứ
                        # append tuần tự thì vector bị gán lệch sang chunk khác —
                        # sai thầm lặng, về sau không phát hiện được. Bỏ cả lô.
                        if len(embs) != len(batch):
                            logger.error(
                                "Gemini trả %d embedding cho %d văn bản — bỏ cả "
                                "lô để tránh gán lệch", len(embs), len(batch))
                            break
                        for embed in embs:
                            results.append(embed["values"])
                        success = True
                        break
                except Exception as e:
                    logger.error(f"Error embedding batch via Gemini API (attempt {attempt+1}): {e}")
                    time.sleep(2 ** attempt)
            
            if not success:
                results.extend([None] * len(batch))
                
        return results

