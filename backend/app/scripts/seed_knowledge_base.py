"""
Knowledge Base Seeder — populates Qdrant with IT runbooks and SOPs.

Run on startup (called from lifespan in main.py) or manually:
    python -m app.scripts.seed_knowledge_base

Documents cover the most common enterprise IT scenarios so the
Knowledge Agent returns useful answers from day one.
"""
import asyncio
from typing import List, Dict

# ── Knowledge Documents ────────────────────────────────────────────────────
KNOWLEDGE_DOCUMENTS: List[Dict[str, str]] = [

    # ── Database Runbooks ──────────────────────────────────────────────────
    {
        "source": "runbook/db-connection-failure",
        "text": (
            "Runbook: Database Connection Failure\n"
            "Symptoms: Application returns 'connection refused', 'timeout', or 'too many connections'.\n"
            "Step 1: Check DB server health — ping the host and verify the port (default 5432 for Postgres) is open.\n"
            "Step 2: Run `SHOW max_connections;` and `SELECT count(*) FROM pg_stat_activity;` to check connection pool exhaustion.\n"
            "Step 3: If pool exhausted, restart connection pooler (PgBouncer) — `systemctl restart pgbouncer`.\n"
            "Step 4: Check disk space on DB host — full disk causes write failures: `df -h`.\n"
            "Step 5: Review DB logs at `/var/log/postgresql/` for lock waits or crash recovery.\n"
            "Step 6: If primary is down, promote standby — `pg_ctl promote -D /var/lib/postgresql/data`.\n"
            "Escalation: If not resolved in 15 min, page the DBA on-call via PagerDuty."
        ),
    },
    {
        "source": "runbook/db-slow-query",
        "text": (
            "Runbook: Slow Database Queries\n"
            "Symptoms: High latency on API endpoints, DB CPU > 80%, query times > 5s.\n"
            "Step 1: Identify slow queries — `SELECT query, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;`\n"
            "Step 2: Run EXPLAIN ANALYZE on the slow query to find missing indexes.\n"
            "Step 3: Add index if missing — `CREATE INDEX CONCURRENTLY idx_name ON table(column);`\n"
            "Step 4: Kill blocking queries — `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE wait_event_type = 'Lock';`\n"
            "Step 5: Check for table bloat — run `VACUUM ANALYZE table_name;`\n"
            "Prevention: Enable `pg_stat_statements`, set `log_min_duration_statement = 1000` (log queries > 1s)."
        ),
    },

    # ── VPN / Network Runbooks ─────────────────────────────────────────────
    {
        "source": "runbook/vpn-access-issues",
        "text": (
            "Runbook: VPN Access Issues\n"
            "Symptoms: User cannot connect to VPN, authentication fails, or connection drops.\n"
            "Step 1: Verify user's VPN credentials are not expired — check AD/LDAP account status.\n"
            "Step 2: Reset VPN password — navigate to IT Portal > User Management > Reset Password.\n"
            "Step 3: Check MFA token — ensure the user's authenticator app is synced (time drift > 30s causes failures).\n"
            "Step 4: If all users affected, check VPN gateway health — ping `vpn.company.com` and verify Cisco ASA/Palo Alto status.\n"
            "Step 5: Check certificate expiry — `openssl s_client -connect vpn.company.com:443 | openssl x509 -noout -dates`\n"
            "Step 6: Collect client logs (Windows: `%APPDATA%\\Cisco\\Cisco AnyConnect`) and open ticket with network team.\n"
            "Self-service: Users can reset their own VPN password at https://selfservice.company.com"
        ),
    },
    {
        "source": "runbook/network-outage",
        "text": (
            "Runbook: Network Outage / High Latency\n"
            "Symptoms: Multiple users report connectivity loss, packet loss > 5%, latency > 200ms.\n"
            "Step 1: Identify scope — is it one office/region or global? Check StatusPage.\n"
            "Step 2: Run traceroute to identify where the packet loss occurs — `tracert 8.8.8.8`\n"
            "Step 3: Check ISP status page and open a support ticket with ISP if WAN is affected.\n"
            "Step 4: Verify core switch health in NOC dashboard — look for spanning tree loops or port flapping.\n"
            "Step 5: If BGP routing issue — check BGP peer status `show bgp summary` on edge routers.\n"
            "Step 6: Failover to backup ISP if primary is down — notify users of maintenance window."
        ),
    },

    # ── Kubernetes / Cloud Runbooks ────────────────────────────────────────
    {
        "source": "runbook/kubernetes-pod-crashloopbackoff",
        "text": (
            "Runbook: Kubernetes CrashLoopBackOff\n"
            "Symptoms: Pod status shows CrashLoopBackOff, application unavailable.\n"
            "Step 1: Get pod logs — `kubectl logs <pod-name> --previous -n <namespace>`\n"
            "Step 2: Describe the pod for events — `kubectl describe pod <pod-name> -n <namespace>`\n"
            "Step 3: Check resource limits — OOMKilled means memory limit too low; increase in deployment spec.\n"
            "Step 4: Check config maps and secrets — missing env vars cause startup crashes.\n"
            "Step 5: Check liveness probe — too aggressive probes kill pods before they finish starting.\n"
            "Step 6: Rollback to last stable deployment — `kubectl rollout undo deployment/<name> -n <namespace>`\n"
            "Step 7: Check image pull errors — verify registry credentials and image tag exists."
        ),
    },
    {
        "source": "runbook/high-cpu-memory",
        "text": (
            "Runbook: High CPU / Memory on Production Servers\n"
            "Symptoms: Server CPU > 90%, memory usage > 95%, application slow or unresponsive.\n"
            "Step 1: Identify top processes — `top` or `htop` on Linux, Task Manager on Windows.\n"
            "Step 2: For CPU — check for runaway processes, infinite loops, or cryptocurrency miners.\n"
            "Step 3: For memory — check for memory leaks `cat /proc/<pid>/status | grep VmRSS`\n"
            "Step 4: Gracefully restart the affected service — `systemctl restart <service-name>`\n"
            "Step 5: Scale horizontally if load is legitimate — add instances via auto-scaling group.\n"
            "Step 6: Enable memory profiling for the next occurrence — attach async-profiler to JVM or pyspy to Python.\n"
            "Alerting: Ensure CloudWatch/Datadog alert is set at 80% for 5 min to catch early."
        ),
    },

    # ── Security / Access Control ──────────────────────────────────────────
    {
        "source": "sop/user-offboarding",
        "text": (
            "SOP: User Offboarding Checklist\n"
            "Triggered when: HR submits offboarding request or employee last day is confirmed.\n"
            "Step 1: Disable AD account immediately — `Disable-ADAccount -Identity username`\n"
            "Step 2: Revoke all SSO sessions — invalidate tokens in Okta/Azure AD.\n"
            "Step 3: Remove from all GitHub/GitLab organizations and teams.\n"
            "Step 4: Transfer Google Drive/OneDrive ownership to manager.\n"
            "Step 5: Revoke AWS/GCP/Azure IAM roles and service account keys.\n"
            "Step 6: Disable MFA devices and remove from all security groups.\n"
            "Step 7: Archive email and forward to manager for 30 days.\n"
            "Step 8: Document completion in the ITSM ticket and notify HR.\n"
            "SLA: Must be completed within 4 hours of last working day."
        ),
    },
    {
        "source": "sop/security-incident-response",
        "text": (
            "SOP: Security Incident Response\n"
            "Severity levels: P1=Active breach, P2=Suspected breach, P3=Policy violation.\n"
            "Immediate (0-15 min): Notify Security Lead, CISO, and Legal. Do NOT publicize.\n"
            "Containment (15-60 min): Isolate affected systems — remove from network, preserve logs.\n"
            "Investigation: Capture memory dump, review auth logs, check for lateral movement.\n"
            "Eradication: Remove malware, patch vulnerability, rotate all credentials.\n"
            "Recovery: Restore from clean backup, verify integrity, monitor for 48h.\n"
            "Post-Incident: Write RCA within 72h, notify affected users, file regulatory report if PII involved.\n"
            "Tools: CrowdStrike for EDR, Splunk for log analysis, Jira for tracking."
        ),
    },

    # ── Service Desk SOPs ──────────────────────────────────────────────────
    {
        "source": "sop/password-reset",
        "text": (
            "SOP: Password Reset Procedure\n"
            "Self-service (preferred): Direct users to https://selfservice.company.com — 24/7 available.\n"
            "Agent-assisted reset:\n"
            "Step 1: Verify user identity — ask for employee ID + last 4 of SSN or manager name.\n"
            "Step 2: Navigate to AD Users & Computers or Azure AD portal.\n"
            "Step 3: Right-click user > Reset Password. Check 'User must change password at next login'.\n"
            "Step 4: Set temporary password (format: Temp@MMYY + employee initials).\n"
            "Step 5: Communicate temporary password via secure channel (not email).\n"
            "Step 6: Log the reset in ITSM ticket with timestamp and agent ID.\n"
            "Note: Never reset password over email. Always verify identity first."
        ),
    },
    {
        "source": "sop/new-employee-onboarding",
        "text": (
            "SOP: New Employee IT Onboarding\n"
            "Day -3 (before start): Create AD account, provision email, order hardware.\n"
            "Day 1 Morning: Laptop setup — join domain, install required software from SCCM/Jamf.\n"
            "Software bundle standard: Office 365, Slack, Zoom, Chrome, 1Password, VPN client, antivirus.\n"
            "Access provisioning: Add to department security groups, provision Jira/Confluence, GitHub org invite.\n"
            "MFA setup: Enroll in Okta, configure Microsoft Authenticator.\n"
            "Compliance: Complete security awareness training (mandatory within 48h).\n"
            "Checklist template: https://wiki.company.com/it/onboarding-checklist"
        ),
    },
    {
        "source": "runbook/email-delivery-failure",
        "text": (
            "Runbook: Email Delivery Failure\n"
            "Symptoms: Users report emails not sending, bouncing, or being marked as spam.\n"
            "Step 1: Check Exchange/Google Workspace mail queue for stuck messages.\n"
            "Step 2: Verify SPF, DKIM, and DMARC records are correct — `dig TXT company.com`\n"
            "Step 3: Check if company IP is on a blacklist — https://mxtoolbox.com/blacklists.aspx\n"
            "Step 4: Check mail server logs for bounce codes (550 = user not found, 421 = temp failure).\n"
            "Step 5: For Office 365 — check Message Trace in Exchange Admin Center.\n"
            "Step 6: Contact Microsoft/Google support if platform-wide issue confirmed."
        ),
    },
    {
        "source": "runbook/api-latency-spike",
        "text": (
            "Runbook: API Latency Spike\n"
            "Symptoms: P95 latency > 2s, error rate increase, user complaints about slowness.\n"
            "Step 1: Check APM dashboard (Datadog/New Relic) — identify slowest endpoints.\n"
            "Step 2: Check downstream dependencies — DB, cache, external APIs. Which is slow?\n"
            "Step 3: Check Redis cache hit rate — if low (<70%), cache may be cold after restart.\n"
            "Step 4: Check for N+1 query problems — look for endpoints with 100+ DB queries per request.\n"
            "Step 5: Enable feature flag to shed load — disable non-critical background jobs.\n"
            "Step 6: Scale API servers if CPU/memory bound — adjust auto-scaling min threshold.\n"
            "Step 7: Implement circuit breaker if a downstream service is causing cascading failures."
        ),
    },
]


async def seed_knowledge_base() -> int:
    """
    Embed all documents and upsert them into Qdrant.
    Returns the number of documents indexed.
    Idempotent — safe to call on every startup.
    """
    from app.services.qdrant_client import init_qdrant, upsert_documents
    from app.services.embeddings import embed_documents

    # Ensure collection exists
    ok = await init_qdrant()
    if not ok:
        print("[Seeder] Qdrant unavailable — skipping knowledge base seed.")
        return 0

    texts = [doc["text"] for doc in KNOWLEDGE_DOCUMENTS]

    print(f"[Seeder] Embedding {len(texts)} knowledge base documents...")
    embeddings = embed_documents(texts)

    success = await upsert_documents(KNOWLEDGE_DOCUMENTS, embeddings)
    if success:
        print(f"[Seeder] ✅ Knowledge base seeded — {len(KNOWLEDGE_DOCUMENTS)} documents indexed.")
        return len(KNOWLEDGE_DOCUMENTS)
    else:
        print("[Seeder] ❌ Upsert failed.")
        return 0


if __name__ == "__main__":
    asyncio.run(seed_knowledge_base())
