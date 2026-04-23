"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Select } from "@/components/ui/select";
import { useTransition } from "react";

export function FinishedGoodsFilters() {
  const router = useRouter();
  const params = useSearchParams();
  const [, startTransition] = useTransition();

  function update(key: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    startTransition(() => {
      router.replace(`/finished-goods?${next.toString()}`);
    });
  }

  return (
    <div className="flex flex-wrap gap-3">
      <Select
        defaultValue={params.get("length") ?? ""}
        onChange={(e) => update("length", e.target.value)}
        className="max-w-[160px]"
      >
        <option value="">Any length</option>
        <option value="40">40′</option>
        <option value="60">60′</option>
        <option value="80">80′</option>
      </Select>
      <Select
        defaultValue={params.get("plate") ?? ""}
        onChange={(e) => update("plate", e.target.value)}
        className="max-w-[160px]"
      >
        <option value="">Any plate</option>
        <option value="Standard">Standard</option>
        <option value="Pandrol">Pandrol</option>
      </Select>
      <Select
        defaultValue={params.get("weight") ?? ""}
        onChange={(e) => update("weight", e.target.value)}
        className="max-w-[160px]"
      >
        <option value="">Any rail weight</option>
        <option value="115">115#</option>
        <option value="136">136#</option>
        <option value="141">141#</option>
      </Select>
    </div>
  );
}
