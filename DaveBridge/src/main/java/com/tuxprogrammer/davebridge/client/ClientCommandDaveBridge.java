package com.tuxprogrammer.davebridge.client;

import java.util.List;

import net.minecraft.client.Minecraft;
import net.minecraft.command.CommandBase;
import net.minecraft.command.ICommandSender;
import net.minecraft.command.WrongUsageException;
import net.minecraft.item.Item;
import net.minecraft.item.ItemStack;
import net.minecraft.util.ChatComponentText;
import net.minecraft.util.ChatComponentTranslation;
import net.minecraft.util.ChatStyle;
import net.minecraft.util.EnumChatFormatting;

import com.tuxprogrammer.davebridge.client.compat.NeiPages;

import cpw.mods.fml.common.registry.GameData;

/**
 * Client command for the client half:
 * <ul>
 * <li>{@code /davebridge nei recipe|uses <modid:name[:meta]>}, behind the recipe links Dave sends. It only opens
 * NEI.</li>
 * <li>{@code /davebridge optin|optout|status}: the client-eval opt-in ({@link OptIn}), also behind the join nudge's
 * buttons. Saved to the client config.</li>
 * </ul>
 */
public class ClientCommandDaveBridge extends CommandBase {

    @Override
    public String getCommandName() {
        return "davebridge";
    }

    @Override
    public String getCommandUsage(ICommandSender sender) {
        return "/davebridge <optin|optout|status> | /davebridge nei <recipe|uses> <modid:name[:meta]>";
    }

    @Override
    public int getRequiredPermissionLevel() {
        return 0;
    }

    @Override
    public boolean canCommandSenderUseCommand(ICommandSender sender) {
        return true;
    }

    @Override
    public void processCommand(ICommandSender sender, String[] args) {
        String sub = args.length == 0 ? "status" : args[0].toLowerCase();
        if (args.length <= 1 && ("optin".equals(sub) || "optout".equals(sub) || "status".equals(sub))) {
            if (!"status".equals(sub)) {
                OptIn.set("optin".equals(sub));
                sender.addChatMessage(
                    new ChatComponentTranslation(
                        "optin".equals(sub) ? "davebridge.optin.done" : "davebridge.optout.done",
                        ClientState.botName));
            } else {
                sender.addChatMessage(OptIn.status());
            }
            return;
        }
        if (args.length != 3 || !"nei".equalsIgnoreCase(args[0])
            || !("recipe".equalsIgnoreCase(args[1]) || "uses".equalsIgnoreCase(args[1]))) {
            throw new WrongUsageException(getCommandUsage(sender));
        }
        if (!NeiPages.available()) {
            error(sender, "NEI is not installed.");
            return;
        }
        ItemStack stack = parse(args[2]);
        if (stack == null) {
            error(sender, "Unknown item " + args[2]);
            return;
        }
        boolean usage = "uses".equalsIgnoreCase(args[1]);
        // Open on the next client tick: a command typed into chat runs before GuiChat closes itself, which would close
        // NEI's page straight away. Close the chat screen first so NEI's page returns to the game, not to chat.
        ClientProxy.QUEUE.submit("nei_page", () -> {
            Minecraft.getMinecraft()
                .displayGuiScreen(null);
            if (!NeiPages.open(stack, usage)) {
                error(sender, "NEI has no " + (usage ? "uses" : "recipes") + " for " + stack.getDisplayName());
            }
        });
    }

    /** "modid:name" or "modid:name:meta". */
    static ItemStack parse(String key) {
        String[] parts = key.split(":");
        if (parts.length < 2 || parts.length > 3) return null;
        int meta = 0;
        if (parts.length == 3) {
            try {
                meta = Integer.parseInt(parts[2]);
            } catch (NumberFormatException e) {
                return null;
            }
        }
        Item item = (Item) GameData.getItemRegistry()
            .getObject(parts[0] + ":" + parts[1]);
        return item == null ? null : new ItemStack(item, 1, meta);
    }

    private static void error(ICommandSender sender, String text) {
        sender
            .addChatMessage(new ChatComponentText(text).setChatStyle(new ChatStyle().setColor(EnumChatFormatting.RED)));
    }

    @Override
    public List<String> addTabCompletionOptions(ICommandSender sender, String[] args) {
        if (args.length == 1) return getListOfStringsMatchingLastWord(args, "optin", "optout", "status", "nei");
        if (args.length == 2 && "nei".equalsIgnoreCase(args[0]))
            return getListOfStringsMatchingLastWord(args, "recipe", "uses");
        return null;
    }
}
