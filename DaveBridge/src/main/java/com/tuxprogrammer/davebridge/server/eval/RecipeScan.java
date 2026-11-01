package com.tuxprogrammer.davebridge.server.eval;

import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import net.minecraft.item.Item;
import net.minecraft.item.ItemStack;
import net.minecraftforge.fluids.FluidStack;
import net.minecraftforge.oredict.OreDictionary;

/**
 * Fast scans for eval scripts: matching item stacks and walking every GregTech recipe map in Java, so a recipe
 * lookup takes milliseconds of the server tick instead of seconds of dynamic Groovy calls (GTNH has well over
 * 100,000 recipes). Scripts get it as {@code dave.items(spec)} and {@code dave.gtRecipes(...)}.
 * <p>
 * GregTech is reached by reflection. Contracts, GT5-Unofficial 5.09.54.265: {@code RecipeMap.ALL_RECIPE_MAPS}
 * (public static Map, api/recipe/RecipeMap.java:48), {@code getAllRecipes()} (:88); {@code GTRecipe} public fields
 * {@code mInputs}, {@code mOutputs} (ItemStack[]), {@code mFluidInputs}, {@code mFluidOutputs} (FluidStack[])
 * (api/util/GTRecipe.java:67,73).
 */
public final class RecipeScan {

    private RecipeScan() {}

    /** Matches stacks against {@code modid:name[:meta]}, {@code ore:<name>} or a display-name fragment. */
    public static final class ItemMatcher {

        private final Item item;
        private final int meta; // -1: any
        private final List<int[]> ores; // [itemId, meta] pairs
        private final String name;
        private final Map<Long, Boolean> nameCache = new HashMap<>();
        public final String error;

        private ItemMatcher(Item item, int meta, List<int[]> ores, String name, String error) {
            this.item = item;
            this.meta = meta;
            this.ores = ores;
            this.name = name;
            this.error = error;
        }

        public static ItemMatcher of(String spec) {
            String s = spec == null ? "" : spec.trim();
            if (s.isEmpty()) {
                return new ItemMatcher(null, -1, null, null, "empty item");
            }
            if (s.startsWith("ore:")) {
                List<int[]> ores = new ArrayList<>();
                for (ItemStack o : OreDictionary.getOres(s.substring(4))) {
                    ores.add(new int[] { Item.getIdFromItem(o.getItem()), o.getItemDamage() });
                }
                return new ItemMatcher(
                    null,
                    -1,
                    ores,
                    null,
                    ores.isEmpty() ? "no items with ore name " + s.substring(4) : null);
            }
            if (s.contains(":")) {
                String[] parts = s.split(":");
                Object item = Item.itemRegistry.getObject(parts[0] + ":" + parts[1]);
                if (!(item instanceof Item)) {
                    return new ItemMatcher(null, -1, null, null, "unknown item id " + parts[0] + ":" + parts[1]);
                }
                int meta = -1;
                if (parts.length > 2) {
                    try {
                        meta = Integer.parseInt(parts[2]);
                    } catch (NumberFormatException e) {
                        return new ItemMatcher(null, -1, null, null, "bad meta in " + s);
                    }
                }
                return new ItemMatcher((Item) item, meta, null, null, null);
            }
            return new ItemMatcher(null, -1, null, s.toLowerCase(Locale.ROOT), null);
        }

        public boolean test(ItemStack s) {
            if (s == null || s.getItem() == null) {
                return false;
            }
            int damage = s.getItemDamage();
            if (item != null) {
                return s.getItem() == item && (meta < 0 || damage == meta || damage == OreDictionary.WILDCARD_VALUE);
            }
            if (ores != null) {
                int id = Item.getIdFromItem(s.getItem());
                for (int[] o : ores) {
                    if (o[0] == id && (o[1] == damage || o[1] == OreDictionary.WILDCARD_VALUE)) {
                        return true;
                    }
                }
                return false;
            }
            if (name != null) {
                long key = ((long) Item.getIdFromItem(s.getItem()) << 32) | (damage & 0xffffffffL);
                Boolean hit = nameCache.get(key);
                if (hit == null) {
                    String display;
                    try {
                        display = s.getDisplayName();
                    } catch (Throwable t) {
                        display = "";
                    }
                    hit = display != null && display.toLowerCase(Locale.ROOT)
                        .contains(name);
                    nameCache.put(key, hit);
                }
                return hit;
            }
            return false;
        }

        public boolean any(Object[] stacks) {
            if (stacks == null) {
                return false;
            }
            for (Object o : stacks) {
                if (o instanceof ItemStack && test((ItemStack) o)) {
                    return true;
                }
            }
            return false;
        }
    }

    private static boolean anyFluid(Object[] fluids, String name) {
        if (fluids == null) {
            return false;
        }
        for (Object o : fluids) {
            if (o instanceof FluidStack && ((FluidStack) o).getFluid() != null
                && ((FluidStack) o).getFluid()
                    .getName()
                    .equalsIgnoreCase(name)) {
                return true;
            }
        }
        return false;
    }

    /**
     * Every GT recipe that produces ({@code uses=false}) or consumes the item or fluid, as
     * {@code {matched, recipes: [{map, recipe}]}} with at most {@code limit} recipes kept.
     *
     * @param itemSpec  item spec (see {@link ItemMatcher#of}), or null when looking for a fluid
     * @param fluid     fluid registry name, or null
     * @param mapFilter only maps whose name contains this (case-insensitive), or null
     */
    public static Map<String, Object> gtRecipes(String itemSpec, String fluid, boolean uses, String mapFilter,
        int limit) throws ReflectiveOperationException {
        Map<String, Object> out = new LinkedHashMap<>();
        ItemMatcher matcher = itemSpec == null ? null : ItemMatcher.of(itemSpec);
        if (matcher != null && matcher.error != null) {
            out.put("error", matcher.error);
            return out;
        }
        Class<?> recipeMap = Class.forName("gregtech.api.recipe.RecipeMap", false, RecipeScan.class.getClassLoader());
        Map<?, ?> maps = (Map<?, ?>) recipeMap.getField("ALL_RECIPE_MAPS")
            .get(null);
        String filter = mapFilter == null ? null : mapFilter.toLowerCase(Locale.ROOT);
        Field items = null, fluids = null;
        int matched = 0;
        List<Map<String, Object>> kept = new ArrayList<>();
        for (Map.Entry<?, ?> e : maps.entrySet()) {
            String mapName = String.valueOf(e.getKey());
            if (filter != null && !mapName.toLowerCase(Locale.ROOT)
                .contains(filter)) {
                continue;
            }
            Collection<?> recipes = (Collection<?>) e.getValue()
                .getClass()
                .getMethod("getAllRecipes")
                .invoke(e.getValue());
            for (Object r : recipes) {
                if (items == null) {
                    Class<?> gtRecipe = r.getClass();
                    items = gtRecipe.getField(uses ? "mInputs" : "mOutputs");
                    fluids = gtRecipe.getField(uses ? "mFluidInputs" : "mFluidOutputs");
                }
                boolean hit = matcher != null ? matcher.any((Object[]) items.get(r))
                    : anyFluid((Object[]) fluids.get(r), fluid);
                if (!hit) {
                    continue;
                }
                matched++;
                if (kept.size() < limit) {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("map", mapName);
                    row.put("recipe", r);
                    kept.add(row);
                }
            }
        }
        out.put("matched", matched);
        out.put("recipes", kept);
        return out;
    }
}
