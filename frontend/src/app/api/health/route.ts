import { createClient } from "redis";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const REDIS_HOST = process.env.REDIS_HOST || "localhost";
const REDIS_PORT = parseInt(process.env.REDIS_PORT || "6379");

export async function GET() {
  const client = createClient({ url: `redis://${REDIS_HOST}:${REDIS_PORT}` });
  try {
    await client.connect();
    const heartbeat = await client.get("orch:heartbeat");
    const orchestratorRunning = !!heartbeat;
    return Response.json({
      redis: true,
      orchestrator: orchestratorRunning,
      heartbeat: heartbeat || null,
    });
  } catch {
    return Response.json({ redis: false, orchestrator: false, heartbeat: null });
  } finally {
    try { await client.quit(); } catch {}
  }
}
