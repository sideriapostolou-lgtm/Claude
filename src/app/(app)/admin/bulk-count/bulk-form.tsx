"use client";

import { useState, useTransition } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";
import { saveBulkCount } from "./actions";
import { useRouter } from "next/navigation";

type RawItem = {
  id: string;
  name: string;
  category: string;
  unit: string;
  qtyOnHand: number;
};
type FgItem = {
  id: string;
  skuCode: string;
  displayName: string;
  qtyOnHand: number;
};

export function BulkCountForm({
  plantId,
  raw,
  finished,
}: {
  plantId: string;
  raw: RawItem[];
  finished: FgItem[];
}) {
  const router = useRouter();
  const [rmCounts, setRmCounts] = useState<Record<string, number>>(
    Object.fromEntries(raw.map((r) => [r.id, r.qtyOnHand]))
  );
  const [fgCounts, setFgCounts] = useState<Record<string, number>>(
    Object.fromEntries(finished.map((f) => [f.id, f.qtyOnHand]))
  );
  const [pending, start] = useTransition();

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    start(async () => {
      const res = await saveBulkCount({
        plantId,
        rawMaterials: Object.entries(rmCounts).map(([id, qty]) => ({
          id,
          qtyOnHand: qty,
        })),
        finishedGoods: Object.entries(fgCounts).map(([id, qty]) => ({
          id,
          qtyOnHand: qty,
        })),
      });
      if (res.ok) {
        toast.success(`Saved ${res.count} counts`);
        router.refresh();
      } else {
        toast.error(res.error ?? "Failed");
      }
    });
  }

  return (
    <form onSubmit={onSubmit} className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Raw materials ({raw.length})</CardTitle>
        </CardHeader>
        <CardContent className="p-0 divide-y">
          {raw.map((r) => (
            <div
              key={r.id}
              className="flex items-center gap-3 px-4 py-2 text-sm"
            >
              <div className="flex-1 min-w-0">
                <div className="truncate">{r.name}</div>
                <div className="text-xs text-muted-foreground">
                  {r.category} · {r.unit}
                </div>
              </div>
              <Input
                type="number"
                min={0}
                value={rmCounts[r.id] ?? 0}
                onChange={(e) =>
                  setRmCounts({
                    ...rmCounts,
                    [r.id]: Math.max(0, Number(e.target.value) || 0),
                  })
                }
                className="w-[110px]"
              />
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Finished panels ({finished.length})</CardTitle>
        </CardHeader>
        <CardContent className="p-0 divide-y">
          {finished.map((f) => (
            <div
              key={f.id}
              className="flex items-center gap-3 px-4 py-2 text-sm"
            >
              <div className="flex-1 min-w-0">
                <div className="font-mono text-xs">{f.skuCode}</div>
                <div className="text-xs text-muted-foreground truncate">
                  {f.displayName}
                </div>
              </div>
              <Input
                type="number"
                min={0}
                value={fgCounts[f.id] ?? 0}
                onChange={(e) =>
                  setFgCounts({
                    ...fgCounts,
                    [f.id]: Math.max(0, Number(e.target.value) || 0),
                  })
                }
                className="w-[110px]"
              />
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="sticky bottom-4 flex justify-end">
        <Button type="submit" disabled={pending} size="lg">
          {pending ? "Saving…" : "Save all counts"}
        </Button>
      </div>
    </form>
  );
}
