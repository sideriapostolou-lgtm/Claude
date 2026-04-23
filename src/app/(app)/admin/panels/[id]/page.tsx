import { notFound } from "next/navigation";
import Link from "next/link";
import { db, schema } from "@/db";
import { eq } from "drizzle-orm";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getBomForPanel } from "@/lib/queries";
import { PanelBomEditor } from "./bom-editor";

export const dynamic = "force-dynamic";

export default async function AdminPanelDetail({
  params,
}: {
  params: { id: string };
}) {
  const [panel] = await db
    .select()
    .from(schema.panelTypes)
    .where(eq(schema.panelTypes.id, params.id));
  if (!panel) notFound();
  const bom = await getBomForPanel(panel.id);

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <Link
          href="/admin/panels"
          className="text-sm text-secondary hover:underline"
        >
          ← All panel types
        </Link>
        <h1 className="text-2xl font-semibold text-omega-navy mt-1 font-mono">
          {panel.skuCode}
        </h1>
        <p className="text-sm text-muted-foreground">{panel.displayName}</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Edit BOM</CardTitle>
        </CardHeader>
        <CardContent>
          <PanelBomEditor
            panelId={panel.id}
            panelDisplayName={panel.displayName}
            panelActive={panel.active}
            lines={bom.map((b) => ({
              id: b.line.id,
              materialName: b.material.name,
              unit: b.material.unit,
              qtyPerPanel: b.line.qtyPerPanel,
            }))}
          />
        </CardContent>
      </Card>
    </div>
  );
}
