// Cloudflare Cron fallback for the GitHub Pages data pipeline.
// This Worker has no public HTTP handler; only the configured cron can run it.

const PAGE_DATA_URL = 'https://kaychen46.github.io/taiwan-trend-radar/data/latest_trends.json';
const WORKFLOW_API_URL = 'https://api.github.com/repos/Kaychen46/taiwan-trend-radar/actions/workflows/run_radar.yml';
const TAIWAN_OFFSET_MS = 8 * 60 * 60 * 1000;

export function isFreshForAfternoon(updatedAt, scheduledTime) {
  if (typeof updatedAt !== 'string' || !/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(updatedAt)) {
    return false;
  }

  const taiwanDate = new Date(scheduledTime + TAIWAN_OFFSET_MS).toISOString().slice(0, 10);
  const afternoonStart = Date.parse(`${taiwanDate}T15:00:00+08:00`);
  const updatedTime = Date.parse(`${updatedAt.replace(' ', 'T')}+08:00`);
  return Number.isFinite(updatedTime) && updatedTime >= afternoonStart;
}

async function siteHasAfternoonUpdate(scheduledTime) {
  try {
    const response = await fetch(`${PAGE_DATA_URL}?check=${scheduledTime}`, {
      cache: 'no-store',
      headers: { 'Cache-Control': 'no-cache' },
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) {
      console.warn(`Published data request failed: ${response.status}`);
      return false;
    }
    const data = await response.json();
    return isFreshForAfternoon(data.updated_at, scheduledTime);
  } catch (error) {
    console.warn(`Published data could not be checked: ${error.name}`);
    return false;
  }
}

function githubHeaders(token) {
  return {
    Accept: 'application/vnd.github+json',
    Authorization: `Bearer ${token}`,
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'taiwan-trend-radar-auto-update',
  };
}

async function hasActiveWorkflowRun(token) {
  const response = await fetch(`${WORKFLOW_API_URL}/runs?branch=main&per_page=20`, {
    headers: githubHeaders(token),
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) {
    throw new Error(`GitHub runs request failed: ${response.status}`);
  }
  const data = await response.json();
  if (!Array.isArray(data.workflow_runs)) {
    throw new Error('GitHub runs response is invalid');
  }
  return data.workflow_runs.some((run) => run.status !== 'completed');
}

async function dispatchWorkflow(token) {
  const response = await fetch(`${WORKFLOW_API_URL}/dispatches`, {
    method: 'POST',
    headers: { ...githubHeaders(token), 'Content-Type': 'application/json' },
    body: JSON.stringify({ ref: 'main' }),
    signal: AbortSignal.timeout(15000),
  });
  if (response.status !== 204) {
    throw new Error(`GitHub workflow dispatch failed: ${response.status}`);
  }
}

export default {
  async scheduled(controller, env) {
    const token = env.GITHUB_ACTIONS_TOKEN;
    if (!token) {
      throw new Error('GITHUB_ACTIONS_TOKEN secret is missing');
    }

    const scheduledTime = controller.scheduledTime;
    if (await siteHasAfternoonUpdate(scheduledTime)) {
      console.log('Published data already updated this afternoon.');
      return;
    }
    if (await hasActiveWorkflowRun(token)) {
      console.log('GitHub workflow is already running.');
      return;
    }
    await dispatchWorkflow(token);
    console.log('Requested GitHub workflow update.');
  },
};
