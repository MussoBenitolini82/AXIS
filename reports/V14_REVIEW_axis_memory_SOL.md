> Not (2026-11-11): Bu inceleme dosyanın daha eski bir sürümüne aittir; buradaki sha256 değerleri güncel kodla eşleşmiyor. Güncel kod bu sağlayıcı tarafından incelenmedi. Son bağımsız inceleme: Claude Opus 5.5, 2026-11-11 (yerel, salt-okunur).

Reviewer: OpenAI Codex
Model (from rollout): MODEL gpt-6.1-sol
Rollout: rollout-2026-11-11T01-24-20-01a1c78f-edaf-7443-a814-f8cc0015f936.jsonl
Date: 2026-11-11
Reviewed file: axis_memory.py, sha256 C66AACA38933E3AEF479A51B0E71348C889A4CC4F2E5A0AB15CF1A5E275CFBF1
Status: COMPLETED

high | backfill | Updates match only id after embedding outside a database transaction; another process can modify or delete/recreate an item meanwhile, attaching an obsolete vector to current text. | Select digest with each row and condition updates on both id and the original digest.
medium | backfill, semantic_search | Hold the global LOCK during Ollama requests; a stalled request blocks all storage, search, status, and reset operations, and backfill can hold it across many 30-second requests. | Release LOCK before network work, then apply results using conditional updates.
medium | _digest, _upsert | Concatenation is ambiguous: label="ab", text="c" and label="a", text="bc" have identical digests, so changed content is silently ignored. | Hash an unambiguous serialization such as JSON containing [label, text].
medium | embed, backfill | Embedding silently truncates label plus text to 2,000 characters while marking the entire item embedded; later content is permanently unsearchable, and a long label can exclude all text. | Chunk complete content into separately stored and embedded records, or enforce and expose an explicit ingestion limit.
medium | semantic_search | LIMIT SCAN_CAP without ordering searches an arbitrary subset; matching items outside the first 20,000 eligible rows can never be returned. | Scan all eligible vectors using bounded batches, or implement an explicit indexed candidate-selection strategy.
medium | _request, _normalise | Response reading and vector dimensions are unrestricted; a faulty local service can exhaust memory or CPU before validation completes. | Bound response bytes and validate maximum vector dimension before normalization.
medium | embed, upsert_many, backfill | Inputs and work have no total bounds: embed materializes arbitrary iterables, upsert_many holds the lock for the entire iterable, and backfill accepts arbitrarily large limits. | Enforce finite batch and text-size limits, cap backfill limits, and process larger workloads incrementally.
