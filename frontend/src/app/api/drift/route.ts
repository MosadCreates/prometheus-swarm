import { createClient } from "redis";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const REDIS_HOST = process.env.REDIS_HOST || "localhost";
const REDIS_PORT = parseInt(process.env.REDIS_PORT || "6379");

export async function GET() {
  const client = createClient({ url: `redis://${REDIS_HOST}:${REDIS_PORT}` });
  await client.connect();

  try {
    const events = await client.xRevRange("harbor_output", "+", "-", { COUNT: 100 });
    const driftEvents = events
      .filter((m) => (m.message as any).event_type === "DRIFT_ALERT")
      .map((m) => ({
        id: m.id,
        job_id: (m.message as any).job_id || "",
        psi: parseFloat((m.message as any).psi || "0"),
        feature: (m.message as any).feature || "",
        timestamp: (m.message as any).timestamp || "",
      }));

    const summary = await client.hGetAll("drift:latest");
    const monitored = await client.sMembers("drift:monitored_jobs");

    return Response.json({ driftEvents, summary, monitoredJobs: monitored });
  } finally {
    await client.quit();
  }
}
