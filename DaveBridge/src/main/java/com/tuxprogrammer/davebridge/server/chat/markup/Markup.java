package com.tuxprogrammer.davebridge.server.chat.markup;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * Dave's chat markup: a small, forgiving language an LLM can write reliably. Parsing is pure (no Minecraft types) so it
 * is unit-tested on its own; {@code MarkupRenderer} turns the result into chat components.
 * <p>
 * Grammar (see PROTOCOL.md "Dave markup" for the user-facing spec):
 * <ul>
 * <li>Newlines separate chat lines. {@code # Heading} lines are bold, {@code - item} / {@code * item} lines become
 * bullets.</li>
 * <li>Markdown spans inside one line: {@code **bold**}, {@code *italic*}, {@code __underline__}, {@code ~~strike~~},
 * {@code `code`}. A delimiter only counts when it has a partner later on the same line.</li>
 * <li>Tag spans: {@code {gold}...{/gold}}, {@code {b}}, {@code {i}}, {@code {u}}, {@code {s}}, {@code {obf}},
 * {@code {color:red}}; {@code {/}} closes the innermost span. Tag spans may cross lines.</li>
 * <li>Tokens: {@code {kind:argument|label}}, kinds in {@link #TOKEN_KINDS}. The label is optional and split off at the
 * last unescaped {@code |}. {@code {hover:text|label}} text may itself hold one level of tags and tokens; it is kept
 * raw and parsed again with {@link #parseHoverText}, where {@code \n} is a line break.</li>
 * <li>{@code \} escapes the next character ({@code \n} in other token arguments and labels is a space). Anything not
 * understood stays literal text and adds a warning.</li>
 * </ul>
 */
public final class Markup {

    /** Token kinds the renderer understands. */
    public static final Set<String> TOKEN_KINDS = Collections.unmodifiableSet(
        new HashSet<>(
            Arrays.asList(
                "item",
                "recipe",
                "uses",
                "fluid",
                "chain",
                "quest",
                "url",
                "link",
                "cmd",
                "suggest",
                "send",
                "hover",
                "player",
                "waypoint",
                "guide")));

    /** Minecraft color names (and a few aliases) accepted as tag names. Values are vanilla color names. */
    public static final Map<String, String> COLORS;

    static {
        Map<String, String> c = new HashMap<>();
        for (String name : new String[] { "black", "dark_blue", "dark_green", "dark_aqua", "dark_red", "dark_purple",
            "gold", "gray", "dark_gray", "blue", "green", "aqua", "red", "light_purple", "yellow", "white" }) {
            c.put(name, name);
        }
        c.put("grey", "gray");
        c.put("dark_grey", "dark_gray");
        c.put("orange", "gold");
        c.put("purple", "dark_purple");
        c.put("pink", "light_purple");
        c.put("magenta", "light_purple");
        c.put("cyan", "aqua");
        c.put("lime", "green");
        COLORS = Collections.unmodifiableMap(c);
    }

    private Markup() {}

    // ------------------------------------------------------------------ model

    /** Text style. Immutable; {@code color} is a vanilla color name or null. */
    public static final class Style {

        public static final Style PLAIN = new Style(null, false, false, false, false, false);

        public final String color;
        public final boolean bold, italic, underline, strike, obfuscated;

        Style(String color, boolean bold, boolean italic, boolean underline, boolean strike, boolean obfuscated) {
            this.color = color;
            this.bold = bold;
            this.italic = italic;
            this.underline = underline;
            this.strike = strike;
            this.obfuscated = obfuscated;
        }

        Style with(String flag) {
            switch (flag) {
                case "b":
                    return new Style(color, true, italic, underline, strike, obfuscated);
                case "i":
                    return new Style(color, bold, true, underline, strike, obfuscated);
                case "u":
                    return new Style(color, bold, italic, true, strike, obfuscated);
                case "s":
                    return new Style(color, bold, italic, underline, true, obfuscated);
                case "obf":
                    return new Style(color, bold, italic, underline, strike, true);
                default:
                    return new Style(flag, bold, italic, underline, strike, obfuscated);
            }
        }

        public boolean isPlain() {
            return color == null && !bold && !italic && !underline && !strike && !obfuscated;
        }

        @Override
        public boolean equals(Object o) {
            if (!(o instanceof Style)) return false;
            Style s = (Style) o;
            return bold == s.bold && italic == s.italic
                && underline == s.underline
                && strike == s.strike
                && obfuscated == s.obfuscated
                && (color == null ? s.color == null : color.equals(s.color));
        }

        @Override
        public int hashCode() {
            return (color == null ? 0 : color.hashCode()) * 31 + (bold ? 1 : 0)
                + (italic ? 2 : 0)
                + (underline ? 4 : 0)
                + (strike ? 8 : 0)
                + (obfuscated ? 16 : 0);
        }

        @Override
        public String toString() {
            StringBuilder sb = new StringBuilder("Style[");
            if (color != null) sb.append(color);
            if (bold) sb.append(" b");
            if (italic) sb.append(" i");
            if (underline) sb.append(" u");
            if (strike) sb.append(" s");
            if (obfuscated) sb.append(" obf");
            return sb.append(']')
                .toString();
        }
    }

    /** A parsed element. */
    public interface Node {
    }

    /** A run of literal text. */
    public static final class Text implements Node {

        public final String text;
        public final Style style;

        Text(String text, Style style) {
            this.text = text;
            this.style = style;
        }

        @Override
        public String toString() {
            return "Text(" + text + ", " + style + ")";
        }
    }

    /** A {@code {kind:arg|label}} token. {@code label} is null when absent. */
    public static final class Token implements Node {

        public final String kind;
        public final String arg;
        public final String label;
        public final Style style;
        /** The token as written, for warnings and plain-text fallback. */
        public final String raw;

        Token(String kind, String arg, String label, Style style, String raw) {
            this.kind = kind;
            this.arg = arg;
            this.label = label;
            this.style = style;
            this.raw = raw;
        }

        /** The label if given, otherwise the argument. */
        public String labelOrArg() {
            return label != null && !label.isEmpty() ? label : arg;
        }

        @Override
        public String toString() {
            return "Token(" + kind + ":" + arg + (label == null ? "" : "|" + label) + ", " + style + ")";
        }
    }

    /** A line break. */
    public static final class Newline implements Node {

        static final Newline INSTANCE = new Newline();

        @Override
        public String toString() {
            return "Newline";
        }
    }

    /** Parse output: nodes in order, plus warnings about anything that was not understood. */
    public static final class Result {

        public final List<Node> nodes;
        public final List<String> warnings;

        Result(List<Node> nodes, List<String> warnings) {
            this.nodes = nodes;
            this.warnings = warnings;
        }
    }

    // ------------------------------------------------------------------ parser

    public static Result parse(String markup) {
        return new Parser(markup == null ? "" : markup, false).run();
    }

    /** Parses the text of a {@code {hover:text|label}} token: like {@link #parse}, but {@code \n} is a line break. */
    public static Result parseHoverText(String text) {
        return new Parser(text == null ? "" : text, true).run();
    }

    private static final class Parser {

        private final String src;
        /** Hover text: {@code \n} is a line break. */
        private final boolean hoverText;
        private final List<Node> nodes = new ArrayList<>();
        private final List<String> warnings = new ArrayList<>();
        /** Open tag spans: names like "gold", "b", "i". Survive line breaks. */
        private final List<String> tags = new ArrayList<>();
        /** Open markdown delimiters on the current line. */
        private final List<String> md = new ArrayList<>();
        private boolean headingLine;
        private final StringBuilder buf = new StringBuilder();
        private Style bufStyle = Style.PLAIN;

        Parser(String src, boolean hoverText) {
            this.src = src.replace("\r\n", "\n")
                .replace('\r', '\n');
            this.hoverText = hoverText;
        }

        Result run() {
            String[] lines = src.split("\n", -1);
            for (int n = 0; n < lines.length; n++) {
                if (n > 0) {
                    flush();
                    nodes.add(Newline.INSTANCE);
                }
                parseLine(lines[n]);
                flush();
                md.clear();
                headingLine = false;
            }
            if (!tags.isEmpty()) {
                warnings.add("unclosed tag(s) " + tags + " closed at end of message");
            }
            return new Result(nodes, warnings);
        }

        private Style style() {
            Style s = headingLine ? Style.PLAIN.with("b") : Style.PLAIN;
            for (String t : tags) s = s.with(t);
            for (String m : md) s = s.with(m);
            return s;
        }

        private void emit(char c) {
            Style s = style();
            if (!s.equals(bufStyle)) {
                flush();
                bufStyle = s;
            }
            buf.append(c);
        }

        private void emit(String str) {
            for (int i = 0; i < str.length(); i++) emit(str.charAt(i));
        }

        private void flush() {
            if (buf.length() > 0) {
                nodes.add(new Text(buf.toString(), bufStyle));
                buf.setLength(0);
            }
        }

        private void parseLine(String line) {
            int i = 0;
            // leading structure: headings and bullets
            int lead = 0;
            while (lead < line.length() && line.charAt(lead) == ' ') lead++;
            String rest = line.substring(lead);
            if (rest.matches("#{1,6} .*")) {
                headingLine = true;
                i = lead + rest.indexOf(' ') + 1;
            } else if (rest.startsWith("- ") || rest.startsWith("* ") || rest.startsWith("+ ")) {
                emit(line.substring(0, lead));
                emit("• ");
                i = lead + 2;
            }

            while (i < line.length()) {
                char c = line.charAt(i);
                if (c == '\\' && i + 1 < line.length()) {
                    if (hoverText && line.charAt(i + 1) == 'n') {
                        flush();
                        nodes.add(Newline.INSTANCE);
                    } else {
                        emit(line.charAt(i + 1));
                    }
                    i += 2;
                    continue;
                }
                if (c == '{') {
                    int close = findClose(line, i + 1);
                    if (close < 0) {
                        warnings.add("unmatched '{' at \"" + snippet(line, i) + "\"");
                        emit(c);
                        i++;
                        continue;
                    }
                    handleBrace(line.substring(i + 1, close), line.substring(i, close + 1));
                    i = close + 1;
                    continue;
                }
                if (c == '`') {
                    int end = line.indexOf('`', i + 1);
                    if (end > i + 1) {
                        flush();
                        String saved = tagsSnapshotPushCode();
                        emit(line.substring(i + 1, end));
                        restoreCode(saved);
                        i = end + 1;
                        continue;
                    }
                }
                String delim = delimiterAt(line, i);
                if (delim != null) {
                    String key = mdKey(delim);
                    if (md.contains(key)) {
                        if (i > 0 && line.charAt(i - 1) != ' ') {
                            md.remove(key);
                            i += delim.length();
                            continue;
                        }
                    } else if (i + delim.length() < line.length() && line.charAt(i + delim.length()) != ' '
                        && hasCloser(line, i + delim.length(), delim)) {
                            md.add(key);
                            i += delim.length();
                            continue;
                        }
                }
                emit(c);
                i++;
            }
        }

        // `code` renders gray; implemented as a temporary tag so it combines with outer styles
        private String tagsSnapshotPushCode() {
            tags.add("gray");
            return "gray";
        }

        private void restoreCode(String tag) {
            int idx = tags.lastIndexOf(tag);
            if (idx >= 0) tags.remove(idx);
        }

        private static String delimiterAt(String line, int i) {
            if (line.startsWith("**", i)) return "**";
            if (line.startsWith("__", i)) return "__";
            if (line.startsWith("~~", i)) return "~~";
            if (line.charAt(i) == '*') return "*";
            return null;
        }

        private static String mdKey(String delim) {
            switch (delim) {
                case "**":
                    return "b";
                case "__":
                    return "u";
                case "~~":
                    return "s";
                default:
                    return "i";
            }
        }

        /** A closing delimiter exists later on the line, preceded by a non-space, outside escapes. */
        private static boolean hasCloser(String line, int from, String delim) {
            int j = from;
            while (j < line.length()) {
                char c = line.charAt(j);
                if (c == '\\') {
                    j += 2;
                    continue;
                }
                if (c == '{') {
                    // a delimiter inside a later {token} (e.g. a chain's *amount) is not a closer
                    int close = findClose(line, j + 1);
                    if (close >= 0) {
                        j = close + 1;
                        continue;
                    }
                }
                if (line.startsWith(delim, j) && line.charAt(j - 1) != ' ') {
                    // a lone '*' must not be half of a '**'
                    if (delim.equals("*") && line.startsWith("**", j)) {
                        j += 2;
                        continue;
                    }
                    return true;
                }
                j++;
            }
            return false;
        }

        /**
         * Index of the {@code }} that closes the brace opened just before {@code from}, or -1. Braces do not nest,
         * except one level inside {@code {hover:...}} (styles and tokens in hover text).
         */
        private static int findClose(String line, int from) {
            int start = from;
            while (start < line.length() && line.charAt(start) == ' ') start++;
            boolean hover = line.regionMatches(true, start, "hover:", 0, 6);
            int depth = 0;
            for (int j = from; j < line.length(); j++) {
                char c = line.charAt(j);
                if (c == '\\') {
                    j++;
                } else if (c == '}') {
                    if (depth == 0) return j;
                    depth--;
                } else if (c == '{') {
                    if (!hover || depth > 0) return -1;
                    depth++;
                }
            }
            return -1;
        }

        private void handleBrace(String inner, String raw) {
            String trimmed = inner.trim();
            String lower = trimmed.toLowerCase(Locale.ROOT);

            if (lower.startsWith("/")) {
                closeTag(
                    lower.substring(1)
                        .trim(),
                    raw);
                return;
            }
            if (lower.equals("br")) {
                flush();
                nodes.add(Newline.INSTANCE);
                return;
            }
            int colon = trimmed.indexOf(':');
            if (colon > 0) {
                String kind = lower.substring(0, colon)
                    .trim();
                String body = trimmed.substring(colon + 1);
                if (kind.equals("color") || kind.equals("colour")) {
                    String color = COLORS.get(
                        body.trim()
                            .toLowerCase(Locale.ROOT));
                    if (color != null) {
                        tags.add(color);
                        return;
                    }
                    warnings.add("unknown color in " + raw);
                    emit(raw);
                    return;
                }
                if (TOKEN_KINDS.contains(kind)) {
                    flush();
                    int bar = lastUnescaped(body, '|');
                    String argText = bar < 0 ? body : body.substring(0, bar);
                    // hover text stays raw: parseHoverText handles its escapes, tags and line breaks
                    String arg = (kind.equals("hover") ? argText : unescape(argText)).trim();
                    String label = bar < 0 ? null : unescape(body.substring(bar + 1)).trim();
                    if (arg.isEmpty()) {
                        warnings.add("empty argument in " + raw);
                        emit(label != null ? label : raw);
                        return;
                    }
                    nodes.add(new Token(kind.equals("link") ? "url" : kind, arg, label, style(), raw));
                    bufStyle = null; // force a fresh Text node after the token
                    return;
                }
                warnings.add("unknown token " + raw + " (kept as text)");
                emit(raw);
                return;
            }
            String tag = normalizeTag(lower);
            if (tag != null && !tag.isEmpty()) {
                tags.add(tag);
                return;
            }
            warnings.add("unknown tag " + raw + " (kept as text)");
            emit(raw);
        }

        /** {@code {/}}, {@code {/name}}, {@code {/color}} or {@code {/color:name}}; anything else stays literal. */
        private void closeTag(String name, String raw) {
            int idx;
            if (name.isEmpty()) {
                idx = tags.size() - 1;
            } else if (name.equals("color") || name.equals("colour")) {
                idx = -1;
                for (int j = tags.size() - 1; j >= 0 && idx < 0; j--) {
                    if (COLORS.containsValue(tags.get(j))) idx = j;
                }
            } else {
                String tag = name.startsWith("color:") || name.startsWith("colour:") ? COLORS.get(
                    name.substring(name.indexOf(':') + 1)
                        .trim())
                    : normalizeTag(name);
                if (tag == null) {
                    warnings.add("unknown closing tag " + raw + " (kept as text)");
                    emit(raw);
                    return;
                }
                idx = tags.lastIndexOf(tag);
            }
            if (idx < 0) {
                warnings.add("stray " + raw + " (kept as text)");
                emit(raw);
                return;
            }
            // close it and anything opened after it
            while (tags.size() > idx) tags.remove(tags.size() - 1);
        }

        /** Maps a tag name to a style key ("b", "i", ... or a color), "" for {/}, null if unknown. */
        private static String normalizeTag(String name) {
            switch (name) {
                case "":
                    return "";
                case "b":
                case "bold":
                    return "b";
                case "i":
                case "italic":
                case "em":
                    return "i";
                case "u":
                case "underline":
                    return "u";
                case "s":
                case "strike":
                case "strikethrough":
                    return "s";
                case "obf":
                case "obfuscated":
                case "magic":
                    return "obf";
                default:
                    return COLORS.get(name);
            }
        }

        /** Last unescaped {@code target} outside nested braces (hover text may hold tokens with their own labels). */
        private static int lastUnescaped(String s, char target) {
            int found = -1;
            int depth = 0;
            for (int j = 0; j < s.length(); j++) {
                char c = s.charAt(j);
                if (c == '\\') {
                    j++;
                } else if (c == '{') {
                    depth++;
                } else if (c == '}') {
                    if (depth > 0) depth--;
                } else if (c == target && depth == 0) {
                    found = j;
                }
            }
            return found;
        }

        private static String unescape(String s) {
            StringBuilder sb = new StringBuilder(s.length());
            for (int j = 0; j < s.length(); j++) {
                char c = s.charAt(j);
                if (c == '\\' && j + 1 < s.length()) {
                    char next = s.charAt(++j);
                    sb.append(next == 'n' ? ' ' : next); // \n is a line break only in hover text; a space here
                } else {
                    sb.append(c);
                }
            }
            return sb.toString();
        }

        private static String snippet(String line, int at) {
            return line.substring(at, Math.min(line.length(), at + 24));
        }
    }
}
