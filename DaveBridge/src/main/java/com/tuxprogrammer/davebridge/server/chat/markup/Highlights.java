package com.tuxprogrammer.davebridge.server.chat.markup;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Automatic highlights for Dave's plain (uncolored) text, so a reply can be skimmed: voltage tiers in GregTech's own
 * tier colors and numbers with their units in yellow. Pure logic; {@link MarkupRenderer} turns the spans into styles.
 */
public final class Highlights {

    private Highlights() {}

    /** Voltage tier names, by tier (GTValues.VN without MAX+). */
    static final String[] TIERS = { "ULV", "LV", "MV", "HV", "EV", "IV", "LuV", "ZPM", "UV", "UHV", "UEV", "UIV", "UMV",
        "UXV", "MAX" };

    /**
     * Each tier's style as in GT tooltips: a color name, then "b" / "u" flags.
     */
    // Source:
    // https://github.com/GTNewHorizons/GT5-Unofficial/blob/5.09.54.265/src/main/java/gregtech/api/enums/GTValues.java
    // (TIER_COLORS)
    static final String[][] TIER_STYLES = { { "red" }, { "dark_green" }, { "gold" }, { "yellow" }, { "dark_gray" },
        { "blue" }, { "light_purple" }, { "aqua" }, { "dark_green", "u" }, { "dark_red", "u" }, { "dark_purple", "u" },
        { "dark_blue", "b", "u" }, { "red", "b", "u" }, { "dark_red", "b", "u" }, { "white", "b", "u" } };

    /** Style of a number with its unit. */
    static final String[] NUMBER_STYLE = { "yellow" };

    private static final String WORD = "\\p{L}\\p{N}_";
    private static final String NUMBER = "(?:-?\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?|-?\\d+(?:\\.\\d+)?)";
    private static final String UNIT = "(?:EU/t|EU|RF|mB|kL|L|A|ticks?|sec|s|min|h|t|x|%|K|\u00b0C|/s|/min|/h)";

    private static final Pattern PATTERN = Pattern.compile(
        "(?<![" + WORD
            + ".,])"
            + "(?:(?<tier>ULV|LV|MV|HV|EV|IV|LuV|ZPM|UV|UHV|UEV|UIV|UMV|UXV|MAX)"
            + "|(?<num>x\\d+|"
            + NUMBER
            + "(?:[-\u2013]\\d+(?:\\.\\d+)?)?(?:\\s?[kMG])?(?:\\s?"
            + UNIT
            + ")?))"
            + "(?!["
            + WORD
            + "]|\\.\\d)");

    /** A run of text and its highlight style (null: unhighlighted). */
    public static final class Span {

        public final String text;
        public final String[] style;

        Span(String text, String[] style) {
            this.text = text;
            this.style = style;
        }

        @Override
        public String toString() {
            return style == null ? text : "[" + text + "|" + String.join(" ", style) + "]";
        }
    }

    /** Splits {@code text} into highlighted and plain spans; concatenated, they give back {@code text}. */
    public static List<Span> split(String text) {
        List<Span> out = new ArrayList<>();
        Matcher m = PATTERN.matcher(text);
        int at = 0;
        while (m.find()) {
            if (m.start() > at) out.add(new Span(text.substring(at, m.start()), null));
            String tier = m.group("tier");
            out.add(new Span(m.group(), tier != null ? TIER_STYLES[indexOf(tier)] : NUMBER_STYLE));
            at = m.end();
        }
        if (at < text.length()) out.add(new Span(text.substring(at), null));
        return out;
    }

    private static int indexOf(String tier) {
        for (int i = 0; i < TIERS.length; i++) {
            if (TIERS[i].equals(tier)) return i;
        }
        throw new IllegalArgumentException(tier);
    }
}
