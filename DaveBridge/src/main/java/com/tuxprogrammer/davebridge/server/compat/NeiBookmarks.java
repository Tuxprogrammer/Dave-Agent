package com.tuxprogrammer.davebridge.server.compat;

import java.util.List;
import java.util.UUID;

import net.minecraft.entity.player.EntityPlayerMP;
import net.minecraft.item.ItemStack;
import net.minecraft.nbt.NBTTagCompound;
import net.minecraft.nbt.NBTTagList;

import com.tuxprogrammer.davebridge.DaveBridge;
import com.tuxprogrammer.davebridge.server.chat.markup.ResolvedLink;

import codechicken.lib.packet.PacketCustom;
import codechicken.nei.recipe.StackInfo;
import cpw.mods.fml.common.Loader;

/**
 * NEI's native chat bookmark links, sent from the server with Dave as the author.
 * <p>
 * NEI's own flow ({@code NEIServerUtils.sendChatItemLink}) sends {@code S2C.CACHE_BOOKMARK_DATA} (payload id +
 * payload NBT) on the "NEI" channel to every player, then a chat line whose click runs the NEI client command
 * {@code /nei_bookmark <payloadId>}; that command adds the cached payload to the player's NEI bookmarks (an item,
 * or a whole bookmark group). We reuse the packet and the command, but send only to the recipients of Dave's message
 * and build the chat line ourselves.
 */
// Source:
// https://github.com/GTNewHorizons/NotEnoughItems/blob/2.8.171-GTNH/src/main/java/codechicken/nei/NEIServerUtils.java
// (sendChatItemLink), .../NEICPH.java (handleCacheBookmarkData), .../commands/CommandBookmarkAdd.java (cache of 64,
// /nei_bookmark), .../bookmark/BookmarkPayload.java (linkType item|recipe|group; item, group, items, recipes tags),
// .../bookmark/BookmarkItem.java (item JSON: item, multiplier, factor, type 0=ITEM 1=RESULT 2=INGREDIENT),
// .../PacketIDs.java (S2C.CACHE_BOOKMARK_DATA = 25).
public final class NeiBookmarks {

    static final String CHANNEL = "NEI";
    static final int S2C_CACHE_BOOKMARK_DATA = 25;

    /** A prepared bookmark link: the click command and the packet each recipient needs first. */
    public static final class Link {

        public final String command;
        public final ResolvedLink.RecipientAction send;

        Link(String command, ResolvedLink.RecipientAction send) {
            this.command = command;
            this.send = send;
        }
    }

    private NeiBookmarks() {}

    public static boolean available() {
        return Loader.isModLoaded("NotEnoughItems");
    }

    /** A single-item bookmark link (NEI linkType "item"). */
    public static Link item(ItemStack stack) {
        NBTTagCompound payload = new NBTTagCompound();
        payload.setString("linkType", "item");
        NBTTagCompound itemTag = stackTag(stack, 1);
        payload.setTag("item", itemTag);
        NBTTagList items = new NBTTagList();
        items.appendTag(bookmarkItem(stack, 1));
        payload.setTag("items", items);
        payload.setTag("recipes", new NBTTagList());
        return link(payload);
    }

    /**
     * A bookmark group of items with amounts (NEI linkType "group", TODO-list view): a shopping list for a crafting
     * chain. Recipes are not linked: NEI recipe ids name client-side recipe handlers the server cannot know.
     */
    public static Link group(List<ItemStack> stacks, List<Integer> amounts) {
        NBTTagCompound payload = new NBTTagCompound();
        payload.setString("linkType", "group");
        NBTTagCompound group = new NBTTagCompound();
        group.setString("viewmode", "TODO_LIST");
        group.setBoolean("crafting", false);
        group.setBoolean("collapsed", false);
        group.setTag("collapsedRecipes", new NBTTagList());
        payload.setTag("group", group);
        NBTTagList items = new NBTTagList();
        for (int i = 0; i < stacks.size(); i++) {
            items.appendTag(bookmarkItem(stacks.get(i), amounts.get(i)));
        }
        payload.setTag("items", items);
        payload.setTag("recipes", new NBTTagList());
        return link(payload);
    }

    private static Link link(NBTTagCompound payload) {
        String id = "dave" + UUID.randomUUID()
            .toString()
            .substring(0, 8);
        ResolvedLink.RecipientAction send = player -> sendPayload(player, id, payload);
        return new Link("/nei_bookmark " + id, send);
    }

    private static NBTTagCompound bookmarkItem(ItemStack stack, int amount) {
        NBTTagCompound tag = new NBTTagCompound();
        tag.setTag("item", stackTag(stack, 1));
        tag.setInteger("multiplier", Math.max(1, amount));
        tag.setInteger("factor", 1);
        tag.setInteger("type", 0); // ITEM
        return tag;
    }

    /** NEI's stack NBT ({@code StackInfo.itemStackToNBT}); falls back to its default format (strId, Count, Damage). */
    static NBTTagCompound stackTag(ItemStack stack, int count) {
        ItemStack copy = stack.copy();
        copy.stackSize = count;
        try {
            NBTTagCompound tag = Impl.stackInfo(copy);
            if (tag != null) return tag;
        } catch (Throwable t) {
            DaveBridge.LOG.debug("NEI StackInfo failed, using the default stack format", t);
        }
        NBTTagCompound tag = new NBTTagCompound();
        tag.setString("strId", String.valueOf(net.minecraft.item.Item.itemRegistry.getNameForObject(copy.getItem())));
        tag.setInteger("Count", count);
        tag.setInteger("Damage", copy.getItemDamage());
        if (copy.hasTagCompound()) tag.setTag(
            "tag",
            copy.getTagCompound()
                .copy());
        return tag;
    }

    private static void sendPayload(EntityPlayerMP player, String id, NBTTagCompound payload) {
        if (player == null) {
            return; // PacketCustom.sendToPlayer(null) would broadcast to everyone
        }
        try {
            Impl.send(player, id, payload);
        } catch (Throwable t) {
            DaveBridge.LOG.warn("Could not send NEI bookmark payload to {}", player.getCommandSenderName(), t);
        }
    }

    /** The only code touching NEI / CodeChickenCore classes, so they load only when NEI is present. */
    private static final class Impl {

        static NBTTagCompound stackInfo(ItemStack stack) {
            return StackInfo.itemStackToNBT(stack);
        }

        static void send(EntityPlayerMP player, String id, NBTTagCompound payload) {
            new PacketCustom(CHANNEL, S2C_CACHE_BOOKMARK_DATA).writeString(id)
                .writeNBTTagCompound(payload)
                .sendToPlayer(player);
        }
    }
}
