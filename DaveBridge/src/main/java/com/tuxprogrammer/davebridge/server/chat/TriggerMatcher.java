package com.tuxprogrammer.davebridge.server.chat;

/** Decides whether a chat line addresses Dave. Pure logic, unit-tested. */
public final class TriggerMatcher {

    private TriggerMatcher() {}

    /**
     * If {@code message} starts with one of {@code prefixes} (case-insensitive, ignoring leading whitespace), returns
     * the rest of the message with the prefix and any following separator ({@code , :}) removed. Otherwise null.
     * <p>
     * A prefix that ends in a letter or digit must be followed by a non-word character, so {@code "@dave"} matches
     * {@code "@dave hi"} and {@code "@dave"} but not {@code "@davey hi"}.
     */
    public static String match(String message, String[] prefixes) {
        if (message == null || prefixes == null) {
            return null;
        }
        String trimmed = message.trim();
        for (String raw : prefixes) {
            if (raw == null) {
                continue;
            }
            String prefix = raw.trim();
            if (prefix.isEmpty() || !trimmed.regionMatches(true, 0, prefix, 0, prefix.length())) {
                continue;
            }
            if (trimmed.length() > prefix.length() && isWordChar(prefix.charAt(prefix.length() - 1))
                && isWordChar(trimmed.charAt(prefix.length()))) {
                continue;
            }
            String rest = trimmed.substring(prefix.length());
            int i = 0;
            while (i < rest.length()
                && (rest.charAt(i) == ',' || rest.charAt(i) == ':' || Character.isWhitespace(rest.charAt(i)))) {
                i++;
            }
            return rest.substring(i);
        }
        return null;
    }

    private static boolean isWordChar(char c) {
        return Character.isLetterOrDigit(c) || c == '_';
    }
}
