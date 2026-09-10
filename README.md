# dcemibot

A [Sonny](https://github.com/driftbluestone/sonny) extension that renders
Minecraft recipes using EMI Widgets as images in Discord.
**[DCEMI](https://github.com/BgameXL/dcemi)** — the headless renderer does
the work; this extension just talks to it over TCP and posts the pictures.

## Commands

- `/recipe <item>` — autocompletes the item id, then pages through every recipe for that item with ◀ ▶ buttons.
- `/list <query>` — search EMI item index by substring.
- `/render <recipe_id>` — render one recipe by its raw id.

## Install in Sonny bot

```
/extension add https://github.com/BgameXL/dcemibot
```

Sonny clones this repo into `extensions/dcemibot/` and loads it. Then enable it
per server with `/extension toggle`.

## Requirements

This extension is **connect-only**

Point the extension at it with environment variables (defaults shown):

| Env          | Default     | Meaning                    |
|--------------|-------------|----------------------------|
| `DCEMI_HOST` | `127.0.0.1` | host of the DCEMI renderer |
| `DCEMI_PORT` | `25599`     | its TCP port               |
