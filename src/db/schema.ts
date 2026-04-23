import {
  pgTable,
  uuid,
  text,
  integer,
  boolean,
  timestamp,
  uniqueIndex,
} from "drizzle-orm/pg-core";
import { relations } from "drizzle-orm";

export const plants = pgTable("plants", {
  id: uuid("id").defaultRandom().primaryKey(),
  code: text("code").notNull().unique(),
  name: text("name").notNull(),
  address: text("address"),
  active: boolean("active").notNull().default(true),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const users = pgTable("users", {
  id: uuid("id").defaultRandom().primaryKey(),
  email: text("email").notNull().unique(),
  name: text("name").notNull(),
  role: text("role").notNull(), // 'admin' | 'viewer' | 'operator'
  active: boolean("active").notNull().default(true),
  receiveAlerts: boolean("receive_alerts").notNull().default(true),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const rawMaterials = pgTable("raw_materials", {
  id: uuid("id").defaultRandom().primaryKey(),
  name: text("name").notNull().unique(),
  skuCode: text("sku_code"),
  unit: text("unit").notNull(),
  category: text("category").notNull(),
  reorderPoint: integer("reorder_point"),
  reorderQty: integer("reorder_qty"),
  vendor: text("vendor"),
  buyAmerica: boolean("buy_america").notNull().default(false),
  notes: text("notes"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const rawMaterialStock = pgTable(
  "raw_material_stock",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    rawMaterialId: uuid("raw_material_id")
      .notNull()
      .references(() => rawMaterials.id, { onDelete: "cascade" }),
    plantId: uuid("plant_id")
      .notNull()
      .references(() => plants.id, { onDelete: "cascade" }),
    qtyOnHand: integer("qty_on_hand").notNull().default(0),
    lastUpdated: timestamp("last_updated", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqMaterialPlant: uniqueIndex("raw_material_stock_material_plant_uniq").on(
      t.rawMaterialId,
      t.plantId
    ),
  })
);

export const rawMaterialLots = pgTable("raw_material_lots", {
  id: uuid("id").defaultRandom().primaryKey(),
  rawMaterialId: uuid("raw_material_id")
    .notNull()
    .references(() => rawMaterials.id, { onDelete: "cascade" }),
  plantId: uuid("plant_id")
    .notNull()
    .references(() => plants.id, { onDelete: "cascade" }),
  lotNumber: text("lot_number").notNull(),
  vendor: text("vendor"),
  poNumber: text("po_number"),
  qtyReceived: integer("qty_received").notNull(),
  qtyRemaining: integer("qty_remaining").notNull(),
  receivedAt: timestamp("received_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
  receivedBy: uuid("received_by").references(() => users.id),
  notes: text("notes"),
});

export const panelTypes = pgTable("panel_types", {
  id: uuid("id").defaultRandom().primaryKey(),
  skuCode: text("sku_code").notNull().unique(),
  lengthFt: integer("length_ft").notNull(),
  plateType: text("plate_type").notNull(), // 'Standard' | 'Pandrol'
  tieType: text("tie_type").notNull(),
  railWeight: integer("rail_weight").notNull(),
  fastenerType: text("fastener_type").notNull(),
  displayName: text("display_name").notNull(),
  active: boolean("active").notNull().default(true),
});

export const bomLines = pgTable(
  "bom_lines",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    panelTypeId: uuid("panel_type_id")
      .notNull()
      .references(() => panelTypes.id, { onDelete: "cascade" }),
    rawMaterialId: uuid("raw_material_id")
      .notNull()
      .references(() => rawMaterials.id, { onDelete: "cascade" }),
    qtyPerPanel: integer("qty_per_panel").notNull(),
  },
  (t) => ({
    uniqPanelMaterial: uniqueIndex("bom_lines_panel_material_uniq").on(
      t.panelTypeId,
      t.rawMaterialId
    ),
  })
);

export const finishedGoodsStock = pgTable(
  "finished_goods_stock",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    panelTypeId: uuid("panel_type_id")
      .notNull()
      .references(() => panelTypes.id, { onDelete: "cascade" }),
    plantId: uuid("plant_id")
      .notNull()
      .references(() => plants.id, { onDelete: "cascade" }),
    qtyOnHand: integer("qty_on_hand").notNull().default(0),
    lastUpdated: timestamp("last_updated", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqPanelPlant: uniqueIndex("finished_goods_stock_panel_plant_uniq").on(
      t.panelTypeId,
      t.plantId
    ),
  })
);

export const buildEvents = pgTable("build_events", {
  id: uuid("id").defaultRandom().primaryKey(),
  panelTypeId: uuid("panel_type_id")
    .notNull()
    .references(() => panelTypes.id),
  plantId: uuid("plant_id")
    .notNull()
    .references(() => plants.id),
  qtyBuilt: integer("qty_built").notNull(),
  railWasteFt: integer("rail_waste_ft").notNull().default(0),
  builtAt: timestamp("built_at", { withTimezone: true }).notNull().defaultNow(),
  builtBy: uuid("built_by").references(() => users.id),
  notes: text("notes"),
});

export const buildEventConsumption = pgTable("build_event_consumption", {
  id: uuid("id").defaultRandom().primaryKey(),
  buildEventId: uuid("build_event_id")
    .notNull()
    .references(() => buildEvents.id, { onDelete: "cascade" }),
  rawMaterialId: uuid("raw_material_id")
    .notNull()
    .references(() => rawMaterials.id),
  qtyConsumed: integer("qty_consumed").notNull(),
  lotId: uuid("lot_id").references(() => rawMaterialLots.id),
});

export const shipmentEvents = pgTable("shipment_events", {
  id: uuid("id").defaultRandom().primaryKey(),
  panelTypeId: uuid("panel_type_id")
    .notNull()
    .references(() => panelTypes.id),
  plantId: uuid("plant_id")
    .notNull()
    .references(() => plants.id),
  qtyShipped: integer("qty_shipped").notNull(),
  customer: text("customer").notNull().default("BNSF"),
  poNumber: text("po_number"),
  shippedAt: timestamp("shipped_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
  shippedBy: uuid("shipped_by").references(() => users.id),
  notes: text("notes"),
});

export const alertLog = pgTable("alert_log", {
  id: uuid("id").defaultRandom().primaryKey(),
  rawMaterialId: uuid("raw_material_id")
    .notNull()
    .references(() => rawMaterials.id, { onDelete: "cascade" }),
  plantId: uuid("plant_id")
    .notNull()
    .references(() => plants.id, { onDelete: "cascade" }),
  qtyAtAlert: integer("qty_at_alert").notNull(),
  reorderPoint: integer("reorder_point").notNull(),
  sentAt: timestamp("sent_at", { withTimezone: true }).notNull().defaultNow(),
  recipients: text("recipients").array().notNull(),
});

export const loginTokens = pgTable("login_tokens", {
  id: uuid("id").defaultRandom().primaryKey(),
  userId: uuid("user_id")
    .notNull()
    .references(() => users.id, { onDelete: "cascade" }),
  tokenHash: text("token_hash").notNull().unique(),
  expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
  consumedAt: timestamp("consumed_at", { withTimezone: true }),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

// Relations (used for Drizzle query API joins)

export const rawMaterialsRelations = relations(rawMaterials, ({ many }) => ({
  stock: many(rawMaterialStock),
  lots: many(rawMaterialLots),
  bomLines: many(bomLines),
}));

export const panelTypesRelations = relations(panelTypes, ({ many }) => ({
  bomLines: many(bomLines),
  stock: many(finishedGoodsStock),
  builds: many(buildEvents),
  shipments: many(shipmentEvents),
}));

export const bomLinesRelations = relations(bomLines, ({ one }) => ({
  panelType: one(panelTypes, {
    fields: [bomLines.panelTypeId],
    references: [panelTypes.id],
  }),
  rawMaterial: one(rawMaterials, {
    fields: [bomLines.rawMaterialId],
    references: [rawMaterials.id],
  }),
}));

export const rawMaterialStockRelations = relations(rawMaterialStock, ({ one }) => ({
  rawMaterial: one(rawMaterials, {
    fields: [rawMaterialStock.rawMaterialId],
    references: [rawMaterials.id],
  }),
  plant: one(plants, {
    fields: [rawMaterialStock.plantId],
    references: [plants.id],
  }),
}));

export const finishedGoodsStockRelations = relations(finishedGoodsStock, ({ one }) => ({
  panelType: one(panelTypes, {
    fields: [finishedGoodsStock.panelTypeId],
    references: [panelTypes.id],
  }),
  plant: one(plants, {
    fields: [finishedGoodsStock.plantId],
    references: [plants.id],
  }),
}));

export const buildEventsRelations = relations(buildEvents, ({ one, many }) => ({
  panelType: one(panelTypes, {
    fields: [buildEvents.panelTypeId],
    references: [panelTypes.id],
  }),
  plant: one(plants, {
    fields: [buildEvents.plantId],
    references: [plants.id],
  }),
  builtByUser: one(users, {
    fields: [buildEvents.builtBy],
    references: [users.id],
  }),
  consumption: many(buildEventConsumption),
}));

export const buildEventConsumptionRelations = relations(
  buildEventConsumption,
  ({ one }) => ({
    buildEvent: one(buildEvents, {
      fields: [buildEventConsumption.buildEventId],
      references: [buildEvents.id],
    }),
    rawMaterial: one(rawMaterials, {
      fields: [buildEventConsumption.rawMaterialId],
      references: [rawMaterials.id],
    }),
    lot: one(rawMaterialLots, {
      fields: [buildEventConsumption.lotId],
      references: [rawMaterialLots.id],
    }),
  })
);

export const shipmentEventsRelations = relations(shipmentEvents, ({ one }) => ({
  panelType: one(panelTypes, {
    fields: [shipmentEvents.panelTypeId],
    references: [panelTypes.id],
  }),
  plant: one(plants, {
    fields: [shipmentEvents.plantId],
    references: [plants.id],
  }),
  shippedByUser: one(users, {
    fields: [shipmentEvents.shippedBy],
    references: [users.id],
  }),
}));

export type Plant = typeof plants.$inferSelect;
export type User = typeof users.$inferSelect;
export type RawMaterial = typeof rawMaterials.$inferSelect;
export type RawMaterialStock = typeof rawMaterialStock.$inferSelect;
export type PanelType = typeof panelTypes.$inferSelect;
export type BomLine = typeof bomLines.$inferSelect;
export type FinishedGoodsStock = typeof finishedGoodsStock.$inferSelect;
export type BuildEvent = typeof buildEvents.$inferSelect;
export type ShipmentEvent = typeof shipmentEvents.$inferSelect;
