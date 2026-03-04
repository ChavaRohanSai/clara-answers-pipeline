#!/usr/bin/env python3
"""
Clara Answers Automation Pipeline
==================================
Pipeline A : demo transcript  -> account_memo v1 + agent_spec v1
Pipeline B : onboarding input -> account_memo v2 + agent_spec v2 + changelog

Usage
-----
  python pipeline.py demo     <transcript.txt> [--company "Name"]
  python pipeline.py onboard  <onboarding.txt> <account_id>
  python pipeline.py batch    <dataset_dir>
  python pipeline.py list

Zero-cost LLM: uses Hugging Face Inference API (free, no billing required).
Set GROQ_API_KEY environment variable with your Hugging Face token.
"""

import json, os, sys, datetime, logging, argparse, re
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = BASE_DIR / "outputs" / "accounts"
LOGS_DIR    = BASE_DIR / "logs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
log_file = LOGS_DIR / f"pipeline_{datetime.date.today()}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("clara")

# ── Hugging Face Inference API ─────────────────────────────────────────────────
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

def call_claude(system: str, user: str, max_tokens: int = 4096) -> str:
    """
    Call Hugging Face Inference API (free tier).
    Requires GROQ_API_KEY env var — get free token at huggingface.co/settings/tokens
    Function kept as call_claude for compatibility but uses HF under the hood.
    """
    try:
        import requests
    except ImportError:
        raise RuntimeError("requests not installed. Run: pip install requests")

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY not set. Run: set GROQ_API_KEY=hf_your_token_here\n"
            "Get a free key at: https://console.groq.com"
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }

    # Retry up to 3 times (model may be loading)
    for attempt in range(3):
        try:
            resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=120)
            if resp.status_code == 503:
                log.warning(f"Model loading, waiting 20s... (attempt {attempt+1}/3)")
                import time; time.sleep(20)
                continue
            if resp.status_code != 200:
                raise RuntimeError(f"API error {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            if attempt == 2:
                raise
            log.warning(f"Attempt {attempt+1} failed: {e}. Retrying...")
            import time; time.sleep(10)

    raise RuntimeError("All retry attempts failed")


def safe_json(raw: str) -> dict:
    """Strip markdown fences and parse JSON. Raises ValueError if parse fails."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse failed: {e}\nRaw:\n{raw[:500]}")


# ── Utilities ─────────────────────────────────────────────────────────────────
def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"['\"]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")

def make_account_id(company_name: str) -> str:
    return slugify(company_name) + "-001"

def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    log.info(f"Saved: {path}")

def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)

def diff_dicts(old: dict, new: dict, path: str = "") -> list:
    """Recursively diff two dicts. Returns list of change records."""
    changes = []
    for key in set(list(old) + list(new)):
        fk = f"{path}.{key}" if path else key
        if key not in old:
            changes.append({"field": fk, "type": "ADDED",   "old": None,      "new": new[key]})
        elif key not in new:
            changes.append({"field": fk, "type": "REMOVED", "old": old[key],  "new": None})
        elif isinstance(old[key], dict) and isinstance(new[key], dict):
            changes.extend(diff_dicts(old[key], new[key], fk))
        elif old[key] != new[key]:
            changes.append({"field": fk, "type": "UPDATED", "old": old[key],  "new": new[key]})
    return changes


# ── Prompts ───────────────────────────────────────────────────────────────────

DEMO_SYSTEM = """
You are a structured data extractor for Clara Answers — an AI voice agent platform for trade businesses (electrical, HVAC, plumbing, fire protection, etc).

INPUT: A demo call transcript between a Clara salesperson and a potential client.

YOUR TASK: Extract ONLY facts that are EXPLICITLY stated in the transcript. 
- Do NOT invent, assume, or infer details not clearly spoken.
- Do NOT fill in business hours, phone numbers, or routing logic unless stated.
- If information is missing or ambiguous, add it to questions_or_unknowns.
- Return ONLY a valid JSON object. No markdown, no explanation, no preamble.

SCHEMA (use exactly these field names, null for missing values):
{
  "account_id": "<slugified-company-name>-001",
  "version": "v1",
  "source": "demo_call",
  "extracted_at": "<YYYY-MM-DD>",
  "company_name": "<string or null>",
  "primary_contact": {
    "name": "<string or null>",
    "role": "<string or null>",
    "email": "<string or null>",
    "phone": "<string or null>"
  },
  "secondary_contact": {
    "name": "<string or null>",
    "role": "<string or null>",
    "email": "<string or null>",
    "phone": "<string or null>",
    "note": "<string or null>"
  },
  "business_info": {
    "industry": "<string or null>",
    "years_in_business": "<number or null>",
    "entity_type": "<string or null>",
    "location": "<city, state/province, country or null>",
    "billing_address": "<full address or null>",
    "crm": "<software name or null>",
    "team_size": "<description or null>"
  },
  "services_supported": ["<only services explicitly mentioned>"],
  "services_not_supported": ["<only services explicitly excluded>"],
  "business_hours": {
    "days": "<e.g. Monday-Friday or null>",
    "start": "<HH:MM AM/PM or null>",
    "end": "<HH:MM AM/PM or null>",
    "timezone": "<IANA tz string or null>",
    "confirmed": false,
    "note": "<any caveats or null>"
  },
  "call_volume_estimate": "<string or null>",
  "emergency_definition": ["<explicit emergency triggers only>"],
  "emergency_routing_rules": {
    "primary_contact": "<name + number or null>",
    "secondary_contact": "<name + number or null>",
    "fallback": "<description or null>",
    "note": "<string or null>"
  },
  "non_emergency_routing_rules": {
    "during_hours": "<description or null>",
    "after_hours": "<description or null>",
    "booking_flow": "<description or null>"
  },
  "call_transfer_rules": {
    "timeout_seconds": null,
    "retries": null,
    "on_fail_message": "<string or null>",
    "vip_bypass_numbers": "<description or null>",
    "screening_exceptions": "<description or null>"
  },
  "integration_constraints": ["<explicit constraints only>"],
  "after_hours_flow_summary": "<1-2 sentences or null>",
  "office_hours_flow_summary": "<1-2 sentences or null>",
  "questions_or_unknowns": ["<list every genuinely missing required field>"],
  "notes": "<brief account summary>"
}
""".strip()


ONBOARDING_SYSTEM = """
You are a configuration update specialist for Clara Answers.

You will receive:
1. An existing v1 account memo (JSON)
2. New onboarding input (transcript or form data)

YOUR TASK: Produce an updated v2 account memo.

STRICT RULES:
- Keep ALL v1 fields that are not mentioned in onboarding input (do not drop them)
- Only UPDATE fields where onboarding explicitly provides new/confirmed data
- If onboarding CONFIRMS a v1 assumption, mark business_hours.confirmed = true
- If onboarding CONTRADICTS a v1 field, update and note the conflict in notes
- Remove items from questions_or_unknowns that are now answered
- Add new questions_or_unknowns if new gaps appear
- Set version = "v2", source = "onboarding_call"
- Return ONLY valid JSON using the same schema. No markdown, no explanation.
""".strip()


AGENT_SPEC_SYSTEM = """
You are a Retell voice agent configuration expert for Clara Answers.

Given an account memo JSON, generate a production-ready Retell agent spec.

MANDATORY RULES:
1. system_prompt MUST include both flows in full detail:

   BUSINESS HOURS FLOW:
   - Greeting (warm, uses company name)
   - Ask purpose of call
   - Collect: name, then phone number (one question at a time)
   - Route or transfer based on call type
   - If transfer fails: apologize, confirm details captured, assure callback
   - Ask: "Is there anything else I can help you with?"
   - Close call warmly

   AFTER-HOURS FLOW:
   - Greeting (acknowledges after hours)
   - Ask purpose
   - Confirm if emergency
   - IF EMERGENCY: collect name -> phone -> address immediately -> attempt transfer -> if fails: apologize + assure urgent followup
   - IF NON-EMERGENCY: collect name, phone, issue details, preferred callback time -> confirm next-business-day followup
   - Ask: "Is there anything else I can help you with?"
   - Close warmly

2. Never mention "function calls", "tools", "backend", or "API" to callers
3. Never auto-confirm appointments — only collect preferences
4. Ask one question at a time — never stack multiple questions
5. Use null for any field not confirmed in the memo (do not invent values)
6. Return ONLY valid JSON. No markdown, no explanation.

SCHEMA:
{
  "agent_name": "<Company Name> - Clara",
  "version": "<v1 or v2>",
  "source": "<demo_call or onboarding_call>",
  "generated_at": "<YYYY-MM-DD>",
  "account_id": "<string>",
  "voice_style": {
    "tone": "professional and warm",
    "speed": "normal",
    "language": "<English or as appropriate>",
    "persona": "Clara, AI receptionist for <Company Name>"
  },
  "key_variables": {
    "company_name": "<string>",
    "owner_name": "<string or null>",
    "emergency_transfer_number": "<string or null>",
    "business_hours_start": "<string or null>",
    "business_hours_end": "<string or null>",
    "business_hours_days": "<string or null>",
    "timezone": "<string or null>",
    "location": "<string or null>",
    "crm": "<string or null>"
  },
  "system_prompt": "<complete system prompt — must include both flows as specified>",
  "call_transfer_protocol": {
    "emergency_number": "<string or null>",
    "standard_number": "<string or null>",
    "when_to_transfer": ["<explicit trigger list>"],
    "transfer_announcement": "<what Clara says before transferring>",
    "timeout_seconds": "<number or null>",
    "on_transfer_fail": "<exact words Clara says>"
  },
  "fallback_protocol": {
    "trigger": "transfer fails or no answer",
    "action": "log call, flag urgency, notify via email+SMS",
    "caller_message": "<exact words Clara says>"
  },
  "spam_handling": {
    "enabled": true,
    "detection": "sales calls, telemarketers, irrelevant callers",
    "response": "<exact words Clara says to end spam calls>"
  },
  "vip_bypass": {
    "enabled": "<true if any VIPs mentioned, else false>",
    "numbers": "<list or null>",
    "behavior": "<description>"
  },
  "crm_integration": {
    "platform": "<string or null>",
    "status": "<live / in_progress / not_configured>",
    "constraints": ["<list from memo>"],
    "current_behavior": "<what Clara does now>",
    "future_behavior": "<what will happen when integration is live>"
  }
}
""".strip()



# ── Task Tracker ──────────────────────────────────────────────────────────────

def log_task(account_id: str, pipeline: str, status: str, notes: str = ""):
    """Log a task entry to _tasks.json (free alternative to Asana)."""
    tasks_file = OUTPUTS_DIR.parent / "_tasks.json"
    tasks = []
    try:
        if tasks_file.exists():
            tasks = json.loads(tasks_file.read_text(encoding="utf-8"))
    except Exception:
        tasks = []

    # Check if task already exists (idempotent)
    existing = next((t for t in tasks if t["account_id"] == account_id and t["pipeline"] == pipeline), None)
    entry = {
        "account_id":  account_id,
        "pipeline":    pipeline,
        "status":      status,
        "updated_at":  datetime.datetime.now().isoformat(),
        "notes":       notes
    }
    if existing:
        tasks[tasks.index(existing)] = entry
    else:
        tasks.append(entry)

    tasks_file.write_text(json.dumps(tasks, indent=2), encoding="utf-8")
    log.info(f"[TASK LOGGED] {account_id} | {pipeline} | {status}")

# ── Pipeline A ────────────────────────────────────────────────────────────────

def truncate_transcript(text: str, max_chars: int = 6000) -> str:
    """Truncate transcript to fit free tier token limits (Groq: ~8000 tokens)."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_period = truncated.rfind('.')
    if last_period > max_chars * 0.8:
        truncated = truncated[:last_period + 1]
    log.warning(f"Transcript truncated from {len(text)} to {len(truncated)} chars to fit token limit")
    return truncated + "\n\n[TRANSCRIPT TRUNCATED — extract what you can from above]"


def pipeline_a(transcript: str, company_hint: str = None) -> dict:
    """Demo transcript -> v1 account memo + v1 agent spec."""
    today = datetime.date.today().isoformat()
    log.info("=== PIPELINE A START ===")

    # Truncate to fit free tier limits
    transcript = truncate_transcript(transcript)

    # Step 1: Extract memo
    log.info("Step 1/2: Extracting account memo from demo transcript...")
    raw = call_claude(DEMO_SYSTEM, f"Date: {today}\n\nTRANSCRIPT:\n{transcript}")
    memo = safe_json(raw)

    # Ensure account_id
    if not memo.get("account_id"):
        name = memo.get("company_name") or company_hint or "unknown-company"
        memo["account_id"] = make_account_id(name)
    memo["extracted_at"] = today

    account_id = memo["account_id"]
    log.info(f"Account ID: {account_id}")
    log.info(f"Unknowns flagged: {len(memo.get('questions_or_unknowns', []))}")

    # Step 2: Generate agent spec
    log.info("Step 2/2: Generating agent spec v1...")
    raw2 = call_claude(AGENT_SPEC_SYSTEM, f"Date: {today}\n\nACCOUNT MEMO:\n{json.dumps(memo, indent=2)}")
    spec = safe_json(raw2)
    spec["version"]    = "v1"
    spec["account_id"] = account_id
    spec["generated_at"] = today

    # Save
    out = OUTPUTS_DIR / account_id / "v1"
    save_json(out / "account_memo.json", memo)
    save_json(out / "agent_spec.json",   spec)
    log_task(account_id, "Pipeline_A", "v1_complete", f"Unknowns: {len(memo.get('questions_or_unknowns', []))}")
    log.info(f"=== PIPELINE A COMPLETE: {account_id} ===")
    return {"account_id": account_id, "memo": memo, "spec": spec}


# ── Pipeline B ────────────────────────────────────────────────────────────────

def pipeline_b(onboarding_text: str, account_id: str) -> dict:
    """Onboarding input -> v2 memo + v2 spec + changelog."""
    today = datetime.date.today().isoformat()
    log.info(f"=== PIPELINE B START: {account_id} ===")

    # Load v1
    v1_path = OUTPUTS_DIR / account_id / "v1" / "account_memo.json"
    if not v1_path.exists():
        raise FileNotFoundError(
            f"No v1 memo found at {v1_path}. Run Pipeline A first."
        )
    v1_memo = load_json(v1_path)
    log.info("Loaded v1 memo.")

    # Step 1: Merge onboarding into v2 memo
    log.info("Step 1/3: Merging onboarding data into v2 memo...")
    prompt = (
        f"Date: {today}\n\n"
        f"V1 ACCOUNT MEMO:\n{json.dumps(v1_memo, indent=2)}\n\n"
        f"ONBOARDING INPUT:\n{onboarding_text}"
    )
    raw = call_claude(ONBOARDING_SYSTEM, prompt)
    v2_memo = safe_json(raw)
    v2_memo["account_id"]   = account_id
    v2_memo["version"]      = "v2"
    v2_memo["extracted_at"] = today

    log.info(f"Unknowns remaining: {len(v2_memo.get('questions_or_unknowns', []))}")

    # Step 2: Regenerate agent spec
    log.info("Step 2/3: Regenerating agent spec v2...")
    raw2 = call_claude(AGENT_SPEC_SYSTEM, f"Date: {today}\n\nACCOUNT MEMO:\n{json.dumps(v2_memo, indent=2)}")
    v2_spec = safe_json(raw2)
    v2_spec["version"]     = "v2"
    v2_spec["account_id"]  = account_id
    v2_spec["generated_at"] = today

    # Step 3: Diff + changelog
    log.info("Step 3/3: Generating changelog...")
    changes = diff_dicts(v1_memo, v2_memo)
    resolved = [
        q for q in v1_memo.get("questions_or_unknowns", [])
        if q not in v2_memo.get("questions_or_unknowns", [])
    ]
    still_open = v2_memo.get("questions_or_unknowns", [])

    changelog = {
        "account_id":    account_id,
        "from_version":  "v1",
        "to_version":    "v2",
        "updated_at":    today,
        "source":        "onboarding_call",
        "total_changes": len(changes),
        "resolved_unknowns": resolved,
        "still_open_unknowns": still_open,
        "changes":       changes,
    }

    # Human-readable markdown changelog
    md  = f"# Changelog — {account_id}\n\n"
    md += f"**Date:** {today}  \n"
    md += f"**Transition:** v1 (demo call) -> v2 (onboarding)  \n"
    md += f"**Total field changes:** {len(changes)}  \n"
    md += f"**Unknowns resolved:** {len(resolved)}  \n"
    md += f"**Still open:** {len(still_open)}\n\n"

    if changes:
        md += "## Field Changes\n\n"
        for c in changes:
            md += f"### `{c['field']}` — {c['type']}\n"
            if c["type"] == "UPDATED":
                md += f"- **Before:** `{c['old']}`\n"
                md += f"- **After:**  `{c['new']}`\n\n"
            elif c["type"] == "ADDED":
                md += f"- **New value:** `{c['new']}`\n\n"
            elif c["type"] == "REMOVED":
                md += f"- **Removed:** `{c['old']}`\n\n"

    if resolved:
        md += "## Resolved Unknowns\n\n"
        for r in resolved:
            md += f"- [RESOLVED] {r}\n"
        md += "\n"

    if still_open:
        md += "## Still Open / Unknown\n\n"
        for r in still_open:
            md += f"- [OPEN] {r}\n"
        md += "\n"

    # Save everything
    v2_out = OUTPUTS_DIR / account_id / "v2"
    save_json(v2_out / "account_memo.json",                     v2_memo)
    save_json(v2_out / "agent_spec.json",                       v2_spec)
    save_json(OUTPUTS_DIR / account_id / "changelog.json",      changelog)
    (OUTPUTS_DIR / account_id / "changelog.md").write_text(md, encoding="utf-8")
    log.info(f"Saved changelog: {len(changes)} changes, {len(resolved)} resolved")
    log_task(account_id, "Pipeline_B", "v2_complete", f"Changes: {len(changes)}, Resolved: {len(resolved)}")
    log.info(f"=== PIPELINE B COMPLETE: {account_id} ===")

    return {
        "account_id": account_id,
        "memo_v2":    v2_memo,
        "spec_v2":    v2_spec,
        "changelog":  changelog,
    }


# ── Batch Runner ──────────────────────────────────────────────────────────────

def run_batch(dataset_dir: str):
    """
    Run Pipeline A + B on all accounts in dataset_dir.

    dataset_dir/
      demo/        <company-slug>.txt   (one file per company)
      onboarding/  <company-slug>.txt   (optional, same slug as demo)
    """
    ds = Path(dataset_dir)
    demo_dir  = ds / "demo"
    onb_dir   = ds / "onboarding"

    if not demo_dir.exists():
        log.error(f"No demo/ folder found in {dataset_dir}")
        return []

    results = []
    files = sorted(demo_dir.glob("*.txt"))
    log.info(f"Batch: found {len(files)} demo file(s)")

    for f in files:
        slug = f.stem
        log.info(f"\n{'='*60}\nProcessing: {slug}\n{'='*60}")

        try:
            transcript = f.read_text(encoding="utf-8")
            result_a   = pipeline_a(transcript, slug)
            account_id = result_a["account_id"]
            status     = "v1"

            onb_file = onb_dir / f"{slug}.txt"
            if onb_file.exists():
                onb_text = onb_file.read_text(encoding="utf-8")
                pipeline_b(onb_text, account_id)
                status = "v1+v2"
            else:
                log.warning(f"No onboarding file for {slug} — v1 only")

            results.append({"slug": slug, "account_id": account_id, "status": status, "error": None})

        except Exception as e:
            log.error(f"Failed processing {slug}: {e}")
            results.append({"slug": slug, "account_id": None, "status": "ERROR", "error": str(e)})

    # Summary
    log.info("\n\n========== BATCH SUMMARY ==========")
    for r in results:
        icon = "[RESOLVED]" if r["status"] != "ERROR" else "❌"
        log.info(f"  {icon} {r['slug']:30s} {r['status']}")
        if r["error"]:
            log.info(f"     └─ {r['error']}")

    # Save run summary
    summary = {
        "run_at": datetime.datetime.now().isoformat(),
        "total": len(results),
        "success": sum(1 for r in results if r["status"] != "ERROR"),
        "errors":  sum(1 for r in results if r["status"] == "ERROR"),
        "accounts": results,
    }
    save_json(OUTPUTS_DIR / "_batch_summary.json", summary)
    return results


def list_accounts():
    """Print all processed accounts and their versions."""
    accounts = [d for d in OUTPUTS_DIR.iterdir() if d.is_dir() and not d.name.startswith("_")]
    if not accounts:
        print("No accounts processed yet.")
        return
    print(f"\n{'ACCOUNT ID':35s} {'VERSIONS':15s} UNKNOWNS")
    print("-" * 65)
    for acc in sorted(accounts):
        versions = []
        unknowns = "—"
        for v in ["v1", "v2"]:
            mp = acc / v / "account_memo.json"
            if mp.exists():
                versions.append(v)
                if v == "v2":
                    m = load_json(mp)
                    unknowns = str(len(m.get("questions_or_unknowns", [])))
        if not versions:
            continue
        print(f"{acc.name:35s} {', '.join(versions):15s} {unknowns} open question(s)")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Clara Answers Pipeline",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    pa = sub.add_parser("demo",    help="Pipeline A: demo transcript -> v1")
    pa.add_argument("file",        help="Path to demo transcript .txt")
    pa.add_argument("--company",   help="Override company name for account_id")

    pb = sub.add_parser("onboard", help="Pipeline B: onboarding -> v2")
    pb.add_argument("file",        help="Path to onboarding transcript .txt")
    pb.add_argument("account_id",  help="Account ID (from v1 output)")

    pbatch = sub.add_parser("batch", help="Batch: run all accounts in dataset dir")
    pbatch.add_argument("dir",       help="Dataset directory path")

    sub.add_parser("list", help="List all processed accounts")

    args = p.parse_args()

    if args.cmd == "demo":
        pipeline_a(Path(args.file).read_text(encoding="utf-8"), args.company)

    elif args.cmd == "onboard":
        pipeline_b(Path(args.file).read_text(encoding="utf-8"), args.account_id)

    elif args.cmd == "batch":
        run_batch(args.dir)

    elif args.cmd == "list":
        list_accounts()

    else:
        p.print_help()
