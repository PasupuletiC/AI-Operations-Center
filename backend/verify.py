import asyncio
import httpx
import json

async def test():
    async with httpx.AsyncClient(timeout=180) as client:

        print("=" * 55)
        print("TEST: P1 Critical — Production DB down")
        print("=" * 55)
        r = await client.post(
            "http://localhost:8000/api/process-email",
            json={"raw_email": (
                "URGENT: Production database is completely down. "
                "All users are getting 500 errors. "
                "Error logs show: Connection refused to db-prod-us-east-1 on port 5432. "
                "This started 10 minutes ago after the last deployment. "
                "All engineering teams are blocked. Revenue impact is critical."
            )}
        )
        print("HTTP Status:", r.status_code)
        if r.status_code == 200:
            d = r.json()
            result = d.get("result", {})
            print("Thread ID  :", d.get("thread_id", "N/A")[:8], "...")
            print("Priority   :", result.get("email_data", {}).get("priority"))
            print("Type       :", result.get("email_data", {}).get("email_type"))
            print("Department :", result.get("email_data", {}).get("department"))
            print("Ticket     :", result.get("ticket_result", {}).get("key") if result.get("ticket_result") else "Paused for approval")
            print("KB docs    :", result.get("knowledge_results", {}).get("documents_found", "not run"))
            print("KB mode    :", result.get("knowledge_results", {}).get("rag_mode", "not run"))
            inc = result.get("incident_result", {})
            triage = inc.get("triage", {})
            print("Severity   :", triage.get("severity"))
            print("Affected   :", triage.get("affected_users"))
            rca = inc.get("rca", {})
            print("Root cause :", str(rca.get("root_cause", "N/A"))[:200])
            summ = result.get("executive_summary", "")
            print("Summary    :", summ[:400] if summ else "Paused (awaiting human approval)")
        else:
            print("ERROR:", r.text[:500])

asyncio.run(test())
