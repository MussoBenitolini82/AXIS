> Not (2026-11-11): Bu inceleme dosyanın daha eski bir sürümüne aittir; buradaki sha256 değerleri güncel kodla eşleşmiyor. Güncel kod bu sağlayıcı tarafından incelenmedi. Son bağımsız inceleme: Claude Opus 5.5, 2026-11-11 (yerel, salt-okunur).

Reviewer: OpenAI Codex
Model (from rollout): MODEL gpt-6-astra (parts 1-4)
Rollout: rollout-2026-11-11T01-28-12-01a1c793-77e3-73c3-9959-7796d7dd0054.jsonl (part 1); rollout-2026-11-11T01-28-56-01a1c794-2178-7381-9a7f-9547cce3fcb8.jsonl (part 2); rollout-2026-11-11T01-29-34-01a1c794-b775-7383-a8c9-ff1f8cc3e830.jsonl (part 3); rollout-2026-11-11T01-30-08-01a1c795-3c5f-7a52-ae53-58b6fe0a37a4.jsonl (part 4)
Date: 2026-11-11
Reviewed file: vector_upgrade.py, sha256 DA4D340CEDF916AE0DE97FD71A2F3F8F73BAD909CE4E7D0A029E5CA46953E5F7
Status: COMPLETED

## Part 1 (lines 1-178)

high | BEHAVIOR_RUNNER / VERIFY_SCRIPT | Candidate code controls the interpreter that reports behavior results and can terminate successfully before any assertions run; suite imports can do likewise. Separate interpreters do not authenticate test completion, so malicious candidates can produce PASS. | Run candidate execution separately from the trusted assertion/controller process, isolate it from controller processes, and require bounded structured responses for every expected test; treat premature exits as failures.
medium | validate_behavior_cases | json.dumps(case) traverses and allocates output for untrusted data before depth, collection-size, and string-length checks. Oversized or deeply nested arguments can exhaust host memory or recursion before being rejected. | Validate structure and limits first using a bounded traversal, then serialize; also bound incoming request size before JSON decoding.
medium | needs_host_program | Any occurrence of shutil.which, including an unused import or unreachable expression, excludes an entire test module. This silently drops tests that could run in the container and weakens the claimed repository-suite gate. | Use an explicit, reviewed exclusion list or test-level dependency markers, and skip only tests whose required executable is actually unavailable.

## Part 2 (lines 179-301)

high | verify | capture_output=True buffers unlimited candidate-controlled stdout/stderr in host memory. Container memory limits and REPORT_LIMIT do not bound this buffering; a printing loop can exhaust host memory before VERIFY_TIMEOUT. | Drain both streams concurrently into bounded tail buffers, enforce a combined output limit, and forcibly remove the container when exceeded.
high | stage_sources | On Windows, directory junctions are not rejected by is_symlink(). A junction beneath static/ can lead os.walk outside ROOT, copying unrelated host files into the candidate-readable container mount. The containment check covers only static itself. | Reject junctions and other directory reparse points throughout traversal; verify every resolved source remains beneath the resolved static directory before copying.
medium | verify | The candidate basename shares a namespace with harness files. If an otherwise permitted target is extensions/test_contract.py or extensions/test_behavior.py, subsequent harness writes overwrite the hash-verified candidate in the root staging directory, so those tests may exercise different bytes than the proposed code. | Store candidates and harness files in separate directories, pass the candidate path explicitly, and verify its digest after staging.

## Part 3 (lines 302-361)

high | decide / _replace_from | The digest is checked on one read of src, but shutil.copy2 later reopens it. A concurrent replacement or modification can install bytes that were never verified or approved. | Capture candidate bytes once, verify and container-test that exact snapshot, then write those same bytes to an exclusively created sibling temporary file and atomically replace dest.
high | decide / rollback | SQLite transactions do not make filesystem changes transactional. A crash after replacement but before commit leaves changed executable code with the previous database status; rollback can likewise restore/delete code while its status remains applied. Exception handlers cannot recover from process termination or power loss. | Persist a recovery journal before modifying files, retain durable recovery copies, and reconcile interrupted operations on startup before loading affected modules.
medium | _replace_from / rollback | Predictable temporary paths are opened with shutil.copy2, which follows existing symbolic links and overwrites existing files. A pre-existing link at the temporary or undo path can redirect writes outside the validated destination, bypassing target protection. Cleanup can also delete a file this operation did not create. | Create temporary and undo files exclusively with tempfile.mkstemp in a validated parent directory, write through the returned handles, and clean up only files owned by this operation.

## Part 4 (lines 363-413)

medium | sweep_untested | Loads every matching proposal into memory and attempts to schedule all of them in one call. An accumulated backlog can exhaust memory or overwhelm the worker queue; repeated sweeps can resubmit proposals whose tests have not started. | Read bounded batches, atomically claim proposals before scheduling, and enforce queue capacity with backpressure.
