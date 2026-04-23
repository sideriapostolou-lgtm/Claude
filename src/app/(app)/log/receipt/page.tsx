import {
  getVancouverPlant,
  getRawMaterialsWithStock,
} from "@/lib/queries";
import { ReceiptForm } from "./receipt-form";

export const dynamic = "force-dynamic";

export default async function LogReceiptPage({
  searchParams,
}: {
  searchParams: { material?: string };
}) {
  const plant = await getVancouverPlant();
  const materials = await getRawMaterialsWithStock(plant.id);
  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-omega-navy">
          Log a raw-material receipt
        </h1>
        <p className="text-sm text-muted-foreground">
          Creates a new lot and increases on-hand.
        </p>
      </div>
      <ReceiptForm
        plantId={plant.id}
        defaultMaterialId={searchParams.material}
        materials={materials.map((m) => ({
          id: m.id,
          name: m.name,
          unit: m.unit,
          vendor: m.vendor,
        }))}
      />
    </div>
  );
}
