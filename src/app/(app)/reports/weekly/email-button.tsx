"use client";

import { useTransition } from "react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { Mail } from "lucide-react";
import { emailWeeklyReport } from "./actions";

export function EmailReportButton() {
  const [pending, start] = useTransition();
  return (
    <Button
      variant="outline"
      disabled={pending}
      onClick={() =>
        start(async () => {
          const res = await emailWeeklyReport();
          if (res.ok) {
            toast.success(`Emailed to ${res.count} recipient${res.count === 1 ? "" : "s"}`);
          } else {
            toast.error(res.error ?? "Failed");
          }
        })
      }
    >
      <Mail size={14} />
      {pending ? "Sending…" : "Email report"}
    </Button>
  );
}
