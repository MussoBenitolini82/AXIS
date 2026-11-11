Reviewer: OpenAI Codex
Model (from rollout): MODEL gpt-6.1-sol
Rollout: rollout-2026-11-11T01-23-16-01a1c78e-f2df-7040-b34a-9adc52831385.jsonl
Date: 2026-11-11
Reviewed file: axis_feedback.py, sha256 DEE9DFA792CAA5243F7F97F7E9E0F1EAF0978B79D2C1795884A95DF498F25D62
Status: COMPLETED

high | prompt_block | PROMPT_NOTE is never included in the returned block. Stored corrections can therefore supply instructions directly to the LLM; replacing angle brackets prevents literal tag closure but does not prevent instruction injection. | Include the distrust policy in a trusted system/developer message, explicitly identify the block as untrusted data, and enforce tool authorization independently of model output.
medium | hints | Every lookup fetches all corrected records, tokenizes every question, and sorts all matches before applying limit. Database growth causes unbounded memory use and increasing runtime; fetchall also holds LOCK while loading the entire history, blocking other operations. | Query a bounded candidate set using SQL LIMIT before fetching, or maintain an indexed retrieval structure; cap the requested limit and retain only the best bounded number of matches.
