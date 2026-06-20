import json
from typing import Dict, Any
from app.core.llm_router import router
from app.core.json_utils import extract_json
from app.services.datadog_client import datadog_service

async def analyze_incident(email_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Two-stage incident analysis:
    Stage 1: Fast triage using Groq Llama 3.3 70B
    Stage 2: Deep root cause analysis using Groq (complex reasoning)
    """
    # 1. Fetch system logs
    query = email_data.get("department", "general")
    logs = await datadog_service.fetch_recent_logs(query=query)
    
    # 2. Stage 1: Triage (Groq - fast)
    triage_model = router.select_model(task_type='triage', sensitivity='low')
    triage_prompt = """
    You are an Incident Triage Agent. Review the incident and system logs.
    Output ONLY JSON:
    {
        "severity": "P1-critical | P2-high | P3-medium | P4-low",
        "urgency_score": float 0-1,
        "affected_systems": ["sys1"],
        "affected_users": "estimate e.g. All users / Engineering team / Unknown",
        "triage_summary": "Short summary of symptoms."
    }
    """
    
    triage_messages = [
        {"role": "system", "content": triage_prompt},
        {"role": "user", "content": f"Incident:\n{json.dumps(email_data)}\n\nLogs:\n{json.dumps(logs)}"}
    ]
    
    try:
        triage_response = await router.call_llm(model=triage_model, messages=triage_messages, max_tokens=400)
        triage_result = extract_json(triage_response)
        if triage_result is None:
            raise ValueError(f"No JSON in triage response: {triage_response[:200]}")
    except Exception as e:
        print(f"Triage Error: {e}")
        triage_result = {"triage_summary": "Failed to triage.", "urgency_score": 0.5}
        
    # 3. Stage 2: Deep RCA (complex reasoning model)
    rca_model = router.select_model(task_type='root_cause', sensitivity='low')
    rca_prompt = """
    You are a Senior SRE conducting Root Cause Analysis. 
    Analyze the incident, logs, and triage summary.
    Output ONLY JSON:
    {
        "root_cause": "Detailed explanation of what failed and why.",
        "remediation_plan": ["Step 1", "Step 2", "Step 3"],
        "post_mortem_draft": "Draft summary for the post-mortem report.",
        "estimated_resolution_time": "e.g. 30 minutes / 2 hours"
    }
    """
    
    rca_messages = [
        {"role": "system", "content": rca_prompt},
        {"role": "user", "content": f"Incident:\n{json.dumps(email_data)}\n\nLogs:\n{json.dumps(logs)}\n\nTriage:\n{json.dumps(triage_result)}"}
    ]
    
    try:
        rca_response = await router.call_llm(model=rca_model, messages=rca_messages, max_tokens=1000)
        rca_result = extract_json(rca_response)
        if rca_result is None:
            raise ValueError(f"No JSON in RCA response: {rca_response[:200]}")
    except Exception as e:
        print(f"RCA Error: {e}")
        rca_result = {"root_cause": "Failed to determine root cause.", "remediation_plan": []}
        
    return {
        "logs": logs,
        "triage": triage_result,
        "rca": rca_result
    }

