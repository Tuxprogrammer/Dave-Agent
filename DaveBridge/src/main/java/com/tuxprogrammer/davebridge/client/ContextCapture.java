package com.tuxprogrammer.davebridge.client;

import net.minecraft.block.Block;
import net.minecraft.client.Minecraft;
import net.minecraft.entity.Entity;
import net.minecraft.entity.EntityList;
import net.minecraft.item.Item;
import net.minecraft.item.ItemStack;
import net.minecraft.tileentity.TileEntity;
import net.minecraft.util.MovingObjectPosition;
import net.minecraft.world.World;
import net.minecraft.world.biome.BiomeGenBase;

import com.google.gson.JsonObject;

/**
 * Captures what the player is looking at, holding and has open, for an {@code Ask}. Every lookup is guarded: some
 * mods throw from display-name or pick-block code, and a failed lookup should just leave the field out.
 */
public final class ContextCapture {

    private ContextCapture() {}

    public static JsonObject capture(Minecraft mc) {
        JsonObject ctx = new JsonObject();
        try {
            if (mc.thePlayer != null) {
                ctx.addProperty("dim", mc.thePlayer.dimension);
                ItemStack held = mc.thePlayer.getHeldItem();
                if (held != null) {
                    ctx.add("heldItem", describe(held));
                }
            }
            if (mc.currentScreen != null) {
                ctx.addProperty(
                    "openGui",
                    mc.currentScreen.getClass()
                        .getName());
            }
            World world = mc.theWorld;
            MovingObjectPosition hit = mc.objectMouseOver;
            if (world != null && hit != null) {
                if (hit.typeOfHit == MovingObjectPosition.MovingObjectType.BLOCK) {
                    ctx.add("lookingAt", describeBlock(world, hit));
                } else if (hit.typeOfHit == MovingObjectPosition.MovingObjectType.ENTITY && hit.entityHit != null) {
                    ctx.add("lookingAt", describeEntity(hit.entityHit));
                }
            }
            if (world != null && mc.thePlayer != null) {
                BiomeGenBase biome = world
                    .getBiomeGenForCoords((int) Math.floor(mc.thePlayer.posX), (int) Math.floor(mc.thePlayer.posZ));
                if (biome != null) {
                    ctx.addProperty("biome", biome.biomeName);
                }
            }
            // TODO: NEI hovered item (needs NEI's API on the classpath; GuiContainerManager.getStackMouseOver).
            // TODO: capture while a GUI is open (key presses in GUIs do not reach KeyInputEvent in 1.7.10).
        } catch (Throwable t) {
            ctx.addProperty("captureError", t.toString());
        }
        return ctx;
    }

    private static JsonObject describeBlock(World world, MovingObjectPosition hit) {
        JsonObject o = new JsonObject();
        o.addProperty("kind", "block");
        o.addProperty("x", hit.blockX);
        o.addProperty("y", hit.blockY);
        o.addProperty("z", hit.blockZ);
        o.addProperty("side", hit.sideHit);
        Block block = world.getBlock(hit.blockX, hit.blockY, hit.blockZ);
        o.addProperty("id", String.valueOf(Block.blockRegistry.getNameForObject(block)));
        o.addProperty("meta", world.getBlockMetadata(hit.blockX, hit.blockY, hit.blockZ));
        try {
            ItemStack pick = block
                .getPickBlock(hit, world, hit.blockX, hit.blockY, hit.blockZ, Minecraft.getMinecraft().thePlayer);
            if (pick != null) {
                o.addProperty("name", pick.getDisplayName());
            }
        } catch (Throwable t) {
            try {
                o.addProperty("name", block.getLocalizedName());
            } catch (Throwable ignored) {}
        }
        TileEntity te = world.getTileEntity(hit.blockX, hit.blockY, hit.blockZ);
        if (te != null) {
            o.addProperty(
                "tileEntity",
                te.getClass()
                    .getName());
        }
        return o;
    }

    private static JsonObject describeEntity(Entity entity) {
        JsonObject o = new JsonObject();
        o.addProperty("kind", "entity");
        o.addProperty("entityId", entity.getEntityId());
        o.addProperty(
            "class",
            entity.getClass()
                .getName());
        String type = EntityList.getEntityString(entity);
        if (type != null) {
            o.addProperty("type", type);
        }
        try {
            o.addProperty("name", entity.getCommandSenderName());
        } catch (Throwable ignored) {}
        o.addProperty(
            "uuid",
            entity.getUniqueID()
                .toString());
        return o;
    }

    private static JsonObject describe(ItemStack stack) {
        JsonObject o = new JsonObject();
        Item item = stack.getItem();
        o.addProperty("id", item == null ? "null" : String.valueOf(Item.itemRegistry.getNameForObject(item)));
        o.addProperty("meta", stack.getItemDamage());
        o.addProperty("count", stack.stackSize);
        o.addProperty("hasNbt", stack.hasTagCompound());
        try {
            o.addProperty("name", stack.getDisplayName());
        } catch (Throwable ignored) {}
        return o;
    }
}
