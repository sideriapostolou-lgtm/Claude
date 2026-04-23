"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { logShipment } from "./actions";

type Panel = { id: string; skuCode: string; displayName: string; qtyOnHand: number };

export function ShipmentForm({
  plantId,
  defaultPanelId,
  panels,
}: {
  plantId: string;
  defaultPanelId?: string;
  panels: Panel[];
}) {
  const router = useRouter();
  const [panelId, setPanelId] = useState(defaultPanelId ?? "");
  const [qty, setQty] = useState(1);
  const [customer, setCustomer] = useState("BNSF");
  const [poNumber, setPoNumber] = useState("");
  const [notes, setNotes] = useState("");
  const [pending, start] = useTransition();
  const selected = panels.find((p) => p.id === panelId);
  const insufficient = selected && qty > selected.qtyOnHand;

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!panelId) return toast.error("Pick a panel");
    if (qty <= 0) return toast.error("Qty must be positive");
    if (insufficient) return toast.error("Not enough on hand");
    start(async () => {
      const res = await logShipment({
        panelTypeId: panelId,
        plantId,
        qtyShipped: qty,
        customer: customer.trim() || "BNSF",
        poNumber: poNumber.trim() || undefined,
        notes: notes.trim() || undefined,
      });
      if (res.ok) {
        toast.success(`Shipped ${qty}× ${selected?.skuCode}`);
        router.push(`/finished-goods/${panelId}`);
        router.refresh();
      } else {
        toast.error(res.error ?? "Failed");
      }
    });
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      <div>
        <Label>Panel type</Label>
        <Select
          value={panelId}
          onChange={(e) => setPanelId(e.target.value)}
          className="mt-1"
          required
        >
          <option value="">— Select a panel —</option>
          {panels.map((p) => (
            <option key={p.id} value={p.id} disabled={p.qtyOnHand === 0}>
              {p.skuCode} — on hand: {p.qtyOnHand}
            </option>
          ))}
        </Select>
      </div>
      <div>
        <Label>Qty shipped</Label>
        <Input
          type="number"
          min={1}
          max={selected?.qtyOnHand}
          value={qty}
          onChange={(e) => setQty(Number(e.target.value) || 0)}
          className="mt-1 max-w-[180px]"
          required
        />
        {insufficient && (
          <p className="text-xs text-omega-red mt-1">
            Only {selected?.qtyOnHand} on hand.
          </p>
        )}
      </div>
      <div className="grid sm:grid-cols-2 gap-4">
        <div>
          <Label>Customer</Label>
          <Input
            value={customer}
            onChange={(e) => setCustomer(e.target.value)}
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
      </div>
      <div>
        <Label>Notes</Label>
        <Textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="mt-1"
        />
      </div>
      <Button type="submit" disabled={pending || !panelId || qty <= 0 || !!insufficient}>
        {pending ? "Logging…" : "Log shipment"}
      </Button>
    </form>
  );
}
