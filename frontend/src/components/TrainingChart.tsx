"use client";

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";

export interface EpochData {
  epoch: number;
  train_loss?: number;
  val_loss?: number;
  [key: string]: unknown;
}

interface TrainingChartProps {
  data: EpochData[];
}

export default function TrainingChart({ data }: TrainingChartProps) {
  if (data.length === 0) return null;

  const hasVal = data.some((d) => d.val_loss !== undefined && d.val_loss !== null);

  return (
    <div className="rounded-xl bg-[#F7F6F3] border border-[#E8E5DF] p-3">
      <div className="text-[11px] font-semibold text-[#8B8982] mb-2">Training Progress</div>
      <ResponsiveContainer width="100%" height={160}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#E8E5DF" />
          <XAxis dataKey="epoch" tick={{ fontSize: 10, fill: "#8B8982" }} label={{ value: "Epoch", position: "insideBottomRight", offset: -4, style: { fontSize: 10, fill: "#8B8982" } }} />
          <YAxis tick={{ fontSize: 10, fill: "#8B8982" }} />
          <Tooltip
            contentStyle={{ fontSize: "11px", borderRadius: "8px", border: "1px solid #E8E5DF", boxShadow: "0 2px 8px rgba(0,0,0,0.06)" }}
          />
          <Legend wrapperStyle={{ fontSize: "10px", paddingTop: "4px" }} />
          <Line type="monotone" dataKey="train_loss" stroke="#C96442" strokeWidth={2} dot={false} name="Train Loss" />
          {hasVal && <Line type="monotone" dataKey="val_loss" stroke="#8B8982" strokeWidth={2} dot={false} name="Val Loss" />}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
