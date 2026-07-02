import { createClient } from "redis";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const REDIS_HOST = process.env.REDIS_HOST || "localhost";
const REDIS_PORT = parseInt(process.env.REDIS_PORT || "6379");

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

    const jobs = Array.from(jobMap.entries())
      .map(([id, data]) => ({ id, ...data }))
      .sort((a, b) => ((b as any).id || "").localeCompare((a as any).id || ""));

    return Response.json({ jobs });
  } finally {
    await client.quit();
  }
}
