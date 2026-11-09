# Gerçek yerel model çalıştırması: qwen3:8b (PR1)

- Çalıştırma zamanı (UTC): 2026-11-09T22:24:46.174132+00:00
- Ollama sürümü (/api/version): 0.40.15
- Model: qwen3:8b, digest: 500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41
- Kod anlık görüntüsü commit: 26f5cca (26f5ccaa25f8e4d663e9f37e4e170beab7b77f5f)
- Paket dosyaları: axis_sqlite.py, vector_upgrade.py, multi_ai_review.py
- bundle_sha256: 897fa63ff33e7b3f53feafc1a09c4aade7bf0de04b12bdeab5d3d0c468a9bc1a
- num_ctx: 14336
- prompt_eval_count: 6173
- eval_count: 2244
- done_reason: stop
- dropped_finding_keys: 0
- Süre: yaklaşık 157 saniye (CPU)
- status: COMPLETED
- reason: Actual model response received; findings unverified
- Bulgu sayısı: 27 (high/critical yok)

## Uyarılar

- Bu çalıştırma tek bir yerel modelle (Reviewer rolü, qwen3:8b) yapılmıştır.
- Bu, bağımsız bir sağlayıcı incelemesi DEĞİLDİR.
- Bulgular doğrulanmamıştır; yanlış pozitif içerebilir. Örneğin satır numaraları ve "ekirdek" ifadesine dair bir bulgu, modelin kodu tam anlamadığını düşündürmektedir.
- FAILED bir çalıştırma inceleme sayılmaz; bu çalıştırma COMPLETED durumundadır, ancak yine de yalnızca doğrulanmamış model çıktısıdır.

## Bulgular (doğrulanmamış model çıktısı)

```json
[
  {
    "severity": "medium",
    "file": "axis_sqlite.py",
    "line": 5,
    "confidence": "high",
    "explanation": "The `ClosingConnection` class overrides `__exit__` but does not explicitly call `super().__exit__` before closing the connection. This could lead to unexpected behavior if the parent class's `__exit__` has side effects."
  },
  {
    "severity": "low",
    "file": "vector_upgrade.py",
    "line": 12,
    "confidence": "medium",
    "explanation": "The `DATA` directory is created with `exist_ok=True`, which is safe, but it would be better to use `Path.mkdir(exist_ok=True, parents=True)` to ensure parent directories are created if they don't exist."
  },
  {
    "severity": "medium",
    "file": "vector_upgrade.py",
    "line": 25,
    "confidence": "high",
    "explanation": "The `connection()` function uses `sqlite3.connect` with a custom factory, but it does not handle exceptions or ensure the connection is properly closed. This could lead to resource leaks if an exception occurs."
  },
  {
    "severity": "medium",
    "file": "vector_upgrade.py",
    "line": 34,
    "confidence": "high",
    "explanation": "The `safe_target()` function raises a `ValueError` with a message that includes the word 'çekirdek' (which means 'core' in Turkish). This could be a security risk if the message is logged or exposed to untrusted users."
  },
  {
    "severity": "medium",
    "file": "vector_upgrade.py",
    "line": 44,
    "confidence": "high",
    "explanation": "The `validate()` function uses `ast.parse()` without handling exceptions. If the code is invalid, this could raise an `ast.ParseError` which is not caught, leading to unhandled exceptions."
  },
  {
    "severity": "medium",
    "file": "vector_upgrade.py",
    "line": 64,
    "confidence": "high",
    "explanation": "The `CONTRACT_TEST` string contains a multi-line Python script. If this string is used in a context where it is executed, it could introduce security risks if the content is not properly sanitized."
  },
  {
    "severity": "medium",
    "file": "vector_upgrade.py",
    "line": 104,
    "confidence": "high",
    "explanation": "The `attach_behavior_cases()` function writes JSON data to a file without validating the content. This could lead to potential security issues if the data is not properly sanitized or if the file is exposed to untrusted users."
  },
  {
    "severity": "medium",
    "file": "vector_upgrade.py",
    "line": 124,
    "confidence": "high",
    "explanation": "The `behavior_cases()` function reads JSON data from a file without validating the content. This could lead to potential security issues if the data is not properly sanitized or if the file is exposed to untrusted users."
  },
  {
    "severity": "medium",
    "file": "vector_upgrade.py",
    "line": 144,
    "confidence": "high",
    "explanation": "The `BEHAVIOR_RUNNER` string contains a multi-line Python script. If this string is used in a context where it is executed, it could introduce security risks if the content is not properly sanitized."
  },
  {
    "severity": "medium",
    "file": "vector_upgrade.py",
    "line": 164,
    "confidence": "high",
    "explanation": "The `docker_available()` function uses `subprocess.run()` without handling exceptions. If the Docker command fails, this could raise an `OSError` or `subprocess.TimeoutExpired` which is not caught, leading to unhandled exceptions."
  },
  {
    "severity": "medium",
    "file": "vector_upgrade.py",
    "line": 184,
    "confidence": "high",
    "explanation": "The `propose()` function writes code to a file without validating the content. This could lead to potential security issues if the data is not properly sanitized or if the file is exposed to untrusted users."
  },
  {
    "severity": "medium",
    "file": "vector_upgrade.py",
    "line": 204,
    "confidence": "high",
    "explanation": "The `detail()` function reads code from a file without validating the content. This could lead to potential security issues if the data is not properly sanitized or if the file is exposed to untrusted users."
  },
  {
    "severity": "medium",
    "file": "vector_upgrade.py",
    "line": 224,
    "confidence": "high",
    "explanation": "The `listing()` function uses `sqlite3` without handling exceptions. If an exception occurs during the query, it could lead to unhandled exceptions."
  },
  {
    "severity": "medium",
    "file": "vector_upgrade.py",
    "line": 244,
    "confidence": "high",
    "explanation": "The `verify()` function uses `subprocess.run()` without handling exceptions. If the Docker command fails, this could raise an `OSError` or `subprocess.TimeoutExpired` which is not caught, leading to unhandled exceptions."
  },
  {
    "severity": "medium",
    "file": "vector_upgrade.py",
    "line": 264,
    "confidence": "high",
    "explanation": "The `decide()` function uses `shutil.copy2()` and `os.replace()` without handling exceptions. If the file operations fail, this could lead to unhandled exceptions."
  },
  {
    "severity": "medium",
    "file": "vector_upgrade.py",
    "line": 284,
    "confidence": "high",
    "explanation": "The `rollback()` function uses `shutil.copy2()` and `os.replace()` without handling exceptions. If the file operations fail, this could lead to unhandled exceptions."
  },
  {
    "severity": "medium",
    "file": "multi_ai_review.py",
    "line": 12,
    "confidence": "high",
    "explanation": "The `ROLES` dictionary includes a 'Security Auditor' role, but the code does not enforce any specific security checks or restrictions. This could lead to potential security risks if the code is not properly secured."
  },
  {
    "severity": "medium",
    "file": "multi_ai_review.py",
    "line": 14,
    "confidence": "high",
    "explanation": "The `_KEYS` variable contains a regex pattern for matching sensitive keys, but it is not used in any of the `SECRET_PATTERNS` entries. This could lead to potential security risks if the code is not properly secured."
  },
  {
    "severity": "medium",
    "file": "multi_ai_review.py",
    "line": 20,
    "confidence": "high",
    "explanation": "The `SECRET_PATTERNS` list contains several regex patterns for matching sensitive information, but none of them are used in the `scrub()` function. This could lead to potential security risks if the code is not properly secured."
  },
  {
    "severity": "medium",
    "file": "multi_ai_review.py",
    "line": 30,
    "confidence": "high",
    "explanation": "The `plan_context()` function calculates the required context length for the model, but it does not handle cases where the model's context length is not available or is zero. This could lead to potential errors if the model's context length is not properly handled."
  },
  {
    "severity": "medium",
    "file": "multi_ai_review.py",
    "line": 40,
    "confidence": "high",
    "explanation": "The `check_response()` function validates the response from the model, but it does not handle all possible error cases. This could lead to potential errors if the model's response is not properly validated."
  },
  {
    "severity": "medium",
    "file": "multi_ai_review.py",
    "line": 50,
    "confidence": "high",
    "explanation": "The `scrub()` function replaces sensitive information in the text, but it does not handle all possible cases. This could lead to potential security risks if the code is not properly secured."
  },
  {
    "severity": "medium",
    "file": "multi_ai_review.py",
    "line": 60,
    "confidence": "high",
    "explanation": "The `_text()` function validates the input text, but it does not handle all possible cases. This could lead to potential errors if the input text is not properly validated."
  },
  {
    "severity": "medium",
    "file": "multi_ai_review.py",
    "line": 70,
    "confidence": "high",
    "explanation": "The `sanitize_findings()` function processes the findings, but it does not handle all possible cases. This could lead to potential errors if the findings are not properly processed."
  },
  {
    "severity": "medium",
    "file": "multi_ai_review.py",
    "line": 80,
    "confidence": "high",
    "explanation": "The `bundle()` function bundles the source files, but it does not handle all possible cases. This could lead to potential errors if the source files are not properly bundled."
  },
  {
    "severity": "medium",
    "file": "multi_ai_review.py",
    "line": 90,
    "confidence": "high",
    "explanation": "The `local_api()` function interacts with the local API, but it does not handle all possible cases. This could lead to potential errors if the API is not properly handled."
  },
  {
    "severity": "medium",
    "file": "multi_ai_review.py",
    "line": 100,
    "confidence": "high",
    "explanation": "The `run()` function runs the review process, but it does not handle all possible cases. This could lead to potential errors if the review process is not properly handled."
  }
]
```
