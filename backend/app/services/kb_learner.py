"""
Self-Learning Knowledge Base — auto-generates runbooks after P1/P2 incidents.
"""
import logging
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def generate_and_save_runbook(subject: str, result: Dict[str, Any]) -> bool:
    """Generate a runbook from a processed incident and save it to Qdrant KB."""
    try:
        from app.core.llm_router import router as llm_router
        from app.services.qdrant_client import upsert_documents, init_qdrant
        from app.services.embeddings import embed_documents

        email_data = result.get("email_data", {})
        priority   = email_data.get("priority",   "")
        email_type = email_data.get("email_type", "incident")
        department = email_data.get("department", "general")

        if priority not in ("P1-critical", "P2-high"):
            return False

        rca         = result.get("incident_result", {}).get("rca", {})
        triage      = result.get("incident_result", {}).get("triage", {})
        root_cause  = rca.get("root_cause", "")
        remediation = rca.get("remediation_plan", [])
        steps_str   = "\n".join(f"{i+1}. {s}" for i, s in enumerate(remediation))
        triage_sum  = triage.get("triage_summary", "")
        summary     = result.get("executive_summary", "")[:300]

        prompt = f"""Write a professional SRE runbook for this incident:

Subject   : {subject}
Priority  : {priority}
Type      : {email_type}
Department: {department}

Root Cause: {root_cause}
Triage    : {triage_sum}
Remediation Steps:
{steps_str}
Summary: {summary}

Format with sections: SYMPTOMS / DIAGNOSIS / FIX STEPS / VERIFICATION / PREVENTION
Be specific and actionable."""

        model    = llm_router.select_model(task_type="executive_summary", sensitivity="low")
        messages = [
            {"role": "system", "content": "You are an expert SRE. Write concise, actionable runbooks."},
            {"role": "user",   "content": prompt},
        ]
        runbook_text = await llm_router.call_llm(model=model, messages=messages, max_tokens=800)

        if not runbook_text or len(runbook_text) < 100:
            return False

        date_str = datetime.now().strftime("%Y-%m-%d")
        title    = f"Auto Runbook: {subject[:55]} [{date_str}]"
        content  = f"AUTO-GENERATED | {date_str} | {priority} | {email_type}\n\n{runbook_text}"

        # Chunk and embed (same as knowledge_routes._ingest_document)
        await init_qdrant()
        chunks = [p.strip() for p in content.split("\n\n") if p.strip()]
        if not chunks:
            return False
        documents  = [{"text": f"{title}\n\n{c}", "source": f"auto-runbook/{date_str}"} for c in chunks]
        embeddings = embed_documents([d["text"] for d in documents])
        saved      = await upsert_documents(documents, embeddings)

        if saved:
            logger.info(f"[KB Learner] ✅ Runbook saved to KB: {title[:60]}")
        return saved

    except Exception as e:
        logger.error(f"[KB Learner] Failed: {e}")
        return False
