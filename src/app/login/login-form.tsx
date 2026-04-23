"use client";

import { useState, useTransition } from "react";
import { requestLoginLink } from "./actions";
import { toast } from "sonner";

export function LoginForm({ nextPath }: { nextPath?: string }) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [pending, startTransition] = useTransition();

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = email.trim().toLowerCase();
    if (!trimmed) return;
    startTransition(async () => {
      const res = await requestLoginLink(trimmed, nextPath);
      if (res.ok) {
        setSent(true);
      } else {
        toast.error(res.error ?? "Something went wrong");
      }
    });
  }

  if (sent) {
    return (
      <div className="text-sm">
        <p className="font-medium text-omega-navy">Check your inbox.</p>
        <p className="text-muted-foreground mt-1">
          If your email is authorized, a login link is on its way. It expires
          in 15 minutes.
        </p>
        <button
          type="button"
          onClick={() => {
            setSent(false);
            setEmail("");
          }}
          className="text-secondary hover:underline text-sm mt-4"
        >
          Use a different email
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div>
        <label
          htmlFor="email"
          className="block text-sm font-medium text-foreground mb-1"
        >
          Email
        </label>
        <input
          id="email"
          type="email"
          required
          autoFocus
          autoComplete="email"
          disabled={pending}
          placeholder="you@omega-industries.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-md border border-input px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-60"
        />
      </div>
      <button
        type="submit"
        disabled={pending}
        className="w-full bg-omega-navy hover:bg-[#162a4b] text-white font-medium py-2.5 rounded-md transition-colors disabled:opacity-60"
      >
        {pending ? "Sending…" : "Send login link"}
      </button>
    </form>
  );
}
