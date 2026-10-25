# WhatsApp bot & AI coach

[← Back to README](../README.md)

## WhatsApp setup (Twilio sandbox, ~10 minutes)

You need: a free Twilio account, WhatsApp on your phone, and a tunnel so Twilio can reach the laptop (ngrok or cloudflared). **Scheduled reports only need steps 1–4 and 7; replying to the bot also needs the tunnel (5–6).**

1. **Sign up** at https://www.twilio.com/try-twilio (free trial) and verify your phone number.
2. In the Twilio Console open **Messaging → Try it out → Send a WhatsApp message**. It shows the sandbox number (usually **+1 415 523 8886**) and a code like `join pink-elephant`.
3. **Join the sandbox from your WhatsApp:** send `join <your-code>` to that number. Twilio replies that you're connected.
4. **Fill in `.env`** (copy `.env.example` if you don't have one):
   ```
   TWILIO_ACCOUNT_SID=ACxxxxxxxx...      # Console home → Account info
   TWILIO_AUTH_TOKEN=xxxxxxxx...         # same place (click to reveal)
   TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
   MY_WHATSAPP_NUMBER=whatsapp:+91XXXXXXXXXX
   ```
5. **Start a tunnel** to the dashboard port. Pick one:
   ```bash
   ngrok http 8787
   ```
   ```bash
   cloudflared tunnel --url http://127.0.0.1:8787
   ```
   (Install with `winget install ngrok.ngrok` + `ngrok config add-authtoken <token>`, or `winget install --id Cloudflare.cloudflared`.) Copy the `https://…` URL it prints.
6. In the sandbox page's **Sandbox settings**, set **"When a message comes in"** to `https://<your-tunnel>/api/whatsapp/twilio`, method **POST**, and save.
7. **Restart and test:**
   ```bash
   .\workpulse stop
   ```
   ```bash
   .\workpulse start
   ```
   ```bash
   .\workpulse wa test
   ```
   A "Hi from WorkPulse" message should arrive. Then send `status`, `today` or `goal add Ship v1` from WhatsApp.

Good to know:
- **Only your number works.** Messages from any other number are ignored (and not stored), and every webhook request must carry a valid Twilio signature.
- **The tunnel exposes only the webhook.** Anything that arrives through a tunnel (detected by its forwarding headers) is refused on every other path, so the dashboard, settings and your data stay laptop-only. Don't enable ngrok's `--host-header=rewrite`.
- **Free tunnel URLs change** when you restart ngrok/cloudflared, so update step 6 when that happens (ngrok accounts include a free static domain if you want one that doesn't change). If signatures fail behind an unusual proxy, set `whatsapp.public_url` in `config.yaml` to the tunnel URL.
- **Sandbox limits:** WhatsApp only lets a business number send free-form messages within **24 hours of your last message to it**, so reply to the bot at least once a day (the morning report invites a `plan` reply) or scheduled reports will bounce with error 63016. The sandbox is for testing and can also drop you after a few days; if messages stop arriving, send your `join <code>` again. For "always on" without these limits, move to the Meta WhatsApp Cloud API later (`whatsapp.provider: meta`, see `.env.example`; implemented, untested against a live account).
- **No credentials? No problem:** with Twilio unset, every message is "dry-run" logged instead of sent. See them with `.\workpulse messages`.

### What the bot sends

| When (config.yaml → `whatsapp.schedule`) | Message |
|---|---|
| Morning, 08:00 | Yesterday in two lines, today's goals and due tasks, **Top 3 priorities** |
| Midday, 13:30 | "You're at X h active, mostly Y", what's left to hit your target |
| Night, 21:30 | Full report: hours, focus score vs average, top apps, best moment, a win, one thing to improve, tomorrow's plan |
| Sunday, 19:00 | Weekly review: trend, best day, streaks, wins, problems, one experiment for next week |
| Every 10 min (outside quiet hours) | Nudges: Entertainment passing 1h/2h…, laptop idle 2h+ in work hours, tasks due within 24h |

Reports are never sent twice in a day. If the laptop was asleep at report time, the report goes out when it wakes, as long as that's within 2 hours. Nothing proactive is sent while tracking is paused (except the morning message).

### Chat commands

`status` · `today` · `week` · `best` · `improve` · `plan` · `goals` · `goal add [daily|weekly|monthly|long] <text> [#coding] [2h]` · `goal done <n>` · `goal progress <n> <%>` · `roadmap` · `team` · `team add <name> <role>` · `task @name <text> [by fri]` · `tasks` · `task done <n>` · `meeting <minutes> <title> [@names]` · `pause` · `resume` · `help`. Anything else goes to the AI coach, which sees your stats, goals, tasks and the last few messages.

Examples: `goal add daily 2h #coding Ship the API` (tracked Coding time counts toward it automatically) · `goal add long Launch my startup` · `task @Riya pitch deck by fri` · `meeting 45 standup @Riya @Arjun` · `goal progress 2 40`.

Try any of them without WhatsApp: `.\workpulse bot today`, `.\workpulse bot goal add weekly 10h #learning ML course`.

## AI coach

Add `ANTHROPIC_API_KEY` to `.env` and restart. The coach writes the priorities, the night report's win / improve / tomorrow lines, the weekly experiment, `plan`, and free-text replies.

- **Numbers are never AI-made.** Report stats are computed by the same code as the CLI/dashboard; the model gets a fact sheet (`.\workpulse bot --facts` shows exactly what it sees) and is told to use only those numbers.
- **Model:** `claude-opus-5-5` at `effort: low` (short texts don't need more), set in `config.yaml → coach`. It sends `fallbacks: "default"`, so if a safety classifier wrongly declines a request, Anthropic re-runs it on its recommended fallback model instead of failing. Set `coach.fallbacks: false` to turn that off.
- **Cost:** each message is a small request (a few thousand input tokens, a short reply). Expect roughly a few cents a day at the default schedule; heavy free-text chatting costs more. Check usage in the Claude Console.
- **Privacy:** only the fact sheet is sent to the API: aggregated stats, app names, site names that appear in insights (e.g. "YouTube"), your goals/tasks/team names and the recent bot chat. Full window titles are never sent. Without a key, nothing is sent anywhere and templates are used.
