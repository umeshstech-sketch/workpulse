# WorkPulse for Android (standalone phone tracker)

[← Back to README](../README.md)

Since version 2.0 the Android app is a complete activity tracker **on its own**. It needs no laptop or account, and nothing leaves the phone. Anyone with an Android phone (8.0 or newer) can install it.

## Install
1. Get `WorkPulse-2.2.0.apk`. Build it with `scripts\build-android.ps1`; a copy lands in `dist\`. Send it to the phone any way you like (WhatsApp, USB, Drive).
2. Open the file on the phone. Android asks to allow installing apps from that source (e.g. WhatsApp or Files) the first time; allow it.
3. Open **WorkPulse** → **Allow usage access** → find WorkPulse in the list → switch it on. Allow notifications when asked (for limits, bedtime and the focus timer).

Updating keeps your data, as long as the new APK is built with the same signing key (the build script keeps a backup of it).

## What's in it
| Tab | What you get |
|---|---|
| **Today** | Screen time against your goal, **balance score** (100 minus four penalties, each shown: screen time over goal, distracting-app share above 30%, pickups over goal, use in bedtime hours), pickups, first pickup, longest stretch, focus time, an hour-by-hour chart (bedtime hours highlighted), categories, plain-language insights and every app with opens and limits. Swipe back through earlier days with ‹ ›. |
| **Coach** | A chat, like the WhatsApp bot on the laptop. Commands are answered on the phone, instantly and offline: *today*, *yesterday*, *week*, *best*, *improve*, *plan*, *apps*, *score*, *limit instagram 30*, *limits*, *goal 2h*, *focus 25*, *stop*, *bedtime 23:00*, *habits*, *habit add …*, *done …* (type *help*). Questions in your own words go to the optional AI coach. |
| **Trends** | 7- or 30-day bars against your goal (tap a day to open it), average vs the previous period, pickups, best day, days within goal, categories and top apps per day. |
| **Focus** | Timer (15–90 min) with a notification when it's done, plus an honest report: which distracting apps you opened during the session. Daily total, streak and distraction-free rate. |
| **Goals** | Daily screen-time and pickup goals; **per-app daily limits** (nudge at 80% and at 100%); bedtime and wake time with a reminder if you're on the phone after bedtime; **habits** with daily check-offs and streaks. |
| **More** | Permissions, which categories count as distracting, the private-apps list, light/dark theme, CSV export, delete everything, and optional laptop sync. |

Tap any app for its 14-day history, to change its category or to set a limit.

## How it works
- Every 15 minutes (Android's minimum), and whenever you open the app, WorkPulse reads Android's usage events: which app was in front, from when to when, and unlocks. It stores one small summary per day in the app's private storage.
- Android keeps detailed events for about a week, so after installing you see roughly the last week straight away. From then on, history is kept for as long as you keep the app.
- Reminders are checked on the same 15-minute schedule, so a limit nudge can come up to 15 minutes late. Each one is sent once a day at most.
- **Private apps:** any app whose name or package contains a word on your list (banking, payment and password apps by default) is stored only as "Private apps". Its time counts but its name is never saved. Adding a word also cleans days already saved.
- **Never recorded:** screen contents, messages, notifications, typing, or anything inside apps. Android's usage stats simply don't contain them.

## Optional: AI coach
Free-form questions ("why am I on my phone so much at night?") are answered by **Google Gemini** (`gemini-flash-latest`, the alias for Google's newest Flash model, falling back to `gemini-2.5-flash`) using **your own Gemini API key**: More → AI coach → paste the key from [Google AI Studio](https://aistudio.google.com) → Get API key. New keys start with `AQ.` (older ones with `AIza`); both work. The key is stored only in the app's private storage on the phone.

When you ask the AI a question, the app sends Google a short text summary of your stats (today, yesterday and 7-day totals, top app names, goals, limits, habits, focus; never private apps) plus the last few chat messages. Commands never leave the phone. On Google's free tier, Google may use what you send to improve its products; a paid (billing-enabled) key isn't used that way. Without a key, the Coach tab still answers every command and points free-form questions at the closest command.

Don't build a key into the APK you share: anyone who has the file can extract it and spend on your account. Each person should add their own key.

## Optional: laptop sync
If you also run WorkPulse on a computer: **More → Laptop sync → Connect to a laptop**, then pair with the code from the laptop ([mobile guide](mobile.md)). The phone keeps working on its own either way; sync just copies your phone usage to the laptop's dashboard.

## Developing the screens
The screens are plain HTML/CSS/JS in `android/app/src/main/assets/app/`, talking to Kotlin through `window.WorkPulse` (`MainActivity.Bridge`). Opened in a desktop browser, they load `dev-mock.js` (made-up data), so you can work on the UI without a phone:
```bat
.venv\Scripts\python -m http.server 8799 --directory android\app\src\main\assets\app
```
