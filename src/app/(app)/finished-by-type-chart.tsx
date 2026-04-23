"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

export function FinishedByTypeChart({
  data,
}: {
  data: { label: string; "115#": number; "136#": number; "141#": number }[];
}) {
  if (!data.length) {
    return (
      <p className="text-sm text-muted-foreground">
        No finished goods to chart yet.
      </p>
    );
  }

  return (
    <div className="h-80 w-full">
      <ResponsiveContainer>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} />
          <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
          <Tooltip />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="115#" stackId="w" fill="#4472C4" />
          <Bar dataKey="136#" stackId="w" fill="#1F3864" />
          <Bar dataKey="141#" stackId="w" fill="#70AD47" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
