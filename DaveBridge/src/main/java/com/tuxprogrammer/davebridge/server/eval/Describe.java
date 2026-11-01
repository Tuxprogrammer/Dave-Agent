package com.tuxprogrammer.davebridge.server.eval;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import net.minecraft.block.Block;
import net.minecraft.entity.Entity;
import net.minecraft.entity.EntityLivingBase;
import net.minecraft.entity.player.EntityPlayer;
import net.minecraft.inventory.IInventory;
import net.minecraft.item.Item;
import net.minecraft.item.ItemStack;
import net.minecraft.tileentity.TileEntity;
import net.minecraft.util.MathHelper;
import net.minecraft.util.MovingObjectPosition;
import net.minecraft.util.Vec3;
import net.minecraft.world.World;

import com.tuxprogrammer.davebridge.common.eval.EvalHelpers;

/**
 * {@code describe}: what a block, tile entity, item or entity is at runtime. Reads only; never loads chunks.
 * <p>
 * GregTech is reached by reflection (it is not a compile dependency). Contracts, GT5-Unofficial 5.09.54.265 (the
 * GTNH 2.9.0 tag): {@code IGregTechTileEntity.getMetaTileID()}, {@code getMetaTileEntity()}, {@code getOwnerName()}
 * (src/main/java/gregtech/api/interfaces/tileentity/IGregTechTileEntity.java:40,50,110);
 * {@code IMetaTileEntity.getMetaName()}, {@code getLocalName()}, {@code getDescription()}
 * (api/interfaces/metatileentity/IMetaTileEntity.java:284,620,393); {@code getRecipeMap()} exists on
 * {@code MTEBasicMachine} (RecipeMapWorkable) and separately on {@code MTEMultiBlockBase} (:2144), so it is looked up
 * by name; {@code RecipeMap.unlocalizedName} is a public field (api/recipe/RecipeMap.java:56);
 * {@code GregTechAPI.METATILEENTITIES} maps a machine item's meta to its MTE (api/GregTechAPI.java:87).
 * <p>
 * Tooltips ({@code ItemStack.getTooltip}, {@code Item.addInformation}) are client-only in 1.7.10 and do not exist on a
 * dedicated server; GT's {@code getDescription()} lines are the server-side equivalent for machines. A player's real
 * tooltip needs client eval.
 */
public final class Describe {

    private Describe() {}

    /** The block at a position, with its tile entity. Null-safe: an unloaded position says so. */
    public static Map<String, Object> block(World world, int x, int y, int z) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("kind", "block");
        out.put("dim", world.provider.dimensionId);
        out.put("x", x);
        out.put("y", y);
        out.put("z", z);
        if (!world.blockExists(x, y, z)) {
            out.put("loaded", false);
            return out;
        }
        Block block = world.getBlock(x, y, z);
        int meta = world.getBlockMetadata(x, y, z);
        Object name = Block.blockRegistry.getNameForObject(block);
        out.put("id", name == null ? null : name.toString());
        out.put("meta", meta);
        out.put(
            "blockClass",
            block.getClass()
                .getName());
        out.put("name", blockName(block, meta));
        out.put("unlocalizedName", block.getUnlocalizedName());
        TileEntity te = world.getTileEntity(x, y, z);
        if (te != null) {
            out.put("tile", tile(te));
        }
        return out;
    }

    private static String blockName(Block block, int meta) {
        try {
            Item item = Item.getItemFromBlock(block);
            if (item != null) {
                return new ItemStack(item, 1, block.damageDropped(meta)).getDisplayName();
            }
            return block.getLocalizedName();
        } catch (Throwable t) {
            return null;
        }
    }

    /** A tile entity: class, GT machine details, inventory summary. */
    public static Map<String, Object> tile(TileEntity te) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put(
            "class",
            te.getClass()
                .getName());
        gregtech(te, out);
        if (te instanceof IInventory) {
            out.put("inventory", inventory((IInventory) te, 54));
        }
        return out;
    }

    /** Non-empty slots of an inventory, at most {@code max}. */
    public static Map<String, Object> inventory(IInventory inv, int max) {
        Map<String, Object> out = new LinkedHashMap<>();
        int size = inv.getSizeInventory();
        out.put("size", size);
        try {
            out.put("name", inv.getInventoryName());
        } catch (Throwable ignored) {
            // some inventories need a client to name themselves
        }
        List<Map<String, Object>> slots = new ArrayList<>();
        for (int i = 0; i < size && slots.size() < max; i++) {
            ItemStack s = inv.getStackInSlot(i);
            if (s != null) {
                Map<String, Object> row = EvalHelpers.item(s);
                row.put("slot", i);
                slots.add(row);
            }
        }
        out.put("slots", slots);
        return out;
    }

    /** A held or stored item; a GT machine item names its machine. */
    public static Map<String, Object> item(ItemStack stack) {
        if (stack == null) {
            return null;
        }
        Map<String, Object> out = EvalHelpers.item(stack);
        out.put(
            "itemClass",
            stack.getItem()
                .getClass()
                .getName());
        out.put("unlocalizedName", stack.getUnlocalizedName());
        out.put("maxStack", stack.getMaxStackSize());
        if (stack.isItemStackDamageable()) {
            out.put("maxDamage", stack.getMaxDamage());
        }
        if ("gregtech:gt.blockmachines".equals(out.get("id"))) {
            Object mte = gtMetaTileEntity(stack.getItemDamage());
            if (mte != null) {
                Map<String, Object> gt = new LinkedHashMap<>();
                gt.put("metaTileId", stack.getItemDamage());
                mteDetails(mte, gt);
                out.put("gregtech", gt);
            }
        }
        out.put("tooltipNote", "tooltips are client-side in 1.7.10; use client eval for a player's real tooltip");
        return out;
    }

    public static Map<String, Object> entity(Entity e) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("kind", "entity");
        out.put("entityId", e.getEntityId());
        out.put(
            "class",
            e.getClass()
                .getName());
        out.put("name", e.getCommandSenderName());
        out.put(
            "uuid",
            e.getUniqueID()
                .toString());
        out.put("dim", e.dimension);
        out.put("x", round(e.posX));
        out.put("y", round(e.posY));
        out.put("z", round(e.posZ));
        if (e instanceof EntityLivingBase) {
            EntityLivingBase living = (EntityLivingBase) e;
            out.put("health", living.getHealth());
            out.put("maxHealth", living.getMaxHealth());
            out.put("held", item(living.getHeldItem()));
        }
        return out;
    }

    /** The block the player looks at within {@code reach} blocks (server-side ray trace), or a miss. */
    public static Map<String, Object> looking(EntityPlayer player, double reach) {
        float pitch = player.rotationPitch;
        float yaw = player.rotationYaw;
        // On the server a player's posY is at the feet; eyes are 1.62 above (1.54 sneaking).
        double eyeY = player.posY + (player.isSneaking() ? 1.54 : 1.62);
        Vec3 eye = Vec3.createVectorHelper(player.posX, eyeY, player.posZ);
        float cosYaw = MathHelper.cos(-yaw * 0.017453292F - (float) Math.PI);
        float sinYaw = MathHelper.sin(-yaw * 0.017453292F - (float) Math.PI);
        float cosPitch = -MathHelper.cos(-pitch * 0.017453292F);
        float sinPitch = MathHelper.sin(-pitch * 0.017453292F);
        Vec3 end = eye.addVector(sinYaw * cosPitch * reach, sinPitch * reach, cosYaw * cosPitch * reach);
        MovingObjectPosition hit = player.worldObj.rayTraceBlocks(eye, end);
        if (hit == null || hit.typeOfHit != MovingObjectPosition.MovingObjectType.BLOCK) {
            Map<String, Object> miss = new LinkedHashMap<>();
            miss.put("kind", "none");
            miss.put("note", "not looking at a block within " + reach + " blocks");
            return miss;
        }
        Map<String, Object> out = block(player.worldObj, hit.blockX, hit.blockY, hit.blockZ);
        out.put("side", hit.sideHit);
        return out;
    }

    // ---- GregTech, by reflection

    private static void gregtech(TileEntity te, Map<String, Object> out) {
        Method getMte = method(te.getClass(), "getMetaTileEntity");
        if (getMte == null) {
            return;
        }
        Map<String, Object> gt = new LinkedHashMap<>();
        gt.put("metaTileId", call(te, "getMetaTileID"));
        gt.put("owner", call(te, "getOwnerName"));
        Object mte = invoke(getMte, te);
        if (mte != null) {
            mteDetails(mte, gt);
        }
        out.put("gregtech", gt);
    }

    private static void mteDetails(Object mte, Map<String, Object> gt) {
        gt.put(
            "mteClass",
            mte.getClass()
                .getName());
        gt.put("metaName", call(mte, "getMetaName"));
        gt.put("localName", call(mte, "getLocalName"));
        Object desc = call(mte, "getDescription");
        if (desc instanceof String[]) {
            List<String> lines = new ArrayList<>();
            for (String line : (String[]) desc) {
                if (line != null && lines.size() < 40) {
                    lines.add(line.replaceAll("§.", ""));
                }
            }
            gt.put("description", lines);
        }
        Object map = call(mte, "getRecipeMap");
        if (map != null) {
            gt.put("recipeMap", field(map, "unlocalizedName"));
        }
    }

    private static Object gtMetaTileEntity(int id) {
        try {
            Class<?> api = Class.forName("gregtech.api.GregTechAPI", false, Describe.class.getClassLoader());
            Object[] all = (Object[]) api.getField("METATILEENTITIES")
                .get(null);
            return id >= 0 && id < all.length ? all[id] : null;
        } catch (Throwable t) {
            return null;
        }
    }

    private static Method method(Class<?> type, String name) {
        try {
            return type.getMethod(name);
        } catch (Throwable t) {
            return null;
        }
    }

    private static Object call(Object target, String name) {
        Method m = method(target.getClass(), name);
        return m == null ? null : invoke(m, target);
    }

    private static Object invoke(Method m, Object target) {
        try {
            m.setAccessible(true);
            return m.invoke(target);
        } catch (Throwable t) {
            return null;
        }
    }

    private static Object field(Object target, String name) {
        try {
            Field f = target.getClass()
                .getField(name);
            return f.get(target);
        } catch (Throwable t) {
            return String.valueOf(target);
        }
    }

    private static double round(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
