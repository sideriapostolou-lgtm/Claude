import {
  getVancouverPlant,
  getLowStockItems,
  countFinishedOnHand,
  getRecentBuilds,
  getRecentShipments,
  getFinishedGoodsWithStock,
} from "@/lib/queries";
import Link from "next/link";
import { formatDistanceToNowStrict } from "date-fns";
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
import { AlertTriangle, Hammer, Package, Truck } from "lucide-react";
import { formatNumber } from "@/lib/utils";
import { FinishedByTypeChart } from "./finished-by-type-chart";

export const dynamic = "force-dynamic";

export default async function Dashboard() {
  const plant = await getVancouverPlant();
  const [lowStock, totalFinished, builds, shipments, finishedGoods] =
    await Promise.all([
      getLowStockItems(plant.id),
      countFinishedOnHand(plant.id),
      getRecentBuilds(plant.id, 5),
      getRecentShipments(plant.id, 5),
      getFinishedGoodsWithStock(plant.id),
    ]);

  const lastBuild = builds[0];
  const lastShipment = shipments[0];

  const chartData = buildChartData(finishedGoods);

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-semibold text-omega-navy">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            {plant.name} · live inventory view
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          icon={<Package className="text-secondary" size={18} />}
          label="Finished panels on hand"
          value={formatNumber(totalFinished)}
        />
        <MetricCard
          icon={<AlertTriangle className="text-omega-red" size={18} />}
          label="Items below reorder point"
          value={formatNumber(lowStock.length)}
          accent={lowStock.length > 0 ? "alert" : undefined}
        />
        <MetricCard
          icon={<Hammer className="text-omega-green" size={18} />}
          label="Last build"
          value={
            lastBuild
              ? `${lastBuild.qtyBuilt}× ${lastBuild.panelSku}`
              : "None yet"
          }
          sub={
            lastBuild
              ? `${formatDistanceToNowStrict(lastBuild.builtAt, {
                  addSuffix: true,
                })} · ${lastBuild.userName ?? ""}`
              : undefined
          }
        />
        <MetricCard
          icon={<Truck className="text-secondary" size={18} />}
          label="Last shipment"
          value={
            lastShipment
              ? `${lastShipment.qtyShipped}× ${lastShipment.panelSku}`
              : "None yet"
          }
          sub={
            lastShipment
              ? `${formatDistanceToNowStrict(lastShipment.shippedAt, {
                  addSuffix: true,
                })} · ${lastShipment.customer}`
              : undefined
          }
        />
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle size={16} className="text-omega-red" />
              Low-stock alerts
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {lowStock.length === 0 ? (
              <p className="p-6 text-sm text-muted-foreground">
                Everything is above reorder point. Nothing to order today.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Material</TableHead>
                    <TableHead className="text-right">On hand</TableHead>
                    <TableHead className="text-right">Reorder at</TableHead>
                    <TableHead className="text-right">Reorder qty</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {lowStock.map((m) => (
                    <TableRow key={m.id} className="bg-red-50/40">
                      <TableCell>
                        <Link
                          href={`/raw-materials/${m.id}`}
                          className="font-medium hover:underline"
                        >
                          {m.name}
                        </Link>
                        <div className="text-xs text-muted-foreground">
                          {m.category}
                        </div>
                      </TableCell>
                      <TableCell className="text-right font-semibold text-omega-red">
                        {formatNumber(m.qtyOnHand)} {m.unit}
                      </TableCell>
                      <TableCell className="text-right">
                        {formatNumber(m.reorderPoint)}
                      </TableCell>
                      <TableCell className="text-right">
                        {formatNumber(m.reorderQty)}
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
            <CardTitle>Recent activity</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {[...builds.map((b) => ({ kind: "build" as const, ...b })),
              ...shipments.map((s) => ({ kind: "ship" as const, ...s }))]
              .sort((a, b) =>
                (b.kind === "build" ? +b.builtAt : +b.shippedAt) -
                (a.kind === "build" ? +a.builtAt : +a.shippedAt)
              )
              .slice(0, 10)
              .map((evt) =>
                evt.kind === "build" ? (
                  <div key={`b-${evt.id}`} className="flex gap-2">
                    <Badge variant="success">Build</Badge>
                    <div className="flex-1 min-w-0">
                      <div className="truncate">
                        {evt.qtyBuilt}× {evt.panelSku}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {formatDistanceToNowStrict(evt.builtAt, {
                          addSuffix: true,
                        })}{" "}
                        · {evt.userName ?? "—"}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div key={`s-${evt.id}`} className="flex gap-2">
                    <Badge variant="secondary">Ship</Badge>
                    <div className="flex-1 min-w-0">
                      <div className="truncate">
                        {evt.qtyShipped}× {evt.panelSku} → {evt.customer}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {formatDistanceToNowStrict(evt.shippedAt, {
                          addSuffix: true,
                        })}
                      </div>
                    </div>
                  </div>
                )
              )}
            {builds.length === 0 && shipments.length === 0 && (
              <p className="text-muted-foreground">
                No builds or shipments logged yet.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Finished goods by panel type</CardTitle>
        </CardHeader>
        <CardContent>
          <FinishedByTypeChart data={chartData} />
        </CardContent>
      </Card>
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  sub,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  accent?: "alert";
}) {
  return (
    <Card
      className={
        accent === "alert" ? "border-omega-red/40 bg-red-50/50" : undefined
      }
    >
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-xs text-muted-foreground uppercase tracking-wide">
          {icon}
          {label}
        </div>
        <div className="text-2xl font-semibold mt-2 text-omega-navy">
          {value}
        </div>
        {sub && <div className="text-xs text-muted-foreground mt-1">{sub}</div>}
      </CardContent>
    </Card>
  );
}

function buildChartData(
  goods: { skuCode: string; lengthFt: number; plateType: string; railWeight: number; tieType: string; qtyOnHand: number }[]
) {
  // Group by type code derived from plate + tie suffix (SE/PE/ST/PT);
  // each bar group contains length+weight stacks.
  const typeCode = (plate: string, tie: string) =>
    `${plate === "Standard" ? "S" : "P"}${tie.startsWith("10") ? "T" : "E"}`;

  // rows keyed by `${type}-${length}` → weight counts
  const rows: Record<string, { type: string; length: number; w115: number; w136: number; w141: number }> = {};
  for (const g of goods) {
    const t = typeCode(g.plateType, g.tieType);
    const key = `${t}-${g.lengthFt}`;
    rows[key] ??= { type: t, length: g.lengthFt, w115: 0, w136: 0, w141: 0 };
    if (g.railWeight === 115) rows[key].w115 += g.qtyOnHand;
    if (g.railWeight === 136) rows[key].w136 += g.qtyOnHand;
    if (g.railWeight === 141) rows[key].w141 += g.qtyOnHand;
  }
  return Object.values(rows)
    .sort(
      (a, b) =>
        a.type.localeCompare(b.type) || a.length - b.length
    )
    .map((r) => ({
      label: `${r.type} ${r.length}'`,
      "115#": r.w115,
      "136#": r.w136,
      "141#": r.w141,
    }));
}
