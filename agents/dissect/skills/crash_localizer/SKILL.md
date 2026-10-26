---
name: crash_localizer
version: "1.0.0"
description: Locate the failing script frame/line from a crash traceback
category: debugging
agents: [dissect]
type: code
deterministic: true
requires_llm: false
entry_class: CrashLocalizerSkill
trusted: true
permissions: [file_read]
---
Locates where in the training script a crash actually happened by parsing the
`traceback` string Furnace captured (falling back to the exception message).
Feeds a `crash_location` (file/line/function/snippet) into Dissect's planning
event and patch log so a human or the LLM prompt sees *where* it broke, not
just which taxonomy category it is.
