package com.tuxprogrammer.davebridge.server.chat;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

import net.minecraft.entity.player.EntityPlayerMP;
import net.minecraft.event.ClickEvent;
import net.minecraft.event.HoverEvent;
import net.minecraft.network.play.server.S29PacketSoundEffect;
import net.minecraft.server.MinecraftServer;
import net.minecraft.util.ChatComponentText;
import net.minecraft.util.ChatComponentTranslation;
import net.minecraft.util.ChatStyle;
import net.minecraft.util.EnumChatFormatting;
import net.minecraft.util.IChatComponent;
import net.minecraftforge.common.ForgeHooks;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.tuxprogrammer.davebridge.DaveBridge;
import com.tuxprogrammer.davebridge.common.Config;
import com.tuxprogrammer.davebridge.common.network.DaveNetwork;
import com.tuxprogrammer.davebridge.common.protocol.Thinking;
import com.tuxprogrammer.davebridge.server.DaveServer;
import com.tuxprogrammer.davebridge.server.bridge.Protocol;
import com.tuxprogrammer.davebridge.server.bridge.ProtocolException;
import com.tuxprogrammer.davebridge.server.chat.markup.MarkupRenderer;
import com.tuxprogrammer.davebridge.server.chat.markup.MinecraftObjects;
import com.tuxprogrammer.davebridge.server.chat.markup.ResolvedLink;
import com.tuxprogrammer.davebridge.server.chat.markup.StandardLinkResolver;

import cpw.mods.fml.common.Loader;

/**
 * Delivers Dave's messages as ordinary chat lines, rendered per recipient: players with the DaveBridge client half
 * get client-command links where native ones don't exist; everyone else gets the native pack formats. Server thread
 * only.
 */
public final class DaveChat {

    /**
     * A chat line is written as one JSON string; the server refuses strings over 32767 UTF-8 bytes (and would drop the
     * player). Stay well under.
     */
    public static final int MAX_LINE_JSON_BYTES = 30000;

    /** What a say did. */
    public static final class SayResult {

        public final int recipients;
        public final List<String> warnings;

        SayResult(int recipients, List<String> warnings) {
            this.recipients = recipients;
            this.warnings = warnings;
        }
    }

    private DaveChat() {}

    /** {@code "@a"} (or empty) for everyone online, otherwise one player by name (case-insensitive). */
    public static List<EntityPlayerMP> resolveTargets(String target) throws ProtocolException {
        List<EntityPlayerMP> online = onlinePlayers();
        if (isEveryone(target)) {
            return online;
        }
        for (EntityPlayerMP player : online) {
            if (player.getCommandSenderName()
                .equalsIgnoreCase(target)) {
                List<EntityPlayerMP> one = new ArrayList<>(1);
                one.add(player);
                return one;
            }
        }
        throw new ProtocolException(Protocol.ERR_NOT_FOUND, "player '" + target + "' is not online");
    }

    static boolean isEveryone(String target) {
        return target == null || target.isEmpty() || "@a".equals(target);
    }

    @SuppressWarnings("unchecked")
    public static List<EntityPlayerMP> onlinePlayers() {
        MinecraftServer server = MinecraftServer.getServer();
        if (server == null || server.getConfigurationManager() == null) {
            return new ArrayList<>();
        }
        return new ArrayList<>((List<EntityPlayerMP>) server.getConfigurationManager().playerEntityList);
    }

    /**
     * Sends a message from Dave. Exactly one of {@code text} (plain), {@code markup} (Dave markup) or
     * {@code components} (raw IChatComponent JSON: one component per line) must be set.
     */
    public static SayResult say(String target, String text, String markup, JsonElement components, String replyTo)
        throws ProtocolException {
        List<EntityPlayerMP> recipients = resolveTargets(target);
        List<String> warnings = new ArrayList<>();
        MarkupRenderer.Rendered rendered;
        if (components != null) {
            rendered = fromComponents(components, warnings);
        } else if (markup != null) {
            rendered = renderer().render(markup);
            warnings.addAll(rendered.warnings);
        } else {
            rendered = plain(text);
            warnings.addAll(rendered.warnings);
        }
        if (rendered.vanillaLines.isEmpty()) {
            throw new ProtocolException(Protocol.ERR_BAD_REQUEST, "message is empty");
        }

        boolean whisper = !isEveryone(target);
        List<IChatComponent> modOut = new ArrayList<>();
        List<IChatComponent> vanillaOut = new ArrayList<>();
        for (int i = 0; i < rendered.vanillaLines.size(); i++) {
            fitBoth(
                prefixed(rendered.modLines.get(i), whisper),
                prefixed(rendered.vanillaLines.get(i), whisper),
                modOut,
                vanillaOut,
                warnings);
        }

        Thinking done = new Thinking();
        done.botName = Config.botName;
        done.clear = true;
        for (EntityPlayerMP player : recipients) {
            boolean hasMod = DaveServer.CLIENTS.hasClientMod(player.getUniqueID());
            for (ResolvedLink.RecipientAction action : rendered.actions) {
                try {
                    action.apply(player);
                } catch (Throwable t) {
                    DaveBridge.LOG.warn("Per-recipient action failed for {}", player.getCommandSenderName(), t);
                }
            }
            // Client-command links only for client halves that speak our protocol and have the command ("nei").
            boolean modLinks = com.tuxprogrammer.davebridge.server.network.ServerPacketHandlers
                .canUseModLinks(player.getUniqueID());
            for (IChatComponent line : modLinks ? modOut : vanillaOut) {
                player.addChatMessage(line);
            }
            if (hasMod) {
                DaveNetwork.sendTo(done, player);
            }
            playReplySound(player);
        }
        String to = isEveryone(target) ? "@a" : target;
        for (IChatComponent line : vanillaOut) {
            DaveBridge.LOG.info("({} -> {}) {}", Config.botName, to, line.getUnformattedText());
        }
        if (replyTo != null) {
            DaveBridge.LOG.debug("say replied to {}", replyTo);
        }
        return new SayResult(recipients.size(), warnings);
    }

    /** Shows the "thinking" indicator to {@code target}. Returns the number of recipients. */
    public static int thinking(String target) throws ProtocolException {
        List<EntityPlayerMP> recipients = resolveTargets(target);
        Thinking packet = new Thinking();
        packet.botName = Config.botName;
        for (EntityPlayerMP player : recipients) {
            if (DaveServer.CLIENTS.hasClientMod(player.getUniqueID())) {
                DaveNetwork.sendTo(packet, player);
            } else {
                player.addChatMessage(notice(Config.botName + " is thinking..."));
            }
        }
        return recipients.size();
    }

    // ------------------------------------------------------------------ rendering

    static MarkupRenderer renderer() {
        StandardLinkResolver.Options options = new StandardLinkResolver.Options();
        options.urlAllowlist = Config.urlAllowlist;
        options.commandAllowlist = Config.commandAllowlist;
        options.sendPrefixes = Config.triggerPrefixes;
        options.waypoints = Loader.isModLoaded("sharewhereiam");
        options.guides = Loader.isModLoaded("guidenh");
        int width = Config.maxLineLength - Config.botName.length() - 3;
        return new MarkupRenderer(
            new StandardLinkResolver(options, new MinecraftObjects()),
            width,
            Config.maxLinesPerMessage);
    }

    static MarkupRenderer.Rendered plain(String text) {
        List<IChatComponent> lines = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        for (String line : ChatText.toLines(text, Config.maxLineLength, Config.maxLinesPerMessage, warnings)) {
            IChatComponent root = new ChatComponentText("");
            root.appendSibling(ForgeHooks.newChatWithLinks(line));
            lines.add(root);
        }
        return new MarkupRenderer.Rendered(lines, lines, new ArrayList<>(), warnings);
    }

    /** The {@code components} escape hatch: raw chat JSON, one component per line, with clicks checked. */
    static MarkupRenderer.Rendered fromComponents(JsonElement components, List<String> warnings)
        throws ProtocolException {
        List<JsonElement> items = new ArrayList<>();
        if (components.isJsonArray()) {
            JsonArray arr = components.getAsJsonArray();
            for (int i = 0; i < arr.size(); i++) items.add(arr.get(i));
        } else {
            items.add(components);
        }
        if (items.size() > Config.maxLinesPerMessage) {
            warnings.add("components cut to " + Config.maxLinesPerMessage + " lines");
            items = items.subList(0, Config.maxLinesPerMessage);
        }
        List<IChatComponent> lines = new ArrayList<>();
        for (JsonElement el : items) {
            warnDroppedClicks(el, warnings);
            IChatComponent c;
            try {
                c = IChatComponent.Serializer.func_150699_a(el.toString());
            } catch (RuntimeException e) {
                throw new ProtocolException(Protocol.ERR_BAD_REQUEST, "invalid chat component: " + e.getMessage());
            }
            if (c == null) continue;
            sanitize(c, warnings);
            IChatComponent root = new ChatComponentText("");
            root.appendSibling(c);
            lines.add(root);
        }
        return new MarkupRenderer.Rendered(lines, lines, new ArrayList<>(), warnings);
    }

    /**
     * Vanilla's deserializer silently drops clicks that are not allowed in chat ({@code open_file},
     * {@code twitch_user_info}) and unknown actions; this reports them, since every removal is a warning.
     */
    static void warnDroppedClicks(JsonElement el, List<String> warnings) {
        if (el == null) return;
        if (el.isJsonArray()) {
            for (JsonElement e : el.getAsJsonArray()) warnDroppedClicks(e, warnings);
            return;
        }
        if (!el.isJsonObject()) return;
        for (Map.Entry<String, JsonElement> e : el.getAsJsonObject()
            .entrySet()) {
            JsonElement v = e.getValue();
            if (e.getKey()
                .equals("clickEvent") && v.isJsonObject()) {
                JsonElement action = v.getAsJsonObject()
                    .get("action");
                String name = action != null && action.isJsonPrimitive() ? action.getAsString() : null;
                ClickEvent.Action a = name == null ? null : ClickEvent.Action.getValueByCanonicalName(name);
                if (a == null || !a.shouldAllowInChat()) {
                    JsonElement value = v.getAsJsonObject()
                        .get("value");
                    warnings.add(
                        "components: removed click " + name
                            + " '"
                            + (value != null && value.isJsonPrimitive() ? value.getAsString() : "")
                            + "': not allowed in chat");
                }
            } else {
                warnDroppedClicks(v, warnings);
            }
        }
    }

    /** Drops clicks the markup would not allow: non-http(s) or off-allowlist URLs, unlisted commands, files. */
    static void sanitize(IChatComponent c, List<String> warnings) {
        ChatStyle style = c.getChatStyle();
        ClickEvent click = style.getChatClickEvent();
        if (click != null) {
            String reason = null;
            switch (click.getAction()) {
                case OPEN_URL:
                    reason = StandardLinkResolver.checkUrl(click.getValue(), Config.urlAllowlist);
                    break;
                case RUN_COMMAND:
                    String v = click.getValue();
                    if (v.startsWith("/")) {
                        reason = StandardLinkResolver.checkCommand(v, Config.commandAllowlist);
                    } else if (TriggerMatcher.match(v, Config.triggerPrefixes) == null
                        || v.length() > StandardLinkResolver.MAX_CHAT_LENGTH
                        || !StandardLinkResolver.isChatSafe(v)) {
                            reason = "run_command chat text must start with a trigger prefix";
                        }
                    break;
                case SUGGEST_COMMAND:
                    break;
                default:
                    reason = click.getAction()
                        .getCanonicalName() + " is not allowed";
            }
            if (reason != null) {
                warnings.add(
                    "components: removed click " + click.getAction()
                        .getCanonicalName() + " '" + click.getValue() + "': " + reason);
                style.setChatClickEvent(null);
            }
        }
        HoverEvent hover = style.getChatHoverEvent();
        if (hover != null && hover.getAction() == HoverEvent.Action.SHOW_TEXT && hover.getValue() != null) {
            sanitize(hover.getValue(), warnings);
        }
        for (Object sibling : c.getSiblings()) {
            sanitize((IChatComponent) sibling, warnings);
        }
        if (c instanceof ChatComponentTranslation) {
            for (Object arg : ((ChatComponentTranslation) c).getFormatArgs()) {
                if (arg instanceof IChatComponent) sanitize((IChatComponent) arg, warnings);
            }
        }
    }

    // ------------------------------------------------------------------ prefix and size

    /**
     * Public lines start {@code <Dave> }; private ones use vanilla's whisper line ("Dave whispers to you: ", gray
     * italic, translated on the client) with the body left in its own style.
     */
    static IChatComponent prefixed(IChatComponent body, boolean whisper) {
        IChatComponent name = new ChatComponentText(Config.botName);
        name.setChatStyle(new ChatStyle().setColor(nameColor()));
        IChatComponent root = new ChatComponentText("");
        if (whisper) {
            IChatComponent prefix = new ChatComponentTranslation("commands.message.display.incoming", name, "");
            prefix.setChatStyle(
                new ChatStyle().setColor(EnumChatFormatting.GRAY)
                    .setItalic(Boolean.TRUE));
            root.appendSibling(prefix);
        } else {
            root.appendText("<");
            root.appendSibling(name);
            root.appendText("> ");
        }
        root.appendSibling(body);
        return root;
    }

    /**
     * Fits both variants of one line, reporting each degradation once even when both variants needed it.
     */
    static void fitBoth(IChatComponent mod, IChatComponent vanilla, List<IChatComponent> modOut,
        List<IChatComponent> vanillaOut, List<String> warnings) {
        Set<String> lineWarnings = new LinkedHashSet<>();
        List<String> vanillaWarnings = new ArrayList<>();
        List<String> modWarnings = new ArrayList<>();
        vanillaOut.add(fit(vanilla, vanillaWarnings));
        modOut.add(fit(mod, modWarnings));
        lineWarnings.addAll(vanillaWarnings);
        lineWarnings.addAll(modWarnings);
        warnings.addAll(lineWarnings);
    }

    /** Keeps a line under {@link #MAX_LINE_JSON_BYTES}, degrading item hovers, then all hovers, then to plain text. */
    static IChatComponent fit(IChatComponent line, List<String> warnings) {
        if (jsonBytes(line) <= MAX_LINE_JSON_BYTES) {
            return line;
        }
        IChatComponent copy = line.createCopy();
        degradeHovers(copy, true);
        if (jsonBytes(copy) <= MAX_LINE_JSON_BYTES) {
            warnings.add("a line was too large for chat; item hovers replaced with names");
            return copy;
        }
        degradeHovers(copy, false);
        if (jsonBytes(copy) <= MAX_LINE_JSON_BYTES) {
            warnings.add("a line was too large for chat; hovers removed");
            return copy;
        }
        warnings.add("a line was too large for chat; sent as plain text");
        String text = line.getUnformattedText();
        return new ChatComponentText(text.length() > 2000 ? text.substring(0, 2000) : text);
    }

    static int jsonBytes(IChatComponent c) {
        return IChatComponent.Serializer.func_150696_a(c)
            .getBytes(StandardCharsets.UTF_8).length;
    }

    private static void degradeHovers(IChatComponent c, boolean itemsOnly) {
        ChatStyle style = c.getChatStyle();
        HoverEvent hover = style.getChatHoverEvent();
        if (hover != null) {
            if (hover.getAction() == HoverEvent.Action.SHOW_ITEM) {
                style.setChatHoverEvent(
                    itemsOnly
                        ? new HoverEvent(HoverEvent.Action.SHOW_TEXT, new ChatComponentText(c.getUnformattedText()))
                        : null);
            } else if (!itemsOnly) {
                style.setChatHoverEvent(null);
            }
        }
        for (Object sibling : c.getSiblings()) {
            degradeHovers((IChatComponent) sibling, itemsOnly);
        }
    }

    // ------------------------------------------------------------------ misc

    /** A short gray italic line, used for status notices to a single player. */
    public static IChatComponent notice(String text) {
        IChatComponent c = new ChatComponentText(text);
        c.setChatStyle(
            new ChatStyle().setColor(EnumChatFormatting.GRAY)
                .setItalic(Boolean.TRUE));
        return c;
    }

    /** A sound only the recipient hears, at their position (works without the client half). */
    static void playReplySound(EntityPlayerMP player) {
        String sound = Config.replySound;
        if (sound == null || sound.trim()
            .isEmpty()) {
            return;
        }
        try {
            player.playerNetServerHandler.sendPacket(
                new S29PacketSoundEffect(
                    sound.trim(),
                    player.posX,
                    player.posY,
                    player.posZ,
                    Config.replySoundVolume,
                    Config.replySoundPitch));
        } catch (Throwable t) {
            DaveBridge.LOG.debug("Could not play reply sound", t);
        }
    }

    static EnumChatFormatting nameColor() {
        EnumChatFormatting color = EnumChatFormatting.getValueByName(
            Config.botNameColor == null ? ""
                : Config.botNameColor.trim()
                    .toLowerCase(Locale.ROOT));
        return color != null && color.isColor() ? color : EnumChatFormatting.AQUA;
    }
}
