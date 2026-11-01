package com.tuxprogrammer.davebridge.server.chat.markup;

/**
 * An item reference as Dave writes it: {@code modid:name}, {@code modid:name:meta}, {@code modid:name@meta},
 * {@code name} (minecraft namespace), {@code ore:ingotSteel} (first OreDictionary entry) or a numeric id
 * {@code 265[:meta]}. An optional {@code *count} suffix gives an amount (used by chains). Pure, unit-tested.
 */
public final class ItemRef {

    /** Registry name ("modid:name"), or null for ore/numeric refs. */
    public final String name;
    /** OreDictionary name for {@code ore:} refs, else null. */
    public final String ore;
    /** Numeric id, or -1. */
    public final int numericId;
    public final int meta;
    public final int count;

    private ItemRef(String name, String ore, int numericId, int meta, int count) {
        this.name = name;
        this.ore = ore;
        this.numericId = numericId;
        this.meta = meta;
        this.count = count;
    }

    /** Parses a reference; returns null if it is malformed. */
    public static ItemRef parse(String ref) {
        if (ref == null) return null;
        String s = ref.trim();
        int count = 1;
        int star = s.lastIndexOf('*');
        if (star > 0) {
            try {
                count = Integer.parseInt(
                    s.substring(star + 1)
                        .trim());
            } catch (NumberFormatException e) {
                return null;
            }
            if (count < 1) return null;
            s = s.substring(0, star)
                .trim();
        }
        if (s.isEmpty() || s.contains(" ")) return null;

        int meta = 0;
        int at = s.indexOf('@');
        if (at > 0) {
            try {
                meta = Integer.parseInt(s.substring(at + 1));
            } catch (NumberFormatException e) {
                return null;
            }
            s = s.substring(0, at);
        }
        String[] parts = s.split(":", -1);
        if (parts.length == 2 && parts[0].equalsIgnoreCase("ore")) {
            return parts[1].isEmpty() ? null : new ItemRef(null, parts[1], -1, 0, count);
        }
        if (parts[0].matches("\\d+")) {
            if (parts.length > 2) return null;
            int id = number(parts[0]);
            if (id < 0) return null;
            if (parts.length == 2) {
                meta = number(parts[1]);
                if (meta < 0) return null;
            }
            return new ItemRef(null, null, id, meta, count);
        }
        switch (parts.length) {
            case 1:
                return new ItemRef("minecraft:" + parts[0], null, -1, meta, count);
            case 2:
                if (parts[0].isEmpty() || parts[1].isEmpty()) return null;
                return new ItemRef(s, null, -1, meta, count);
            case 3:
                int m = number(parts[2]);
                if (m < 0 || parts[0].isEmpty() || parts[1].isEmpty()) return null;
                return new ItemRef(parts[0] + ":" + parts[1], null, -1, m, count);
            default:
                return null;
        }
    }

    /** A non-negative decimal int, or -1 if {@code s} is not one (including values too large for an int). */
    private static int number(String s) {
        if (!s.matches("\\d+")) return -1;
        try {
            return Integer.parseInt(s);
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    @Override
    public String toString() {
        String base = ore != null ? "ore:" + ore : name != null ? name : String.valueOf(numericId);
        return base + ":" + meta + (count != 1 ? "*" + count : "");
    }
}
