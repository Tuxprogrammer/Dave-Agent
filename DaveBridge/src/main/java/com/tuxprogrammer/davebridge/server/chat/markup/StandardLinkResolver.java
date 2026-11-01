package com.tuxprogrammer.davebridge.server.chat.markup;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import net.minecraft.util.ChatComponentText;
import net.minecraft.util.ChatStyle;
import net.minecraft.util.EnumChatFormatting;
import net.minecraft.util.IChatComponent;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;

/**
 * Resolves the tokens that need no game state (links, buttons, waypoints, guides) and hands game objects (items,
 * fluids, quests, players, chains) to a {@link GameObjects}. Everything is validated; anything that fails returns null
 * with a warning, and the renderer shows plain text instead.
 */
public final class StandardLinkResolver implements LinkResolver {

    /** Vanilla's client-to-server chat limit; a clicked run_command goes through it. */
    public static final int MAX_CHAT_LENGTH = 100;

    /** Settings the resolver needs, kept separate from Config so tests can build them. */
    public static final class Options {

        /** Host suffixes allowed for {url:}; empty means any host. */
        public String[] urlAllowlist = new String[0];
        /** Command names (with leading slash) allowed for {cmd:} and raw run_command clicks. */
        public String[] commandAllowlist = { "/dave", "/davebridge", "/bq_client", "/nei_bookmark", "/savewaypoint",
            "/guidenhc" };
        /** {send:} text must start with one of these (Dave's trigger prefixes). */
        public String[] sendPrefixes = { "dave", "@dave", "!dave" };
        /** The waypoint mod (sharewhereiam) is installed, so /savewaypoint exists on clients. */
        public boolean waypoints;
        /** GuideNH is installed, so /guidenhc exists on clients. */
        public boolean guides;
    }

    /** Game-object tokens. Implemented against the live game; faked in tests. */
    public interface GameObjects {

        /** {@code kind} is item, recipe or uses. */
        ResolvedLink item(Markup.Token token, List<String> warnings);

        ResolvedLink fluid(Markup.Token token, List<String> warnings);

        ResolvedLink chain(Markup.Token token, List<String> warnings);

        ResolvedLink quest(Markup.Token token, List<String> warnings);

        ResolvedLink player(Markup.Token token, List<String> warnings);
    }

    private final Options options;
    private final GameObjects game;

    public StandardLinkResolver(Options options, GameObjects game) {
        this.options = options;
        this.game = game;
    }

    /**
     * Grey type words shown before links whose label alone doesn't say what clicking does, e.g.
     * {@code Recipe: [NAND Chip]} or {@code Ask: [More detail]}. Items, fluids, players and plain URLs read fine inline
     * and get none.
     */
    static final Map<String, String> TYPE_LABELS = new HashMap<>();

    static {
        TYPE_LABELS.put("recipe", "Recipe");
        TYPE_LABELS.put("uses", "Uses");
        TYPE_LABELS.put("quest", "Quest");
        TYPE_LABELS.put("send", "Ask");
        TYPE_LABELS.put("waypoint", "Waypoint");
        TYPE_LABELS.put("guide", "Guide");
    }

    @Override
    public ResolvedLink resolve(Markup.Token token, List<String> warnings) {
        ResolvedLink link = resolveKind(token, warnings);
        String type = TYPE_LABELS.get(token.kind);
        if (link == null || type == null) {
            return link;
        }
        // Item links (recipe, uses) are bare names when labelled; buttons are bracketed already, and a quest is
        // BetterQuesting's share token, which must stay exactly as BQ wrote it.
        boolean bracket = "recipe".equals(token.kind) || "uses".equals(token.kind);
        return new ResolvedLink(
            typed(type, link.vanilla, bracket),
            link.mod == link.vanilla ? null : typed(type, link.mod, bracket),
            link.ownLine,
            link.actions);
    }

    /**
     * {@code Type: link} with the type word in grey. With {@code bracket}, an unbracketed link becomes {@code [link]},
     * with the link's own click and hover on the brackets too; an already bracketed one (a vanilla item name) keeps its
     * own.
     */
    static IChatComponent typed(String type, IChatComponent link, boolean bracket) {
        IChatComponent out = new ChatComponentText("");
        out.appendSibling(ChatStyles.text(type + ": ", EnumChatFormatting.GRAY));
        if (!bracket || link.getUnformattedText()
            .startsWith("[")) {
            out.appendSibling(link);
            return out;
        }
        IChatComponent open = new ChatComponentText("[");
        open.setChatStyle(
            link.getChatStyle()
                .createShallowCopy());
        IChatComponent close = new ChatComponentText("]");
        close.setChatStyle(
            link.getChatStyle()
                .createShallowCopy());
        out.appendSibling(open);
        out.appendSibling(link);
        out.appendSibling(close);
        return out;
    }

    private ResolvedLink resolveKind(Markup.Token token, List<String> warnings) {
        switch (token.kind) {
            case "url":
                return url(token, warnings);
            case "cmd":
                return cmd(token, warnings);
            case "suggest":
                return suggest(token, warnings);
            case "send":
                return send(token, warnings);
            case "show":
                return show(token, warnings);
            case "waypoint":
                return waypoint(token, warnings);
            case "guide":
                return guide(token, warnings);
            case "item":
            case "recipe":
            case "uses":
                return game.item(token, warnings);
            case "fluid":
                return game.fluid(token, warnings);
            case "chain":
                return game.chain(token, warnings);
            case "quest":
                return game.quest(token, warnings);
            case "player":
                return game.player(token, warnings);
            default:
                warnings.add("unsupported token " + token.raw);
                return null;
        }
    }

    // ------------------------------------------------------------------ url

    ResolvedLink url(Markup.Token token, List<String> warnings) {
        String reason = checkUrl(token.arg, options.urlAllowlist);
        if (reason != null) {
            warnings.add(token.raw + ": " + reason);
            return null;
        }
        String label = token.label != null && !token.label.isEmpty() ? token.label : token.arg;
        IChatComponent c = new ChatComponentText(label);
        ChatStyle style = ChatStyles.apply(
            token.style,
            new ChatStyle().setColor(EnumChatFormatting.BLUE)
                .setUnderlined(Boolean.TRUE));
        style.setChatClickEvent(ChatStyles.openUrl(token.arg));
        style.setChatHoverEvent(ChatStyles.hoverText(token.arg));
        c.setChatStyle(style);
        return ResolvedLink.same(c);
    }

    /** Null if allowed, otherwise why not. Only http and https; the 1.7.10 client refuses everything else anyway. */
    public static String checkUrl(String url, String[] allowlist) {
        URI uri;
        try {
            uri = new URI(url);
        } catch (Exception e) {
            return "not a valid URL";
        }
        String scheme = uri.getScheme() == null ? ""
            : uri.getScheme()
                .toLowerCase(Locale.ROOT);
        if (!scheme.equals("http") && !scheme.equals("https")) {
            return "only http and https links are allowed";
        }
        String host = uri.getHost() == null ? ""
            : uri.getHost()
                .toLowerCase(Locale.ROOT);
        if (host.isEmpty()) {
            return "URL has no host";
        }
        if (allowlist != null && allowlist.length > 0) {
            for (String allowed : allowlist) {
                String a = allowed == null ? ""
                    : allowed.trim()
                        .toLowerCase(Locale.ROOT);
                if (!a.isEmpty() && (host.equals(a) || host.endsWith("." + a))) {
                    return null;
                }
            }
            return "host " + host + " is not in urlAllowlist";
        }
        return null;
    }

    // ------------------------------------------------------------------ buttons

    ResolvedLink cmd(Markup.Token token, List<String> warnings) {
        String reason = checkCommand(token.arg, options.commandAllowlist);
        if (reason != null) {
            warnings.add(token.raw + ": " + reason);
            return null;
        }
        String label = token.label != null && !token.label.isEmpty() ? token.label : token.arg;
        return ResolvedLink.same(
            ChatStyles.button(
                label,
                EnumChatFormatting.GOLD,
                token.style,
                ChatStyles.hoverText("Click to run: " + token.arg),
                ChatStyles.run(token.arg)));
    }

    /** Null if {@code command} may be a click target, otherwise why not. */
    public static String checkCommand(String command, String[] allowlist) {
        if (!command.startsWith("/")) {
            return "commands must start with /";
        }
        if (command.length() > MAX_CHAT_LENGTH) {
            return "command longer than " + MAX_CHAT_LENGTH + " characters";
        }
        if (!isChatSafe(command)) {
            return "command contains characters chat cannot send";
        }
        String name = command.split(" ", 2)[0].toLowerCase(Locale.ROOT);
        for (String allowed : allowlist) {
            if (allowed != null && name.equals(
                allowed.trim()
                    .toLowerCase(Locale.ROOT))) {
                return null;
            }
        }
        return name + " is not in commandAllowlist";
    }

    ResolvedLink suggest(Markup.Token token, List<String> warnings) {
        String text = token.arg;
        if (text.length() > MAX_CHAT_LENGTH) {
            warnings.add(token.raw + ": suggestion cut to " + MAX_CHAT_LENGTH + " characters");
            text = text.substring(0, MAX_CHAT_LENGTH);
        }
        String label = token.label != null && !token.label.isEmpty() ? token.label : text.trim();
        return ResolvedLink.same(
            ChatStyles.button(
                label,
                EnumChatFormatting.AQUA,
                token.style,
                ChatStyles.hoverText("Click to put in your chat line: " + text),
                ChatStyles.suggest(text)));
    }

    /**
     * {@code {send:dave, more|More}}: clicking sends the text as the player's chat. In 1.7.10 a run_command click goes
     * through GuiChat's send path: ClientCommandHandler first (it strips a leading "/" and looks up the first word),
     * then chat to the server. Requiring a trigger prefix keeps it from hitting a client command and from making
     * players say arbitrary things; anything else degrades to a suggestion.
     */
    ResolvedLink send(Markup.Token token, List<String> warnings) {
        String text = token.arg.trim();
        String label = token.label != null && !token.label.isEmpty() ? token.label : text;
        boolean prefixed = false;
        for (String p : options.sendPrefixes) {
            if (p != null && !p.trim()
                .isEmpty()
                && text.regionMatches(
                    true,
                    0,
                    p.trim(),
                    0,
                    p.trim()
                        .length())) {
                prefixed = true;
                break;
            }
        }
        if (!prefixed || text.length() > MAX_CHAT_LENGTH || !isChatSafe(text)) {
            warnings.add(
                token.raw + ": send text must start with a trigger prefix, be at most "
                    + MAX_CHAT_LENGTH
                    + " characters and contain no formatting codes; shown as a suggestion instead");
            Markup.Token asSuggest = new Markup.Token("suggest", stripUnsafe(text), label, token.style, token.raw);
            return suggest(asSuggest, warnings);
        }
        return ResolvedLink.same(
            ChatStyles.button(
                label,
                EnumChatFormatting.GREEN,
                token.style,
                ChatStyles.hoverText("Click to say: " + text),
                ChatStyles.run(text)));
    }

    /** Label of a {@code {show:}} button when the token has none. */
    static final String SHOW_LABEL = "Show me in game";

    /**
     * {@code {show:what|label}}: a {@code [Show me in game]} button that says "dave, show me <what> in game", which
     * asks Dave for a guided demonstration. Only players with the client half can watch one, so the vanilla variant
     * is empty (the caller drops a line left blank by it).
     */
    ResolvedLink show(Markup.Token token, List<String> warnings) {
        String prefix = options.sendPrefixes.length > 0 && options.sendPrefixes[0] != null
            ? options.sendPrefixes[0].trim()
            : "dave";
        String head = prefix + (prefix.endsWith(",") ? " " : ", ") + "show me ";
        String tail = " in game";
        String what = stripUnsafe(token.arg.trim());
        int room = MAX_CHAT_LENGTH - head.length() - tail.length();
        if (what.length() > room) {
            warnings.add(token.raw + ": show text cut to " + room + " characters");
            what = what.substring(0, Math.max(0, room))
                .trim();
        }
        String text = head + what + tail;
        String label = token.label != null && !token.label.isEmpty() ? token.label : SHOW_LABEL;
        IChatComponent mod = ChatStyles.button(
            label,
            EnumChatFormatting.LIGHT_PURPLE,
            token.style,
            ChatStyles.hoverText("Dave walks you there in game (only you see him)\nClick to say: " + text),
            ChatStyles.run(text));
        return new ResolvedLink(new ChatComponentText(""), mod, false, null);
    }

    /** Characters the server accepts in a chat packet (vanilla kicks for §, control characters and DEL). */
    public static boolean isChatSafe(String s) {
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '§' || c < ' ' || c == 127) {
                return false;
            }
        }
        return true;
    }

    private static String stripUnsafe(String s) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < s.length() && sb.length() < MAX_CHAT_LENGTH; i++) {
            char c = s.charAt(i);
            if (c != '§' && c >= ' ' && c != 127) sb.append(c);
        }
        return sb.toString();
    }

    // ------------------------------------------------------------------ waypoints and guides

    /**
     * {@code {waypoint:x,y,z[,dim]|name}} in sharewhereiam's share format: a click runs its client command
     * {@code /savewaypoint <base64 JSON>}, which opens JourneyMap's waypoint editor pre-filled.
     */
    // Source:
    // https://github.com/GTNewHorizons/Share-Where-I-am/blob/1.3.55/src/main/java/com/muxiu1997/sharewhereiam/model/SharedWaypoint.java
    // JSON shape (JourneyMap 5): id, name, icon, x, y, z, r, g, b, enable, type, origin, dimensions,
    // primaryDimension. Nether coordinates are stored in overworld scale (x8).
    ResolvedLink waypoint(Markup.Token token, List<String> warnings) {
        String[] parts = token.arg.split(",");
        int x, y, z, dim = 0;
        try {
            if (parts.length < 3 || parts.length > 4) throw new NumberFormatException();
            x = Integer.parseInt(parts[0].trim());
            y = Integer.parseInt(parts[1].trim());
            z = Integer.parseInt(parts[2].trim());
            if (parts.length == 4) dim = Integer.parseInt(parts[3].trim());
        } catch (NumberFormatException e) {
            warnings.add(token.raw + ": expected {waypoint:x,y,z[,dim]|name}");
            return null;
        }
        String name = token.label != null && !token.label.isEmpty() ? token.label : x + ", " + z;
        String coords = x + ", " + y + ", " + z + (dim != 0 ? " (dim " + dim + ")" : "");
        IChatComponent hover = new ChatComponentText(name + "\n" + coords);
        if (!options.waypoints) {
            // no waypoint mod: show the coordinates with a hover, no click
            IChatComponent c = new ChatComponentText(name + " (" + coords + ")");
            c.setChatStyle(
                ChatStyles.apply(token.style, new ChatStyle().setColor(EnumChatFormatting.GREEN))
                    .setChatHoverEvent(ChatStyles.hoverText(hover)));
            return ResolvedLink.same(c);
        }
        hover.appendText("\nClick to add it as a JourneyMap waypoint");
        String command = "/savewaypoint " + waypointBase64(name, x, y, z, dim);
        return ResolvedLink.same(
            ChatStyles.button(
                name + " " + x + ", " + y + ", " + z,
                EnumChatFormatting.GREEN,
                token.style,
                ChatStyles.hoverText(hover),
                ChatStyles.run(command)));
    }

    static String waypointBase64(String name, int x, int y, int z, int dim) {
        int storedX = dim == -1 ? x * 8 : x;
        int storedZ = dim == -1 ? z * 8 : z;
        JsonObject o = new JsonObject();
        o.addProperty("id", String.format("%s_%s,%s,%s", name, storedX, y, storedZ));
        o.addProperty("name", name);
        o.addProperty("icon", "waypoint-normal.png");
        o.addProperty("x", storedX);
        o.addProperty("y", y);
        o.addProperty("z", storedZ);
        o.addProperty("r", 0x55);
        o.addProperty("g", 0xFF);
        o.addProperty("b", 0xFF);
        o.addProperty("enable", true);
        o.addProperty("type", "Normal");
        o.addProperty("origin", "JourneyMap");
        JsonArray dims = new JsonArray();
        dims.add(new JsonPrimitive(dim));
        o.add("dimensions", dims);
        o.addProperty("primaryDimension", dim);
        return Base64.getEncoder()
            .encodeToString(
                o.toString()
                    .getBytes(StandardCharsets.UTF_8));
    }

    /**
     * {@code {guide:modid:path|label}}: GuideNH's client command {@code /guidenhc open <id>}. Guide ids live in client
     * resources, so the server cannot check them; GuideNH says "guide not found" itself.
     */
    // Source: GuideNH 2.1.11, com/hfstudio/guidenh/client/command/GuideNhClientCommand.java (openGuide)
    ResolvedLink guide(Markup.Token token, List<String> warnings) {
        if (!options.guides) {
            warnings.add(token.raw + ": GuideNH is not installed");
            return null;
        }
        if (!token.arg.matches("[a-z0-9_.-]+:[a-z0-9_./-]+")) {
            warnings.add(token.raw + ": guide id must look like modid:path");
            return null;
        }
        String label = token.label != null && !token.label.isEmpty() ? token.label : token.arg;
        return ResolvedLink.same(
            ChatStyles.button(
                label,
                EnumChatFormatting.LIGHT_PURPLE,
                token.style,
                ChatStyles.hoverText("Click to open the guide " + token.arg),
                ChatStyles.run("/guidenhc open " + token.arg)));
    }
}
