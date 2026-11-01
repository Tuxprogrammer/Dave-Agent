package com.tuxprogrammer.davebridge.server.chat.markup;

/**
 * Pixel widths of text in the default Minecraft font, as the client's FontRenderer.getStringWidth measures them: each
 * glyph's width plus one pixel of spacing, one more when bold. The server has no font, so this is a table of the
 * default ascii.png glyphs; anything else counts as a full-width 6. Used to cut Dave's replies into lines that fit the
 * chat box, so the client never has to wrap (and cut words in two).
 */
public final class FontWidths {

    private FontWidths() {}

    /** Advance (glyph + 1) of printable ASCII 32..126; other characters use {@link #OTHER}. */
    private static final int[] ASCII = new int[127];
    public static final int OTHER = 6;

    static {
        for (int c = 32; c < 127; c++) ASCII[c] = 6;
        // Measured from 1.7.10's assets/minecraft/textures/font/ascii.png the way FontRenderer.readFontTexture does.
        set(" I[]t", 4);
        set("!,.:;i|", 2);
        set("'`l", 3);
        set("\"()*<>fk{}", 5);
        set("@~", 7);
    }

    private static void set(String chars, int advance) {
        for (int i = 0; i < chars.length(); i++) ASCII[chars.charAt(i)] = advance;
    }

    public static int width(char c, boolean bold) {
        int w = c < ASCII.length && ASCII[c] > 0 ? ASCII[c] : OTHER;
        return bold ? w + 1 : w;
    }

    public static int width(String s, boolean bold) {
        int w = 0;
        for (int i = 0; i < s.length(); i++) w += width(s.charAt(i), bold);
        return w;
    }

    /** How many leading characters of {@code s} fit in {@code pixels}. */
    public static int fit(String s, boolean bold, int pixels) {
        int w = 0;
        for (int i = 0; i < s.length(); i++) {
            w += width(s.charAt(i), bold);
            if (w > pixels) return i;
        }
        return s.length();
    }
}
