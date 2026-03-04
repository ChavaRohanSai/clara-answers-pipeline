# Clara Answers — Automation Pipeline

Converts demo and onboarding call transcripts into versioned Retell AI voice agent configurations.

---

## How It Works

```
demo_transcript.txt
       │
       ▼
  Pipeline A
       │
       ├──▶ outputs/accounts/<id>/v1/account_memo.json   ← structured business data
       └──▶ outputs/accounts/<id>/v1/agent_spec.json     ← full Retell agent config + prompt

onboarding_transcript.txt
       │
       ▼
  Pipeline B
       │
       ├──▶ outputs/accounts/<id>/v2/account_memo.json   ← updated data
       ├──▶ outputs/accounts/<id>/v2/agent_spec.json     ← regenerated config
       └──▶ outputs/accounts/<id>/changelog.md           ← field-by-field diff
```

---

## Setup

### 1. Install dependencies
```bash
pip install requests
```

### 2. Set your API key (zero-cost: use Claude free tier key)
```bash
export ANTHROPIC_API_KEY=your_key_here
```

Get a free API key at: https://console.anthropic.com

---

## Run

### Single demo call → v1
```bash
python scripts/pipeline.py demo dataset/demo/bens-electric.txt
```

### Single onboarding → v2
```bash
python scripts/pipeline.py onboard dataset/onboarding/bens-electric.txt bens-electric-001
```

### Batch (all 10 files at once)
```bash
python scripts/pipeline.py batch dataset/
```

### List all processed accounts
```bash
python scripts/pipeline.py list
```

---

## Dataset Folder Structure

```
dataset/
  demo/
    bens-electric.txt
    company-two.txt
    ...
  onboarding/
    bens-electric.txt     ← same slug as demo file
    company-two.txt
    ...
```

---

## Output Structure

```
outputs/
  accounts/
    bens-electric-001/
      v1/
        account_memo.json   ← extracted from demo call
        agent_spec.json     ← generated Retell config v1
      v2/
        account_memo.json   ← updated from onboarding
        agent_spec.json     ← regenerated Retell config v2
      changelog.md          ← human-readable diff
      changelog.json        ← machine-readable diff
  _batch_summary.json       ← created after batch run
```

---

## Dashboard (Bonus UI)

Open `dashboard.html` in any modern browser.
Click **Load outputs/ folder** and select the `outputs/` directory.

Features:
- View all accounts in sidebar
- Overview tab: business info, hours, routing, services
- Agent Prompt tab: full system prompt
- Changelog tab: field-by-field v1→v2 diff
- Unknowns tab: open questions flagged during extraction

---

## How to Import into Retell (Manual)

Since Retell free tier does not expose programmatic agent creation:

1. Log in at [retell.ai](https://retell.ai)
2. Create a new Agent
3. Copy `system_prompt` from `agent_spec.json`
4. Paste into the agent's system prompt field
5. Set the transfer number from `call_transfer_protocol.emergency_number`
6. Set voice, language, timezone from `key_variables`
7. Save and test by calling the agent's phone number

---

## Key Design Decisions

| Decision | Reason |
|---|---|
| Separate v1/v2 folders | Clean version history, never overwrite |
| `questions_or_unknowns` field | Explicit about missing data — no hallucination |
| `confirmed: false` on business hours in v1 | Demo calls rarely confirm exact hours |
| Idempotent runs | Running pipeline twice produces same output |
| Batch summary JSON | Easy to see which accounts succeeded/failed |
| Diff at field level | Precise changelog, not just "things changed" |

---

## Known Limitations

- Jobber integration not yet live for Ben's Electric — CRM sync is manual until Retell-Jobber integration ships
- Transfer timeout values marked null until confirmed in onboarding
- Batch runner requires matching filenames between demo/ and onboarding/

---

## What Would Improve in Production

- Webhook from Fireflies → auto-trigger Pipeline A when transcript is ready
- Retell API integration → auto-create/update agents programmatically
- Supabase for storage instead of flat JSON files
- Asana task auto-creation on Pipeline A completion
- Confidence scores on extracted fields
- Multi-language transcript support
