import Link from "next/link";
import {
  getVancouverPlant,
  getFinishedGoodsWithStock,
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
import { formatNumber } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { FinishedGoodsFilters } from "./filters";

export const dynamic = "force-dynamic";

export default async function FinishedGoodsPage({
  searchParams,
}: {
  searchParams: { length?: string; plate?: string; weight?: string };
}) {
  const [plant, user] = await Promise.all([
    getVancouverPlant(),
    getCurrentUser(),
  ]);
  const goods = await getFinishedGoodsWithStock(plant.id);

  const filtered = goods.filter((g) => {
    if (searchParams.length && g.lengthFt !== Number(searchParams.length))
      return false;
    if (searchParams.plate && g.plateType !== searchParams.plate) return false;
    if (searchParams.weight && g.railWeight !== Number(searchParams.weight))
      return false;
    return true;
  });

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-omega-navy">
            Finished goods
          </h1>
          <p className="text-sm text-muted-foreground">
            36 panel types · {plant.name}
          </p>
        </div>
        {user?.role === "admin" && (
          <div className="flex gap-2">
            <Button asChild variant="secondary">
              <Link href="/log/build">Log build</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/log/shipment">Log shipment</Link>
            </Button>
          </div>
        )}
      </div>

      <FinishedGoodsFilters />

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>SKU</TableHead>
                <TableHead>Description</TableHead>
                <TableHead className="text-right">Length</TableHead>
                <TableHead>Plate</TableHead>
                <TableHead className="text-right">Rail #</TableHead>
                <TableHead className="text-right">On hand</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((g) => (
                <TableRow key={g.id}>
                  <TableCell className="font-mono text-xs">
                    <Link
                      href={`/finished-goods/${g.id}`}
                      className="font-semibold hover:underline"
                    >
                      {g.skuCode}
                    </Link>
                  </TableCell>
                  <TableCell>{g.displayName}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {g.lengthFt}′
                  </TableCell>
                  <TableCell>{g.plateType}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {g.railWeight}#
                  </TableCell>
                  <TableCell className="text-right tabular-nums font-semibold">
                    {formatNumber(g.qtyOnHand)}
                  </TableCell>
                </TableRow>
              ))}
              {filtered.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                    No panel types match those filters.
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
