import { notFound } from "next/navigation";
import Link from "next/link";
import { db, schema } from "@/db";
import { and, eq } from "drizzle-orm";
import {
  getVancouverPlant,
  getLotsForMaterial,
  getConsumptionForMaterial,
} from "@/lib/queries";
import { getCurrentUser } from "@/lib/session";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatNumber } from "@/lib/utils";
import { format } from "date-fns";
import { Button } from "@/components/ui/button";
import { EditMaterialForm } from "./edit-form";

export const dynamic = "force-dynamic";

export default async function RawMaterialDetail({
  params,
}: {
  params: { id: string };
}) {
  const [plant, user] = await Promise.all([
    getVancouverPlant(),
    getCurrentUser(),
  ]);

  const [material] = await db
    .select()
    .from(schema.rawMaterials)
    .where(eq(schema.rawMaterials.id, params.id));
  if (!material) notFound();

  const [stock] = await db
    .select()
    .from(schema.rawMaterialStock)
    .where(
      and(
        eq(schema.rawMaterialStock.rawMaterialId, material.id),
        eq(schema.rawMaterialStock.plantId, plant.id)
      )
    );
  const qty = stock?.qtyOnHand ?? 0;
  const low = material.reorderPoint !== null && qty < material.reorderPoint;

  const [lots, consumption] = await Promise.all([
    getLotsForMaterial(material.id, plant.id),
    getConsumptionForMaterial(material.id, plant.id, 30),
  ]);

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/raw-materials"
          className="text-sm text-secondary hover:underline"
        >
          ← All raw materials
        </Link>
        <h1 className="text-2xl font-semibold text-omega-navy mt-1">
          {material.name}
        </h1>
        <div className="flex gap-2 mt-1 text-sm text-muted-foreground">
          <span>{material.category}</span>
          <span>·</span>
          <span>Unit: {material.unit}</span>
          {material.buyAmerica && (
            <>
              <span>·</span>
              <Badge variant="outline">Buy America</Badge>
            </>
          )}
        </div>
      </div>

      <div className="grid md:grid-cols-3 gap-4">
        <Card className={low ? "border-omega-red/40 bg-red-50/40" : undefined}>
          <CardContent className="p-4">
            <div className="text-xs uppercase text-muted-foreground">
              On hand
            </div>
            <div
              className={`text-3xl font-semibold mt-1 ${low ? "text-omega-red" : "text-omega-navy"}`}
            >
              {formatNumber(qty)}
              <span className="text-base text-muted-foreground ml-1">
                {material.unit}
              </span>
            </div>
            {low && (
              <Badge variant="destructive" className="mt-2">
                Below reorder
              </Badge>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="text-xs uppercase text-muted-foreground">
              Reorder point
            </div>
            <div className="text-3xl font-semibold mt-1 text-omega-navy">
              {formatNumber(material.reorderPoint)}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="text-xs uppercase text-muted-foreground">
              Reorder qty
            </div>
            <div className="text-3xl font-semibold mt-1 text-omega-navy">
              {formatNumber(material.reorderQty)}
            </div>
            <div className="text-xs text-muted-foreground mt-2">
              Vendor: {material.vendor ?? "—"}
            </div>
          </CardContent>
        </Card>
      </div>

      {user?.role === "admin" && (
        <Card>
          <CardHeader>
            <CardTitle>Edit settings</CardTitle>
          </CardHeader>
          <CardContent>
            <EditMaterialForm
              id={material.id}
              initial={{
                reorderPoint: material.reorderPoint,
                reorderQty: material.reorderQty,
                vendor: material.vendor,
                notes: material.notes,
              }}
            />
          </CardContent>
        </Card>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Lot history</CardTitle>
              {user?.role === "admin" && (
                <Button asChild size="sm" variant="secondary">
                  <Link href={`/log/receipt?material=${material.id}`}>
                    Log receipt
                  </Link>
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {lots.length === 0 ? (
              <p className="p-6 text-sm text-muted-foreground">
                No receipts logged yet.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Lot #</TableHead>
                    <TableHead>Received</TableHead>
                    <TableHead>Vendor / PO</TableHead>
                    <TableHead className="text-right">Received</TableHead>
                    <TableHead className="text-right">Remaining</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {lots.map((l) => (
                    <TableRow key={l.id}>
                      <TableCell className="font-mono text-xs">
                        {l.lotNumber}
                      </TableCell>
                      <TableCell>
                        {format(l.receivedAt, "yyyy-MM-dd")}
                      </TableCell>
                      <TableCell>
                        <div>{l.vendor ?? "—"}</div>
                        <div className="text-xs text-muted-foreground">
                          {l.poNumber ?? ""}
                        </div>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatNumber(l.qtyReceived)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatNumber(l.qtyRemaining)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Consumption — last 30 builds</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {consumption.length === 0 ? (
              <p className="p-6 text-sm text-muted-foreground">
                Not consumed in any build yet.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead>Panel</TableHead>
                    <TableHead className="text-right">Panels built</TableHead>
                    <TableHead className="text-right">Qty consumed</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {consumption.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell>{format(c.builtAt, "yyyy-MM-dd")}</TableCell>
                      <TableCell className="font-mono text-xs">
                        {c.panelSku}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatNumber(c.qtyBuilt)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatNumber(c.qtyConsumed)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
