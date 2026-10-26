---
name: error_signature_extractor
version: "1.0.0"
description: Normalize a crash into a readable, stable error signature
category: debugging
agents: [dissect]
type: code
deterministic: true
requires_llm: false
entry_class: ErrorSignatureExtractorSkill
trusted: true
---
Complements `compute_fingerprint` (the opaque hash used for dedup) with a
*readable* signature — the taxonomy category plus a whitespace-normalized
message and a short digest. Dissect surfaces this in events and the patch log
instead of the raw message, so the same error produced by different volatile
values still reads identically.
