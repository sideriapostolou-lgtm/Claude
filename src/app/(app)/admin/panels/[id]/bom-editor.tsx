"use client";

import { useState, useTransition } from "react";
import { Input, Label } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { updatePanel, updateBomLine } from "./actions";
import { useRouter } from "next/navigation";

type Line = {
  id: string;
  materialName: string;
  unit: string;
  qtyPerPanel: number;
};

export function PanelBomEditor({
  panelId,
  panelDisplayName,
  panelActive,
  lines,
}: {
  panelId: string;
  panelDisplayName: string;
  panelActive: boolean;
  lines: Line[];
}) {
  const router = useRouter();
  const [displayName, setDisplayName] = useState(panelDisplayName);
  const [active, setActive] = useState(panelActive);
  const [pending, start] = useTransition();

  function savePanel() {
    start(async () => {
      const res = await updatePanel(panelId, { displayName, active });
      if (res.ok) {
        toast.success("Panel updated");
        router.refresh();
      } else {
        toast.error(res.error ?? "Failed");
      }
    });
  }

  return (
    <div className="space-y-6">
      <div className="grid sm:grid-cols-[1fr_auto_auto] gap-3 items-end">
        <div className="flex-1">
          <Label>Display name</Label>
          <Input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="mt-1"
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={active}
            onChange={(e) => setActive(e.target.checked)}
          />
          Active
        </label>
        <Button onClick={savePanel} disabled={pending}>
          Save panel
        </Button>
      </div>

      <div className="border rounded-lg">
        <div className="bg-muted px-4 py-2 text-sm font-medium">
          BOM lines (qty per panel)
        </div>
        <div className="divide-y">
          {lines.map((line) => (
            <BomLineRow key={line.id} line={line} onSaved={() => router.refresh()} />
          ))}
          {lines.length === 0 && (
            <p className="p-4 text-sm text-muted-foreground">
              No BOM lines for this panel. Run the seed script to regenerate.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function BomLineRow({ line, onSaved }: { line: Line; onSaved: () => void }) {
  const [qty, setQty] = useState(line.qtyPerPanel);
  const [pending, start] = useTransition();

  return (
    <div className="flex items-center gap-3 px-4 py-2 text-sm">
      <div className="flex-1 min-w-0">
        <div className="truncate">{line.materialName}</div>
        <div className="text-xs text-muted-foreground">per panel ({line.unit})</div>
      </div>
      <Input
        type="number"
        min={0}
        value={qty}
        onChange={(e) => setQty(Number(e.target.value) || 0)}
        className="w-[90px]"
      />
      <Button
        size="sm"
        variant="outline"
        disabled={pending || qty === line.qtyPerPanel}
        onClick={() =>
          start(async () => {
            const res = await updateBomLine(line.id, qty);
            if (res.ok) {
              toast.success("Saved");
              onSaved();
            } else {
              toast.error(res.error ?? "Failed");
            }
          })
        }
      >
        Save
      </Button>
    </div>
  );
}
