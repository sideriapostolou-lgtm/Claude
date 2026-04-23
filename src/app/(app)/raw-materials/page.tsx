import Link from "next/link";
import {
  getVancouverPlant,
  getRawMaterialsWithStock,
} from "@/lib/queries";
import { getCurrentUser } from "@/lib/session";
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
import { formatNumber } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { RawMaterialsFilters } from "./filters";

export const dynamic = "force-dynamic";

export default async function RawMaterialsPage({
  searchParams,
}: {
  searchParams: { q?: string; category?: string };
}) {
  const [plant, user] = await Promise.all([
    getVancouverPlant(),
    getCurrentUser(),
  ]);
  const all = await getRawMaterialsWithStock(plant.id);
  const categories = Array.from(new Set(all.map((m) => m.category))).sort();

  const q = (searchParams.q ?? "").trim().toLowerCase();
  const cat = searchParams.category ?? "";
  const filtered = all.filter(
    (m) =>
      (!q || m.name.toLowerCase().includes(q)) && (!cat || m.category === cat)
  );

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-omega-navy">
            Raw materials
          </h1>
          <p className="text-sm text-muted-foreground">
            {all.length} SKUs · {plant.name}
          </p>
        </div>
        {user?.role === "admin" && (
          <Button asChild variant="secondary">
            <Link href="/log/receipt">Log a receipt</Link>
          </Button>
        )}
      </div>

      <RawMaterialsFilters categories={categories} />

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Unit</TableHead>
                <TableHead className="text-right">On hand</TableHead>
                <TableHead className="text-right">Reorder point</TableHead>
                <TableHead className="text-right">Reorder qty</TableHead>
                <TableHead>Vendor</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((m) => {
                const low =
                  m.reorderPoint !== null && m.qtyOnHand < (m.reorderPoint ?? 0);
                return (
                  <TableRow
                    key={m.id}
                    className={low ? "bg-red-50/60 hover:bg-red-50" : ""}
                  >
                    <TableCell>
                      <Link
                        href={`/raw-materials/${m.id}`}
                        className="font-medium hover:underline"
                      >
                        {m.name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {m.category}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {m.unit}
                    </TableCell>
                    <TableCell
                      className={`text-right tabular-nums ${low ? "font-semibold text-omega-red" : ""}`}
                    >
                      {formatNumber(m.qtyOnHand)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatNumber(m.reorderPoint)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatNumber(m.reorderQty)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {m.vendor ?? "—"}
                    </TableCell>
                    <TableCell>
                      {low ? (
                        <Badge variant="destructive">Below reorder</Badge>
                      ) : m.reorderPoint === null ? (
                        <Badge variant="outline">No reorder set</Badge>
                      ) : (
                        <Badge variant="success">OK</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
              {filtered.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                    No materials match those filters.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
