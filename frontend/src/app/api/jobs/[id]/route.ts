import { createClient } from "redis";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const REDIS_HOST = process.env.REDIS_HOST || "localhost";
const REDIS_PORT = parseInt(process.env.REDIS_PORT || "6379");

export async function GET(_req: Request, { params }: { params: { id: string } }) {
  const client = createClient({ url: `redis://${REDIS_HOST}:${REDIS_PORT}` });
  await client.connect();

  try {
    const keys = await client.keys(`job:${params.id}:*`);
    const data: Record<string, string> = {};

    for (const key of keys) {
      const parts = key.split(":");
      const field = parts.slice(2).join(":");
      try {
        const val = await client.get(key);
        if (val) data[field] = val;
      } catch {}
    }

    const history: any[] = [];
    for (const streamName of ["harbor_output", "arbiter_output", "furnace_feed", "furnace_crash", "dissect_output", "scout_output", "forge_output"]) {
      try {
        const msgs = await client.xRange(streamName, "-", "+", { COUNT: 500 });
        for (const msg of msgs) {
          if (msg.message?.job_id === params.id) {
            history.push({ id: msg.id, stream: streamName, ...msg.message });
          }
        }
      } catch {}
    }

    let endpointUrl: string | null = null;
    let passFail: string | null = null;
    let bestMetric: { value: number; label: string } | null = null;
    let architecture: string | null = null;

    for (const evt of history) {
      if (evt.stream === "harbor_output" && evt.event_type === "ENDPOINT_LIVE") {
        if (evt.endpoint_url) endpointUrl = evt.endpoint_url;
      }
      if (evt.stream === "arbiter_output" && (evt.event_type === "EVALUATION_PASS" || evt.event_type === "EVALUATION_RETRY" || evt.event_type === "ESCALATE")) {
        passFail = evt.decision || evt.event_type.replace("EVALUATION_", "").toLowerCase();
        if (evt.metrics) {
          try {
            const m = typeof evt.metrics === "string" ? JSON.parse(evt.metrics) : evt.metrics;
            if (m.auc_roc) bestMetric = { value: parseFloat(m.auc_roc), label: "AUC" };
            else if (m.accuracy) bestMetric = { value: parseFloat(m.accuracy), label: "Accuracy" };
            else if (m.f1) bestMetric = { value: parseFloat(m.f1), label: "F1" };
            else if (m.rmse) bestMetric = { value: parseFloat(m.rmse), label: "RMSE" };
            else if (m.r2) bestMetric = { value: parseFloat(m.r2), label: "R²" };
          } catch {}
        }
      }
      if (evt.stream === "forge_output" && evt.event_type === "TRAINING_SCRIPT_READY") {
        architecture = evt.architecture || null;
      }
    }

    return Response.json({
      id: params.id,
      data,
      history,
      computed: {
        endpoint_url: endpointUrl,
        pass_fail: passFail,
        best_metric: bestMetric,
        architecture: architecture,
      },
    });
  } finally {
    await client.quit();
  }
}
