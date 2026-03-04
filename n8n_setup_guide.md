# n8n Workflow Setup Guide

## What This Workflow Does

- **Pipeline A** (triggered by `{transcript, company_name}`): demo transcript → v1 account memo + v1 agent spec
- **Pipeline B** (triggered by `{onboarding_text, account_id}`): onboarding transcript → v2 memo + v2 agent spec + changelog

Both pipelines auto-detect which mode to run based on the input shape.

---

## Step 1 — Run n8n Locally (Docker)

```bash
docker run -it --rm \
  --name n8n \
  -p 5678:5678 \
  -v ~/.n8n:/home/node/.n8n \
  -e ANTHROPIC_API_KEY=your_key_here \
  -e OUTPUTS_DIR=/home/node/.n8n/outputs \
  -e LOGS_DIR=/home/node/.n8n/logs \
  n8nio/n8n
```

Then open: http://localhost:5678

---

## Step 2 — Import the Workflow

1. In n8n, click **Workflows → Import from File**
2. Select `workflows/clara_pipeline_n8n.json`
3. Click **Save**

---

## Step 3 — Set Environment Variables

In Docker run command or n8n Settings → Environment:

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ Yes | Your Claude API key (free tier) |
| `OUTPUTS_DIR` | ✅ Yes | Where to save outputs (e.g. `/home/node/.n8n/outputs`) |
| `LOGS_DIR` | No | Log file location (defaults to `./logs`) |
| `GITHUB_TOKEN` | No | For GitHub Issues task tracker (optional) |
| `GITHUB_REPO` | No | e.g. `yourname/clara-pipeline` (optional) |

> **Zero-cost note:** `ANTHROPIC_API_KEY` on the free tier gives you enough credits to run all 10 transcripts. If you hit limits, use the Python script (`pipeline.py`) which is identical logic.

---

## Step 4 — Run Pipeline A (Demo Call)

Trigger the workflow manually with this JSON input:

```json
{
  "transcript": "<paste full demo transcript text here>",
  "company_name": "Ben's Electric Solutions"
}
```

**Output files created:**
```
outputs/accounts/bens-electric-solutions-001/v1/account_memo.json
outputs/accounts/bens-electric-solutions-001/v1/agent_spec.json
```

---

## Step 5 — Run Pipeline B (Onboarding)

Trigger with:

```json
{
  "onboarding_text": "<paste onboarding transcript or form data here>",
  "account_id": "bens-electric-solutions-001"
}
```

**Output files created:**
```
outputs/accounts/bens-electric-solutions-001/v2/account_memo.json
outputs/accounts/bens-electric-solutions-001/v2/agent_spec.json
outputs/accounts/bens-electric-solutions-001/changelog.md
outputs/accounts/bens-electric-solutions-001/changelog.json
```

---

## Step 6 — Batch Run (All 10 Files)

Use the Python batch runner (faster for bulk processing):

```bash
cd clara-pipeline
python scripts/pipeline.py batch dataset/
```

Or trigger n8n workflow multiple times via its REST API:

```bash
# Get your workflow ID from n8n UI
WORKFLOW_ID=your_workflow_id

for file in dataset/demo/*.txt; do
  company=$(basename "$file" .txt)
  transcript=$(cat "$file")
  curl -X POST http://localhost:5678/webhook/clara-pipeline \
    -H "Content-Type: application/json" \
    -d "{\"transcript\": \"$(echo $transcript | sed 's/"/\\"/g')\", \"company_name\": \"$company\"}"
  sleep 2
done
```

---

## Task Tracking

By default, completed runs are logged to `outputs/_tasks.json`.

To use GitHub Issues instead:
1. Set `GITHUB_TOKEN` (create at github.com/settings/tokens — free)
2. Set `GITHUB_REPO` to `yourname/repo`
3. Each pipeline run creates a GitHub Issue titled `[Clara] <account_id> — <status>`

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `JSON parse failed` | Claude returned markdown in response — the parser strips it automatically. If it persists, check the raw response in n8n execution logs |
| `No v1 memo found` | Run Pipeline A before Pipeline B for the same account_id |
| `API error 401` | Check your ANTHROPIC_API_KEY is set correctly |
| `API error 429` | Rate limited — wait 60s and retry. All nodes have built-in retry logic |
