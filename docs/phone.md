# Phone tracking

[← Back to README](../README.md)

## Ways to add phone data

**On Android, the easiest way is the [WorkPulse Android app](mobile.md)**: it tracks phone usage automatically and syncs over your Wi-Fi. The other methods below are for iPhone, or if you'd rather not install it.

Phone data comes in as **daily totals per app** (no timeline). Pick whatever's easiest; every method lands in the same place, and re-adding a day replaces it (no double counting).

| Method | Android | iPhone | Effort |
|---|---|---|---|
| **Screenshot**: Digital Wellbeing / Screen Time → Digital day tab → *Read screenshot* | ✅ | ✅ | ~20 s a day, needs `ANTHROPIC_API_KEY` |
| **Manual**: type total + top apps in the Digital day tab, or `.\workpulse phone add --total 3h --app "Instagram=1h10m"` | ✅ | ✅ | ~30 s a day |
| **CSV/JSON file**: export from a usage-tracking app or a spreadsheet → *Import* (or `.\workpulse phone import usage.csv`) | ✅ | (if you have a CSV) | whenever |
| **ADB pull** (experimental): phone on USB with debugging on → `.\workpulse phone pull-android` | ✅ | ❌ | plug in + one command |
| **Automatic POST**: Tasker / an iOS Shortcut / any script sends JSON to `/api/phone/ingest` | ✅ | ✅ (semi: Shortcut asks you the numbers) | set up once |

Then see it in the **Digital day** tab, with `phone` on WhatsApp / in the Coach tab, and as a 📱 line in the night report and weekly review.

**Honest limits**
- **iPhone:** Apple doesn't let Shortcuts or other apps read Screen Time numbers (the data is sandboxed and can't be exported). So on iOS it's a screenshot, typing the numbers, or a Shortcut that asks you for them. No app can do it silently.
- **Android:** the [WorkPulse Android app](mobile.md) reads usage stats automatically (with your Usage access permission). Without it: screenshot, a usage app's CSV export, ADB, or Tasker posting numbers you've collected.
- **ADB pull** parses `dumpsys usagestats`, whose format changes between Android versions. Compare its numbers with Digital Wellbeing the first time. Needs Android platform-tools (`winget install Google.PlatformTools`) and USB debugging (Settings → About → tap Build number 7× → Developer options → USB debugging).
- **Screenshots:** the image goes to the Anthropic API to read the numbers, is held only in memory for that one request, and is **never saved**. You check and edit the numbers before anything is stored. Use a single-day view; the importer warns if it looks like a weekly one.

### CSV format
One row per app per day. Column names are matched loosely: `date`/`day`; `app`/`app name`/`package`; and a time column: `time`/`duration`/`usage time` (e.g. `1h 20m`, `01:20:00`, `80` = minutes), or `minutes`, `seconds`, `milliseconds`. Optional `pickups`, `device`. A row whose app is `Total` sets the day's total. Dates can be `2026-10-20` or `20/10/2026`.
```
date,app,time
2026-10-20,Instagram,1h 10m
2026-10-20,WhatsApp,45m
```

### Automatic POST (Tasker, iOS Shortcuts, scripts)
Get the endpoint and phone token with `.\workpulse phone token` (or the dashboard: Digital day → *Show endpoint & token*). The phone token can **only** add phone screen time, so it's safe to put in Tasker/Shortcuts. Send:
```
POST https://<your-tunnel>/api/phone/ingest        (or http://127.0.0.1:8787/... from the laptop)
X-WorkPulse-Phone-Token: <token>
Content-Type: application/json

{"day": "2026-10-20", "device": "phone", "total": "3h 20m", "pickups": 85,
 "apps": [{"name": "Instagram", "minutes": 70}, {"name": "WhatsApp", "time": "45m"}]}
```
Also accepted: `total_minutes` / `total_s`, `apps` items with `seconds` or `package`, a list of days, and the Shortcut-friendly `"apps_text": "Instagram=70m, WhatsApp=40m"`. Without `day` it's today. The phone needs to reach the laptop, so use the same ngrok/cloudflared tunnel as WhatsApp (this endpoint is the only other path the tunnel can reach, and it requires the token).

**iPhone Shortcut (semi-automatic):** Shortcuts → Automation → *Time of Day* 23:00 → actions: *Ask for Input* (Number: "Screen time today in minutes?") → *Ask for Input* (Text: "Top apps? e.g. Instagram=70m, WhatsApp=40m") → *Get Contents of URL*: your tunnel URL + `/api/phone/ingest`, Method **POST**, Header `X-WorkPulse-Phone-Token` = your token, Request Body **JSON** with `total_minutes` = first input and `apps_text` = second input. It pops up at 23:00; you read the numbers off Screen Time and type them.

**Android Tasker:** add an *HTTP Request* action (POST, same URL, header and JSON body as above) to a nightly profile, filling the numbers from whatever usage source you use in Tasker.
