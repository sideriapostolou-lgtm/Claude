import { db, schema } from "@/db";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

export const dynamic = "force-dynamic";

export default async function PanelsAdminPage() {
  const panels = await db
    .select()
    .from(schema.panelTypes)
    .orderBy(
      schema.panelTypes.lengthFt,
      schema.panelTypes.railWeight,
      schema.panelTypes.skuCode
    );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-omega-navy">Panel types</h1>
        <p className="text-sm text-muted-foreground">
          36 panel SKUs generated from the spec. Click a row to view or edit
          its BOM.
        </p>
      </div>
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>SKU</TableHead>
                <TableHead>Display name</TableHead>
                <TableHead>Length</TableHead>
                <TableHead>Plate</TableHead>
                <TableHead>Rail</TableHead>
                <TableHead>Active</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {panels.map((p) => (
                <TableRow key={p.id}>
                  <TableCell className="font-mono text-xs">
                    <Link
                      href={`/admin/panels/${p.id}`}
                      className="font-semibold hover:underline"
                    >
                      {p.skuCode}
                    </Link>
                  </TableCell>
                  <TableCell>{p.displayName}</TableCell>
                  <TableCell>{p.lengthFt}′</TableCell>
                  <TableCell>{p.plateType}</TableCell>
                  <TableCell>{p.railWeight}#</TableCell>
                  <TableCell>
                    {p.active ? (
                      <Badge variant="success">Active</Badge>
                    ) : (
                      <Badge variant="outline">Inactive</Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
