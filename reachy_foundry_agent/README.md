---
title: Reachy Foundry Agent
emoji: 🤖
colorFrom: red
colorTo: blue
sdk: static
pinned: false
short_description: Talk to Reachy Mini; a Foundry-hosted agent reacts with its body
tags:
 - reachy_mini
 - reachy_mini_python_app
---

# Reachy Foundry Agent

The Reachy Mini app of the [Reachy-Foundry](../README.md) sample: voice in, Foundry model plus
Microsoft Agent Framework in the middle, voice and movement out. It runs on the robot itself.

See the [docs](../docs/) for architecture, tools, models, configuration and deployment.

## Develop

```bash
pip install -e ".[dev]"
pytest
reachy-mini-app-assistant check .
```
