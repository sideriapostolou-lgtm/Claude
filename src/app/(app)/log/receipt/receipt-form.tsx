"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { format } from "date-fns";
import { logReceipt } from "./actions";

type Material = { id: string; name: string; unit: string; vendor: string | null };

function suggestLotNumber() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const suffix = String(d.getHours() * 60 + d.getMinutes()).padStart(3, "0");
  return `LOT-${y}${m}${day}-${suffix}`;
}

export function ReceiptForm({
  plantId,
  defaultMaterialId,
  materials,
}: {
  plantId: string;
  defaultMaterialId?: string;
  materials: Material[];
}) {
  const router = useRouter();
  const [materialId, setMaterialId] = useState(defaultMaterialId ?? "");
  const [lotNumber, setLotNumber] = useState(suggestLotNumber());
  const [vendor, setVendor] = useState("");
  const [poNumber, setPoNumber] = useState("");
  const [qty, setQty] = useState<number>(0);
  const [receivedAt, setReceivedAt] = useState(format(new Date(), "yyyy-MM-dd"));
  const [notes, setNotes] = useState("");
  const [pending, start] = useTransition();

  const selected = materials.find((m) => m.id === materialId);

  function onMaterialChange(id: string) {
    setMaterialId(id);
    const m = materials.find((m) => m.id === id);
    if (m && !vendor && m.vendor) setVendor(m.vendor);
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!materialId) return toast.error("Pick a material");
    if (qty <= 0) return toast.error("Qty must be positive");
    start(async () => {
      const res = await logReceipt({
        rawMaterialId: materialId,
        plantId,
        lotNumber: lotNumber.trim(),
        vendor: vendor.trim() || undefined,
        poNumber: poNumber.trim() || undefined,
        qtyReceived: qty,
        receivedAt: new Date(receivedAt).toISOString(),
        notes: notes.trim() || undefined,
      });
      if (res.ok) {
        toast.success(`Received ${qty} ${selected?.unit} of ${selected?.name}`);
        router.push(`/raw-materials/${materialId}`);
        router.refresh();
      } else {
        toast.error(res.error ?? "Failed");
      }
    });
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      <div>
        <Label>Material</Label>
        <Select
          value={materialId}
          onChange={(e) => onMaterialChange(e.target.value)}
          className="mt-1"
          required
        >
          <option value="">— Select a material —</option>
          {materials.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </Select>
      </div>
      <div className="grid sm:grid-cols-2 gap-4">
        <div>
          <Label>Lot number</Label>
          <Input
            value={lotNumber}
            onChange={(e) => setLotNumber(e.target.value)}
            className="mt-1 font-mono text-sm"
            required
          />
        </div>
        <div>
          <Label>Received date</Label>
          <Input
            type="date"
            value={receivedAt}
            onChange={(e) => setReceivedAt(e.target.value)}
            className="mt-1"
            required
          />
        </div>
        <div>
          <Label>Vendor</Label>
          <Input
            value={vendor}
            onChange={(e) => setVendor(e.target.value)}
            className="mt-1"
          />
        </div>
        <div>
          <Label>PO number</Label>
          <Input
            value={poNumber}
            onChange={(e) => setPoNumber(e.target.value)}
            className="mt-1"
          />
        </div>
        <div>
          <Label>Qty received</Label>
          <Input
            type="number"
            min={1}
            value={qty || ""}
            onChange={(e) => setQty(Number(e.target.value) || 0)}
            className="mt-1"
            required
          />
          {selected && (
            <p className="text-xs text-muted-foreground mt-1">
              Unit: {selected.unit}
            </p>
          )}
        </div>
      </div>
      <div>
        <Label>Notes</Label>
        <Textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="mt-1"
        />
      </div>
      <Button type="submit" disabled={pending || !materialId || qty <= 0}>
        {pending ? "Logging…" : "Log receipt"}
      </Button>
    </form>
  );
}
