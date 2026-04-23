import {
  getVancouverPlant,
  getFinishedGoodsWithStock,
} from "@/lib/queries";
import { ShipmentForm } from "./shipment-form";

export const dynamic = "force-dynamic";

export default async function LogShipmentPage({
  searchParams,
}: {
  searchParams: { panel?: string };
}) {
  const plant = await getVancouverPlant();
  const panels = await getFinishedGoodsWithStock(plant.id);
  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-omega-navy">Log a shipment</h1>
        <p className="text-sm text-muted-foreground">
          Records finished panels shipped out. Decrements finished-goods on-hand.
        </p>
      </div>
      <ShipmentForm
        plantId={plant.id}
        defaultPanelId={searchParams.panel}
        panels={panels.map((p) => ({
          id: p.id,
          skuCode: p.skuCode,
          displayName: p.displayName,
          qtyOnHand: p.qtyOnHand,
        }))}
      />
    </div>
  );
}
