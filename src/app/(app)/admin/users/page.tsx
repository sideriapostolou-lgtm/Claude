import { db, schema } from "@/db";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { UsersAdmin } from "./users-admin";

export const dynamic = "force-dynamic";

export default async function UsersAdminPage() {
  const users = await db.select().from(schema.users).orderBy(schema.users.name);
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-omega-navy">Users</h1>
        <p className="text-sm text-muted-foreground">
          Only whitelisted users can log in. Add a row here before the person
          can request a magic link.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Existing users</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Active</TableHead>
                <TableHead>Alerts</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-medium">{u.name}</TableCell>
                  <TableCell className="font-mono text-xs">{u.email}</TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        u.role === "admin"
                          ? "default"
                          : u.role === "viewer"
                          ? "secondary"
                          : "outline"
                      }
                    >
                      {u.role}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {u.active ? (
                      <Badge variant="success">Active</Badge>
                    ) : (
                      <Badge variant="outline">Inactive</Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {u.receiveAlerts ? (
                      <Badge variant="secondary">On</Badge>
                    ) : (
                      <Badge variant="outline">Off</Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <UsersAdmin users={users} />
    </div>
  );
}
