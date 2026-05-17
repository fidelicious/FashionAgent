# Runbooks

Short procedures for specific failure modes. Each runbook follows the same
shape:

  1. **Symptom** — what you see when this is happening.
  2. **Diagnose** — commands to confirm root cause.
  3. **Fix** — minimal steps to restore service.
  4. **Prevent** — config or process change to reduce recurrence.

Look here when something specific has broken. For first-time setup or
"how does X work" questions, read [../../GUIDE.md](../../GUIDE.md) instead.

## Index

- [database-locked.md](database-locked.md) — `sqlite3.OperationalError: database is locked` in the logs.
- [daily-outfit-failed.md](daily-outfit-failed.md) — no Discord message at 7am.
- [discord-token-expired.md](discord-token-expired.md) — bot offline, can't reach the LLM, etc.
- [disk-full.md](disk-full.md) — hourly disk warning, or jobs failing with "no space left".
- [inbox-stuck.md](inbox-stuck.md) — files dropped in `inbox/` aren't being processed.
- [llm-unavailable.md](llm-unavailable.md) — Discord messages prefixed `[LLM fallback]`, or LLM tests timing out.
