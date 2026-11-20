# Instagram Reel Individual Profile Investigation Agent
> **Autonomous Visual Computer-Use Assistant Operating Inside Your Existing Chrome Session**

---

## 1. Overview & Mission

This agent is an autonomous visual computer-use investigator engineered to assist operators analyzing Instagram Reels. 

The operator retains **100% control over scrolling and Reel discovery**. Once you scroll to a Reel and pause for **15 seconds**, the agent automatically takes over to:
1. Capture context and a fresh screenshot of the Reel.
2. Open the comments section.
3. Investigate commenters **individually, one by one**.
4. Open each commenter's profile directly to inspect public/private status, bio information, and technical direct-messaging availability.
5. Apply the **Decision Engine** (powered by **Groq Llama-3.3-70B**, with local **Ollama** and deterministic rule fallbacks).
6. Distinguish strictly between **technical message availability** and **explicit DM consent**.
7. If and only if a prospect is **`ELIGIBLE`**, synthesize **one single personalized question** (< 25 words, max 1 question mark) referencing their comment.
8. Safely return to the original Reel, reopen comments if needed, and proceed to the next commenter.
9. Close comments when done and await the user's next manual scroll.

> [!IMPORTANT]
> **Zero Unsolicited Messaging & Human-in-the-Loop**: The agent **never** sends unsolicited DMs or automated mass messages. All eligible leads and their prepared questions are deposited into an operator review queue (`session_data/queue.json`) accessible via `python ui/cli.py`.

---

## 2. Operating Loop

```
USER SCROLLS REELS
        ↓
WAIT 15 SECONDS (Cooldown & Debounce)
        ↓
CAPTURE REEL SCREENSHOT & CONTEXT
        ↓
OPEN REEL COMMENTS
        ↓
READ COMMENT INDIVIDUALLY
        ↓
OPEN COMMENTER PROFILE (Mandatory Step)
        ↓
INSPECT PROFILE (Public/Private, Bio, Msg Button, Restrictions)
        ↓
DECISION ENGINE (Groq / Ollama / Deterministic Fallback)
        ↓
ELIGIBLE? ──► YES ──► SYNTHESIZE 1 PERSONALIZED QUESTION ──► ADD TO QUEUE
        │
       NO ──► RECORD REASON (Interested / Unavailable / DNC)
        ↓
RETURN TO ORIGINAL REEL & REOPEN COMMENTS
        ↓
INVESTIGATE NEXT UNPROCESSED COMMENTER
        ↓
ALL ACCESSIBLE COMMENTS INSPECTED?
        ↓
CLOSE COMMENTS & RESTORE REEL VIEW
        ↓
WAIT FOR USER TO SCROLL TO NEXT REEL
```

---

## 3. Quick Start Guide

### Step 1: Launch Chrome with Remote Debugging (Preserves Session)
To reuse your active Instagram login, cookies, and tabs without opening secondary windows:

**Option A (Windows Batch):**
Double-click `launch_chrome.bat` or run:
```cmd
launch_chrome.bat
```

**Option B (PowerShell):**
```powershell
.\launch_chrome.ps1
```
*This launches your installed Google Chrome listening on `http://127.0.0.1:9222`, restoring your existing user profile (`%LOCALAPPDATA%\Google\Chrome\User Data`). You stay logged in to Instagram!*

---

### Step 2: Configure Environment (Optional)
Copy `.env.example` to `.env`:
```cmd
copy .env.example .env
```
Edit `.env` to configure your LLM providers:
```ini
# Primary: Groq API (Ultra-fast Llama-3.3-70B / Llama-3.1-8B)
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile

# Fallback 1: Local Ollama (Set to true if Ollama is running)
OLLAMA_ENABLED=false
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3:latest

# Fallback 2: The deterministic rule engine is ALWAYS active and needs no API keys!
```

---

### Step 3: Start the Agent
```bash
python main.py
```
1. The agent connects to your open Chrome window via CDP.
2. Browse to Instagram Reels (`https://www.instagram.com/reels/`).
3. Whenever you pause on a Reel for 3.5 seconds (configurable via `REEL_COOLDOWN_SECONDS`), the agent begins its systematic profile investigation.

---

### Step 4: Review Leads & Prepared Questions
Open a separate terminal window at any time to inspect eligible prospects and approve questions:
```bash
python ui/cli.py
```

---

## 4. Decision Engine Classification Taxonomy

| Decision Classification | Criteria | Action Taken |
| :--- | :--- | :--- |
| **`ELIGIBLE`** | Commenter explicitly welcomes a private message ("DM me", "send info to inbox"), Message button is visible, and platform permits interaction. | Generates 1 concise personalized question and queues for review. |
| **`INTERESTED_BUT_NO_PERMISSION`** | Commenter asks for price or expresses interest ("How much is this?", "Link?"), but did **not** explicitly invite a DM. | Logged in CSV and stats; no DM prepared (respects user privacy). |
| **`NOT_INTERESTED`** | Casual engagement ("Cool video", "🔥", "Nice"), emoji-only comments, or unrelated remarks. | Logged as not interested. |
| **`UNAVAILABLE`** | Profile cannot be opened, or Instagram does not provide a Message button / restricts messaging. | Marked unavailable in session report. |
| **`DO_NOT_CONTACT`** | Commenter explicitly refuses messages ("Don't DM me", "Stop messaging", "No DMs"). | Added to persistent exclusion list. |
| **`UNCERTAIN`** | Insufficient context to determine intent. | Marked for human review. |

---

## 5. The One-Question Rule

For every **`ELIGIBLE`** prospect:
- **Strictly 1 question**: Maximum 1 question mark (`?`). Never asks multiple or compound questions.
- **Concise & natural**: Under 25 words, zero marketing buzzwords, directly addressing what they mentioned in their comment.
- **Example**:
  - *Comment*: "DM me the pricing and setup details please."
  - *Question*: *"Hey! Happy to share the pricing—are you looking for individual or team options?"*

---

## 6. Directory Structure & Generated Files

```
INSTA-reel-comment-auto/
├── config/
│   ├── settings.py             # Agent settings, delays, timeouts, and API keys
│   └── selectors.json          # Multi-layer fallback Instagram DOM selectors
├── core/
│   ├── browser_controller.py   # CDP connection to running Chrome session
│   ├── reel_detector.py        # 15s scroll cooldown monitor and context extractor
│   ├── comment_reader.py       # Comments drawer reader and commenter clicker
│   ├── profile_inspector.py    # Profile visitor, private/message button inspector
│   └── decision_engine.py      # Multi-tier intent analysis and 1-question rule
├── models/
│   ├── schemas.py              # Pydantic data schemas
│   └── classifier.py           # Groq API + Ollama fallback + Rule engine
├── storage/
│   ├── session_logger.py       # Session stats, CSV exporter, queue manager
│   └── state_manager.py        # Deduplication cache for usernames and reels
├── ui/
│   ├── dashboard.py            # Rich terminal tables and live stats
│   └── cli.py                  # Operator review queue command
├── session_data/
│   ├── screenshots/            # Screenshots of inspected Reels and profiles
│   ├── processed_cache.json    # Deduplication memory across sessions
│   ├── session_leads.csv       # Spreadsheet of all analyzed comments
│   ├── session_report.json     # Statistics covering all 10 required metrics
│   └── queue.json              # Review queue for ELIGIBLE leads
├── launch_chrome.bat           # 1-Click Windows Batch launcher with port 9222
├── launch_chrome.ps1           # 1-Click PowerShell launcher with port 9222
├── main.py                     # Primary agent execution loop
├── test_sync.py                # Standalone scenario verification suite
└── requirements.txt            # Dependencies
```

---

## 7. Verification

Run the comprehensive scenario verification test:
```bash
python test_sync.py
```
This tests:
1. Explicit DM invitations with visible message buttons (`ELIGIBLE` + 1 question).
2. Info requests without permission (`INTERESTED_BUT_NO_PERMISSION`).
3. Explicit DM refusals (`DO_NOT_CONTACT`).
4. Missing or locked message buttons (`UNAVAILABLE`).
5. Deduplication and persistence across session restarts.
6. All 10 session statistics metrics.

