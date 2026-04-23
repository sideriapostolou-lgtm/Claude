import {
  getVancouverPlant,
  getRawMaterialsWithStock,
  getFinishedGoodsWithStock,
  getLowStockItems,
} from "@/lib/queries";
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
import { format } from "date-fns";
import { formatNumber } from "@/lib/utils";
import { Download, Mail } from "lucide-react";
import { EmailReportButton } from "./email-button";

export const dynamic = "force-dynamic";

export default async function WeeklyReport() {
  const plant = await getVancouverPlant();
  const [raw, finished, low] = await Promise.all([
    getRawMaterialsWithStock(plant.id),
    getFinishedGoodsWithStock(plant.id),
    getLowStockItems(plant.id),
  ]);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-omega-navy">
            Weekly inventory report
          </h1>
          <p className="text-sm text-muted-foreground">
            {plant.name} · {format(new Date(), "MMMM d, yyyy")}
          </p>
        </div>
        <div className="flex gap-2">
          <Button asChild variant="secondary">
            <a href="/api/reports/weekly/xlsx" download>
              <Download size={14} /> Export Excel
            </a>
          </Button>
          <EmailReportButton />
        </div>
      </div>

      {low.length > 0 && (
        <Card className="border-omega-red/50 bg-red-50/40">
          <CardHeader>
            <CardTitle className="text-omega-red">
              {low.length} item{low.length === 1 ? "" : "s"} below reorder point
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Material</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead className="text-right">On hand</TableHead>
                  <TableHead className="text-right">Reorder point</TableHead>
                  <TableHead className="text-right">Reorder qty</TableHead>
                  <TableHead>Vendor</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {low.map((m) => (
                  <TableRow key={m.id}>
                    <TableCell className="font-medium">{m.name}</TableCell>
                    <TableCell>{m.category}</TableCell>
                    <TableCell className="text-right tabular-nums text-omega-red font-semibold">
                      {formatNumber(m.qtyOnHand)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatNumber(m.reorderPoint)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatNumber(m.reorderQty)}
                    </TableCell>
                    <TableCell>{m.vendor ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Raw materials</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Unit</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {raw.map((m) => {
                const isLow =
                  m.reorderPoint !== null && m.qtyOnHand < (m.reorderPoint ?? 0);
                return (
                  <TableRow key={m.id}>
                    <TableCell>{m.name}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {m.unit}
                    </TableCell>
                    <TableCell
                      className={`text-right tabular-nums ${isLow ? "text-omega-red font-semibold" : ""}`}
                    >
                      {formatNumber(m.qtyOnHand)}
                    </TableCell>
                    <TableCell>
                      {isLow ? (
                        <Badge variant="destructive">Low</Badge>
                      ) : (
                        <Badge variant="success">OK</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Finished track panels</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>SKU</TableHead>
                <TableHead>Description</TableHead>
                <TableHead className="text-right">Qty</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {finished.map((p) => (
                <TableRow key={p.id}>
                  <TableCell className="font-mono text-xs">
                    {p.skuCode}
                  </TableCell>
                  <TableCell>{p.displayName}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatNumber(p.qtyOnHand)}
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
