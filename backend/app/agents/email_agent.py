import json
from typing import Dict, Any
from app.core.llm_router import router
from app.core.json_utils import extract_json

async def process_email(email_content: str, is_sensitive: bool = False) -> Dict[str, Any]:
    """
    Classifies an email and extracts relevant entities using the free Groq model.
    """
    sensitivity = 'high' if is_sensitive else 'low'
    model = router.select_model(task_type='classify', sensitivity=sensitivity)
    
    system_prompt = """
    You are an expert AI Email classification agent for an enterprise IT support center.
    Read the following email and output ONLY a JSON object with the following schema:
    {
      "email_type": "incident | request | query | complaint",
      "priority": "P1-critical | P2-high | P3-medium | P4-low",
      "sentiment": float between 0 and 1 (0 = negative, 1 = positive),
      "department": "engineering | finance | hr | product | it",
      "requires_ticket": boolean,
      "extracted_entities": [{"type": "error_code|system|user|date", "value": "extracted_value"}]
    }
    """
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Email Content:\n{email_content}"}
    ]
    
    try:
        response_text = await router.call_llm(model=model, messages=messages, max_tokens=500)
        result = extract_json(response_text)
        if result is None:
            raise ValueError(f"No JSON found in response: {response_text[:200]}")
        return result
    except Exception as e:
        print(f"Email Agent Error: {e}")
        return {"error": str(e), "requires_ticket": False}
