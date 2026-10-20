"""T6: the OpenClaw profile is judged by its effective result; each trap found on 2026.10.5 has a case."""
import copy
import json
import unittest
from pathlib import Path

from rg.openclaw_policy import check_config, check_runtime

CONFIG = json.loads((Path(__file__).resolve().parent.parent / 'substrate' / 'openclaw.json').read_text(encoding='utf-8'))
GOOD_PLUGINS = {'plugins': [{'id': 'anthropic', 'status': 'loaded', 'toolNames': [], 'hookNames': []},
                            {'id': 'web-readability', 'status': 'loaded', 'toolNames': [], 'hookNames': []},
                            {'id': 'browser', 'status': 'disabled', 'toolNames': ['browser'], 'hookNames': []}]}
GOOD_AUDIT = {'summary': {'critical': 0, 'warn': 1, 'info': 1}}


def mutate(fn, base=CONFIG):
    obj = copy.deepcopy(base)
    fn(obj)
    return obj


class Static(unittest.TestCase):
    def test_repository_profile_passes(self):
        self.assertEqual(check_config(CONFIG), [])

    def test_empty_plugin_allowlist_is_not_deny_all(self):
        self.assertTrue(check_config(mutate(lambda c: c['plugins'].update(allow=[]))))
        self.assertTrue(check_config(mutate(lambda c: c['plugins'].pop('allow'))))

    def test_unlisted_plugin_rejected(self):
        self.assertTrue(check_config(mutate(lambda c: c['plugins']['allow'].append('browser'))))

    def test_typo_in_deny_is_caught(self):
        errors = check_config(mutate(lambda c: c['tools']['deny'].append('group:runtim')))
        self.assertTrue(any('unknown tool or group' in e for e in errors))

    def test_effective_tools_limited_to_research(self):
        for extra in ('exec', 'read', 'write', 'browser', 'sessions_spawn', 'group:fs', 'group:runtime'):
            self.assertTrue(check_config(mutate(lambda c: c['tools']['alsoAllow'].append(extra))), extra)

    def test_unfiltered_profiles_rejected(self):
        for profile in ('full', 'coding', 'messaging', None):
            self.assertTrue(check_config(mutate(lambda c: c['tools'].update(profile=profile))), profile)

    def test_hardening_switches(self):
        cases = [
            lambda c: c['tools']['exec'].update(security='allowlist'), lambda c: c['tools'].update(codeMode=True),
            lambda c: c['tools']['elevated'].update(enabled=True), lambda c: c['tools']['fs'].update(workspaceOnly=False),
            lambda c: c['tools']['agentToAgent'].update(enabled=True), lambda c: c['browser'].update(enabled=True),
            lambda c: c['plugins'].pop('slots'), lambda c: c['gateway'].update(bind='lan'), lambda c: c.pop('proxy'),
            lambda c: c['models']['catalogRefresh'].update(enabled=True), lambda c: c['update'].update(checkOnStart=True),
            lambda c: c['telemetry'].update(enabled=True),
        ]
        for fn in cases:
            self.assertTrue(check_config(mutate(fn)))

    def test_literal_secrets_rejected(self):
        self.assertTrue(check_config(mutate(lambda c: c['gateway']['auth'].update(token='hunter2-literal'))))
        self.assertTrue(check_config(mutate(lambda c: c.setdefault('models', {}).update(apiKey='sk-ant-xxxx'))))


class Runtime(unittest.TestCase):
    def test_measured_runtime_passes(self):
        self.assertEqual(check_runtime(CONFIG, GOOD_PLUGINS, GOOD_AUDIT), [])

    def test_extra_loaded_plugin_rejected(self):
        report = copy.deepcopy(GOOD_PLUGINS)
        report['plugins'].append({'id': 'memory-core', 'status': 'loaded', 'toolNames': ['memory_get'], 'hookNames': []})
        self.assertTrue(check_runtime(CONFIG, report, GOOD_AUDIT))

    def test_plugin_adding_tools_or_hooks_rejected(self):
        report = copy.deepcopy(GOOD_PLUGINS)
        report['plugins'][0]['hookNames'] = ['before_tool_call']
        self.assertTrue(check_runtime(CONFIG, report, GOOD_AUDIT))

    def test_critical_audit_finding_rejected(self):
        self.assertTrue(check_runtime(CONFIG, GOOD_PLUGINS, {'summary': {'critical': 1}}))
        self.assertTrue(check_runtime(CONFIG, GOOD_PLUGINS, {}))


if __name__ == '__main__':
    unittest.main()
