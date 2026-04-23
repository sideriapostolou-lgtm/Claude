import {
  getVancouverPlant,
  getRawMaterialsWithStock,
  getFinishedGoodsWithStock,
} from "@/lib/queries";
import { BulkCountForm } from "./bulk-form";

export const dynamic = "force-dynamic";

export default async function BulkCountPage() {
  const plant = await getVancouverPlant();
  const [raw, finished] = await Promise.all([
    getRawMaterialsWithStock(plant.id),
    getFinishedGoodsWithStock(plant.id),
  ]);
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-omega-navy">
          Bulk physical count
        </h1>
        <p className="text-sm text-muted-foreground max-w-2xl">
          Use this page during a physical inventory count — for example at
          go-live. All values save in one transaction when you click{" "}
          <span className="font-medium">Save all</span>.
        </p>
      </div>
      <BulkCountForm
        plantId={plant.id}
        raw={raw.map((r) => ({
          id: r.id,
          name: r.name,
          category: r.category,
          unit: r.unit,
          qtyOnHand: r.qtyOnHand,
        }))}
        finished={finished.map((f) => ({
          id: f.id,
          skuCode: f.skuCode,
          displayName: f.displayName,
          qtyOnHand: f.qtyOnHand,
        }))}
      />
    </div>
  );
}
