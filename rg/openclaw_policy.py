"""Check the RESEARCH GROUP OpenClaw profile by its EFFECTIVE result, not by how it reads.

Traps found on OpenClaw 2026.10.5 (docs/OPENCLAW_EVALUATION.md):
  1. plugins.allow = [] means "no restriction": 41 bundled plugins loaded (computer use, browser, file transfer, github).
  2. config validate accepts an unknown name inside tools.deny, so a typo denies nothing while the config is "valid".
  3. memory-core loads outside plugins.allow and adds tools unless plugins.slots.memory = "none".
  4. the gateway fetches a remote model catalog (catalog.openclaw.ai) at startup unless models.catalogRefresh is off.
Static check: python -m rg.openclaw_policy substrate/openclaw.json
Runtime check (outputs of `openclaw plugins list --json` and `openclaw security audit --json` in the container):
  python -m rg.openclaw_policy substrate/openclaw.json --plugins plugins.json --audit audit.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

# Tool groups and profiles as documented by OpenClaw v2026.10.5 (docs/gateway/config-tools/tool-policy.md).
GROUPS = {
    'group:runtime': {'exec', 'process', 'code_execution', 'bash'},
    'group:fs': {'read', 'write', 'edit', 'apply_patch'},
    'group:sessions': {'sessions', 'sessions_list', 'sessions_history', 'sessions_search', 'conversations_list',
                       'conversations_send', 'conversations_turn', 'sessions_send', 'sessions_spawn', 'sessions_yield',
                       'subagents', 'session_status', 'suggest_task', 'dismiss_task'},
    'group:memory': {'memory_search', 'memory_get'},
    'group:web': {'web_search', 'x_search', 'web_fetch'},
    'group:ui': {'browser', 'screen', 'theme', 'dashboard', 'terminal', 'portal', 'canvas', 'show_widget'},
    'group:automation': {'heartbeat_respond', 'automations', 'cron', 'gateway', 'plugins', 'openclaw'},
    'group:messaging': {'message'},
    'group:nodes': {'nodes', 'computer'},
    'group:agents': {'agents_list', 'get_goal', 'create_goal', 'update_goal', 'progress_card', 'ask_user', 'skill_workshop'},
    'group:media': {'view_image', 'image_generate', 'music_generate', 'video_generate', 'tts', 'pdf'},
}
KNOWN_TOOLS = set().union(*GROUPS.values())
PROFILES = {'minimal': {'session_status', 'gateway'}}  # the only profile RG accepts; unset/full = unfiltered

RESEARCH_TOOLS = {'web_search', 'web_fetch'}  # no file tools: the packet leaves as the agent's output, captured outside its reach
ALLOWED_PLUGINS = {'anthropic', 'web-readability'}
SECRET_KEYS = re.compile(r'(token|secret|password|api_?key|apikey|credential)', re.I)
ENV_REF = re.compile(r'^\$\{[A-Z][A-Z0-9_]*\}$')


def _get(cfg, dotted, default=None):
    node = cfg
    for part in dotted.split('.'):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def _expand(names, errors, where):
    out = set()
    for name in names:
        if name in GROUPS:
            out |= GROUPS[name]
        elif name in KNOWN_TOOLS:
            out.add(name)
        else:
            errors.append(f'{where}: unknown tool or group {name!r} (OpenClaw would accept it silently)')
    return out


def effective_tools(cfg, errors):
    tools = cfg.get('tools', {})
    profile = tools.get('profile')
    if profile not in PROFILES:
        errors.append(f'tools.profile must be one of {sorted(PROFILES)}, got {profile!r}')
        return set(KNOWN_TOOLS)
    requested = _expand(tools.get('alsoAllow', []), errors, 'tools.alsoAllow')
    if requested - RESEARCH_TOOLS:  # never even ask for more, so safety does not hinge on the deny list alone
        errors.append(f'tools.alsoAllow requests tools beyond the research set: {sorted(requested - RESEARCH_TOOLS)}')
    return (PROFILES[profile] | requested) - _expand(tools.get('deny', []), errors, 'tools.deny')


def _secret_literals(node, path=''):
    if isinstance(node, dict):
        for k, v in node.items():
            p = f'{path}.{k}' if path else k
            if isinstance(v, str) and SECRET_KEYS.search(k) and not ENV_REF.match(v):
                yield p
            yield from _secret_literals(v, p)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _secret_literals(v, f'{path}[{i}]')


def check_config(cfg):
    errors = []
    expect = {
        'gateway.bind': 'loopback', 'gateway.auth.mode': 'token', 'plugins.slots.memory': 'none',
        'tools.fs.workspaceOnly': True, 'tools.exec.security': 'deny', 'tools.elevated.enabled': False,
        'tools.agentToAgent.enabled': False, 'tools.codeMode': False, 'browser.enabled': False,
        # no vendor phone-home: the remote model catalog can change behavior; update checks send host details
        'models.catalogRefresh.enabled': False, 'update.checkOnStart': False, 'telemetry.enabled': False,
    }
    for key, want in expect.items():
        if _get(cfg, key) != want:
            errors.append(f'{key} must be {want!r}, got {_get(cfg, key)!r}')
    if not _get(cfg, 'proxy.proxyUrl'):
        errors.append('proxy.proxyUrl must route all egress through the egress proxy')
    if _get(cfg, 'proxy.loopbackMode', 'gateway-only') not in ('gateway-only', 'block'):
        errors.append('proxy.loopbackMode must be gateway-only or block')
    allow = _get(cfg, 'plugins.allow')
    if not isinstance(allow, list) or not allow:
        errors.append('plugins.allow must be a non-empty list (an empty list means no restriction)')
    elif set(allow) - ALLOWED_PLUGINS:
        errors.append(f'plugins.allow has plugins outside {sorted(ALLOWED_PLUGINS)}: {sorted(set(allow) - ALLOWED_PLUGINS)}')
    extra = effective_tools(cfg, errors) - RESEARCH_TOOLS
    if extra:
        errors.append(f'effective tools beyond research set {sorted(RESEARCH_TOOLS)}: {sorted(extra)}')
    for path in _secret_literals(cfg):
        errors.append(f'{path}: secrets must be ${{ENV}} references, never literals')
    return errors


def _json_after_banner(text):
    return json.loads(text[text.find('{'):])


def check_runtime(cfg, plugins_report, audit_report):
    errors = []
    loaded = [p for p in plugins_report.get('plugins', []) if p.get('status') == 'loaded']
    ids = {p['id'] for p in loaded}
    if ids != set(_get(cfg, 'plugins.allow') or []):
        errors.append(f'loaded plugins {sorted(ids)} != plugins.allow {sorted(_get(cfg, "plugins.allow") or [])}')
    for p in loaded:
        if p.get('toolNames') or p.get('hookNames'):
            errors.append(f"plugin {p['id']} adds tools/hooks {p.get('toolNames')}/{p.get('hookNames')} outside the core-tool check")
    critical = (audit_report.get('summary') or {}).get('critical')
    if critical != 0:
        errors.append(f'openclaw security audit reports critical={critical}')
    return errors


def main(argv=None):
    a = argparse.ArgumentParser(description='RESEARCH GROUP OpenClaw policy check')
    a.add_argument('config')
    a.add_argument('--plugins')
    a.add_argument('--audit')
    x = a.parse_args(argv)
    cfg = json.loads(Path(x.config).read_text(encoding='utf-8'))
    errors = check_config(cfg)
    if x.plugins or x.audit:
        if not (x.plugins and x.audit):
            a.error('--plugins and --audit go together')
        errors += check_runtime(cfg, _json_after_banner(Path(x.plugins).read_text(encoding='utf-8')),
                                _json_after_banner(Path(x.audit).read_text(encoding='utf-8')))
    for e in errors:
        print('FAIL', e)
    print('POLICY OK' if not errors else f'POLICY FAIL ({len(errors)})')
    return 0 if not errors else 1


if __name__ == '__main__':
    sys.exit(main())
