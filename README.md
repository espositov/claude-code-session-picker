# Claude Code Session Picker 


A terminal UI for browsing your **Claude Code** sessions, skimming AI‑generated summaries, and reopening a session with a single keystroke.

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
| Node.js | 18 or newer |
| Claude Code CLI | `npm install -g @anthropic-ai/claude-code` |
| Python | 3.6 or newer |
| platformdirs (Python) | `pip install platformdirs` |

---

## ⚡ Installation

```bash
# 1. Clone the repository
git clone https://github.com/espositov/claude-session-picker.git
cd claude-session-picker

# 2. Make executable and install globally
chmod +x claude-session-picker.py
sudo ln -s "$(pwd)/claude-session-picker.py" /usr/local/bin/claude-session-picker
sudo ln -s "$(pwd)/claude-session-picker.py" /usr/local/bin/cc-picker

# 3. Install dependencies
npm install -g @anthropic-ai/claude-code   # Node 18+ required
pip install platformdirs                  # Python helper for config paths
```

Now you can run `claude-session-picker` or `cc-picker` from anywhere!

---

## 🚀 Usage

```bash
claude-session-picker
# or use the short version:
cc-picker
```

### First Run Setup
1. **Auto-detection**: Script looks for `~/.claude/projects`
2. **Manual setup**: If not found, you'll be prompted:
   ```
   Default Claude projects directory not found.
   Enter path to Claude projects directory: /your/custom/path
   Session summaries directory [/Users/you/.claude/Session Summaries]: 
   ```
3. **Config saved**: Settings stored in OS-appropriate config directory

### Everyday Workflow

**Step 1: Select Project**
```
================================================================================
SELECT PROJECT DIRECTORY  
================================================================================
 1. my-app
    15 sessions • Jun 04, 2025 at 03:12 PM
 2. website-redesign  
    8 sessions • Jun 03, 2025 at 02:21 PM
 3. data-analysis
    23 sessions • Jun 02, 2025 at 08:14 PM

Select project (1-3) or 'q' to quit: 1
```

**Step 2: Browse Sessions**
```
================================================================================
CLAUDE CODE SESSION PICKER
================================================================================
```
*(See example output below for the full session display)*

**Step 3: Launch Session**
```
Select session (1-15) or 'q' to quit: 3

Launching Claude Code session in: /Users/you/my-app
Session ID: 'abc123def456...'
```

---

## 🔍 How it works

| Stage | What it does |
|-------|-------------|
| Scan | Finds all .jsonl files under the projects folder |
| Summarise | Sends trimmed convo snippets to claude CLI; caches result |
| Cache | Per‑project JSON cache lives in Session Summaries/ |
| Launch | Runs claude -r <session_id> inside the correct directory |

---

## ⚙️ Configuration

```json
// config.json (auto‑generated)
{
  "claude_projects_dir": "/Users/you/.claude/projects",
  "session_summaries_dir": "/Users/you/.claude/Session Summaries"
}
```

Delete this file to rerun the wizard.

---

## 🪄 Example Session Display

```
================================================================================
CLAUDE CODE SESSION PICKER
================================================================================

┌──────────────────────────────────────────────────────────────────────────────┐
│ 1. Jun 04, 3:12 PM │ my-app │ 24 msgs │ abc123def456…                      │
├──────────────────────────────────────────────────────────────────────────────┤
│ Summary: Created Python script                                               │
│ • Fixed API authentication errors                                            │
│ • Added response caching system                                              │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ 2. Jun 03, 2:45 PM │ my-app │ 18 msgs │ def789ghi012…                      │
├──────────────────────────────────────────────────────────────────────────────┤
│ Summary: Database optimization                                               │
│ • Implemented connection pooling                                             │
│ • Added query performance monitoring                                         │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ 3. Jun 02, 8:14 PM │ my-app │ 31 msgs │ ghi345jkl678…                      │
├──────────────────────────────────────────────────────────────────────────────┤
│ Summary: UI component refactoring                                            │
│ • Migrated to TypeScript                                                     │
│ • Created reusable button components                                         │
└──────────────────────────────────────────────────────────────────────────────┘

Select session (1-3) or 'q' to quit: 
```

---

## 🚑 Troubleshooting

| Problem | Fix |
|---------|-----|
| "Claude CLI not found" | `pip install claude-cli` |
| "No sessions found" | Confirm claude_projects_dir path and that .jsonl logs exist |
| Permission denied | Ensure read/write access to the projects and summaries dirs |

---

## 🤝 Contributing

Pull requests and issues welcome! Please run ruff / black before opening a PR.
