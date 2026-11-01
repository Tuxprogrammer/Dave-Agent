package com.tuxprogrammer.davebridge.server.chat;

import java.util.ArrayList;
import java.util.List;

/** Turns agent text into chat-sized lines. Pure logic, unit-tested. */
public final class ChatText {

    public static final String TRUNCATED = "... (truncated)";

    private ChatText() {}

    /**
     * Splits {@code text} on newlines, drops blank lines, wraps lines longer than {@code maxLength} (at a space when
     * possible) and keeps at most {@code maxLines} lines, replacing the last with {@link #TRUNCATED} when cut.
     * Control characters other than newlines become spaces.
     */
    public static List<String> toLines(String text, int maxLength, int maxLines) {
        return toLines(text, maxLength, maxLines, null);
    }

    /** As {@link #toLines(String, int, int)}, adding a warning to {@code warnings} (if not null) when lines are cut. */
    public static List<String> toLines(String text, int maxLength, int maxLines, List<String> warnings) {
        List<String> out = new ArrayList<>();
        if (text == null) {
            return out;
        }
        maxLength = Math.max(1, maxLength);
        maxLines = Math.max(1, maxLines);
        String normalized = sanitize(
            text.replace("\r\n", "\n")
                .replace('\r', '\n'));
        for (String line : normalized.split("\n", -1)) {
            String rest = rtrim(line);
            if (rest.trim()
                .isEmpty()) {
                continue;
            }
            while (rest.length() > maxLength) {
                int cut = rest.lastIndexOf(' ', maxLength);
                if (cut <= maxLength / 3) {
                    cut = maxLength; // no good break point: hard cut
                }
                out.add(rtrim(rest.substring(0, cut)));
                rest = rest.substring(cut)
                    .replaceFirst("^ +", "");
            }
            if (!rest.isEmpty()) {
                out.add(rest);
            }
        }
        if (out.size() > maxLines) {
            if (warnings != null) {
                warnings.add("message cut to " + maxLines + " lines");
            }
            List<String> cut = new ArrayList<>(out.subList(0, maxLines - 1));
            cut.add(TRUNCATED);
            return cut;
        }
        return out;
    }

    /** Replaces control characters (except newline) with spaces; tabs become four spaces. */
    public static String sanitize(String text) {
        StringBuilder sb = new StringBuilder(text.length());
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (c == '\t') {
                sb.append("    ");
            } else if (c != '\n' && (c < 0x20 || c == 0x7f)) {
                sb.append(' ');
            } else {
                sb.append(c);
            }
        }
        return sb.toString();
    }

    private static String rtrim(String s) {
        int end = s.length();
        while (end > 0 && Character.isWhitespace(s.charAt(end - 1))) {
            end--;
        }
        return s.substring(0, end);
    }
}
