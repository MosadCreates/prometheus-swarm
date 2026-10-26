import { createClient } from "redis";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const REDIS_HOST = process.env.REDIS_HOST || "localhost";
const REDIS_PORT = parseInt(process.env.REDIS_PORT || "6379");

// MissionPhase values the orchestrator persists (see contracts/state.py).
const ACTIVE_MARKERS = ["_RUNNING", "RETRY_", "HARBOR_DEPLOYING", "DISSECT_", "SCOUT_RETRAIN"];
const QUEUED_MARKERS = ["MISSION_CREATED", "RETRY_PENDING", "QUEUED"];
const COMPLETED_MARKERS = ["MISSION_PASSED", "HARBOR_COMPLETED", "ENDPOINT_LIVE"];
const FAILED_MARKERS = ["MISSION_FAILED", "TRAINING_FAILED", "CANCELLED", "ESCALATE"];

function classify(status: string): "active" | "queued" | "completed" | "failed" | "unknown" {
  if (!status) return "unknown";
  const s = status.toUpperCase();
  if (ACTIVE_MARKERS.some((m) => s.includes(m))) return "active";
  if (QUEUED_MARKERS.some((m) => s.includes(m))) return "queued";
  if (COMPLETED_MARKERS.some((m) => s.includes(m))) return "completed";
  if (FAILED_MARKERS.some((m) => s.includes(m))) return "failed";
  return "unknown";
}

interface RecentMission {
  id: string;
  name: string;
  status: string;
  progress: number;
  agents: string[];
  started: string;
  eta: string;
}

export async function GET() {
  const client = createClient({ url: `redis://${REDIS_HOST}:${REDIS_PORT}` });
  await client.connect();

  try {
    const keys = await client.keys("job:*");
    const jobMap = new Map<string, Record<string, string>>();

    for (const key of keys) {
      const parts = key.split(":");
      if (parts.length < 3) continue;
      const jid = parts[1];
      const field = parts.slice(2).join(":");
      if (!jobMap.has(jid)) jobMap.set(jid, {});
      try {
        const type = await client.type(key);
        if (type !== "string") continue;
        const val = await client.get(key);
        if (val) jobMap.get(jid)![field] = val;
      } catch {
        // skip non-string keys
      }
    }

    let active = 0;
    let queued = 0;
    let completed = 0;
    let failed = 0;
    let trainedModels = 0;
    const recentMissions: RecentMission[] = [];

    for (const [jid, data] of jobMap.entries()) {
      // The current phase lives in mission_state JSON, meta JSON, or the raw
      // job:{id}:status string. Prefer mission_state, then meta, then status.
      let status = data["status"] || "";
      try {
        const state = JSON.parse(data["mission_state"] || "{}");
        if (state && state.phase) status = state.phase;
      } catch {
        // fall through
      }
      if (!status) {
        try {
          const meta = JSON.parse(data["meta"] || "{}");
          if (meta && meta.status) status = meta.status;
        } catch {
          // fall through
        }
      }

      const bucket = classify(status);
      if (bucket === "active") active++;
      else if (bucket === "queued") queued++;
      else if (bucket === "completed") {
        completed++;
        trainedModels++;
      } else if (bucket === "failed") failed++;

      let name = "";
      let createdAt = "";
      try {
        const brief = JSON.parse(data["mission_brief"] || "{}");
        name = brief.problem_description || brief.task_description || "";
      } catch {
        // fall through
      }
      try {
        const meta = JSON.parse(data["meta"] || "{}");
        createdAt = meta.created_at || "";
      } catch {
        // fall through
      }
      if (!name) {
        try {
          const spec = JSON.parse(data["mission_spec"] || "{}");
          name = spec.problem_description || spec.task_description || "";
        } catch {
          // fall through
        }
      }

      recentMissions.push({
        id: jid,
        name: name || `Mission ${jid.slice(0, 8)}`,
        status: status || "unknown",
        progress: 0,
        agents: [],
        started: createdAt,
        eta: "",
      });
    }

    recentMissions.sort((a, b) => b.started.localeCompare(a.started));

    return Response.json({
      active,
      queued,
      completed,
      failed,
      total: jobMap.size,
      trained_models: trainedModels,
      recent_missions: recentMissions.slice(0, 6),
    });
  } finally {
    await client.quit();
  }
}
