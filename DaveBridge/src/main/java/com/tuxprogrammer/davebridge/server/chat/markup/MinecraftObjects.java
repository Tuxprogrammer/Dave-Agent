package com.tuxprogrammer.davebridge.server.chat.markup;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import net.minecraft.block.Block;
import net.minecraft.entity.player.EntityPlayerMP;
import net.minecraft.event.HoverEvent;
import net.minecraft.item.Item;
import net.minecraft.item.ItemStack;
import net.minecraft.nbt.NBTTagCompound;
import net.minecraft.util.ChatComponentText;
import net.minecraft.util.ChatStyle;
import net.minecraft.util.EnumChatFormatting;
import net.minecraft.util.IChatComponent;
import net.minecraftforge.fluids.Fluid;
import net.minecraftforge.fluids.FluidRegistry;
import net.minecraftforge.fluids.FluidStack;
import net.minecraftforge.oredict.OreDictionary;

import com.tuxprogrammer.davebridge.server.chat.DaveChat;
import com.tuxprogrammer.davebridge.server.compat.BqQuests;
import com.tuxprogrammer.davebridge.server.compat.GtnhLibChat;
import com.tuxprogrammer.davebridge.server.compat.NeiBookmarks;

import cpw.mods.fml.common.registry.GameData;

/**
 * Game-object tokens resolved against the live server: registries, OreDictionary, online players, and the native
 * NEI / BetterQuesting link formats. Server thread only.
 */
public final class MinecraftObjects implements StandardLinkResolver.GameObjects {

    /** The client half's command that opens NEI's recipe or usage page (NEI has no native one). */
    public static final String CLIENT_NEI_COMMAND = "/davebridge nei";

    // ------------------------------------------------------------------ items

    @Override
    public ResolvedLink item(Markup.Token token, List<String> warnings) {
        ItemStack stack = stack(token.arg, token.raw, warnings);
        if (stack == null) {
            return null;
        }
        IChatComponent base = itemComponent(stack, token);

        // Default click for everyone: NEI's native bookmark link. Recipe/usage pages need the client half.
        NeiBookmarks.Link bookmark = NeiBookmarks.available() ? NeiBookmarks.item(stack) : null;
        String page = "uses".equals(token.kind) ? "uses" : "recipe";
        String clientCommand = CLIENT_NEI_COMMAND + " " + page + " " + key(stack);

        IChatComponent vanilla = base.createCopy();
        IChatComponent mod = base.createCopy();
        if (bookmark != null) {
            vanilla.getChatStyle()
                .setChatClickEvent(ChatStyles.run(bookmark.command));
        } else if (!"item".equals(token.kind)) {
            warnings.add(token.raw + ": NEI is not on the server, so players without the client half get no click");
        }
        if ("item".equals(token.kind) && bookmark != null) {
            mod.getChatStyle()
                .setChatClickEvent(ChatStyles.run(bookmark.command));
        } else {
            mod.getChatStyle()
                .setChatClickEvent(ChatStyles.run(clientCommand));
        }
        List<ResolvedLink.RecipientAction> actions = bookmark == null ? null : Collections.singletonList(bookmark.send);
        return new ResolvedLink(vanilla, mod, false, actions);
    }

    /**
     * The item's own chat component when there is no label: vanilla {@code ItemStack.func_151000_E()}, which in GTNH
     * (GTNHLib's MixinItemStack_GetChatComponent) carries the stack so the client shows the name in its own
     * language. Both variants have the show_item hover, i.e. the real tooltip.
     */
    // Source:
    // https://github.com/GTNewHorizons/GTNHLib/blob/0.11.54/src/main/java/com/gtnewhorizon/gtnhlib/mixins/early/MixinItemStack_GetChatComponent.java
    static IChatComponent itemComponent(ItemStack stack, Markup.Token token) {
        IChatComponent c;
        if (token.label != null && !token.label.isEmpty()) {
            c = new ChatComponentText(token.label);
            NBTTagCompound tag = new NBTTagCompound();
            stack.writeToNBT(tag);
            c.setChatStyle(
                new ChatStyle().setColor(stack.getRarity().rarityColor)
                    .setChatHoverEvent(
                        new HoverEvent(HoverEvent.Action.SHOW_ITEM, new ChatComponentText(tag.toString()))));
        } else {
            c = stack.func_151000_E()
                .createCopy();
        }
        c.setChatStyle(ChatStyles.apply(token.style, c.getChatStyle()));
        return c;
    }

    /** "modid:name:meta", the argument of the client half's NEI command. */
    static String key(ItemStack stack) {
        return GameData.getItemRegistry()
            .getNameForObject(stack.getItem()) + ":"
            + stack.getItemDamage();
    }

    /** Resolves an item reference to a stack, or null with a warning. */
    static ItemStack stack(String arg, String raw, List<String> warnings) {
        ItemRef ref = ItemRef.parse(arg);
        if (ref == null) {
            warnings.add(raw + ": not an item reference (use modid:name[:meta] or ore:name)");
            return null;
        }
        ItemStack stack = null;
        if (ref.ore != null) {
            List<ItemStack> ores = oreStacks(ref.ore);
            if (!ores.isEmpty()) {
                stack = ores.get(0)
                    .copy();
                if (stack.getItemDamage() == OreDictionary.WILDCARD_VALUE) stack.setItemDamage(0);
            }
        } else {
            Item item = ref.name != null ? (Item) GameData.getItemRegistry()
                .getObject(ref.name) : Item.getItemById(ref.numericId);
            if (item == null && ref.name != null) {
                Block block = (Block) GameData.getBlockRegistry()
                    .getObject(ref.name);
                if (block != null && block != net.minecraft.init.Blocks.air) {
                    item = Item.getItemFromBlock(block);
                }
            }
            if (item != null) {
                stack = new ItemStack(item, 1, ref.meta);
            }
        }
        if (stack == null || stack.getItem() == null) {
            warnings.add(raw + ": unknown item " + ref);
            return null;
        }
        stack.stackSize = ref.count;
        String name;
        try {
            name = stack.getDisplayName();
        } catch (VirtualMachineError e) {
            throw e;
        } catch (Throwable e) {
            warnings.add(raw + ": " + ref + " has no valid display name (wrong meta?)");
            return null;
        }
        if (name == null || name.trim()
            .isEmpty() || name.endsWith(".name")) {
            warnings.add(raw + ": " + ref + " looks invalid (name '" + name + "'); wrong meta?");
            return null;
        }
        return stack;
    }

    /**
     * The stacks registered under an ore name. Never creates the name: Forge's {@code getOres(String)} registers any
     * unknown name it is asked about, so a typo would add an empty ore name to the server for good.
     */
    static List<ItemStack> oreStacks(String oreName) {
        return OreDictionary.getOres(oreName, false);
    }

    // ------------------------------------------------------------------ fluids

    @Override
    public ResolvedLink fluid(Markup.Token token, List<String> warnings) {
        Fluid fluid = FluidRegistry.getFluid(token.arg.trim());
        if (fluid == null) {
            fluid = FluidRegistry.getFluid(
                token.arg.trim()
                    .toLowerCase(java.util.Locale.ROOT));
        }
        if (fluid == null) {
            warnings.add(token.raw + ": unknown fluid " + token.arg);
            return null;
        }
        FluidStack fs = new FluidStack(fluid, 1000);
        IChatComponent name = GtnhLibChat.fluidName(fs); // localized on each client when GTNHLib is present
        IChatComponent hover = name.createCopy();
        hover.appendSibling(ChatStyles.text("\nFluid: " + fluid.getName(), EnumChatFormatting.GRAY));
        hover.appendSibling(
            ChatStyles.text("\nTemperature: " + fluid.getTemperature(fs) + " K", EnumChatFormatting.GRAY));
        if (fluid.isGaseous(fs)) hover.appendSibling(ChatStyles.text("\nGas", EnumChatFormatting.GRAY));

        IChatComponent c = token.label != null && !token.label.isEmpty() ? new ChatComponentText(token.label) : name;
        c.setChatStyle(
            ChatStyles.apply(token.style, new ChatStyle().setColor(EnumChatFormatting.AQUA))
                .setChatHoverEvent(ChatStyles.hoverText(hover)));
        return ResolvedLink.same(c);
    }

    // ------------------------------------------------------------------ chains

    /** {@code {chain:item*2, item*4|label}}: an NEI bookmark group (TODO list) of the items with amounts. */
    @Override
    public ResolvedLink chain(Markup.Token token, List<String> warnings) {
        List<ItemStack> stacks = new ArrayList<>();
        List<Integer> amounts = new ArrayList<>();
        IChatComponent hover = new ChatComponentText("");
        for (String part : token.arg.split(",")) {
            if (part.trim()
                .isEmpty()) continue;
            ItemStack s;
            try {
                s = stack(part, token.raw, warnings);
            } catch (VirtualMachineError e) {
                throw e;
            } catch (Throwable t) {
                // one bad part must not drop the rest of the chain
                warnings.add(token.raw + ": could not resolve " + part.trim() + ": " + t);
                continue;
            }
            if (s == null) continue;
            stacks.add(s);
            amounts.add(s.stackSize);
            if (!stacks.isEmpty() && stacks.size() > 1) hover.appendText("\n");
            hover.appendSibling(ChatStyles.text(s.stackSize + " x ", EnumChatFormatting.GRAY));
            IChatComponent n = new ChatComponentText(s.getDisplayName());
            n.getChatStyle()
                .setColor(s.getRarity().rarityColor);
            hover.appendSibling(n);
        }
        if (stacks.isEmpty()) {
            warnings.add(token.raw + ": no valid items in chain");
            return null;
        }
        String label = token.label != null && !token.label.isEmpty() ? token.label
            : stacks.size() + " item" + (stacks.size() == 1 ? "" : "s");
        if (!NeiBookmarks.available()) {
            warnings.add(token.raw + ": NEI is not on the server; chain shown as a hover list");
            IChatComponent c = new ChatComponentText("[" + label + "]");
            c.setChatStyle(
                ChatStyles.apply(token.style, new ChatStyle().setColor(EnumChatFormatting.YELLOW))
                    .setChatHoverEvent(ChatStyles.hoverText(hover)));
            return ResolvedLink.same(c);
        }
        NeiBookmarks.Link link = NeiBookmarks.group(stacks, amounts);
        hover.appendSibling(ChatStyles.text("\nClick to add as an NEI bookmark group", EnumChatFormatting.GOLD));
        IChatComponent c = ChatStyles.button(
            label,
            EnumChatFormatting.YELLOW,
            token.style,
            ChatStyles.hoverText(hover),
            ChatStyles.run(link.command));
        return new ResolvedLink(c, c, false, Collections.singletonList(link.send));
    }

    // ------------------------------------------------------------------ quests

    /** BetterQuesting's own share token on a line of its own; the BQ client turns it into a clickable quest link. */
    @Override
    public ResolvedLink quest(Markup.Token token, List<String> warnings) {
        if (!BqQuests.available()) {
            warnings.add(token.raw + ": BetterQuesting is not on the server");
            return null;
        }
        BqQuests.Quest quest = BqQuests.find(token.arg);
        if (quest == null) {
            warnings.add(token.raw + ": no quest with that id or name");
            return null;
        }
        if (quest.matches > 1) {
            warnings.add(token.raw + ": " + quest.matches + " quests have that name; linked the first");
        }
        IChatComponent c = new ChatComponentText("");
        if (token.label != null && !token.label.isEmpty()) {
            IChatComponent label = new ChatComponentText(token.label + " ");
            label.setChatStyle(ChatStyles.apply(token.style, new ChatStyle()));
            c.appendSibling(label);
        }
        // The token must stay one unstyled run so BQ finds the 24 id characters in the formatted text.
        c.appendSibling(new ChatComponentText(quest.shareToken()));
        return new ResolvedLink(c, c, true, null);
    }

    // ------------------------------------------------------------------ players

    @Override
    public ResolvedLink player(Markup.Token token, List<String> warnings) {
        for (EntityPlayerMP p : DaveChat.onlinePlayers()) {
            if (p.getCommandSenderName()
                .equalsIgnoreCase(token.arg.trim())) {
                String name = p.getCommandSenderName();
                IChatComponent c = new ChatComponentText(
                    token.label != null && !token.label.isEmpty() ? token.label : name);
                c.setChatStyle(
                    ChatStyles.apply(token.style, new ChatStyle().setColor(EnumChatFormatting.YELLOW))
                        .setChatHoverEvent(ChatStyles.hoverText(name + "\nClick to message"))
                        .setChatClickEvent(ChatStyles.suggest("/msg " + name + " ")));
                return ResolvedLink.same(c);
            }
        }
        warnings.add(token.raw + ": player is not online");
        return null;
    }
}
