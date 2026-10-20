// Runs INSIDE the gateway container: drives OpenClaw's own tools through POST /tools/invoke (no model, no key).
const token = process.env.OPENCLAW_GATEWAY_TOKEN;
const base = 'http://127.0.0.1:18789';
async function invoke(tool, args) {
  try {
    const r = await fetch(`${base}/tools/invoke`, {
      method: 'POST', headers: { 'content-type': 'application/json', authorization: `Bearer ${token}` },
      body: JSON.stringify({ tool, args }), signal: AbortSignal.timeout(45000),
    });
    return { status: r.status, body: await r.text() };
  } catch (e) { return { status: 0, body: String(e) }; }
}
const ok = (r) => r.status === 200 && !/"ok"\s*:\s*false|"isError"\s*:\s*true|"error"\s*:/.test(r.body);
const cases = [
  ['web_fetch public page', 'allow', 'web_fetch', { url: 'https://example.com/' }, (r) => ok(r) && /Example Domain/i.test(r.body)],
  ['web_fetch metadata IP', 'deny', 'web_fetch', { url: 'http://169.254.169.254/latest/meta-data/' }, (r) => !ok(r)],
  ['web_fetch loopback', 'deny', 'web_fetch', { url: 'http://127.0.0.1:18789/' }, (r) => !ok(r)],
  ['web_fetch name rebinding to loopback', 'deny', 'web_fetch', { url: 'http://localtest.me/' }, (r) => !ok(r)],
  ['read a host file', 'deny', 'read', { path: '/etc/passwd' }, (r) => r.status === 404 || r.status === 403],
  ['write a file', 'deny', 'write', { path: '/workspace/e2e-probe.txt', content: 'probe' }, (r) => r.status === 404 || r.status === 403],
];
for (const tool of ['exec', 'process', 'code_execution', 'browser', 'canvas', 'computer', 'nodes', 'message', 'memory_search',
                    'sessions_list', 'sessions_spawn', 'subagents', 'file_fetch', 'file_write', 'cron', 'gateway', 'plugins', 'edit', 'apply_patch']) {
  cases.push([`tool ${tool} not offered`, 'deny', tool, {}, (r) => r.status === 404 || r.status === 403]);
}
let fails = 0;
for (const [name, kind, tool, args, pass] of cases) {
  const r = await invoke(tool, args);
  const good = pass(r);
  if (!good) fails++;
  console.log(`${good ? 'PASS' : 'FAIL'} ${name} [${kind}] status=${r.status}${good ? '' : ' body=' + r.body.slice(0, 200).replace(/\s+/g, ' ')}`);
}
console.log(fails ? `E2E FAIL (${fails})` : 'E2E OK');
process.exit(fails ? 1 : 0);
