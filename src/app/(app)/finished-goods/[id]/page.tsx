import { notFound } from "next/navigation";
import Link from "next/link";
import { db, schema } from "@/db";
import { and, eq, desc } from "drizzle-orm";
import {
  getVancouverPlant,
  getBomForPanel,
  getRawMaterialsWithStock,
} from "@/lib/queries";
import { getCurrentUser } from "@/lib/session";
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
import { Button } from "@/components/ui/button";
import { formatNumber } from "@/lib/utils";
import { format } from "date-fns";

export const dynamic = "force-dynamic";

export default async function FinishedGoodsDetail({
  params,
}: {
  params: { id: string };
}) {
  const [plant, user] = await Promise.all([
    getVancouverPlant(),
    getCurrentUser(),
  ]);

  const [panel] = await db
    .select()
    .from(schema.panelTypes)
    .where(eq(schema.panelTypes.id, params.id));
  if (!panel) notFound();

  const [stock] = await db
    .select()
    .from(schema.finishedGoodsStock)
    .where(
      and(
        eq(schema.finishedGoodsStock.panelTypeId, panel.id),
        eq(schema.finishedGoodsStock.plantId, plant.id)
      )
    );

  const [bom, rmStock, builds, shipments] = await Promise.all([
    getBomForPanel(panel.id),
    getRawMaterialsWithStock(plant.id),
    db
      .select({
        id: schema.buildEvents.id,
        qtyBuilt: schema.buildEvents.qtyBuilt,
        builtAt: schema.buildEvents.builtAt,
        notes: schema.buildEvents.notes,
        railWasteFt: schema.buildEvents.railWasteFt,
        userName: schema.users.name,
      })
      .from(schema.buildEvents)
      .leftJoin(schema.users, eq(schema.users.id, schema.buildEvents.builtBy))
      .where(
        and(
          eq(schema.buildEvents.panelTypeId, panel.id),
          eq(schema.buildEvents.plantId, plant.id)
        )
      )
      .orderBy(desc(schema.buildEvents.builtAt))
      .limit(20),
    db
      .select({
        id: schema.shipmentEvents.id,
        qtyShipped: schema.shipmentEvents.qtyShipped,
        shippedAt: schema.shipmentEvents.shippedAt,
        customer: schema.shipmentEvents.customer,
        poNumber: schema.shipmentEvents.poNumber,
        notes: schema.shipmentEvents.notes,
        userName: schema.users.name,
      })
      .from(schema.shipmentEvents)
      .leftJoin(
        schema.users,
        eq(schema.users.id, schema.shipmentEvents.shippedBy)
      )
      .where(
        and(
          eq(schema.shipmentEvents.panelTypeId, panel.id),
          eq(schema.shipmentEvents.plantId, plant.id)
        )
      )
      .orderBy(desc(schema.shipmentEvents.shippedAt))
      .limit(20),
  ]);

  // "Can build X more" = min over BOM of floor(on_hand / qty_per_panel)
  const rmById = new Map(rmStock.map((r) => [r.id, r]));
  let canBuild = Infinity;
  let bottleneck: { name: string; available: number; perPanel: number } | null = null;
  for (const b of bom) {
    const rm = rmById.get(b.material.id);
    const avail = rm?.qtyOnHand ?? 0;
    const possible = Math.floor(avail / b.line.qtyPerPanel);
    if (possible < canBuild) {
      canBuild = possible;
      bottleneck = {
        name: b.material.name,
        available: avail,
        perPanel: b.line.qtyPerPanel,
      };
    }
  }
  if (!isFinite(canBuild)) canBuild = 0;

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/finished-goods"
          className="text-sm text-secondary hover:underline"
        >
          ← All finished goods
        </Link>
        <div className="flex items-baseline gap-3 mt-1 flex-wrap">
          <h1 className="text-2xl font-semibold text-omega-navy font-mono">
            {panel.skuCode}
          </h1>
          <span className="text-muted-foreground">{panel.displayName}</span>
        </div>
      </div>

      <div className="grid md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4">
            <div className="text-xs uppercase text-muted-foreground">
              On hand
            </div>
            <div className="text-3xl font-semibold mt-1 text-omega-navy">
              {formatNumber(stock?.qtyOnHand ?? 0)}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="text-xs uppercase text-muted-foreground">
              Can build more
            </div>
            <div className="text-3xl font-semibold mt-1 text-omega-navy">
              {formatNumber(canBuild)}
            </div>
            {bottleneck && canBuild < 100 && (
              <div className="text-xs text-muted-foreground mt-1">
                Limited by <span className="font-medium">{bottleneck.name}</span>
                {" "}
                ({bottleneck.available} ÷ {bottleneck.perPanel} per panel)
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 space-y-2">
            <div className="text-xs uppercase text-muted-foreground">Spec</div>
            <div className="text-sm">
              <div>Length: {panel.lengthFt}′</div>
              <div>Plate: {panel.plateType}</div>
              <div>Rail: {panel.railWeight}#</div>
              <div>Tie: {panel.tieType}</div>
              <div>Fasteners: {panel.fastenerType}</div>
            </div>
          </CardContent>
        </Card>
      </div>

      {user?.role === "admin" && (
        <div className="flex gap-2">
          <Button asChild variant="secondary">
            <Link href={`/log/build?panel=${panel.id}`}>
              Log build for {panel.skuCode}
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href={`/log/shipment?panel=${panel.id}`}>
              Log shipment for {panel.skuCode}
            </Link>
          </Button>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Bill of materials (1 panel)</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Material</TableHead>
                <TableHead>Category</TableHead>
                <TableHead className="text-right">Per panel</TableHead>
                <TableHead className="text-right">On hand</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {bom.map((b) => {
                const avail = rmById.get(b.material.id)?.qtyOnHand ?? 0;
                const enough = avail >= b.line.qtyPerPanel;
                return (
                  <TableRow key={b.line.id}>
                    <TableCell>
                      <Link
                        href={`/raw-materials/${b.material.id}`}
                        className="font-medium hover:underline"
                      >
                        {b.material.name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {b.material.category}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatNumber(b.line.qtyPerPanel)} {b.material.unit}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatNumber(avail)}
                    </TableCell>
                    <TableCell>
                      {enough ? (
                        <Badge variant="success">OK</Badge>
                      ) : (
                        <Badge variant="destructive">Short</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <div className="grid lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Recent builds</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {builds.length === 0 ? (
              <p className="p-6 text-sm text-muted-foreground">
                No builds logged yet.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead>By</TableHead>
                    <TableHead>Notes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {builds.map((b) => (
                    <TableRow key={b.id}>
                      <TableCell>{format(b.builtAt, "yyyy-MM-dd")}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatNumber(b.qtyBuilt)}
                      </TableCell>
                      <TableCell>{b.userName ?? "—"}</TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {b.notes ?? ""}
                        {b.railWasteFt > 0 &&
                          ` · ${b.railWasteFt}ft rail scrap`}
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
            <CardTitle>Recent shipments</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {shipments.length === 0 ? (
              <p className="p-6 text-sm text-muted-foreground">
                No shipments logged yet.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead>Customer / PO</TableHead>
                    <TableHead>By</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {shipments.map((s) => (
                    <TableRow key={s.id}>
                      <TableCell>{format(s.shippedAt, "yyyy-MM-dd")}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatNumber(s.qtyShipped)}
                      </TableCell>
                      <TableCell>
                        <div>{s.customer}</div>
                        <div className="text-xs text-muted-foreground">
                          {s.poNumber ?? ""}
                        </div>
                      </TableCell>
                      <TableCell>{s.userName ?? "—"}</TableCell>
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
