"""Cost guards in the workflows: minutes are spent only where they buy certainty (docs/COSTOS.md)."""
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[1] / '.github' / 'workflows'


def load(name):
    return yaml.safe_load((WF / name).read_text(encoding='utf-8'))


def on(doc):
    return doc.get('on', doc.get(True))  # YAML 1.1 reads the key `on` as True


class Mutation(unittest.TestCase):
    def test_mutation_runs_only_on_pull_requests(self):
        self.assertEqual(load('ci.yml')['jobs']['mutation']['if'], "github.event_name == 'pull_request'")


class CatalogChain(unittest.TestCase):
    def setUp(self):
        self.doc = load('catalog-mx.yml')
        self.chain = self.doc['jobs']['chain']

    def test_the_chain_can_only_dispatch_this_workflow_from_main(self):
        self.assertEqual(self.chain['permissions'], {'actions': 'write'})
        self.assertEqual(self.chain['needs'], 'run')
        run = self.chain['steps'][0]['run']
        self.assertIn('gh workflow run catalog-mx.yml -R "$GITHUB_REPOSITORY" --ref main', run)
        self.assertIn('-f chain="$(( CHAIN - 1 ))"', run)  # one less each time: it ends by construction

    def test_the_chain_is_bounded_and_opt_in(self):
        self.assertEqual(self.chain['if'], "needs.run.outputs.more == 'true' && inputs.chain != '' && inputs.chain != '0'"
                                           " && !cancelled() && needs.run.outputs.published == 'true'"
                                           " && contains(fromJSON('[\"0\", \"3\", \"4\"]'), needs.run.outputs.rc)")
        self.assertIn('(( CHAIN >= 1 && CHAIN <= 30 ))', self.chain['steps'][0]['run'])
        self.assertEqual(set(on(self.doc)), {'schedule', 'workflow_dispatch'})  # never code from a pull request

    def test_a_data_finding_does_not_stop_the_catch_up_but_a_broken_run_does(self):
        # 2026-10-27: one unparsed NOM title (exit 3) stopped the DOF catch-up for six days. A finding still fails the
        # run; only a run whose data was scanned for tokens, uploaded and pushed hands on, and never after a crash.
        run = self.doc['jobs']['run']
        self.assertEqual(run['outputs'], {'more': '${{ steps.catalog.outputs.more }}', 'rc': '${{ steps.catalog.outputs.rc }}',
                                          'published': '${{ steps.commit.outputs.published }}'})
        names = [s.get('name') or s.get('uses', '') for s in run['steps']]
        commit = next(s for s in run['steps'] if s.get('id') == 'commit')
        self.assertEqual(commit['run'].strip().splitlines()[-1], 'echo "published=true" >> "$GITHUB_OUTPUT"')  # after the push
        scan, upload = names.index('No token in anything that is committed or uploaded'), names.index(next(n for n in names if n.startswith('Upload raw bundle')))
        self.assertLess(scan, upload)
        self.assertLess(upload, run['steps'].index(commit))
        self.assertLess(run['steps'].index(commit), names.index('Fail on coverage or schema problems'))
        catalog = next(s for s in run['steps'] if s.get('id') == 'catalog')
        self.assertIn('echo "rc=$?" >> "$GITHUB_OUTPUT"', catalog['run'])

    def test_only_main_writes_the_data_branch(self):
        self.assertEqual(self.doc['jobs']['run']['if'], "github.ref == 'refs/heads/main'")


class ChainInputs(unittest.TestCase):
    """The chain step's own script, run against a stub gh: only plain numbers in range dispatch, and an input is never
    evaluated as an expression (GPT review of #19, c671ad3)."""

    def dispatch(self, chain, budget='12000', index_days='1500'):
        step = load('catalog-mx.yml')['jobs']['chain']['steps'][0]['run']
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'gh').write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$GH_ARGS"\n', encoding='utf-8')
            (Path(d) / 'gh').chmod(0o755)
            env = {**os.environ, 'PATH': d + os.pathsep + os.environ['PATH'], 'GH_ARGS': str(Path(d) / 'args'),
                   'GITHUB_REPOSITORY': 'o/r', 'CHAIN': chain, 'BUDGET': budget, 'INDEX_DAYS': index_days}
            r = subprocess.run(['bash', '-c', step], cwd=d, env=env, capture_output=True, text=True, timeout=30)
            args = (Path(d) / 'args').read_text(encoding='utf-8').split('\n') if (Path(d) / 'args').exists() else None
            return r.returncode, args, (Path(d) / 'pwned').exists()

    def test_a_number_in_range_dispatches_one_less(self):
        rc, args, _ = self.dispatch('3')
        self.assertEqual(rc, 0)
        self.assertEqual(args[:9], ['workflow', 'run', 'catalog-mx.yml', '-R', 'o/r', '--ref', 'main', '-f', 'budget=12000'])
        self.assertIn('chain=2', args)

    def test_anything_but_a_plain_number_in_range_dispatches_nothing(self):
        for chain in ('0', '31', '1+1', '2*3', 'a[$(touch pwned)]', ' 3', ''):
            rc, args, pwned = self.dispatch(chain)
            self.assertEqual((rc, args, pwned), (2, None, False), repr(chain))
        for budget, days in (('12x', '1'), ('1', '$(touch pwned)'), ('1-1', '1')):
            rc, args, pwned = self.dispatch('3', budget, days)
            self.assertEqual((rc, args, pwned), (2, None, False), (budget, days))


class ThisRunsManifest(unittest.TestCase):
    """`more` must come from the manifest this run wrote, never from an older one already on the data branch."""

    def more(self, old_text, new_text):
        step = next(s for s in load('catalog-mx.yml')['jobs']['run']['steps'] if s.get('id') == 'catalog')['run']
        lines = [l.strip() for l in step.splitlines()]
        pick = next(l for l in lines if l.startswith('manifest=$(find data/mx/runs'))
        decide = next(l for l in lines if l.startswith('more=$('))
        with tempfile.TemporaryDirectory() as d:
            runs = Path(d) / 'data' / 'mx' / 'runs'
            runs.mkdir(parents=True)
            if old_text is not None:
                (runs / '2026-10-01T000000Z.json').write_text(old_text, encoding='utf-8')
                past = time.time() - 3600
                os.utime(runs / '2026-10-01T000000Z.json', (past, past))
            script = f'marker=$(mktemp)\n'
            if new_text is not None:
                script += f"sleep 0.01; printf '%s' {new_text!r} > data/mx/runs/2026-10-22T000000Z.json\n"
            script += f'{pick}\n{decide}\necho "$more"\n'
            out = subprocess.run(['bash', '-c', script], cwd=d, capture_output=True, text=True, check=True, timeout=30)
            return out.stdout.strip()

    def test_more_reads_only_this_runs_manifest(self):
        old = '{"errors": ["mx.dof: request budget reached (continues next run)"]}'
        self.assertEqual(self.more(old, None), 'false')  # this run wrote nothing: not the old run's answer
        self.assertEqual(self.more(old, '{"errors": []}'), 'false')
        self.assertEqual(self.more(None, '{"errors": ["mx.dof: request budget reached (continues next run)"]}'), 'true')



class OwnRunner(unittest.TestCase):
    """scripts/runner_setup.sh and the catalog job: only main's catalog and text runs reach the rented server, each in a
    runner that lives for one job (GPT on 2308494)."""
    REPO = 'romerobarcenabraulio-hash/ZPMND-RESEARCH-GROUP'

    def setUp(self):
        import re
        self.script = (WF.parents[1] / 'scripts' / 'runner_setup.sh').read_text(encoding='utf-8')
        self.guard = re.search(r"<<'GUARD'\n(.*?)\nGUARD\n", self.script, re.S).group(1)

    def allowed(self, event, workflow_ref):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GITHUB_')}
        if event is not None:
            env['GITHUB_EVENT_NAME'] = event
        if workflow_ref is not None:
            env['GITHUB_WORKFLOW_REF'] = workflow_ref
        try:  # a guard that hangs is a guard that fails (REGLAS 13)
            return subprocess.run(['bash', '-c', self.guard], env=env, capture_output=True, timeout=10).returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def test_the_guard_lets_in_only_main_catalog_and_text_runs_on_schedule_or_dispatch(self):
        main = f'{self.REPO}/.github/workflows/catalog-mx.yml@refs/heads/main'
        self.assertTrue(self.allowed('schedule', main))
        self.assertTrue(self.allowed('workflow_dispatch', f'{self.REPO}/.github/workflows/texto-mx.yml@refs/heads/main'))
        self.assertFalse(self.allowed('workflow_dispatch', f'{self.REPO}/.github/workflows/catalog-mx.yml@refs/heads/x'))
        self.assertFalse(self.allowed('pull_request', main))
        self.assertFalse(self.allowed('pull_request_target', main))
        self.assertFalse(self.allowed('push', main))
        self.assertFalse(self.allowed('workflow_dispatch', f'{self.REPO}/.github/workflows/ci.yml@refs/heads/main'))
        self.assertFalse(self.allowed('workflow_dispatch', f'otro/repo/.github/workflows/catalog-mx.yml@refs/heads/main'))
        self.assertFalse(self.allowed(None, None))  # missing context fails closed

    def test_the_token_is_roots_alone_and_never_an_argument(self):
        self.assertIn('read -rsp', self.script)
        self.assertIn('[[ "$token" =~ ^github_pat_[A-Za-z0-9_]{50,255}$ ]]', self.script)
        self.assertIn("(umask 077 && printf 'Authorization: Bearer %s\\n' \"$token\" > /etc/rg/auth-header)", self.script)
        self.assertIn('install -d -o root -g root -m 700 /etc/rg', self.script)
        self.assertIn('chown root:root /etc/rg/auth-header && chmod 600 /etc/rg/auth-header', self.script)
        self.assertLess(self.script.index('unset token'), self.script.index('curl -fsS -o /dev/null -H @/etc/rg/auth-header'))
        self.assertNotIn('--token', self.script)
        self.assertEqual(self.script.count('Bearer'), 1)  # written once, into the root-only file

    def test_the_installer_proves_the_jobs_user_reaches_none_of_it_before_starting_anything(self):
        check = 'bash "$HERE/runner_reach.sh" rgjob /etc/rg "$DIR" /opt/rg /var/lib/rg /etc/systemd/system/rg-runner.service\n'
        self.assertIn(check, self.script)
        # set -e makes a failed check the end of the install, and nothing is enabled or started before it (GPT on fa742b6)
        self.assertIn('set -euo pipefail\n', self.script)
        self.assertLess(self.script.index(check), self.script.index('systemctl enable --now rg-runner'))
        self.assertLess(self.script.index('systemctl disable --now rg-runner'), self.script.index(check))
        self.assertEqual(self.script.count('systemctl enable'), 1)
        self.assertIn('chown -R root:root "$DIR"', self.script)
        self.assertIn('chown root:root /opt/rg/runner_guard.sh && chmod 755 /opt/rg/runner_guard.sh', self.script)
        self.assertIn('install -o root -g root -m 755 "$HERE/runner_controller.sh" /opt/rg/runner_controller.sh', self.script)
        self.assertNotIn('svc.sh', self.script)  # no long-lived runner service: only the controller's one-job runners
        self.assertNotIn('config.sh', self.script)

    def test_the_installer_refuses_a_python_older_than_the_one_ci_tests(self):
        self.assertIn("python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))'", self.script)
        self.assertLess(self.script.index('sys.version_info < (3, 12)'), self.script.index('apt-get update'))

    def test_the_runner_is_verified(self):
        self.assertIn('echo "$RUNNER_SHA256  $tmp/runner.tgz" | sha256sum -c -', self.script)
        self.assertRegex(self.script, r'RUNNER_SHA256=[0-9a-f]{64}\b')

    def test_the_catalog_and_text_jobs_move_only_by_the_variable_and_start_from_a_fresh_venv(self):
        run = load('catalog-mx.yml')['jobs']['run']
        self.assertEqual(run['if'], "github.ref == 'refs/heads/main'")
        self.assertEqual(run['runs-on'], """${{ fromJSON(vars.CATALOG_RUNS_ON || '"ubuntu-24.04"') }}""")
        by = {s.get('name') or s.get('uses'): s for s in run['steps']}
        self.assertEqual(by['Free runner disk (the raw corpus and its parts need the room)']['if'], "runner.environment == 'github-hosted'")
        setup = next(s for s in run['steps'] if s.get('uses', '').startswith('actions/setup-python@'))
        self.assertEqual(setup['if'], "runner.environment == 'github-hosted'")
        for wf, job in (('catalog-mx.yml', 'run'), ('texto-mx.yml', next(iter(load('texto-mx.yml')['jobs'])))):
            step = next(s for s in load(wf)['jobs'][job]['steps'] if s.get('name', '').startswith('Python on our own runner'))
            self.assertEqual(step['if'], "runner.environment != 'github-hosted'", wf)
            with tempfile.TemporaryDirectory() as d:  # a venv left by an earlier job stops this one
                Path(d, 'venv').mkdir()
                r = subprocess.run(['bash', '-c', step['run']], env={**os.environ, 'RUNNER_TEMP': d, 'GITHUB_PATH': os.devnull},
                                   capture_output=True, text=True, timeout=60)
                self.assertNotEqual(r.returncode, 0, wf)
                self.assertIn('this runner is not fresh', r.stdout, wf)


STUB_CURL = r"""#!/bin/bash
printf '%s\n' "$*" >> "$STUBS/curl.argv"
url=; method=GET; body=
while [ $# -gt 0 ]; do
  case "$1" in -X) method=$2; shift ;; --data) body=$(cat); ;; https://*) url=$1 ;; esac; shift
done
case "$method $url" in
  "GET "*"/runs?status=queued"*) cat "$STUBS/runs_queued.json" ;;
  "GET "*"/runs?status=in_progress"*) cat "$STUBS/runs_progress.json" ;;
  "GET "*"/runs/"*"/jobs"*) id=${url##*/runs/}; id=${id%%/*}; cat "$STUBS/jobs_$id.json" 2>/dev/null || exit 22 ;;
  "POST "*"/runners/generate-jitconfig") printf '%s' "$body" > "$STUBS/jit.body"; cat "$STUBS/jit.json" || exit 22 ;;
  "GET "*"/runners/"*) echo '{"busy": true}' ;;
  "DELETE "*"/runners/"*) echo "${url##*/}" >> "$STUBS/deleted" ;;
  *) exit 22 ;;
esac
"""
STUB_SYSTEMD_RUN = r"""#!/bin/bash
printf '%s\n' "$@" > "$STUBS/systemd-run.argv"
stat -c '%a' "$RG_JOB_DIR/jit" > "$STUBS/jit.mode" 2>/dev/null || stat -f '%Lp' "$RG_JOB_DIR/jit" > "$STUBS/jit.mode"
ls -A "$RG_JOB_HOME" > "$STUBS/home.before"
cp "$RG_JOB_DIR/runner/.env" "$STUBS/env.file"
mkdir -p "$RG_JOB_HOME/.local/lib" "$RG_JOB_DIR/runner/_work/_temp/venv"   # what a job could leave behind
echo 'import os' > "$RG_JOB_HOME/.local/lib/evil.pth"; echo x > "$RG_JOB_DIR/runner/_work/_temp/venv/evil.pth"
exit "${STUB_RUN_RC:-0}"
"""
STUB_SYSTEMCTL = r"""#!/bin/bash
printf '%s\n' "$*" >> "$STUBS/systemctl.argv"
[ "$1" = is-active ] && exit 3
exit 0
"""


@unittest.skipIf(os.geteuid() == 0, 'root ignores the permissions this proves')
class Reach(unittest.TestCase):
    """scripts/runner_reach.sh, run for real against real permissions as the current user (GPT on fa742b6: a check that
    cannot finish must refuse, not abort or pass)."""

    def setUp(self):
        import getpass
        self.user = getpass.getuser()
        self.t = Path(tempfile.mkdtemp())
        self.secret = self.t / 'secret'; self.secret.mkdir(); (self.secret / 'auth-header').write_text('x')
        self.tree = self.t / 'tree'; (self.tree / 'sub').mkdir(parents=True); (self.tree / 'sub' / 'f').write_text('x')
        self.lock()

    def lock(self):
        (self.tree / 'sub' / 'f').chmod(0o444); (self.tree / 'sub').chmod(0o555); self.tree.chmod(0o555); self.secret.chmod(0o000)

    def tearDown(self):
        for p in (self.secret, self.tree, self.tree / 'sub'):
            p.chmod(0o755)
        import shutil
        shutil.rmtree(self.t)

    def reach(self):
        return subprocess.run(['bash', str(WF.parents[1] / 'scripts' / 'runner_reach.sh'), self.user, str(self.secret),
                               str(self.tree)], capture_output=True, text=True, timeout=30)

    def test_nothing_reachable_passes(self):
        r = self.reach()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_an_enterable_secret_folder_fails(self):
        self.secret.chmod(0o700)
        r = self.reach()
        self.assertEqual(r.returncode, 1); self.assertIn('can enter', r.stdout)

    def test_a_writable_file_fails(self):
        (self.tree / 'sub').chmod(0o755); (self.tree / 'sub' / 'f').chmod(0o644); (self.tree / 'sub').chmod(0o555)
        r = self.reach()
        self.assertEqual(r.returncode, 1); self.assertIn('can write', r.stdout)

    def test_a_folder_it_cannot_read_fails_instead_of_passing(self):
        (self.tree / 'sub').chmod(0o000)
        r = self.reach()
        self.assertEqual(r.returncode, 1); self.assertIn('could not check', r.stdout)

class Limits(unittest.TestCase):
    """GPT on fa742b6: the long runs the server is for must exist: on our own runner the job may last 23 hours, each run's
    own deadline ends it before that, and the unit's 24-hour cap is outside both; GitHub's runners keep 300 minutes."""

    def test_the_run_deadline_fits_inside_the_job_and_the_job_inside_the_unit(self):
        import re
        unit = int(re.search(r'RuntimeMaxSec=(\d+)', (WF.parents[1] / 'scripts' / 'runner_controller.sh').read_text()).group(1))
        for wf in ('catalog-mx.yml', 'texto-mx.yml'):
            with self.subTest(wf=wf):
                text = (WF / wf).read_text(encoding='utf-8')
                switch = "contains(vars.CATALOG_RUNS_ON || '', 'self-hosted')"
                own, hosted = map(int, re.search(r"timeout-minutes: \$\{\{ " + re.escape(switch) + r" && (\d+) \|\| (\d+) \}\}", text).groups())
                d_own, d_hosted = map(int, re.search(r"DEADLINE_MINUTES: \$\{\{ " + re.escape(switch) + r" && '(\d+)' \|\| '(\d+)' \}\}", text).groups())
                self.assertIn('--deadline-minutes "$DEADLINE_MINUTES"', text)
                self.assertEqual(hosted, 300)
                self.assertLessEqual(d_hosted + 60, hosted)   # an hour to publish what the run found
                self.assertLessEqual(d_own + 60, own)
                self.assertLess(own * 60, unit)
                self.assertGreater(own, 360)                   # longer than GitHub's six hours, or the server buys nothing

class Controller(unittest.TestCase):
    """scripts/runner_controller.sh, one pass, against stubs of GitHub's API and systemd."""
    REPO = OwnRunner.REPO
    TOKEN = 'github_pat_' + 'S3CRET' * 12

    def setUp(self):
        import grp
        import json
        import pwd
        self.json = json
        self.t = Path(tempfile.mkdtemp())
        self.stubs = self.t / 'stubs'; self.stubs.mkdir()
        bin_ = self.t / 'bin'; bin_.mkdir()
        for name, body in (('curl', STUB_CURL), ('systemd-run', STUB_SYSTEMD_RUN), ('systemctl', STUB_SYSTEMCTL),
                           ('pkill', '#!/bin/bash\nexit "${STUB_PKILL_RC:-1}"\n'),
                           ('pgrep', '#!/bin/bash\n[ -z "${STUB_SURVIVOR:-}" ] || exit 0\nexit "${STUB_PGREP_RC:-1}"\n')):
            (bin_ / name).write_text(body); (bin_ / name).chmod(0o755)
        (self.t / 'etc-rg').mkdir()
        self.header = self.t / 'etc-rg' / 'auth-header'
        self.header.write_text(f'Authorization: Bearer {self.TOKEN}\n')
        runner = self.t / 'runner'; runner.mkdir(); (runner / 'run.sh').write_text('#!/bin/bash\n')
        self.job, self.home = self.t / 'job', self.t / 'home'
        self.env = {**os.environ, 'PATH': f'{bin_}:{os.environ["PATH"]}', 'STUBS': str(self.stubs), 'RG_CONTROLLER_ONCE': '1',
                    'RG_AUTH_HEADER': str(self.header), 'RG_RUNNER_DIR': str(runner), 'RG_JOB_DIR': str(self.job),
                    'RG_JOB_HOME': str(self.home), 'RG_JOB_USER': pwd.getpwuid(os.getuid()).pw_name,
                    'RG_JOB_GROUP': grp.getgrgid(os.getgid()).gr_name}
        self.queue(run={})
        (self.stubs / 'jit.json').write_text('{"runner": {"id": 77}, "encoded_jit_config": "Sk1U"}')

    def queue(self, run=None, job=None):
        base = {'id': 5, 'path': '.github/workflows/catalog-mx.yml', 'event': 'schedule', 'head_branch': 'main',
                'repository': {'full_name': self.REPO}, 'head_repository': {'full_name': self.REPO}}
        runs = [] if run is None else [{**base, **run}]
        (self.stubs / 'runs_queued.json').write_text(self.json.dumps({'workflow_runs': runs}))
        (self.stubs / 'runs_progress.json').write_text('{"workflow_runs": []}')
        j = {'status': 'queued', 'labels': ['self-hosted', 'rg-catalog'], **(job or {})}
        (self.stubs / 'jobs_5.json').write_text(self.json.dumps({'jobs': [j]}))

    def run_pass(self, **extra):
        return subprocess.run(['bash', str(WF.parents[1] / 'scripts' / 'runner_controller.sh')], env={**self.env, **extra},
                              capture_output=True, text=True, timeout=60)

    def started(self):
        return (self.stubs / 'systemd-run.argv').exists()

    def test_an_allowed_queued_job_gets_one_runner_for_one_job(self):
        r = self.run_pass()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = self.json.loads((self.stubs / 'jit.body').read_text())
        self.assertEqual({k: body[k] for k in ('runner_group_id', 'labels', 'work_folder')},
                         {'runner_group_id': 1, 'labels': ['self-hosted', 'rg-catalog'], 'work_folder': '_work'})
        argv = (self.stubs / 'systemd-run.argv').read_text().split('\n')
        for want in ('--unit=rg-job-77', f'--uid={self.env["RG_JOB_USER"]}', 'KillMode=control-group', 'NoNewPrivileges=yes',
                     'PrivateTmp=yes', 'ProtectSystem=strict', f'ReadWritePaths={self.job}', f'ReadWritePaths={self.home}',
                     f'InaccessiblePaths={self.header.parent}', 'RestrictSUIDSGID=yes', 'RuntimeMaxSec=86400'):
            self.assertIn(want, argv)
        self.assertEqual((self.stubs / 'jit.mode').read_text().strip(), '600')
        self.assertEqual((self.stubs / 'home.before').read_text(), '')  # the job starts from an empty home
        self.assertEqual((self.stubs / 'deleted').read_text().split(), ['77'])
        self.assertEqual((self.stubs / 'env.file').read_text(), 'ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/rg/runner_guard.sh\n')

    def test_nothing_a_job_leaves_reaches_the_next_one_even_when_it_fails(self):
        for rc in ('0', '1'):
            with self.subTest(rc=rc):
                r = self.run_pass(STUB_RUN_RC=rc)
                self.assertFalse(self.job.exists(), r.stdout + r.stderr)   # its folder, with the seeded venv and .pth
                self.assertFalse(self.home.exists())  # its home, with the seeded .pth
                (self.stubs / 'systemd-run.argv').unlink(missing_ok=True)

    def test_a_process_that_survives_its_job_stops_the_service(self):
        r = self.run_pass(STUB_SURVIVOR='1')
        self.assertEqual(r.returncode, 1)
        self.assertIn('survived', r.stdout)
        self.assertFalse(self.started())  # caught by the clean pass before any runner starts

    def test_a_cleanup_that_cannot_tell_or_cannot_kill_stops_the_service(self):
        # GPT on fa742b6: only pgrep's 1 (no process) may let the next job in; an error is not an empty list
        for extra in ({'STUB_PGREP_RC': '2'}, {'STUB_PGREP_RC': '3'}, {'STUB_PKILL_RC': '2'}, {'STUB_PKILL_RC': '3'}):
            with self.subTest(**extra):
                self.job.mkdir(exist_ok=True)
                r = self.run_pass(**extra)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn('stopping', r.stdout)
                self.assertFalse(self.started())
                self.assertTrue(self.job.exists())  # nothing is deleted or reused on a cleanup that could not finish

    def test_the_token_never_reaches_a_command_line(self):
        self.run_pass()
        argv = (self.stubs / 'curl.argv').read_text()
        self.assertIn(f'-H @{self.header}', argv)
        self.assertNotIn(self.TOKEN, argv)
        self.assertNotIn(self.TOKEN, (self.stubs / 'systemd-run.argv').read_text())

    def test_no_runner_for_anything_else(self):
        cases = {'no queued run': None,
                 'another workflow': {'path': '.github/workflows/ci.yml'},
                 'a pull request': {'event': 'pull_request'},
                 'a push': {'event': 'push'},
                 'a branch': {'head_branch': 'feature'},
                 'a fork': {'head_repository': {'full_name': 'otro/repo'}}}
        for name, run in cases.items():
            with self.subTest(name=name):
                self.queue(run=run)
                r = self.run_pass()
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertFalse((self.stubs / 'jit.body').exists())
                self.assertFalse(self.started())
        for name, job in {'another label': {'labels': ['ubuntu-24.04']}, 'already running': {'status': 'in_progress'}}.items():
            with self.subTest(name=name):
                self.queue(run={}, job=job)
                self.run_pass()
                self.assertFalse((self.stubs / 'jit.body').exists())

    def test_github_not_answering_or_giving_no_runner_starts_nothing(self):
        (self.stubs / 'runs_queued.json').unlink()
        r = self.run_pass()
        self.assertIn('GitHub did not answer', r.stdout)
        self.assertFalse(self.started())
        self.queue(run={})
        (self.stubs / 'jit.json').write_text('{"message": "Bad credentials"}')
        r = self.run_pass()
        self.assertIn('GitHub gave no runner', r.stdout)
        self.assertFalse(self.started())

    def test_no_token_no_service(self):
        self.header.unlink()
        r = self.run_pass()
        self.assertEqual(r.returncode, 1)
        self.assertIn('no token', r.stdout)


if __name__ == '__main__':
    unittest.main()
