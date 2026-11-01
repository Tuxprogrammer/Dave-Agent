package com.tuxprogrammer.davebridge.server.compat;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

import net.minecraft.util.StatCollector;

import betterquesting.api.properties.NativeProps;
import betterquesting.api.questing.IQuest;
import betterquesting.questing.QuestDatabase;
import cpw.mods.fml.common.Loader;

/**
 * BetterQuesting's native quest share link. The BQ client rewrites any incoming chat line whose formatted text
 * contains {@code betterquesting.msg.sharequest:<24-char id>} into "[Quest: #id - name]" with a click that runs
 * {@code /bq_client show <id>} (or a "currently inaccessible" hover if the player cannot see that quest). It reads
 * the whole line's {@code getFormattedText()} and replaces the line with one text component, so a quest link must be
 * alone on its line and keeps only the formatting of the text around it.
 */
// Source:
// https://github.com/GTNewHorizons/BetterQuesting/blob/3.8.92-GTNH/src/main/java/betterquesting/handlers/EventHandler.java#L116-L176
// (onClientChatReceived), .../api/utils/UuidConverter.java (URL-safe base64 of the 16 UUID bytes, with padding = 24
// chars), .../client/gui2/GuiQuestLines.java#L681 (BQ's own share button sends exactly this token as chat),
// .../api2/utils/QuestTranslation.java (name key betterquesting.quest.<unpadded id>.name). QuestTranslation is not
// used directly because it also references the client-only I18n class.
public final class BqQuests {

    public static final String SHARE_PREFIX = "betterquesting.msg.sharequest:";

    private BqQuests() {}

    public static boolean available() {
        return Loader.isModLoaded("betterquesting");
    }

    /** A found quest: its id and server-side name. */
    public static final class Quest {

        public final UUID id;
        public final String name;
        public final int matches;

        Quest(UUID id, String name, int matches) {
            this.id = id;
            this.name = name;
            this.matches = matches;
        }

        /** The chat token the BQ client turns into a quest link. */
        public String shareToken() {
            return SHARE_PREFIX + encode(id);
        }
    }

    /**
     * Finds a quest by UUID ("0b3c...-..."), BQ's compact id (22 or 24 base64 chars), or exact name
     * (case-insensitive). Returns null if there is no such quest.
     */
    public static Quest find(String ref) {
        return find(ref, Impl.SOURCE);
    }

    /** The quest database as {@link #find(String, Source)} needs it; faked in tests. */
    interface Source {

        /** The quest's name, or null if there is no quest with that id. */
        String nameOf(UUID id);

        /** All quest ids. */
        Iterable<UUID> ids();
    }

    /**
     * An id (UUID or compact) that names an existing quest wins; otherwise the reference is matched as a name, so a
     * quest whose name merely looks like a compact id (22 letters) is still found.
     */
    static Quest find(String ref, Source source) {
        String trimmed = ref.trim();
        UUID id = parseId(trimmed);
        if (id != null) {
            String name = source.nameOf(id);
            if (name != null) return new Quest(id, name, 1);
        }
        String wanted = plain(trimmed);
        UUID firstId = null;
        String firstName = null;
        int matches = 0;
        for (UUID questId : source.ids()) {
            String n = source.nameOf(questId);
            if (n != null && plain(n).equals(wanted)) {
                matches++;
                if (firstId == null) {
                    firstId = questId;
                    firstName = n;
                }
            }
        }
        return firstId == null ? null : new Quest(firstId, firstName, matches);
    }

    /**
     * A quest name for matching: without formatting codes (GTNH titles are mostly coloured, e.g.
     * {@code §5§lNOR and NAND Chips}), trimmed, lower case.
     */
    static String plain(String name) {
        return name.replaceAll("§.", "")
            .trim()
            .toLowerCase(Locale.ROOT);
    }

    /** UUID string, or BQ's compact base64 id with or without padding; null otherwise. */
    static UUID parseId(String ref) {
        try {
            if (ref.length() == 36) return UUID.fromString(ref);
            if (ref.matches("[A-Za-z0-9_-]{22}(==)?")) {
                byte[] b = java.util.Base64.getUrlDecoder()
                    .decode(ref.length() == 22 ? ref + "==" : ref);
                long hi = 0, lo = 0;
                for (int i = 0; i < 8; i++) hi = (hi << 8) | (b[i] & 0xff);
                for (int i = 8; i < 16; i++) lo = (lo << 8) | (b[i] & 0xff);
                return new UUID(hi, lo);
            }
        } catch (IllegalArgumentException ignored) {}
        return null;
    }

    /** BQ's compact id: URL-safe base64 of the 16 UUID bytes, padded to 24 chars (UuidConverter.encodeUuid). */
    public static String encode(UUID id) {
        byte[] b = new byte[16];
        long hi = id.getMostSignificantBits(), lo = id.getLeastSignificantBits();
        for (int i = 7; i >= 0; i--) {
            b[i] = (byte) hi;
            hi >>>= 8;
        }
        for (int i = 15; i >= 8; i--) {
            b[i] = (byte) lo;
            lo >>>= 8;
        }
        return java.util.Base64.getUrlEncoder()
            .encodeToString(b);
    }

    /** The only code touching BetterQuesting classes, so they load only when BQ is present. */
    private static final class Impl {

        static final Source SOURCE = new Source() {

            @Override
            public String nameOf(UUID id) {
                IQuest quest = QuestDatabase.INSTANCE.get(id);
                if (quest == null) return null;
                String name = name(id, quest);
                return name == null ? "" : name;
            }

            @Override
            public Iterable<UUID> ids() {
                List<UUID> ids = new ArrayList<>();
                for (Map.Entry<UUID, IQuest> e : QuestDatabase.INSTANCE.entrySet()) ids.add(e.getKey());
                return ids;
            }
        };

        static String name(UUID id, IQuest quest) {
            String key = "betterquesting.quest." + encode(id).replace("=", "") + ".name";
            if (StatCollector.canTranslate(key)) {
                return StatCollector.translateToLocal(key);
            }
            return quest.getProperty(NativeProps.NAME);
        }
    }
}
