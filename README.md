# 📺 YouTube → Telegram Transcript Bot

Monitors YouTube channels for new uploads and sends the full transcript to your Telegram — automatically, every 5 minutes, for free via GitHub Actions.

**No OpenAI. No paid APIs. No server needed.**

---

## How It Works

```
Every 5 min (GitHub Actions)
  → Read channels.json
  → Fetch YouTube RSS feed for each channel
  → Check if latest video is already in posted.json
  → If new: fetch transcript → send to Telegram
  → Save video ID to posted.json
```

---

## Project Structure

```
ytbot-tg/
├── main.py              # The entire bot logic
├── channels.json        # Your list of YouTube channels to monitor
├── posted.json          # Auto-updated: tracks already-sent videos
├── requirements.txt     # 3 dependencies only
├── .env.example         # Template for local testing
├── .gitignore
├── .github/
│   └── workflows/
│       └── bot.yml      # GitHub Actions: runs every 5 minutes
└── README.md
```

---

## Setup (5 steps)

### Step 1 — Create a Telegram Bot

1. Open Telegram and message **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** it gives you (looks like `123456789:ABCdef…`)
4. Start a chat with your new bot (just send it `/start`)

### Step 2 — Get your Telegram Chat ID

1. Message **@userinfobot** on Telegram
2. It will reply with your numeric ID (e.g. `987654321`)

> To send to a **group**: add the bot to the group, then use the group's chat ID (starts with `-100…`)

### Step 3 — Configure your channels

Edit `channels.json` with the YouTube channels you want to monitor:

```json
[
  {
    "id": "UCBcRF18a7Qf58cCRy5xuWwQ",
    "name": "Google for Developers"
  }
]
```

**How to find a channel ID:**
- Go to the YouTube channel page
- View page source (Ctrl+U) and search for `"channelId"`
- Or use: https://www.tunepocket.com/youtube-channel-id-finder/

Channel IDs always start with `UC` and are 24 characters long.

### Step 4 — Push to GitHub

```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

### Step 5 — Add GitHub Secrets

1. Go to your repo on GitHub
2. Click **Settings → Secrets and variables → Actions**
3. Click **New repository secret** and add both:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Your bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Your numeric chat ID |

That's it. The bot runs automatically every 5 minutes.

---

## Local Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env and fill in your credentials

# Run once
python main.py
```

To load `.env` locally:
```bash
# Linux/Mac
export $(cat .env | xargs) && python main.py

# Windows PowerShell
Get-Content .env | ForEach-Object { $k,$v = $_ -split '=',2; [System.Environment]::SetEnvironmentVariable($k,$v) }
python main.py
```

---

## Telegram Message Format

```
🎬 New YouTube Video!

📺 Channel: Google for Developers
🎥 Title: What's new in Android 15
🔗 Link: https://youtube.com/watch?v=xxxxx
🕐 Published: May 27, 2026 at 14:30 UTC

📝 Transcript Preview:
Welcome everyone to today's session. We're going to cover the biggest
changes coming in Android 15 including the new photo picker improvements…

────────────────────
📄 Full Transcript:
[full transcript text here]
```

---

## Troubleshooting

**Bot isn't running?**
- Check the Actions tab on GitHub for error logs
- Verify both secrets are set correctly

**"No transcript available"?**
- The channel hasn't enabled captions
- It's a brand-new video (captions appear after a few minutes)
- The video is in a language YouTube doesn't auto-caption

**Getting duplicate messages?**
- Make sure `posted.json` is being committed — check the Actions log for the "Save updated posted.json" step
- The workflow needs `contents: write` permission (already in `bot.yml`)

**GitHub Actions only runs every ~10 minutes?**
- GitHub's free tier may delay scheduled workflows by a few minutes. This is normal — you can't go below 5 min intervals on GitHub Actions.

---

## Usage After Receiving the Transcript

Once you get the Telegram message, you can paste the transcript into ChatGPT and use prompts like:

```
Summarise this YouTube transcript in 5 bullet points.
Write 3 tweet variations based on this transcript.
Create a LinkedIn post from this transcript.
Extract the 5 most interesting quotes.
```

---

## Limitations

| Item | Detail |
|---|---|
| GitHub Actions minimum interval | 5 minutes |
| Telegram message limit | 4096 chars (bot splits automatically) |
| Transcripts | Only available if video has captions |
| Channels monitored | Only the **latest** video per channel per check |
