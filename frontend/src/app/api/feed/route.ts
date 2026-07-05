import { createClient } from "redis";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const REDIS_HOST = process.env.REDIS_HOST || "localhost";
const REDIS_PORT = parseInt(process.env.REDIS_PORT || "6379");

const EVENT_STREAMS = [
  "scout_output",
  "forge_output",
  "furnace_feed",
  "furnace_output",
  "furnace_crash",
  "dissect_output",
  "arbiter_output",
  "harbor_output",
  "orchestrator_output",
];

interface StreamEvent {
  stream: string;
  id: string;
  data: Record<string, string>;
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const filterJobId = searchParams.get("job_id");
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      const redis = createClient({
        url: `redis://${REDIS_HOST}:${REDIS_PORT}`,
      });

      try {
        await redis.connect();
        console.log(`SSE: Connected to Redis (filter=${filterJobId || "all"})`);

        controller.enqueue(encoder.encode("data: {\"status\":\"connected\"}\n\n"));

        const ids: Record<string, string> = {};
        for (const s of EVENT_STREAMS) ids[s] = "$";

        while (true) {
          try {
            const results = await redis.xRead(
              EVENT_STREAMS.map((s) => ({ key: s, id: ids[s] })),
              { BLOCK: 2000, COUNT: 10 }
            );

            if (results) {
              for (const result of results) {
                const streamName = result.name;
                for (const msg of result.messages) {
                  ids[streamName] = msg.id;

                  if (filterJobId && msg.message?.job_id !== filterJobId) continue;

                  const event: StreamEvent = {
                    stream: streamName,
                    id: msg.id,
                    data: msg.message || {},
                  };

                  controller.enqueue(
                    encoder.encode(`data: ${JSON.stringify(event)}\n\n`)
                  );
                }
              }
            }
          } catch (readErr) {
            console.error("SSE: Redis read error", readErr);
            await new Promise((r) => setTimeout(r, 1000));
          }
        }
      } catch (err) {
        console.error("SSE: Redis connection error", err);
        controller.enqueue(
          encoder.encode(
            `data: ${JSON.stringify({ error: "Redis connection failed", detail: String(err) })}\n\n`
          )
        );
      } finally {
        try {
          await redis.quit();
        } catch {}
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
