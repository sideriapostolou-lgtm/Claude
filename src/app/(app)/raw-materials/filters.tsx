"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useTransition } from "react";

export function RawMaterialsFilters({ categories }: { categories: string[] }) {
  const router = useRouter();
  const params = useSearchParams();
  const [, startTransition] = useTransition();

  function update(key: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    startTransition(() => {
      router.replace(`/raw-materials?${next.toString()}`);
    });
  }

  return (
    <div className="flex flex-wrap gap-3">
      <Input
        placeholder="Search by name…"
        defaultValue={params.get("q") ?? ""}
        onChange={(e) => update("q", e.target.value)}
        className="max-w-xs"
      />
      <Select
        defaultValue={params.get("category") ?? ""}
        onChange={(e) => update("category", e.target.value)}
        className="max-w-xs"
      >
        <option value="">All categories</option>
        {categories.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </Select>
    </div>
  );
}
