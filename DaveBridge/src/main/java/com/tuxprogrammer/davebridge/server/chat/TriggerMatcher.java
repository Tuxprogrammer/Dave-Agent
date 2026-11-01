package com.tuxprogrammer.davebridge.server.chat;

/** Decides whether a chat line addresses Dave. Pure logic, unit-tested. */
public final class TriggerMatcher {

    private TriggerMatcher() {}

    /** Words a player may put before Dave's name ("hey dave, ..."); matched case-insensitively. */
    private static final String[] GREETINGS = { "hey", "hi", "hello", "hiya", "yo", "oi", "ok", "okay", "thanks",
        "thank you" };

    /**
     * Whether a plain chat line addresses Dave, and if so the question without his name. Looser than {@link #match}
     * so players who never read the docs are not silently ignored: besides a leading prefix it accepts a greeting
     * before it ({@code "hey dave, ..."}) and the name at the end ({@code "how do I make steel, dave?"}, returned as
     * {@code "how do I make steel?"}). When nothing is left after the name ({@code "thanks dave"}, {@code "dave?"}),
     * the whole line is the prompt, so Dave always has something to answer. Only for chat lines: link and command
     * checks must use {@link #match}.
     */
    public static String addressed(String message, String[] prefixes) {
        if (message == null || prefixes == null) {
            return null;
        }
        String trimmed = message.trim();
        String prompt = match(trimmed, prefixes);
        for (int i = 0; prompt == null && i < GREETINGS.length; i++) {
            String rest = afterWord(trimmed, GREETINGS[i]);
            if (rest != null) {
                prompt = match(rest, prefixes);
            }
        }
        if (prompt == null) {
            prompt = trailing(trimmed, prefixes);
        }
        if (prompt == null) {
            return null;
        }
        return prompt.matches("[\\s?!.]*") ? trimmed : prompt;
    }

    /** {@code message} with a trailing prefix (after a space or comma, before optional ?!.) removed, or null. */
    private static String trailing(String message, String[] prefixes) {
        int end = message.length();
        while (end > 0 && "?!.".indexOf(message.charAt(end - 1)) >= 0) {
            end--;
        }
        String punctuation = message.substring(end);
        for (String raw : prefixes) {
            if (raw == null) {
                continue;
            }
            String prefix = raw.trim();
            int start = end - prefix.length();
            if (prefix.isEmpty() || start <= 0 || !message.regionMatches(true, start, prefix, 0, prefix.length())) {
                continue;
            }
            char before = message.charAt(start - 1);
            if (!Character.isWhitespace(before) && before != ',') {
                continue;
            }
            int cut = start;
            while (cut > 0 && (message.charAt(cut - 1) == ',' || Character.isWhitespace(message.charAt(cut - 1)))) {
                cut--;
            }
            if (cut > 0) {
                return message.substring(0, cut) + punctuation;
            }
        }
        return null;
    }

    /** The text after {@code word} and any separators when {@code text} starts with it as a whole word, else null. */
    private static String afterWord(String text, String word) {
        if (text.length() <= word.length() || !text.regionMatches(true, 0, word, 0, word.length())
            || isWordChar(text.charAt(word.length()))) {
            return null;
        }
        return text.substring(word.length());
    }

    /**
     * If {@code message} starts with one of {@code prefixes} (case-insensitive, ignoring leading whitespace), returns
     * the rest of the message with the prefix and any following separator ({@code , :}) removed. Otherwise null.
     * <p>
     * A prefix that ends in a letter or digit must be followed by a non-word character, so {@code "dave"} matches
     * {@code "Dave how do I..."}, {@code "dave, hi"} and {@code "dave"} but not {@code "davey hi"} or
     * {@code "dave's base"} (an apostrophe counts as part of the word).
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
        return Character.isLetterOrDigit(c) || c == '_' || c == '\'' || c == '’';
    }
}
