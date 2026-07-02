import { createClient } from "redis";
import { writeFile, mkdir } from "fs/promises";
import { join } from "path";
import { randomUUID } from "crypto";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const REDIS_HOST = process.env.REDIS_HOST || "localhost";
const REDIS_PORT = parseInt(process.env.REDIS_PORT || "6379");
const UPLOAD_DIR = join(process.cwd(), "..", "uploads");

export async function POST(req: Request) {
  const form = await req.formData();
  const problemDescription = form.get("problem_description")?.toString().trim();
  const file = form.get("file") as File | null;
  const targetColumn = form.get("target_column")?.toString().trim() || null;
  const maxLatency = form.get("max_latency")?.toString().trim() || null;
  const maxModelSize = form.get("max_model_size")?.toString().trim() || null;

  if (!problemDescription) {
    return Response.json({ error: "problem_description is required" }, { status: 400 });
  }
  if (!file) {
    return Response.json({ error: "file is required" }, { status: 400 });
  }

  const jobId = randomUUID();
  const jobDir = join(UPLOAD_DIR, jobId);
  await mkdir(jobDir, { recursive: true });

  const ext = file.name.split(".").pop() || "csv";
  const savedPath = join(jobDir, `data.${ext}`);
  const buf = Buffer.from(await file.arrayBuffer());
  await writeFile(savedPath, buf);

  const client = createClient({ url: `redis://${REDIS_HOST}:${REDIS_PORT}` });
  await client.connect();

  try {
    const now = new Date().toISOString();
    const meta = {
      job_id: jobId,
      problem_description: problemDescription,
      file_path: savedPath,
      target_column: targetColumn,
      constraints: JSON.stringify({
        max_latency_ms: maxLatency ? parseInt(maxLatency) : null,
        max_model_size_mb: maxModelSize ? parseInt(maxModelSize) : null,
      }),
      status: "QUEUED",
      created_at: now,
      current_agent: null,
    };

    for (const [k, v] of Object.entries(meta)) {
      if (v !== null && v !== undefined) {
        await client.set(`job:${jobId}:${k}`, String(v));
      }
    }
    await client.set(`job:${jobId}:status`, "QUEUED");
    await client.set(`job:${jobId}:crash_count`, "0");

    const streamKey = "scout_output";
    await client.xAdd(streamKey, "*", {
      event_type: "MISSION_BRIEF_READY",
      job_id: jobId,
      problem_description: problemDescription,
      file_path: savedPath,
      target_column: targetColumn || "",
      timestamp: now,
    });

    return Response.json({ job_id: jobId, status: "QUEUED" });
  } finally {
    await client.quit();
  }
}
