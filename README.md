# OSRS AFK Roulette 🎡

A static page that rolls your daily AFK task for Old School RuneScape — with a spinning roulette wheel.

**Live**: https://afk.rosu.fi (leaderboard API: https://afk-api.rosu.fi)

## How it works

1. Enter your OSRS username → levels are fetched from the [Wise Old Man](https://wiseoldman.net) API (fallback: official hiscores via a CORS proxy).
2. The task pool ([tasks.js](tasks.js)) is curated from the [OSRS Wiki AFK list](https://oldschool.runescape.wiki/w/Guide:AFK_Skilling_Methods) — only tasks whose skill requirements you meet make it onto the wheel.
3. **Generate** → the roulette wheel spins and lands on today's task.
4. The result can be posted to a Discord channel via a webhook (⚙️ settings; the URL is stored only in your browser's localStorage, never in the repo).

## Creating the Discord webhook

In Discord: Channel settings → Integrations → Webhooks → New Webhook → Copy URL → paste it into the page's ⚙️ settings.

No build, no backend — plain HTML/CSS/JS hosted on GitHub Pages.
