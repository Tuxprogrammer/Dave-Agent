package com.tuxprogrammer.davebridge.client;

import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiNewChat;
import net.minecraft.event.HoverEvent;
import net.minecraft.util.ChatComponentText;
import net.minecraft.util.ChatStyle;
import net.minecraft.util.EnumChatFormatting;
import net.minecraft.util.IChatComponent;
import net.minecraftforge.common.ForgeHooks;

import com.tuxprogrammer.davebridge.common.protocol.DaveMessage;

/**
 * Renders Dave's messages for players with the client half: a styled {@code [Dave]} tag, wrapping left to the chat
 * GUI, and a "thinking" line that replaces itself and disappears when the answer arrives. Client thread only.
 */
public final class DaveChatRenderer {

    /** Chat line id for the thinking indicator, so it can be replaced and deleted. */
    static final int THINKING_LINE_ID = 0x0DA7EB01;
    static final long THINKING_TIMEOUT_MILLIS = 60_000L;
    static final int MAX_LINES = 100;

    private static long thinkingSince;

    private DaveChatRenderer() {}

    public static void showMessage(DaveMessage message) {
        GuiNewChat chat = chat();
        if (chat == null || message.text == null) {
            return;
        }
        clearThinking();
        String name = message.botName == null ? ClientState.botName : message.botName;
        String[] lines = message.text.replace("\r\n", "\n")
            .split("\n");
        int shown = 0;
        for (String line : lines) {
            if (line.trim()
                .isEmpty()) {
                continue;
            }
            if (++shown > MAX_LINES) {
                chat.printChatMessage(gray("  ... (truncated)"));
                break;
            }
            IChatComponent out = shown == 1 ? tag(name, message.replyTo) : new ChatComponentText("  ");
            out.appendSibling(ForgeHooks.newChatWithLinks(line));
            chat.printChatMessage(out);
        }
    }

    public static void showThinking(String botName) {
        GuiNewChat chat = chat();
        if (chat == null) {
            return;
        }
        String name = botName == null ? ClientState.botName : botName;
        chat.printChatMessageWithOptionalDeletion(gray(name + " is thinking..."), THINKING_LINE_ID);
        thinkingSince = System.currentTimeMillis();
    }

    /** A gray italic status line from the client half itself. */
    static void notice(String text) {
        GuiNewChat chat = chat();
        if (chat != null) {
            chat.printChatMessage(gray(text));
        }
    }

    /** Called every client tick: drop a stale thinking line. */
    static void tick() {
        if (thinkingSince != 0 && System.currentTimeMillis() - thinkingSince > THINKING_TIMEOUT_MILLIS) {
            clearThinking();
        }
    }

    static void clearThinking() {
        if (thinkingSince != 0) {
            GuiNewChat chat = chat();
            if (chat != null) {
                chat.deleteChatLine(THINKING_LINE_ID);
            }
            thinkingSince = 0;
        }
    }

    /** Prints a line built by the client half itself. */
    static void print(IChatComponent line) {
        GuiNewChat chat = chat();
        if (chat != null) {
            chat.printChatMessage(line);
        }
    }

    static IChatComponent tag(String name, String replyTo) {
        IChatComponent nameComponent = new ChatComponentText(name);
        String hover = "DaveBridge assistant" + (replyTo == null ? "" : "\nreply to " + replyTo);
        nameComponent.setChatStyle(
            new ChatStyle().setColor(EnumChatFormatting.AQUA)
                .setBold(Boolean.TRUE)
                .setChatHoverEvent(new HoverEvent(HoverEvent.Action.SHOW_TEXT, new ChatComponentText(hover))));
        IChatComponent out = new ChatComponentText("[");
        out.getChatStyle()
            .setColor(EnumChatFormatting.DARK_AQUA);
        out.appendSibling(nameComponent);
        IChatComponent close = new ChatComponentText("] ");
        close.setChatStyle(new ChatStyle().setColor(EnumChatFormatting.DARK_AQUA));
        out.appendSibling(close);
        return out;
    }

    private static IChatComponent gray(String text) {
        IChatComponent c = new ChatComponentText(text);
        c.setChatStyle(
            new ChatStyle().setColor(EnumChatFormatting.GRAY)
                .setItalic(Boolean.TRUE));
        return c;
    }

    private static GuiNewChat chat() {
        Minecraft mc = Minecraft.getMinecraft();
        return mc.ingameGUI == null ? null : mc.ingameGUI.getChatGUI();
    }
}
