---
name: crash_localizer
version: "1.1.0"
description: Locate the failing script frame/line and suggest a next action (installed shadow demo)
category: debugging
agents: [dissect]
type: code
deterministic: true
requires_llm: false
entry_class: CrashLocalizerPlusSkill
trusted: true
---
Installed demo variant of the bundled `crash_localizer`: same traceback/message
parsing contract, plus a deterministic `suggestion` field in `detail` telling the
researcher what to do next based on how confidently the crash site was located.
Never raises; a non-locatable crash is a successful negative (`locatable=False`).
