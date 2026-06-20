import json
from typing import Dict, Any
from app.core.llm_router import router
from app.core.json_utils import extract_json
from app.services.calendar_client import calendar_service

async def schedule_meeting(email_data: Dict[str, Any], workflow_plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Uses Gemma 2 9B to draft an agenda and schedule a calendar event.
    """
    # 1. Generate Agenda
    model = router.select_model(task_type='agenda_write', sensitivity='low')
    
    system_prompt = """
    You are an AI Scheduling Assistant. Based on the incident/request context, draft a concise 
    meeting agenda (3-5 bullet points) and suggest a summary title.
    Output ONLY JSON:
    {
        "title": "Discussion: Issue Title",
        "agenda": "1. Point one\n2. Point two\n...",
        "attendees": ["user@example.com", "manager@example.com"]
    }
    """
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Context:\n{json.dumps(email_data)}\nWorkflow:\n{json.dumps(workflow_plan)}"}
    ]
    
    try:
        response = await router.call_llm(model=model, messages=messages, max_tokens=300)
        agenda_data = extract_json(response)
        if agenda_data is None:
            raise ValueError(f"No JSON in agenda response: {response[:200]}")
    except Exception as e:
        print(f"Meeting Agent Error: {e}")
        agenda_data = {
            "title": "Incident Follow-up",
            "agenda": "- Review incident\n- Discuss remediation",
            "attendees": ["team@example.com"]
        }
        
    # 2. Find slots and schedule
    start_time = await calendar_service.find_available_slots(agenda_data.get("attendees", []))
    event = await calendar_service.create_event(
        summary=agenda_data.get("title", "Meeting"),
        description=agenda_data.get("agenda", ""),
        start_time=start_time,
        attendees=agenda_data.get("attendees", [])
    )
    
    return {
        "event_id": event.get("id"),
        "link": event.get("htmlLink"),
        "start_time": start_time,
        "agenda": agenda_data
    }
