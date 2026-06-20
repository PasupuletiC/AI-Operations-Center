"""
PII Scrubber — masks sensitive personal information before sending to cloud LLMs.

Replaces with placeholder tokens so the LLM can still understand context
but real data never leaves the network when sensitivity is high.

Patterns scrubbed:
  - Email addresses     → [EMAIL]
  - Phone numbers       → [PHONE]
  - Credit card numbers → [CREDIT_CARD]
  - IP addresses        → [IP_ADDRESS]
  - SSN (US)           → [SSN]
  - API keys / tokens   → [API_KEY]
"""
import re

# Ordered by specificity (most specific first to avoid partial replacements)
_PATTERNS = [
    # API keys / tokens (long hex/base64 strings)
    (re.compile(r'\b(sk-|gsk_|AIza|ghp_|xoxb-|Bearer\s+)[A-Za-z0-9\-_]{20,}\b'), "[API_KEY]"),
    # Credit card (Luhn-like: 4 groups of 4 digits)
    (re.compile(r'\b(?:\d{4}[- ]?){3}\d{4}\b'), "[CREDIT_CARD]"),
    # SSN
    (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), "[SSN]"),
    # IPv4 addresses
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), "[IP_ADDRESS]"),
    # Email addresses
    (re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'), "[EMAIL]"),
    # Phone numbers (various formats)
    (re.compile(r'\b(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b'), "[PHONE]"),
]


def scrub_pii(text: str) -> str:
    """
    Replace PII in text with placeholder tokens.
    Returns the scrubbed string. Non-destructive — original string unchanged.
    """
    if not text:
        return text
    result = text
    for pattern, placeholder in _PATTERNS:
        result = pattern.sub(placeholder, result)
    return result


def contains_pii(text: str) -> bool:
    """Returns True if the text contains any detected PII."""
    return any(pattern.search(text) for pattern, _ in _PATTERNS)


# ── Quick self-test ────────────────────────────────────────────────────────
if __name__ == "__main__":
    sample = """
    Hi team, my name is John Doe, email john.doe@company.com, phone +1 (555) 123-4567.
    Server IP is 192.168.1.100. Card ending 4111 1111 1111 1111.
    SSN: 123-45-6789. Token: sk-abc123def456ghi789jkl012mno345pqr678.
    """
    print("Original:", sample)
    print("Scrubbed:", scrub_pii(sample))
    print("Has PII:", contains_pii(sample))
