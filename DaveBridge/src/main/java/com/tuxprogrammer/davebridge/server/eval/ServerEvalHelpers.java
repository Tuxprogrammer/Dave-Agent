package com.tuxprogrammer.davebridge.server.eval;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import net.minecraft.entity.player.EntityPlayerMP;
import net.minecraft.item.ItemStack;
import net.minecraft.server.MinecraftServer;
import net.minecraft.tileentity.TileEntity;
import net.minecraft.world.World;
import net.minecraft.world.WorldServer;
import net.minecraftforge.common.DimensionManager;

import com.tuxprogrammer.davebridge.common.eval.EvalHelpers;
import com.tuxprogrammer.davebridge.server.chat.DaveChat;

/**
 * The {@code dave} variable of server-side scripts: {@link EvalHelpers} plus server lookups. Everything here reads
 * loaded state only; nothing loads a chunk.
 */
public final class ServerEvalHelpers extends EvalHelpers {

    public MinecraftServer server() {
        return MinecraftServer.getServer();
    }

    /** Online players. */
    public List<EntityPlayerMP> players() {
        return DaveChat.onlinePlayers();
    }

    /** An online player by name (case-insensitive), or null. */
    public EntityPlayerMP player(String name) {
        for (EntityPlayerMP p : players()) {
            if (p.getCommandSenderName()
                .equalsIgnoreCase(name)) {
                return p;
            }
        }
        return null;
    }

    /** A loaded dimension's world, or null when it is not loaded. */
    public WorldServer world(int dim) {
        return DimensionManager.getWorld(dim);
    }

    /** Every loaded world. */
    public List<WorldServer> worlds() {
        List<WorldServer> out = new ArrayList<>();
        for (Integer id : DimensionManager.getIDs()) {
            WorldServer w = DimensionManager.getWorld(id);
            if (w != null) {
                out.add(w);
            }
        }
        return out;
    }

    /** The tile entity at a position if its chunk is loaded, else null. */
    public TileEntity te(int dim, int x, int y, int z) {
        World w = world(dim);
        return w == null || !w.blockExists(x, y, z) ? null : w.getTileEntity(x, y, z);
    }

    /** A copy of a world's loaded tile entities (safe to iterate while the game runs). */
    public List<TileEntity> tiles(World world) {
        List<TileEntity> out = new ArrayList<>();
        for (Object o : world.loadedTileEntityList) {
            if (o instanceof TileEntity && !((TileEntity) o).isInvalid()) {
                out.add((TileEntity) o);
            }
        }
        return out;
    }

    /** Loaded tile entities of every loaded world. */
    public List<TileEntity> tiles() {
        List<TileEntity> out = new ArrayList<>();
        for (WorldServer w : worlds()) {
            out.addAll(tiles(w));
        }
        return out;
    }

    /** {@code describe} of a block. */
    public Map<String, Object> describe(int dim, int x, int y, int z) {
        World w = world(dim);
        return w == null ? null : Describe.block(w, x, y, z);
    }

    /** {@code describe} of an item stack. */
    public Map<String, Object> describe(ItemStack stack) {
        return Describe.item(stack);
    }

    /** {@code describe} of what a player is looking at. */
    public Map<String, Object> looking(EntityPlayerMP player) {
        return Describe.looking(player, 64);
    }

    /** A fast item matcher: {@code modid:name[:meta]}, {@code ore:<name>} or a display-name fragment. */
    public RecipeScan.ItemMatcher items(String spec) {
        return RecipeScan.ItemMatcher.of(spec);
    }

    /**
     * GregTech recipes that make ({@code uses=false}) or consume an item ({@code itemSpec}) or a fluid
     * ({@code fluid}), scanned in Java: {@code [matched: n, recipes: [[map: name, recipe: GTRecipe], ...]]}.
     */
    public Map<String, Object> gtRecipes(String itemSpec, String fluid, boolean uses, String mapFilter, int limit)
        throws ReflectiveOperationException {
        return RecipeScan.gtRecipes(itemSpec, fluid, uses, mapFilter, limit);
    }

    /** Squared distance between a player and a position (same dimension assumed). */
    public static double dist2(EntityPlayerMP p, double x, double y, double z) {
        double dx = p.posX - x, dy = p.posY - y, dz = p.posZ - z;
        return dx * dx + dy * dy + dz * dz;
    }
}
