package com.tuxprogrammer.davebridge.server.chat.markup;

import net.minecraft.event.ClickEvent;
import net.minecraft.event.HoverEvent;
import net.minecraft.util.ChatComponentText;
import net.minecraft.util.ChatStyle;
import net.minecraft.util.EnumChatFormatting;
import net.minecraft.util.IChatComponent;

/** Small helpers for building styled chat components. */
public final class ChatStyles {

    private ChatStyles() {}

    /** Applies a markup style on top of {@code base} (markup color wins over the base color). */
    public static ChatStyle apply(Markup.Style s, ChatStyle base) {
        ChatStyle out = base == null ? new ChatStyle() : base.createShallowCopy();
        if (s == null) {
            return out;
        }
        if (s.color != null) {
            EnumChatFormatting color = EnumChatFormatting.getValueByName(s.color);
            if (color != null) out.setColor(color);
        }
        if (s.bold) out.setBold(Boolean.TRUE);
        if (s.italic) out.setItalic(Boolean.TRUE);
        if (s.underline) out.setUnderlined(Boolean.TRUE);
        if (s.strike) out.setStrikethrough(Boolean.TRUE);
        if (s.obfuscated) out.setObfuscated(Boolean.TRUE);
        return out;
    }

    public static IChatComponent text(String text, EnumChatFormatting color) {
        IChatComponent c = new ChatComponentText(text);
        if (color != null) c.getChatStyle()
            .setColor(color);
        return c;
    }

    public static HoverEvent hoverText(IChatComponent text) {
        return new HoverEvent(HoverEvent.Action.SHOW_TEXT, text);
    }

    public static HoverEvent hoverText(String text) {
        return hoverText(new ChatComponentText(text));
    }

    public static ClickEvent run(String command) {
        return new ClickEvent(ClickEvent.Action.RUN_COMMAND, command);
    }

    public static ClickEvent suggest(String text) {
        return new ClickEvent(ClickEvent.Action.SUGGEST_COMMAND, text);
    }

    public static ClickEvent openUrl(String url) {
        return new ClickEvent(ClickEvent.Action.OPEN_URL, url);
    }

    /** A {@code [label]} button: brackets and label in {@code color}, with hover and click. */
    public static IChatComponent button(String label, EnumChatFormatting color, Markup.Style markupStyle,
        HoverEvent hover, ClickEvent click) {
        IChatComponent c = new ChatComponentText("[" + label + "]");
        ChatStyle style = new ChatStyle().setColor(color);
        style = apply(markupStyle, style);
        style.setChatHoverEvent(hover);
        style.setChatClickEvent(click);
        c.setChatStyle(style);
        return c;
    }
}
