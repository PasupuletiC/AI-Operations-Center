import json
import logging
from typing import Dict, Any, Optional
from app.core.llm_router import router
from app.core.json_utils import extract_json
from app.services.jira_client import jira_service

logger = logging.getLogger(__name__)

async def create_jira_ticket(email_data: Dict[str, Any], workflow_plan: Dict[str, Any], incident_result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Uses Llama 3.1 8B to format the ticket fields and pushes to Jira.
    """
    # 1. Format ticket fields using the fast Groq model
    model = router.select_model(task_type='ticket_fields', sensitivity='low')
    
    system_prompt = """
    You are a Ticket Formatting Agent. Your job is to take raw email, workflow data, and potential incident RCA and 
    output a strict JSON object with a clear 'summary' (max 60 chars) and a detailed 'description'.
    If incident RCA is present, make sure the description includes the Root Cause and Remediation Plan.
    Output format:
    {
        "summary": "Short title",
        "description": "Detailed description of the issue."
    }
    """
    
    user_content = f"Email Data:\n{json.dumps(email_data)}\n\nWorkflow:\n{json.dumps(workflow_plan)}"
    if incident_result:
        user_content += f"\n\nIncident Analysis:\n{json.dumps(incident_result)}"
        
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]
    
    try:
        response = await router.call_llm(model=model, messages=messages, max_tokens=500)
        fields = extract_json(response)
        if fields is None:
            raise ValueError(f"No JSON in ticket response: {response[:200]}")
    except Exception as e:
        logger.error(f"[TicketAgent] LLM field formatting failed: {e}")
        fields = {
            "summary": f"Incident: {email_data.get('email_type', 'Unknown')}",
            "description": str(email_data)
        }
        
    # 2. Push to Jira
    priority = email_data.get("priority", "P3-medium")
    ticket_result = await jira_service.create_ticket(
        summary=fields["summary"],
        description=fields["description"],
        priority=priority
    )
    
    return ticket_result
