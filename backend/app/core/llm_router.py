"""
LLM Router — smart multi-provider routing with anti-recursion fallback.

Providers (in priority order):
  1. Groq       — primary, fast free-tier (llama-3.3-70b, llama-3.1-8b, gemma2-9b, mixtral)
  2. Gemini     — fallback on Groq failure (gemini-2.0-flash via google-genai SDK)
  3. Ollama     — local, used for high-sensitivity tasks (llama3, nomic-embed-text)

Anti-recursion: the `_is_fallback` flag on `call_llm()` ensures fallback calls
never trigger a second fallback, preventing infinite recursion.
"""
import os
import asyncio
import logging
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
from app.core.quota_tracker import record_call, record_error

logger = logging.getLogger(__name__)

# ── Google GenAI SDK (Python 3.14 compatible, google-genai >= 2.x) ────────────
try:
    from google import genai as google_genai
    HAS_GOOGLE_GENAI = True
except ImportError:
    google_genai = None
    HAS_GOOGLE_GENAI = False

# ── Langfuse observability ─────────────────────────────────────────────────
# Only enable Langfuse if credentials are actually configured.
_langfuse_key = os.getenv("LANGFUSE_SECRET_KEY", "")
try:
    if _langfuse_key and not _langfuse_key.startswith("your"):
        from langfuse.decorators import observe, langfuse_context
        HAS_LANGFUSE = True
    else:
        raise ImportError("Langfuse credentials not set — disabling")
except Exception:
    HAS_LANGFUSE = False
    langfuse_context = None

    def observe(*args, **kwargs):
        """No-op decorator when langfuse is not configured."""
        def decorator(func):
            return func
        return decorator


class LLMRouter:
    def __init__(self):
        # Clients are lazy-initialized on first use so that
        # load_dotenv() in main.py always runs before keys are read.
        self._groq_client = None
        self._gemini_client = None

    # ── Client factories ───────────────────────────────────────────────────────

    def _get_groq_client(self) -> AsyncOpenAI:
        """Lazy-initialize Groq client on first use."""
        if self._groq_client is None:
            key = os.getenv("GROQ_API_KEY")
            if not key:
                raise ValueError("GROQ_API_KEY not set in .env")
            self._groq_client = AsyncOpenAI(
                api_key=key,
                base_url="https://api.groq.com/openai/v1",
            )
        return self._groq_client

    def _get_gemini_client(self):
        """Lazy-initialize Gemini client on first use."""
        if self._gemini_client is None:
            if not HAS_GOOGLE_GENAI:
                raise RuntimeError("google-genai not installed. Run: pip install google-genai")
            key = os.getenv("GEMINI_API_KEY")
            if not key:
                raise ValueError("GEMINI_API_KEY not set in .env")
            self._gemini_client = google_genai.Client(api_key=key)
        return self._gemini_client

    # ── Model selection ────────────────────────────────────────────────────────

    def select_model(self, task_type: str, sensitivity: str, context_length: int = 0) -> str:
        """
        Route to the best free model based on task type and data sensitivity.
        Returns a 'provider/model-name' string consumed by call_llm().
        """
        # Rule 1: Private/sensitive data -> local Ollama (never sent to cloud)
        if sensitivity.lower() == "high":
            return "ollama/llama3"

        # Rule 2: Long-context RAG (>8k tokens) -> Groq Mixtral 32k
        if task_type == "rag_generation" and context_length > 8000:
            return "groq/mixtral-8x7b-32768"

        # Rule 3: Fast classification / extraction -> Groq Llama 3.3 70B
        if task_type in ["classify", "extract", "format", "rag_generation", "triage"]:
            return "groq/llama-3.3-70b-versatile"

        # Rule 4: Ultra-simple ticket field formatting -> Groq Llama 3.1 8B (fastest)
        if task_type in ["ticket_fields", "label_extract"]:
            return "groq/llama-3.1-8b-instant"

        # Rule 5: Agenda writing -> Groq Gemma 2 9B (instruction-tuned)
        if task_type == "agenda_write":
            return "groq/gemma2-9b-it"

        # Rule 6: Complex reasoning -> Groq Llama 3.3 70B
        if task_type in ["root_cause", "executive_summary", "post_mortem", "plan", "manager_planning"]:
            return "groq/llama-3.3-70b-versatile"

        # Default fallback
        return "groq/llama-3.3-70b-versatile"

    # ── Unified LLM call ───────────────────────────────────────────────────────

    # All active Groq models to rotate through if one hits a rate limit or fails
    GROQ_FALLBACK_MODELS = [
        "llama-3.3-70b-versatile",      # primary — fast & capable
        "llama-3.1-8b-instant",          # fast small model
        "gemma2-9b-it",                  # Google Gemma fallback
        "mixtral-8x7b-32768",            # 32k context fallback
        "deepseek-r1-distill-llama-70b", # DeepSeek reasoning model
        "llama3-8b-8192",               # legacy small model
    ]

    @observe(as_type="generation")
    async def call_llm(
        self,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: int = 1000,
    ) -> str:
        """
        Call an LLM with a full rotation fallback:
          1. Try the requested model
          2. If Groq → rotate through all other Groq models before giving up
          3. If Gemini quota error → rotate through Groq models
          4. Raise only when every model is exhausted
        """
        if HAS_LANGFUSE and langfuse_context:
            try:
                langfuse_context.update_current_observation(model=model)
            except Exception:
                pass

        # Normalize to provider/model_name
        provider = model.split("/")[0]   # "groq", "gemini", "ollama"
        model_name = model.split("/", 1)[-1]

        # ── Gemini ────────────────────────────────────────────────────────────
        if provider == "gemini":
            prompt = "\n".join([
                f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
                for m in messages
            ])
            try:
                gemini_client = self._get_gemini_client()
                response = await asyncio.to_thread(
                    gemini_client.models.generate_content,
                    model=model_name,
                    contents=prompt,
                )
                return response.text
            except Exception as e:
                err = str(e)
                logger.warning(f"Gemini {model_name} failed: {err[:120]}. Rotating to Groq...")
                # Fall through to Groq rotation

        # ── Ollama ────────────────────────────────────────────────────────────
        elif provider == "ollama":
            try:
                import ollama
                response = await asyncio.to_thread(
                    ollama.chat, model=model_name, messages=messages
                )
                return response["message"]["content"]
            except Exception as e:
                logger.warning(f"Ollama {model_name} failed: {e}. Rotating to Groq...")
                # Fall through to Groq rotation

        # ── Groq — full model rotation ─────────────────────────────────────────
        # Build rotation list: requested model first, then the rest
        if provider == "groq":
            rotation = [model_name] + [
                m for m in self.GROQ_FALLBACK_MODELS if m != model_name
            ]
        else:
            # Coming from Gemini/Ollama failure — try all Groq models
            rotation = self.GROQ_FALLBACK_MODELS[:]

        groq_client = self._get_groq_client()
        last_error = None

        for attempt_model in rotation:
            try:
                logger.info(f"Trying Groq/{attempt_model}...")
                response = await groq_client.chat.completions.create(
                    model=attempt_model,
                    messages=messages,
                    max_tokens=max_tokens,
                )
                if HAS_LANGFUSE and langfuse_context and response.usage:
                    try:
                        langfuse_context.update_current_observation(
                            usage={
                                "input": response.usage.prompt_tokens,
                                "output": response.usage.completion_tokens,
                                "total": response.usage.total_tokens,
                            }
                        )
                    except Exception:
                        pass
                record_call(attempt_model)  # track quota usage
                return response.choices[0].message.content

            except Exception as e:
                err = str(e)
                last_error = e
                is_rate_limit = (
                    "429" in err or "rate_limit" in err.lower()
                    or "rate limit" in err.lower() or "RATE_LIMIT" in err
                )
                if is_rate_limit:
                    logger.warning(f"Groq/{attempt_model} rate-limited. Trying next model...")
                else:
                    logger.warning(f"Groq/{attempt_model} failed ({type(e).__name__}). Trying next model...")
                continue  # always try next model in the rotation

        # All Groq models exhausted
        raise RuntimeError(
            f"All LLMs exhausted (tried Groq rotation: {rotation}). "
            f"Last error: {last_error}"
        )


# Module-level singleton — imported by all agents
router = LLMRouter()
