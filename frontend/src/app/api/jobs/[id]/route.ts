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
      const val = await client.get(key);
      if (val) data[field] = val;
    }

    const streams = await client.xRange(params.id, "-", "+");
    const history = streams.map((msg) => ({
      id: msg.id,
      ...msg.message,
    }));

    return Response.json({ id: params.id, data, history });
  } finally {
    await client.quit();
  }
}
