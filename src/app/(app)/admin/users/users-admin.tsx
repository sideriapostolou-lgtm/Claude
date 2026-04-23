"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { addUser, updateUser } from "./actions";
import type { User } from "@/db/schema";

export function UsersAdmin({ users }: { users: User[] }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<"admin" | "viewer" | "operator">("viewer");
  const [alerts, setAlerts] = useState(true);
  const [pending, start] = useTransition();

  function onAdd(e: React.FormEvent) {
    e.preventDefault();
    start(async () => {
      const res = await addUser({ email, name, role, receiveAlerts: alerts });
      if (res.ok) {
        toast.success(`Added ${email}`);
        setEmail("");
        setName("");
        router.refresh();
      } else {
        toast.error(res.error ?? "Failed");
      }
    });
  }

  return (
    <div className="grid lg:grid-cols-2 gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Add a user</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={onAdd} className="space-y-4">
            <div>
              <Label>Email</Label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value.toLowerCase())}
                required
                className="mt-1"
                placeholder="name@omega-industries.com"
              />
            </div>
            <div>
              <Label>Name</Label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                className="mt-1"
              />
            </div>
            <div>
              <Label>Role</Label>
              <Select
                value={role}
                onChange={(e) =>
                  setRole(e.target.value as "admin" | "viewer" | "operator")
                }
                className="mt-1"
              >
                <option value="viewer">viewer — read-only + alerts</option>
                <option value="admin">admin — everything</option>
                <option value="operator">operator — log events only</option>
              </Select>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={alerts}
                onChange={(e) => setAlerts(e.target.checked)}
              />
              Receive low-stock alert emails
            </label>
            <Button type="submit" disabled={pending}>
              {pending ? "Adding…" : "Add user"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Edit users</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {users.map((u) => (
            <EditRow key={u.id} user={u} onUpdate={() => router.refresh()} />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function EditRow({ user, onUpdate }: { user: User; onUpdate: () => void }) {
  const [role, setRole] = useState<User["role"]>(user.role);
  const [active, setActive] = useState(user.active);
  const [alerts, setAlerts] = useState(user.receiveAlerts);
  const [pending, start] = useTransition();

  function save() {
    start(async () => {
      const res = await updateUser(user.id, {
        role: role as "admin" | "viewer" | "operator",
        active,
        receiveAlerts: alerts,
      });
      if (res.ok) {
        toast.success("Updated");
        onUpdate();
      } else {
        toast.error(res.error ?? "Failed");
      }
    });
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-b pb-3 last:border-b-0 text-sm">
      <div className="flex-1 min-w-[160px]">
        <div className="font-medium">{user.name}</div>
        <div className="text-xs text-muted-foreground">{user.email}</div>
      </div>
      <Select
        value={role}
        onChange={(e) => setRole(e.target.value as User["role"])}
        className="w-[110px]"
      >
        <option value="admin">admin</option>
        <option value="viewer">viewer</option>
        <option value="operator">operator</option>
      </Select>
      <label className="flex items-center gap-1.5">
        <input
          type="checkbox"
          checked={active}
          onChange={(e) => setActive(e.target.checked)}
        />
        Active
      </label>
      <label className="flex items-center gap-1.5">
        <input
          type="checkbox"
          checked={alerts}
          onChange={(e) => setAlerts(e.target.checked)}
        />
        Alerts
      </label>
      <Button size="sm" onClick={save} disabled={pending}>
        {pending ? "…" : "Save"}
      </Button>
    </div>
  );
}
