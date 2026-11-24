import test from 'node:test';
import assert from 'node:assert/strict';

import worker, { isFreshForAfternoon } from './auto_update.mjs';

const checkTime = Date.parse('2026-11-24T07:45:00Z'); // 15:45 in Taiwan

test('accepts only an update after 15:00 Taiwan time today', () => {
  assert.equal(isFreshForAfternoon('2026-11-24 15:01:00', checkTime), true);
  assert.equal(isFreshForAfternoon('2026-11-24 14:59:59', checkTime), false);
  assert.equal(isFreshForAfternoon('2026-11-23 23:31:49', checkTime), false);
  assert.equal(isFreshForAfternoon('unavailable', checkTime), false);
});

async function runWithResponses({ updatedAt, runs = [], runsStatus = 200 }) {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, options = {}) => {
    const url = String(input);
    calls.push({ url, options });
    if (url.includes('/data/latest_trends.json')) {
      return Response.json({ updated_at: updatedAt });
    }
    if (url.includes('/actions/workflows/run_radar.yml/runs')) {
      return Response.json({ workflow_runs: runs }, { status: runsStatus });
    }
    if (url.endsWith('/actions/workflows/run_radar.yml/dispatches')) {
      return new Response(null, { status: 204 });
    }
    throw new Error(`Unexpected URL: ${url}`);
  };
  try {
    await worker.scheduled(
      { scheduledTime: checkTime },
      { GITHUB_ACTIONS_TOKEN: 'test-token' },
      { waitUntil() {} },
    );
    return calls;
  } finally {
    globalThis.fetch = originalFetch;
  }
}

test('does not dispatch when the site already has an afternoon update', async () => {
  const calls = await runWithResponses({ updatedAt: '2026-11-24 15:20:00' });
  assert.equal(calls.length, 1);
});

test('dispatches once when the site is stale and no run is active', async () => {
  const calls = await runWithResponses({ updatedAt: '2026-11-23 23:31:49' });
  assert.equal(calls.length, 3);
  assert.match(calls[2].url, /\/dispatches$/);
  assert.equal(JSON.parse(calls[2].options.body).ref, 'main');
});

test('waits for an existing run instead of dispatching another', async () => {
  const calls = await runWithResponses({
    updatedAt: '2026-11-23 23:31:49',
    runs: [{ status: 'in_progress', created_at: '2026-11-24T07:20:00Z' }],
  });
  assert.equal(calls.length, 2);
});

test('does not dispatch when GitHub run status cannot be checked', async () => {
  await assert.rejects(
    runWithResponses({ updatedAt: '2026-11-23 23:31:49', runsStatus: 503 }),
    /GitHub runs request failed: 503/,
  );
});
