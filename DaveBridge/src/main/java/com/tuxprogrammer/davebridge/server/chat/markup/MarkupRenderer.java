package com.tuxprogrammer.davebridge.server.chat.markup;

import java.util.ArrayList;
import java.util.List;

import net.minecraft.util.ChatComponentText;
import net.minecraft.util.ChatStyle;
import net.minecraft.util.IChatComponent;

/**
 * Lays parsed markup out into chat lines. Resolves tokens once, then builds two variants of every line: one for
 * players with the DaveBridge client half and one for everyone else. Lines carry no prefix; the caller adds
 * {@code <Dave>} or the whisper prefix.
 * <p>
 * Wrapping: plain text wraps at spaces; a token's component is never split. An exclusive token (a BetterQuesting
 * quest link) never shares a line with another link.
 */
public final class MarkupRenderer {

    public static final String TRUNCATED = "... (truncated)";

    /**
     * Markup longer than this many characters per allowed output character (lines x width) is cut before parsing:
     * nothing past it could be shown, and the parser and wrapper slow down on huge single lines.
     */
    static final int MARKUP_CHARS_PER_VISIBLE_CHAR = 4;

    /** Rendering output. {@code modLines} and {@code vanillaLines} have the same length. */
    public static final class Rendered {

        public final List<IChatComponent> modLines;
        public final List<IChatComponent> vanillaLines;
        public final List<ResolvedLink.RecipientAction> actions;
        public final List<String> warnings;

        public Rendered(List<IChatComponent> modLines, List<IChatComponent> vanillaLines,
            List<ResolvedLink.RecipientAction> actions, List<String> warnings) {
            this.modLines = modLines;
            this.vanillaLines = vanillaLines;
            this.actions = actions;
            this.warnings = warnings;
        }
    }

    private final LinkResolver resolver;
    private final int width;
    private final int maxLines;

    /**
     * @param width    visible characters per line, excluding the prefix
     * @param maxLines lines kept before the message is cut with {@link #TRUNCATED}
     */
    public MarkupRenderer(LinkResolver resolver, int width, int maxLines) {
        this.resolver = resolver;
        this.width = Math.max(20, width);
        this.maxLines = Math.max(1, maxLines);
    }

    /** The longest markup {@link #render} parses; the rest is dropped with a warning. */
    int maxMarkupLength() {
        return maxLines * width * MARKUP_CHARS_PER_VISIBLE_CHAR;
    }

    public Rendered render(String markup) {
        List<String> warnings = new ArrayList<>();
        int cap = maxMarkupLength();
        if (markup != null && markup.length() > cap) {
            if (Character.isHighSurrogate(markup.charAt(cap - 1))) cap--;
            warnings.add("markup longer than " + cap + " characters; the rest was dropped");
            markup = markup.substring(0, cap);
        }
        Markup.Result parsed = Markup.parse(markup);
        warnings.addAll(parsed.warnings);
        List<ResolvedLink.RecipientAction> actions = new ArrayList<>();
        List<Piece> pieces = new ArrayList<>();

        for (Markup.Node node : parsed.nodes) {
            if (node instanceof Markup.Newline) {
                pieces.add(Piece.NEWLINE);
            } else if (node instanceof Markup.Text) {
                Markup.Text t = (Markup.Text) node;
                pieces.add(Piece.text(t.text, ChatStyles.apply(t.style, null)));
            } else if (node instanceof Markup.Token) {
                Markup.Token token = (Markup.Token) node;
                ResolvedLink link;
                try {
                    link = "hover".equals(token.kind) ? hover(token, warnings) : resolver.resolve(token, warnings);
                } catch (VirtualMachineError e) {
                    throw e;
                } catch (Throwable t) {
                    // one bad token (e.g. a mod item whose name needs a client class) must not lose the whole message
                    warnings.add("could not resolve " + token.raw + ": " + t);
                    link = null;
                }
                if (link == null) {
                    // unresolved: keep the readable part as plain styled text
                    pieces.add(Piece.text(token.labelOrArg(), ChatStyles.apply(token.style, null)));
                } else {
                    pieces.add(Piece.atom(link));
                    actions.addAll(link.actions);
                }
            }
        }

        List<Integer> soft = new ArrayList<>();
        List<List<Piece>> lines = layout(pieces, soft);
        if (lines.size() > maxLines) {
            warnings.add("message cut to " + maxLines + " lines");
            lines = new ArrayList<>(lines.subList(0, maxLines - 1));
            soft = new ArrayList<>(soft.subList(0, maxLines - 1));
            soft.set(soft.size() - 1, HARD);
            List<Piece> cut = new ArrayList<>();
            cut.add(Piece.text(TRUNCATED, new ChatStyle().setColor(net.minecraft.util.EnumChatFormatting.GRAY)));
            lines.add(cut);
            soft.add(HARD);
        }
        lines = joinSoftBreaks(lines, soft);
        List<IChatComponent> mod = new ArrayList<>();
        List<IChatComponent> vanilla = new ArrayList<>();
        for (List<Piece> line : lines) {
            mod.add(build(line, true));
            vanilla.add(build(line, false));
        }
        return new Rendered(mod, vanilla, actions, warnings);
    }

    /**
     * {@code {hover:text|label}}: the label with a show_text hover. The hover text may use style markup, including one
     * level of tags ({@code {red}...{/}}); tokens in it show their label as text; {@code \n} is a line break.
     */
    static ResolvedLink hover(Markup.Token token, List<String> warnings) {
        IChatComponent hoverText = new ChatComponentText("");
        boolean first = true;
        Markup.Result parsed = Markup.parseHoverText(token.arg);
        for (String w : parsed.warnings) warnings.add(token.raw + ": " + w);
        for (Markup.Node n : parsed.nodes) {
            if (n instanceof Markup.Newline) {
                hoverText.appendText("\n");
            } else if (n instanceof Markup.Text) {
                Markup.Text t = (Markup.Text) n;
                IChatComponent part = new ChatComponentText(t.text);
                part.setChatStyle(ChatStyles.apply(t.style, null));
                hoverText.appendSibling(part);
            } else if (n instanceof Markup.Token) {
                Markup.Token t = (Markup.Token) n;
                IChatComponent part = new ChatComponentText(t.labelOrArg());
                part.setChatStyle(ChatStyles.apply(t.style, null));
                hoverText.appendSibling(part);
            }
            first = false;
        }
        String label = token.label != null && !token.label.isEmpty() ? token.label : "[?]";
        IChatComponent c = new ChatComponentText(label);
        ChatStyle style = ChatStyles.apply(token.style, new ChatStyle());
        if (token.style == null || !token.style.underline) {
            style.setUnderlined(Boolean.TRUE);
        }
        style.setChatHoverEvent(ChatStyles.hoverText(first ? new ChatComponentText(token.arg) : hoverText));
        c.setChatStyle(style);
        return ResolvedLink.same(c);
    }

    // ------------------------------------------------------------------ layout

    private static final class Piece {

        static final Piece NEWLINE = new Piece(null, null, null, null);

        final String text; // non-null for splittable text
        final ChatStyle style;
        final ResolvedLink link; // non-null for atoms
        final Integer length;

        private Piece(String text, ChatStyle style, ResolvedLink link, Integer length) {
            this.text = text;
            this.style = style;
            this.link = link;
            this.length = length;
        }

        static Piece text(String text, ChatStyle style) {
            return new Piece(text, style, null, text.length());
        }

        static Piece atom(ResolvedLink link) {
            return new Piece(null, null, link, visibleLength(link.vanilla));
        }

        boolean isNewline() {
            return this == NEWLINE;
        }
    }

    static int visibleLength(IChatComponent c) {
        try {
            return c.getUnformattedText()
                .length();
        } catch (RuntimeException e) {
            return 10;
        }
    }

    /**
     * Rejoins lines that were split only because they were wider than {@link #width}, so one paragraph is one chat
     * message and the client wraps it to the player's chat width. Splitting it would start every piece with the bot's
     * name, often mid-sentence. Dave's own line breaks stay, and so do the splits that keep an exclusive (quest) link
     * apart from other links.
     */
    static List<List<Piece>> joinSoftBreaks(List<List<Piece>> lines, List<Integer> soft) {
        List<List<Piece>> out = new ArrayList<>();
        for (int i = 0; i < lines.size(); i++) {
            List<Piece> line = lines.get(i);
            if (i > 0 && soft.get(i - 1) != HARD && canShare(out.get(out.size() - 1), line)) {
                List<Piece> prev = out.get(out.size() - 1);
                if (soft.get(i - 1) == SOFT_SPACE) {
                    prev.add(Piece.text(" ", new ChatStyle()));
                }
                prev.addAll(line);
            } else {
                out.add(new ArrayList<>(line));
            }
        }
        return out;
    }

    /** Whether two lines may become one message: never an exclusive link together with another link. */
    private static boolean canShare(List<Piece> a, List<Piece> b) {
        int links = 0;
        boolean exclusive = false;
        for (List<Piece> line : java.util.Arrays.asList(a, b)) {
            for (Piece p : line) {
                if (p.link != null) {
                    links++;
                    exclusive |= p.link.ownLine;
                }
            }
        }
        return !exclusive || links <= 1;
    }

    /** How a laid-out line ended: a real break, or width alone (rejoined with or without the space it replaced). */
    static final int HARD = 0, SOFT_SPACE = 1, SOFT_JOIN = 2;

    /** Lays pieces into lines of at most {@link #width}; {@code soft} gets, per line, how it ended. */
    private List<List<Piece>> layout(List<Piece> pieces, List<Integer> soft) {
        List<List<Piece>> lines = new ArrayList<>();
        List<Piece> cur = new ArrayList<>();
        int[] curLen = { 0 };

        for (Piece p : pieces) {
            if (p.isNewline()) {
                endLine(lines, soft, HARD, cur, curLen);
                cur = new ArrayList<>();
                continue;
            }
            if (p.link != null) {
                // An exclusive link (quest) may share its line with text, but not with other links: the BQ client
                // replaces the whole line, which would drop their clicks and hovers.
                boolean lineHasLink = false, lineExclusive = false;
                for (Piece q : cur) {
                    if (q.link != null) {
                        lineHasLink = true;
                        lineExclusive |= q.link.ownLine;
                    }
                }
                boolean clash = p.link.ownLine ? lineHasLink : lineExclusive;
                if (clash || (curLen[0] > 0 && curLen[0] + p.length > width)) {
                    endLine(lines, soft, clash ? HARD : SOFT_SPACE, cur, curLen);
                    cur = new ArrayList<>();
                }
                cur.add(p);
                curLen[0] += p.length;
                continue;
            }
            String rest = curLen[0] == 0 ? stripLeading(p.text) : p.text;
            while (!rest.isEmpty()) {
                int available = width - curLen[0];
                if (rest.length() <= available) {
                    cur.add(Piece.text(rest, p.style));
                    curLen[0] += rest.length();
                    break;
                }
                int cut = available > 0 ? rest.lastIndexOf(' ', available) : -1;
                int end = SOFT_SPACE;
                if (cut > 0) {
                    cur.add(Piece.text(rest.substring(0, cut), p.style));
                    rest = rest.substring(cut + 1);
                } else if (curLen[0] > 0) {
                    // nothing fits on this line; continue on the next one
                } else {
                    cur.add(Piece.text(rest.substring(0, available), p.style));
                    rest = rest.substring(available);
                    end = SOFT_JOIN; // cut inside a word
                }
                curLen[0] += 1; // force the line to end
                endLine(lines, soft, end, cur, curLen);
                cur = new ArrayList<>();
                rest = stripLeading(rest);
            }
        }
        endLine(lines, soft, HARD, cur, curLen);
        return lines;
    }

    private static void endLine(List<List<Piece>> lines, List<Integer> soft, int softEnd, List<Piece> cur,
        int[] curLen) {
        // drop lines that are empty or only whitespace
        boolean blank = true;
        for (Piece p : cur) {
            if (p.link != null || !p.text.trim()
                .isEmpty()) {
                blank = false;
                break;
            }
        }
        if (!blank) {
            // trim trailing spaces of the last text piece
            Piece last = cur.get(cur.size() - 1);
            if (last.link == null) {
                String t = rtrim(last.text);
                cur.set(cur.size() - 1, Piece.text(t, last.style));
            }
            lines.add(new ArrayList<>(cur));
            soft.add(softEnd);
        }
        cur.clear();
        curLen[0] = 0;
    }

    private static IChatComponent build(List<Piece> line, boolean mod) {
        IChatComponent root = new ChatComponentText("");
        for (Piece p : line) {
            if (p.link != null) {
                root.appendSibling((mod ? p.link.mod : p.link.vanilla).createCopy());
            } else if (!p.text.isEmpty()) {
                IChatComponent c = new ChatComponentText(p.text);
                c.setChatStyle(p.style.createShallowCopy());
                root.appendSibling(c);
            }
        }
        return root;
    }

    private static String stripLeading(String s) {
        int i = 0;
        while (i < s.length() && s.charAt(i) == ' ') i++;
        return s.substring(i);
    }

    private static String rtrim(String s) {
        int end = s.length();
        while (end > 0 && s.charAt(end - 1) == ' ') end--;
        return s.substring(0, end);
    }
}
