"use client";

import { useTransition } from "react";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { updateRawMaterial } from "./actions";

export function EditMaterialForm({
  id,
  initial,
}: {
  id: string;
  initial: {
    reorderPoint: number | null;
    reorderQty: number | null;
    vendor: string | null;
    notes: string | null;
  };
}) {
  const [pending, start] = useTransition();

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    start(async () => {
      const res = await updateRawMaterial(id, fd);
      if (res.ok) toast.success("Saved");
      else toast.error(res.error ?? "Save failed");
    });
  }

  return (
    <form onSubmit={onSubmit} className="grid sm:grid-cols-2 gap-4">
      <div>
        <Label>Reorder point</Label>
        <Input
          type="number"
          min={0}
          name="reorderPoint"
          defaultValue={initial.reorderPoint ?? ""}
          className="mt-1"
        />
      </div>
      <div>
        <Label>Reorder qty</Label>
        <Input
          type="number"
          min={0}
          name="reorderQty"
          defaultValue={initial.reorderQty ?? ""}
          className="mt-1"
        />
      </div>
      <div className="sm:col-span-2">
        <Label>Vendor</Label>
        <Input name="vendor" defaultValue={initial.vendor ?? ""} className="mt-1" />
      </div>
      <div className="sm:col-span-2">
        <Label>Notes</Label>
        <Textarea name="notes" defaultValue={initial.notes ?? ""} className="mt-1" />
      </div>
      <div className="sm:col-span-2">
        <Button type="submit" disabled={pending}>
          {pending ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}
