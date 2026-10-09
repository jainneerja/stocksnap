import { createContext, useContext } from "react";
import type { Preset, Shop } from "./api";

export interface ShopState {
  shop: Shop;
  presets: Preset[];
  logoVersion: number;
}

export const ShopContext = createContext<ShopState | null>(null);

export function useShop(): ShopState {
  const s = useContext(ShopContext);
  if (!s) throw new Error("useShop outside ShopContext");
  return s;
}

/** Fixed categories for this shop's main product type (empty for "other"). */
export function shopCategories(state: ShopState | null): string[] {
  if (!state) return [];
  return state.presets.find((p) => p.key === state.shop.kind)?.categories ?? [];
}
