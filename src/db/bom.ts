// BOM calculation logic — keep this identical across seed + UI "can build" math.
// Source of truth: CLAUDE spec 4/22/26 (Sideri). 80' sticks only; 40'/60' cut on floor.

export type PanelTypeCode = "SE" | "PE" | "ST" | "PT"; // Std-8'6", Pandrol-8'6", Std-10', Pandrol-10'
export type RailWeight = 115 | 136 | 141;
export type PanelLength = 40 | 60 | 80;

export interface BomLineSpec {
  material: string; // raw_materials.name
  qty: number;
}

export function calcBom(
  length: PanelLength,
  type: PanelTypeCode,
  weight: RailWeight
): BomLineSpec[] {
  const scale = length / 40;
  const plate = type[0] as "S" | "P";
  const tieLen = type[1] as "E" | "T"; // 'E' = 8'6", 'T' = 10'
  const base = weight === 115 ? "5.5" : "6";
  const railSticks = length === 40 ? 1 : 2;

  const lines: BomLineSpec[] = [
    { material: `New ${weight}# 80' Rail Head Hardened`, qty: railSticks },
    {
      material:
        tieLen === "E" ? `7"x9"x8'-6" Hardwood Tie` : `7"x9"x10' Hardwood Tie`,
      qty: Math.round(24 * scale),
    },
  ];

  if (plate === "S") {
    lines.push({
      material: `14" Tie Plate Std ${base}" base`,
      qty: Math.round(48 * scale),
    });
    lines.push({
      material: `Bar Stock Anchor ${base}" base`,
      qty: Math.round(96 * scale),
    });
  } else {
    const platePrefix = weight === 115 ? "15" : "16";
    lines.push({
      material: `${platePrefix}" Tie Plate Pandrol ${base}" base`,
      qty: Math.round(48 * scale),
    });
  }

  lines.push({
    material: weight === 115 ? `Joint Bar 115RE` : `Joint Bar 136RE`,
    qty: 4,
  });
  lines.push({
    material:
      weight === 115
        ? `1-1/16"x6" Track Bolt + Washer (#115)`
        : `1-1/8"x6" Track Bolt + Washer (#136)`,
    qty: 8,
  });
  lines.push({
    material: plate === "S" ? `Cut Spikes (5/8"x6")` : `Screw Spikes (5/8"x6")`,
    qty: Math.round(192 * scale),
  });

  if (plate === "P") {
    lines.push({
      material: `Pandrol "E" Clip PR601`,
      qty: Math.round(96 * scale),
    });
  }

  lines.push({ material: `Bonding Wire (P/N 39242)`, qty: 4 });
  lines.push({ material: `Brazing Pin (P/N 35835)`, qty: 4 });
  lines.push({ material: `Ceramic Ring (P/N 35832)`, qty: 4 });

  return lines;
}

export function displayName(
  length: PanelLength,
  type: PanelTypeCode,
  weight: RailWeight
): string {
  const plate = type[0] === "S" ? "Standard" : "Pandrol";
  const tie = type[1] === "E" ? `8'6" tie` : `10' switch tie`;
  return `${plate} Track Panel — ${length}ft, ${weight}# rail, ${tie}`;
}

export function railWasteForBuild(length: PanelLength, qtyBuilt: number): number {
  // 60' panel: 2 sticks of 80' rail cut to 60' → 20' scrap per stick × 2 sticks = 40ft per panel
  return length === 60 ? qtyBuilt * 40 : 0;
}

export function fastenerType(type: PanelTypeCode): string {
  return type[0] === "S" ? "Cut Spikes" : "Screw Spikes + Pandrol Clip";
}

export function panelSku(length: PanelLength, type: PanelTypeCode, weight: RailWeight) {
  return `OM${length}${type}${weight}`;
}

export const ALL_LENGTHS: PanelLength[] = [40, 60, 80];
export const ALL_TYPES: PanelTypeCode[] = ["SE", "PE", "ST", "PT"];
export const ALL_WEIGHTS: RailWeight[] = [115, 136, 141];
