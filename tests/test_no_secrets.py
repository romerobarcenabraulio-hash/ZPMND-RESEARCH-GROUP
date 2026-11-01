"""T7: nothing tracked in git looks like a credential (backstop; the rule is to never have secrets here)."""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = re.compile('|'.join([
    r'sk-ant-[A-Za-z0-9_-]{20,}', r'sk-(proj-)?[A-Za-z0-9]{32,}', r'gh[pousr]_[A-Za-z0-9]{30,}', r'github_pat_[A-Za-z0-9_]{40,}',
    r'AKIA[0-9A-Z]{16}', r'-----BEGIN [A-Z ]*PRIVATE KEY-----', r'xox[baprs]-[A-Za-z0-9-]{10,}', r'AIza[0-9A-Za-z_-]{35}',
    # a database URI with a password for any host but this machine (RG_DB_URL lives only in the repo's secrets)
    r'postgres(?:ql)?://[^:/\s@]+:[^@\s]+@(?!localhost[:/]|127\.0\.0\.1[:/]|\[::1\][:/])(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)',
]))


class NoSecrets(unittest.TestCase):
    def test_pattern_detects_examples(self):
        self.assertTrue(PATTERNS.search('key=sk-ant-' + 'a' * 30))
        self.assertTrue(PATTERNS.search('ghp_' + 'b' * 36))
        self.assertTrue(PATTERNS.search('postgresql://postgres.abc:' + 'x' * 12 + '@aws-0-us-east-1.pooler.supabase.com:5432/postgres'))
        self.assertFalse(PATTERNS.search('postgresql://postgres:postgres@localhost:5432/postgres'))
        self.assertTrue(PATTERNS.search('postgresql://u:' + 'x' * 12 + '@[2001:db8::7]:5432/postgres'))  # GPT on f6c1e87
        self.assertFalse(PATTERNS.search('postgresql://postgres:postgres@[::1]:5432/postgres'))

    def test_tracked_files_have_no_credentials(self):
        files = subprocess.run(['git', 'ls-files', '-co', '--exclude-standard'], cwd=ROOT, capture_output=True,
                               text=True, check=True).stdout.split('\n')
        hits = []
        for name in filter(None, files):
            path = ROOT / name
            if path.is_file() and path.stat().st_size < 2_000_000:
                text = path.read_text(encoding='utf-8', errors='ignore')
                hits += [f'{name}: {m.group(0)[:12]}...' for m in PATTERNS.finditer(text)]
        self.assertEqual(hits, [])


if __name__ == '__main__':
    unittest.main()
