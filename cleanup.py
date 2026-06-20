import sqlite3, os

DB = r'C:\Users\tejak\Downloads\AI_Operations_Center\backend\ai_ops.db'
UID = r'C:\Users\tejak\Downloads\AI_Operations_Center\backend\processed_uids.json'

with sqlite3.connect(DB) as conn:
    # Show current state
    cur = conn.execute("SELECT COUNT(*), priority, kanban_status FROM processed_emails GROUP BY priority, kanban_status")
    print("=== Current DB State ===")
    for row in cur.fetchall():
        print(f"  {row[0]:3d} x {row[1]} | {row[2]}")

    # Delete stale test data
    cur2 = conn.execute(
        "DELETE FROM processed_emails WHERE subject LIKE ? OR ticket_key LIKE ? OR subject LIKE ?",
        ('%Post-Mortem%', 'MOCK-%', '%Re: 📄%')
    )
    conn.commit()
    print(f"\nDeleted {cur2.rowcount} stale records")

    cur3 = conn.execute("SELECT COUNT(*) FROM processed_emails")
    print(f"Remaining: {cur3.fetchone()[0]} records")

# Reset UID cache
if os.path.exists(UID):
    os.remove(UID)
    print("UID cache cleared — poller will re-check inbox on next poll")
print("Done!")
