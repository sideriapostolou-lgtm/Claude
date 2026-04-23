// Static seed data from CLAUDE spec (Sideri, 4/22/26 revision).

export const PLANT = {
  code: "VAN",
  name: "Vancouver, WA",
  address: "Vancouver, WA",
};

export const USERS = [
  {
    email: "sideri@omega-industries.com",
    name: "Sideri Apostolou",
    role: "admin" as const,
  },
  {
    email: "argyro@omega-industries.com",
    name: "Argyro Apostolou",
    role: "viewer" as const,
  },
  {
    email: "serafim@omega-industries.com",
    name: "Serafim Apostolou",
    role: "admin" as const,
  },
];

export type RawMaterialSeed = {
  name: string;
  unit: string;
  category: string;
  buyAmerica?: boolean;
  reorderPoint?: number | null;
};

export const RAW_MATERIALS: RawMaterialSeed[] = [
  { name: `New 115# 80' Rail Head Hardened`, unit: "sticks", category: "RAILS" },
  { name: `New 136# 80' Rail Head Hardened`, unit: "sticks", category: "RAILS" },
  { name: `New 141# 80' Rail Head Hardened`, unit: "sticks", category: "RAILS" },
  { name: `New 136# 70' Rail SS`, unit: "sticks", category: "RAILS" },
  { name: `7"x9"x8'-6" Hardwood Tie`, unit: "each", category: "TIES", reorderPoint: 900 },
  { name: `7"x9"x10' Hardwood Tie`, unit: "each", category: "TIES", reorderPoint: 600 },
  { name: `14" Tie Plate Std 5.5" base`, unit: "each", category: "TIE PLATES", reorderPoint: 1000 },
  { name: `14" Tie Plate Std 6" base`, unit: "each", category: "TIE PLATES", reorderPoint: 3000 },
  { name: `15" Tie Plate Pandrol 5.5" base`, unit: "each", category: "TIE PLATES", reorderPoint: 1000 },
  { name: `16" Tie Plate Pandrol 6" base`, unit: "each", category: "TIE PLATES", reorderPoint: 3000 },
  { name: `Bar Stock Anchor 5.5" base`, unit: "each", category: "ANCHORS", reorderPoint: 2000 },
  { name: `Bar Stock Anchor 6" base`, unit: "each", category: "ANCHORS", reorderPoint: 6000 },
  { name: `Joint Bar 115RE`, unit: "each", category: "JOINT BARS" },
  { name: `Joint Bar 136RE`, unit: "each", category: "JOINT BARS" },
  { name: `1-1/16"x6" Track Bolt + Washer (#115)`, unit: "sets", category: "BOLTS", reorderPoint: 100 },
  { name: `1-1/8"x6" Track Bolt + Washer (#136)`, unit: "sets", category: "BOLTS", reorderPoint: 400 },
  { name: `Pandrol "E" Clip PR601`, unit: "each", category: "FASTENERS", reorderPoint: 10000 },
  { name: `Cut Spikes (5/8"x6")`, unit: "each", category: "FASTENERS", reorderPoint: 15000 },
  { name: `Screw Spikes (5/8"x6")`, unit: "each", category: "FASTENERS", reorderPoint: 3000 },
  { name: `Bonding Wire (P/N 39242)`, unit: "each", category: "WELDING", reorderPoint: 200 },
  { name: `Brazing Pin (P/N 35835)`, unit: "each", category: "WELDING", reorderPoint: 200 },
  { name: `Ceramic Ring (P/N 35832)`, unit: "each", category: "WELDING", reorderPoint: 200 },
];

// Initial on-hand counts from 4/3/26 report. Replaced at launch via bulk-count page.
export const RAW_MATERIAL_ON_HAND: Record<string, number> = {
  [`New 115# 80' Rail Head Hardened`]: 33,
  [`New 136# 80' Rail Head Hardened`]: 57,
  [`New 141# 80' Rail Head Hardened`]: 38,
  [`New 136# 70' Rail SS`]: 2,
  [`7"x9"x8'-6" Hardwood Tie`]: 1367,
  [`7"x9"x10' Hardwood Tie`]: 506,
  [`14" Tie Plate Std 5.5" base`]: 912,
  [`14" Tie Plate Std 6" base`]: 6864,
  [`15" Tie Plate Pandrol 5.5" base`]: 1964,
  [`16" Tie Plate Pandrol 6" base`]: 5708,
  [`Bar Stock Anchor 5.5" base`]: 5058,
  [`Bar Stock Anchor 6" base`]: 23056,
  [`Joint Bar 115RE`]: 84,
  [`Joint Bar 136RE`]: 20,
  [`1-1/16"x6" Track Bolt + Washer (#115)`]: 250,
  [`1-1/8"x6" Track Bolt + Washer (#136)`]: 1304,
  [`Pandrol "E" Clip PR601`]: 13214,
  [`Cut Spikes (5/8"x6")`]: 41601,
  [`Screw Spikes (5/8"x6")`]: 11848,
  [`Bonding Wire (P/N 39242)`]: 1136,
  [`Brazing Pin (P/N 35835)`]: 1036,
  [`Ceramic Ring (P/N 35832)`]: 1536,
};

// Initial finished panel counts from 4/3/26 report. Missing SKUs default to 0.
export const FINISHED_ON_HAND: Record<string, number> = {
  OM40SE115: 24,
  OM40PE115: 2,
  OM40ST115: 0,
  OM40PT115: 10,
  OM40SE136: 111,
  OM40PE136: 3,
  OM40ST136: 1,
  OM40PT136: 18,
  OM60PT136: 0,
  OM80SE136: 0,
  OM80PT136: 0,
  OM40SE141: 1,
  OM40PT141: 2,
  OM40PE141: 6,
  OM60PE141: 2,
};
