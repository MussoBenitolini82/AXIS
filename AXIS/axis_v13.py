"""AXIS V13 orchestration: audited task events, guarded repair proposals and model suggestions.
No model downloads, host code execution, or automatic deployment.
"""
import json
import re
import uuid
from datetime import datetime, timezone
import axis_learning
import vector_agents
import vector_discovery
import vector_upgrade

ROLES = ('planner', 'researcher', 'coder', 'reviewer', 'tester', 'orchestrator')
# Model metadata is curated suggestions, not a live remote catalog or verified installability.
MODEL_CATALOG = (
    {'name': 'qwen3:8b', 'role': 'general', 'ram_note': 'Quantized; check local VRAM and context usage'},
    {'name': 'qwen3:4b', 'role': 'helper', 'ram_note': 'Smaller optional helper; verify availability in Ollama'},
    {'name': 'nomic-embed-text', 'role': 'embeddings', 'ram_note': 'Optional embeddings model; verify availability'},
)

def log_stage(task_id, agent, stage, outcome, *, detail=None):
    if agent not in ROLES:
        raise ValueError('Unknown agent role')
    # Avoid logging raw prompts, user documents, code, credentials, or arbitrary payloads.
    return axis_learning.record(task_id, agent, 'agent_stage', stage, outcome,
                                {'detail': str(detail or '')[:180]})

def development(request, target='research_extensions.py'):
    """Existing role pipeline; results are proposals, never deployed automatically."""
    task_id = uuid.uuid4().hex
    log_stage(task_id, 'orchestrator', 'start', 'success')
    try:
        result = vector_agents.run(request, target)
        status = result.get('status', 'failed')
        log_stage(task_id, 'coder', 'proposal', 'success' if status == 'awaiting_tests_and_approval' else 'failure', detail=status)
        log_stage(task_id, 'reviewer', 'review', 'success' if status == 'awaiting_tests_and_approval' else 'failure')
        return {'task_id': task_id, 'result': result, 'requires_approval': True,
                'next_step': 'Use existing /api/upgrade-test then /api/upgrade-decision with explicit approval'}
    except Exception as exc:
        log_stage(task_id, 'orchestrator', 'error', 'failure', detail=type(exc).__name__)
        raise

def repair(error_summary, target='research_extensions.py'):
    """Draft repair through existing guarded agent pipeline; never auto-apply."""
    if not isinstance(error_summary, str) or not 12 <= len(error_summary) <= 1200:
        raise ValueError('Provide a 12-1200 character error summary')
    vector_upgrade.safe_target(target)
    request = ('Investigate the reported failure and propose a minimal, testable correction. '
               'Preserve existing behavior; include testable pure functions. Error report: ' + error_summary)
    return development(request, target)

def model_suggestions(request):
    """Deterministic capability suggestions. Installation always remains a separate user action."""
    if not isinstance(request, str) or not 1 <= len(request) <= 1200:
        raise ValueError('Invalid request')
    scan = vector_discovery.scan(request)
    text = request.casefold()
    roles = ['general']
    if any(word in text for word in ('ara', 'search', 'hafıza', 'memory', 'semantic', 'embedding')):
        roles.append('embeddings')
    if any(word in text for word in ('hız', 'fast', 'hafif', 'small', 'parallel')):
        roles.append('helper')
    return {'capabilities': scan, 'suggestions': [m for m in MODEL_CATALOG if m['role'] in roles],
            'installed': 'not_checked', 'downloads_performed': False, 'approval_required': True}

def dashboard(limit=80):
    ev = axis_learning.events(limit=min(150, max(1, int(limit))))
    lessons = axis_learning.lessons()
    nodes = {}
    edges = []
    for event in ev:
        agent = 'agent:' + event['agent']
        task = 'task:' + event['task_id']
        nodes[agent] = {'id': agent, 'label': event['agent'], 'kind': 'agent'}
        nodes[task] = {'id': task, 'label': event['task_id'][:8], 'kind': 'task'}
        edges.append({'source': agent, 'target': task, 'relation': event['outcome']})
    for lesson in lessons[:40]:
        lid = 'lesson:' + lesson['id']
        nodes[lid] = {'id': lid, 'label': lesson['signature'][:35], 'kind': 'lesson'}
        try:
            evidence = json.loads(lesson['evidence'])
        except (TypeError, ValueError):
            evidence = []
        matched = {e['id']: e for e in ev}
        for event_id in evidence:
            if event_id in matched:
                task = 'task:' + matched[event_id]['task_id']
                edges.append({'source': task, 'target': lid, 'relation': 'learned_from'})
    return {'version': '13', 'generated_at': datetime.now(timezone.utc).isoformat(),
            'events': ev, 'lessons': lessons, 'nodes': list(nodes.values()), 'edges': edges}