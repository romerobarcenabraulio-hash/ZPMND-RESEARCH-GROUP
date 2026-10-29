"""scripts/turno.sh: which of the owner's credentials a model call gets, one at a time, as the step order says.

Built here (CONSTRUIDO): a fake CLI that writes what it saw (its environment's credentials and its command line) and
fails or answers as told; the real turno.sh run by bash, as the investigar.yml steps run it.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAKE = r'''#!/bin/bash
# what this call saw, and an answer or a failure as $FAIL_WITH says
cred=none
[ -n "${ANTHROPIC_API_KEY:-}" ] && cred="api:$ANTHROPIC_API_KEY"
[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && cred="$cred+sub:$CLAUDE_CODE_OAUTH_TOKEN"
echo "$cred|${RG_API:-}|${RG_SUSCRIPCION:-}|$*" >> "$SEEN"
cat > /dev/null
if [ -n "$FAIL_WITH" ]; then case "${cred%%:*}" in *"$FAIL_WITH"*) echo '{"is_error": true}'; exit 7 ;; esac; fi
echo "{\"answer\": \"${cred%%:*}\"}"
'''


@unittest.skipUnless(shutil.which('bash'), 'needs bash, as on the runner')
class Turno(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.cli = self.d / 'claude'
        self.cli.write_text(FAKE)
        self.cli.chmod(0o755)
        (self.d / 'in.txt').write_text('prompt')

    def turno(self, order, api='KEY-API', sub='KEY-SUB', fail=''):
        env = {'PATH': os.environ['PATH'], 'SEEN': str(self.d / 'seen'), 'FAIL_WITH': fail, 'RG_ORDEN': order,
               'RG_API': api, 'RG_SUSCRIPCION': sub,
               'ANTHROPIC_API_KEY': 'STEP-API', 'CLAUDE_CODE_OAUTH_TOKEN': 'STEP-SUB'}  # whatever the step held never reaches a call
        script = (f'set -euo pipefail\n. "{ROOT / "scripts" / "turno.sh"}"\n'
                  f'turno "{self.d / "out.json"}" "{self.d / "in.txt"}" "{self.cli}" -p --tools "" \\\n  || exit $?\n'
                  'echo "after: ${RG_API:-}${RG_SUSCRIPCION:-}"')
        r = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
        seen = (self.d / 'seen').read_text().splitlines() if (self.d / 'seen').exists() else []
        out = (self.d / 'out.json').read_text() if (self.d / 'out.json').exists() else ''
        return r.returncode, r.stdout, seen, out

    def test_the_light_order_takes_the_api_first_and_only_that(self):
        rc, stdout, seen, out = self.turno('api')
        self.assertEqual((rc, seen, json.loads(out)), (0, ['api:KEY-API|||-p --tools '], {'answer': 'api'}))
        self.assertIn('credencial: api', stdout)
        self.assertIn('after: \n', stdout + '\n')  # the step's credentials left the environment

    def test_a_failed_api_call_falls_back_to_the_subscription_and_the_answer_is_the_last_one(self):
        rc, stdout, seen, out = self.turno('api', fail='api')
        self.assertEqual(rc, 0)
        self.assertEqual(seen, ['api:KEY-API|||-p --tools ', 'none+sub:KEY-SUB|||-p --tools '])  # one credential each
        self.assertEqual(json.loads(out), {'answer': 'none+sub'})  # not both answers in one file
        self.assertIn('la llamada con api terminó con 7', stdout)

    def test_the_heavy_order_is_the_subscription_alone_and_never_falls_back_to_the_key(self):
        for order in ('', 'suscripcion', 'otra cosa'):
            with self.subTest(order=order):
                (self.d / 'seen').unlink(missing_ok=True)
                rc, _, seen, _ = self.turno(order, fail='sub')
                self.assertEqual((rc, seen), (7, ['none+sub:KEY-SUB|||-p --tools ']))  # the key, though present, never used

    def test_a_missing_credential_is_skipped_and_none_at_all_fails(self):
        rc, _, seen, _ = self.turno('api', api='')
        self.assertEqual((rc, seen), (0, ['none+sub:KEY-SUB|||-p --tools ']))
        (self.d / 'seen').unlink()
        rc, _, seen, _ = self.turno('api', api='', sub='')
        self.assertEqual((rc, seen), (1, []))

    def test_no_credential_ever_reaches_a_command_line(self):
        self.turno('api', fail='api')
        for line in (self.d / 'seen').read_text().splitlines():
            self.assertNotIn('KEY-', line.split('|', 3)[3])


if __name__ == '__main__':
    unittest.main()
