# Claude Code Session Picker 


A terminal UI for browsing your **Claude Code** sessions, skimming AI‑generated summaries, and reopening a session with a single keystroke.

---

## ✨ Features

- **First‑run wizard** – auto‑detects Claude folders or lets you set custom paths  
- **AI summaries** – 2‑3‑bullet digests via Claude CLI  
- **Smart cache** – skips re‑summarising unchanged sessions  
- **Project filter** – sessions grouped by project directory  
- **One‑click launch** – jump straight back into the chosen chat  
- **Empty‑session cleanup** – detect & optionally delete zero‑message files  

---

## 🛠 Requirements

| Tool | Version |
|------|---------|
| Python | 3.6 or newer |
| [`claude-cli`](https://github.com/anthropic/claude-cli) | `pip install claude-cli` |
| Claude Code `.jsonl` session logs | (created automatically when you use Claude Code) |

---

## ⚡ Installation

```bash
# 1. Grab the script
curl -O https://raw.githubusercontent.com/<your‑github>/claude-session-picker/main/claude-session-picker.py
chmod +x claude-session-picker.py

# 2. Install dependencies
pip install claude-cli rich  # rich just makes the CLI output prettier

(Replace <your‑github> with your username once you push the repo.)

⸻

🚀 Usage

python3 claude-session-picker.py

First run
    1.    Script looks for ~/.claude/projects
    2.    If missing, you point it to your Claude projects folder
    3.    Session Summaries/ cache folder is created
    4.    Settings saved to config.json next to the script

Everyday flow
    1.    Pick a project
    2.    Browse nicely boxed sessions with AI blurbs
    3.    Press a number → session reopens in Claude Code

⸻

🔍 How it works

Stage    What it does
Scan    Finds all .jsonl files under the projects folder
Summarise    Sends trimmed convo snippets to claude CLI; caches result
Cache    Per‑project JSON cache lives in Session Summaries/
Launch    Runs claude -r <session_id> inside the correct directory


⸻

⚙️ Configuration

// config.json (auto‑generated)
{
  "claude_projects_dir": "/Users/you/.claude/projects",
  "session_summaries_dir": "/Users/you/.claude/Session Summaries"
}

Delete this file to rerun the wizard.

⸻

🪄 Example output

===============================================================================
CLAUDE CODE SESSION PICKER
===============================================================================

┌──────────────────────────────────────────────────────────────────────────────┐
│ 1. Mar 17, 2:30 PM │ my‑project │ 24 msgs │ abc123def456…                  │
├──────────────────────────────────────────────────────────────────────────────┤
│ Summary: Created Python script                                               │
│ • Fixed API errors                                                           │
│ • Added caching system                                                       │
└──────────────────────────────────────────────────────────────────────────────┘


⸻

🚑 Troubleshooting

Problem    Fix
“Claude CLI not found”    pip install claude-cli
“No sessions found”    Confirm claude_projects_dir path and that .jsonl logs exist
Permission denied    Ensure read/write access to the projects and summaries dirs


⸻

🤝 Contributing

Pull requests and issues welcome! Please run ruff / black before opening a PR.

