package com.tuxprogrammer.davebridge.server.chat.markup;

import java.util.ArrayList;
import java.util.List;

import net.minecraft.util.ChatComponentText;
import net.minecraft.util.ChatStyle;
import net.minecraft.util.EnumChatFormatting;
import net.minecraft.util.IChatComponent;

/**
 * Lays parsed markup out into chat lines. Resolves tokens once, then builds two variants of every line: one for
 * players with the DaveBridge client half and one for everyone else. Lines carry no prefix; the caller adds
 * {@code <Dave>} or the whisper prefix.
 * <p>
 * Wrapping happens here, not on the client: vanilla chat wraps one styled piece at a time and cuts a piece with no
 * space in it mid-word. Lines are measured in pixels of the default font ({@link FontWidths}) and broken only at
 * spaces, so a word that runs across several colors ("45s" then ")") moves to the next line whole. A line Dave
 * started gets the caller's {@code <Dave>} prefix; a continuation line is marked {@code continued} and indented with
 * {@link #INDENT} instead. A token's component is never split, and an exclusive token (a BetterQuesting quest link)
 * never shares a line with another link. Only a word wider than a whole line is cut.
 */
public final class MarkupRenderer {

    public static final String TRUNCATED = "... (truncated)";

    /** What the caller puts before a continuation line instead of the {@code <Dave>} prefix. */
    public static final String INDENT = "  ";

    /**
     * Rendering output. {@code modLines}, {@code vanillaLines} and {@code continued} have the same length; a continued
     * line carries on the line before it (indent it, no prefix).
     */
    public static final class Rendered {

        public final List<IChatComponent> modLines;
        public final List<IChatComponent> vanillaLines;
        public final List<ResolvedLink.RecipientAction> actions;
        public final List<String> warnings;
        public final List<Boolean> continued;

        public Rendered(List<IChatComponent> modLines, List<IChatComponent> vanillaLines,
            List<ResolvedLink.RecipientAction> actions, List<String> warnings) {
            this(modLines, vanillaLines, actions, warnings, null);
        }

        public Rendered(List<IChatComponent> modLines, List<IChatComponent> vanillaLines,
            List<ResolvedLink.RecipientAction> actions, List<String> warnings, List<Boolean> continued) {
            this.modLines = modLines;
            this.vanillaLines = vanillaLines;
            this.actions = actions;
            this.warnings = warnings;
            if (continued == null) {
                continued = new ArrayList<>();
                for (int i = 0; i < vanillaLines.size(); i++) continued.add(Boolean.FALSE);
            }
            this.continued = continued;
        }
    }

    private final LinkResolver resolver;
    private final int firstWidth;
    private final int nextWidth;
    private final int maxLines;

    /**
     * @param firstWidth pixels for a line Dave started, after the prefix the caller adds
     * @param nextWidth  pixels for a continuation line, after {@link #INDENT}
     * @param maxLines   lines kept before the message is cut with {@link #TRUNCATED}
     */
    public MarkupRenderer(LinkResolver resolver, int firstWidth, int nextWidth, int maxLines) {
        this.resolver = resolver;
        this.firstWidth = Math.max(60, firstWidth);
        this.nextWidth = Math.max(60, nextWidth);
        this.maxLines = Math.max(1, maxLines);
    }

    /**
     * The longest markup {@link #render} parses (one markup character per pixel of allowed output, several per
     * visible character); the rest is dropped with a warning: nothing past it could be shown, and the parser and
     * wrapper slow down on huge single lines.
     */
    int maxMarkupLength() {
        return maxLines * nextWidth;
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
                if (t.style.color != null) {
                    pieces.add(Piece.text(t.text, ChatStyles.apply(t.style, null)));
                } else {
                    // Text Dave left uncolored gets the automatic highlights (tiers, numbers).
                    for (Highlights.Span span : Highlights.split(t.text)) {
                        pieces.add(Piece.text(span.text, ChatStyles.apply(t.style, highlight(span.style))));
                    }
                }
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
                    // unresolved: keep the readable part as plain styled text; an item or fluid still reads as one
                    pieces.add(Piece.text(token.labelOrArg(), ChatStyles.apply(token.style, unresolvedBase(token))));
                } else {
                    pieces.add(Piece.atom(link));
                    actions.addAll(link.actions);
                }
            }
        }

        List<Line> lines = layout(pieces);
        if (lines.size() > maxLines) {
            warnings.add("message cut to " + maxLines + " lines");
            lines = new ArrayList<>(lines.subList(0, maxLines - 1));
            Line cut = new Line(true);
            cut.add(Piece.text(TRUNCATED, new ChatStyle().setColor(EnumChatFormatting.GRAY)));
            lines.add(cut);
        }
        List<IChatComponent> mod = new ArrayList<>();
        List<IChatComponent> vanilla = new ArrayList<>();
        List<Boolean> continued = new ArrayList<>();
        for (Line line : lines) {
            mod.add(build(line.pieces, true));
            vanilla.add(build(line.pieces, false));
            continued.add(line.continued);
        }
        return new Rendered(mod, vanilla, actions, warnings, continued);
    }

    /** Item and fluid links that did not resolve keep the item green, so the name still stands out. */
    static ChatStyle unresolvedBase(Markup.Token token) {
        switch (token.kind) {
            case "item":
            case "fluid":
            case "recipe":
            case "uses":
                return highlight(new String[] { Markup.NAME_COLORS.get("i") });
            default:
                return null;
        }
    }

    /** The base style of a highlight span: a color name, then "b" / "u" flags; null for none. */
    static ChatStyle highlight(String[] style) {
        if (style == null) return null;
        ChatStyle out = new ChatStyle().setColor(EnumChatFormatting.getValueByName(style[0]));
        for (int i = 1; i < style.length; i++) {
            if ("b".equals(style[i])) out.setBold(Boolean.TRUE);
            if ("u".equals(style[i])) out.setUnderlined(Boolean.TRUE);
        }
        return out;
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

        static final Piece NEWLINE = new Piece(null, null, null, 0);

        final String text; // non-null for splittable text
        final ChatStyle style;
        final ResolvedLink link; // non-null for atoms
        final int width; // pixels

        private Piece(String text, ChatStyle style, ResolvedLink link, int width) {
            this.text = text;
            this.style = style;
            this.link = link;
            this.width = width;
        }

        static Piece text(String text, ChatStyle style) {
            return new Piece(text, style, null, FontWidths.width(text, bold(style)));
        }

        /**
         * An exclusive (quest) link counts as zero width: the BQ client rewrites its whole line into one component
         * ("[Quest: #id - name]" plus the text around it), which the client then wraps at spaces itself.
         */
        static Piece atom(ResolvedLink link) {
            return new Piece(
                null,
                null,
                link,
                link.ownLine ? 0 : Math.max(pixelWidth(link.vanilla), pixelWidth(link.mod)));
        }

        boolean isNewline() {
            return this == NEWLINE;
        }
    }

    private static boolean bold(ChatStyle style) {
        return style != null && style.getBold();
    }

    /** Pixel width of a component as the client draws it (each part in its own boldness). */
    static int pixelWidth(IChatComponent c) {
        try {
            int w = 0;
            for (Object o : c) {
                IChatComponent part = (IChatComponent) o;
                w += FontWidths.width(part.getUnformattedTextForChat(), bold(part.getChatStyle()));
            }
            return w;
        } catch (RuntimeException e) {
            return 60;
        }
    }

    /** One output line: pieces and the pixels they use. */
    private static final class Line {

        final boolean continued;
        final List<Piece> pieces = new ArrayList<>();
        int used;

        Line(boolean continued) {
            this.continued = continued;
        }

        void add(Piece p) {
            pieces.add(p);
            used += p.width;
        }

        boolean isEmpty() {
            return pieces.isEmpty();
        }

        boolean hasLink(boolean exclusiveOnly) {
            for (Piece p : pieces) {
                if (p.link != null && (!exclusiveOnly || p.link.ownLine)) return true;
            }
            return false;
        }
    }

    private int cap(Line line) {
        return line.continued ? nextWidth : firstWidth;
    }

    /**
     * Lays pieces into lines. Words (runs without spaces, possibly across styles and links) are placed whole with the
     * spaces before them; a word that does not fit starts a continuation line, and the spaces before it are dropped.
     */
    private List<Line> layout(List<Piece> pieces) {
        List<Line> lines = new ArrayList<>();
        Line line = new Line(false);
        List<Piece> spaces = new ArrayList<>();
        List<Piece> word = new ArrayList<>();
        for (Piece p : pieces) {
            if (p.isNewline()) {
                line = place(lines, line, spaces, word);
                finish(lines, line);
                line = new Line(false);
                spaces.clear();
                word.clear();
            } else if (p.link != null) {
                word.add(p);
            } else {
                String t = p.text;
                int i = 0;
                while (i < t.length()) {
                    boolean space = t.charAt(i) == ' ';
                    int k = i;
                    while (k < t.length() && (t.charAt(k) == ' ') == space) k++;
                    Piece run = Piece.text(t.substring(i, k), p.style);
                    if (space) {
                        if (!word.isEmpty()) {
                            line = place(lines, line, spaces, word);
                            spaces.clear();
                            word.clear();
                        }
                        spaces.add(run);
                    } else {
                        word.add(run);
                    }
                    i = k;
                }
            }
        }
        line = place(lines, line, spaces, word);
        finish(lines, line);
        return lines;
    }

    /** Places one word (and the spaces before it); returns the line that is now current. */
    private Line place(List<Line> lines, Line line, List<Piece> spaces, List<Piece> word) {
        if (word.isEmpty()) {
            return line; // trailing spaces
        }
        int spaceWidth = 0, wordWidth = 0;
        boolean wordLink = false, wordExclusive = false;
        for (Piece p : spaces) spaceWidth += p.width;
        for (Piece p : word) {
            wordWidth += p.width;
            if (p.link != null) {
                wordLink = true;
                wordExclusive |= p.link.ownLine;
            }
        }
        // An exclusive link (quest) may share its line with text, but not with other links: the BQ client replaces
        // the whole line, which would drop their clicks and hovers.
        boolean clash = wordExclusive ? line.hasLink(false) : wordLink && line.hasLink(true);
        if (!line.isEmpty() && (clash || line.used + spaceWidth + wordWidth > cap(line))) {
            finish(lines, line);
            line = new Line(true);
        } else if (!line.isEmpty()) {
            for (Piece p : spaces) line.add(p);
        }
        if (line.used + wordWidth <= cap(line)) {
            for (Piece p : word) line.add(p);
            return line;
        }
        // Wider than a whole line: cut it where lines end (links stay whole).
        for (Piece p : word) {
            if (p.link != null) {
                if (!line.isEmpty() && line.used + p.width > cap(line)) {
                    finish(lines, line);
                    line = new Line(true);
                }
                line.add(p);
                continue;
            }
            String rest = p.text;
            boolean bold = bold(p.style);
            while (!rest.isEmpty()) {
                int n = FontWidths.fit(rest, bold, cap(line) - line.used);
                if (n == 0 && line.isEmpty()) n = 1; // always make progress
                if (n > 0) {
                    line.add(Piece.text(rest.substring(0, n), p.style));
                    rest = rest.substring(n);
                }
                if (!rest.isEmpty()) {
                    finish(lines, line);
                    line = new Line(true);
                }
            }
        }
        return line;
    }

    /** Adds the line unless it has nothing visible. */
    private static void finish(List<Line> lines, Line line) {
        for (Piece p : line.pieces) {
            if (p.link != null || !p.text.trim()
                .isEmpty()) {
                lines.add(line);
                return;
            }
        }
    }

    /** One component per run of same-styled text (layout splits words apart; this joins them back), plus links. */
    private static IChatComponent build(List<Piece> line, boolean mod) {
        IChatComponent root = new ChatComponentText("");
        StringBuilder text = new StringBuilder();
        ChatStyle style = null;
        for (Piece p : line) {
            if (p.link == null && style != null && p.style.equals(style)) {
                text.append(p.text);
                continue;
            }
            appendText(root, text, style);
            style = null;
            if (p.link != null) {
                root.appendSibling((mod ? p.link.mod : p.link.vanilla).createCopy());
            } else {
                text.append(p.text);
                style = p.style;
            }
        }
        appendText(root, text, style);
        return root;
    }

    private static void appendText(IChatComponent root, StringBuilder text, ChatStyle style) {
        if (text.length() > 0) {
            IChatComponent c = new ChatComponentText(text.toString());
            c.setChatStyle(style.createShallowCopy());
            root.appendSibling(c);
            text.setLength(0);
        }
    }
}
