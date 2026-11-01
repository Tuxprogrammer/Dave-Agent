package com.tuxprogrammer.davebridge.client.compat;

import net.minecraft.item.ItemStack;

import codechicken.nei.recipe.GuiCraftingRecipe;
import codechicken.nei.recipe.GuiUsageRecipe;
import cpw.mods.fml.common.Loader;

/**
 * Opens NEI's recipe or usage page for an item. NEI has no chat command for this (its only chat link,
 * {@code /nei_bookmark}, adds a bookmark), so this is the client half's gap-filler. Only opens a GUI.
 */
// Source:
// https://github.com/GTNewHorizons/NotEnoughItems/blob/2.8.171-GTNH/src/main/java/codechicken/nei/recipe/GuiCraftingRecipe.java#L26
// openRecipeGui("item", stack) / GuiUsageRecipe.openRecipeGui("item", stack) return false when nothing matches.
public final class NeiPages {

    private NeiPages() {}

    public static boolean available() {
        return Loader.isModLoaded("NotEnoughItems");
    }

    /** @return false if NEI has no recipe (or usage) for the stack */
    public static boolean open(ItemStack stack, boolean usage) {
        return usage ? Impl.usage(stack) : Impl.recipe(stack);
    }

    private static final class Impl {

        static boolean recipe(ItemStack stack) {
            return GuiCraftingRecipe.openRecipeGui("item", stack);
        }

        static boolean usage(ItemStack stack) {
            return GuiUsageRecipe.openRecipeGui("item", stack);
        }
    }
}
