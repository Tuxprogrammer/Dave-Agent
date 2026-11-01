package com.tuxprogrammer.davebridge.server.command;

import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import net.minecraft.entity.player.EntityPlayerMP;
import net.minecraft.util.ChunkCoordinates;
import net.minecraft.world.World;
import net.minecraftforge.common.DimensionManager;
import net.minecraftforge.common.UsernameCache;

import com.google.gson.JsonObject;
import com.tuxprogrammer.davebridge.server.DaveServer;
import com.tuxprogrammer.davebridge.server.bridge.Protocol;
import com.tuxprogrammer.davebridge.server.chat.DaveChat;
import com.tuxprogrammer.davebridge.server.chat.TriggerMatcher;

/**
 * Op and console test hooks (PROTOCOL.md section 5), so the whole Dave loop can be exercised over RCON with nobody
 * online: {@code /dave ask} sends the agent a chat event exactly like a triggered chat line from a named player.
 */
public final class TestHooks {

    private static final Pattern POSITION = Pattern
        .compile("@(-?\\d+(?:\\.\\d+)?),(-?\\d+(?:\\.\\d+)?),(-?\\d+(?:\\.\\d+)?)(?:,(-?\\d+))?");

    private TestHooks() {}

    /**
     * The UUID for a player name: an online player's own, else the one Forge's username cache remembers for that name
     * (a player who has joined before; no network lookup), else the stable offline-mode UUID derived from the name.
     */
    public static UUID uuidFor(String name) {
        for (EntityPlayerMP p : DaveChat.onlinePlayers()) {
            if (p.getCommandSenderName()
                .equalsIgnoreCase(name)) {
                return p.getUniqueID();
            }
        }
        try {
            for (Map.Entry<UUID, String> e : UsernameCache.getMap()
                .entrySet()) {
                if (e.getValue() != null && e.getValue()
                    .equalsIgnoreCase(name)) {
                    return e.getKey();
                }
            }
        } catch (Throwable ignored) {
            // the cache file may be unreadable; fall through to the derived id
        }
        return offlineUuid(name);
    }

    /** What an offline-mode server would give {@code name}: a v3 UUID of {@code "OfflinePlayer:" + name}. */
    public static UUID offlineUuid(String name) {
        return UUID.nameUUIDFromBytes(("OfflinePlayer:" + name).getBytes(StandardCharsets.UTF_8));
    }

    /** The parsed arguments of {@code /dave ask <asName> [@x,y,z[,dim]] <question...>}. */
    public static final class Ask {

        public final String name;
        public final double[] pos;
        public final Integer dim;
        public final String question;

        Ask(String name, double[] pos, Integer dim, String question) {
            this.name = name;
            this.pos = pos;
            this.dim = dim;
            this.question = question;
        }
    }

    /** Parses the arguments after {@code ask}, or returns null when they do not fit. Pure; unit-tested. */
    public static Ask parseAsk(String[] args, int from) {
        if (args.length - from < 2) {
            return null;
        }
        String name = args[from];
        int i = from + 1;
        double[] pos = null;
        Integer dim = null;
        Matcher m = POSITION.matcher(args[i]);
        if (m.matches()) {
            pos = new double[] { Double.parseDouble(m.group(1)), Double.parseDouble(m.group(2)),
                Double.parseDouble(m.group(3)) };
            dim = m.group(4) == null ? null : Integer.valueOf(m.group(4));
            i++;
        }
        StringBuilder q = new StringBuilder();
        for (; i < args.length; i++) {
            q.append(q.length() == 0 ? "" : " ")
                .append(args[i]);
        }
        String question = q.toString()
            .trim();
        return question.isEmpty() ? null : new Ask(name, pos, dim, question);
    }

    /**
     * Sends the agent a {@code chat} event for {@code ask}, with {@code source:"console"}. Server thread.
     *
     * @return how many agents received it
     */
    public static int sendAsk(Ask ask) {
        EntityPlayerMP online = null;
        for (EntityPlayerMP p : DaveChat.onlinePlayers()) {
            if (p.getCommandSenderName()
                .equalsIgnoreCase(ask.name)) {
                online = p;
            }
        }
        int dim = ask.dim != null ? ask.dim : online != null && ask.pos == null ? online.dimension : 0;
        double[] pos = ask.pos;
        if (pos == null && online != null) {
            pos = new double[] { online.posX, online.posY, online.posZ };
        }
        if (pos == null) {
            World overworld = DimensionManager.getWorld(0);
            ChunkCoordinates spawn = overworld == null ? new ChunkCoordinates(0, 64, 0) : overworld.getSpawnPoint();
            pos = new double[] { spawn.posX + 0.5, spawn.posY, spawn.posZ + 0.5 };
        }
        String prompt = TriggerMatcher
            .addressed(ask.question, com.tuxprogrammer.davebridge.common.Config.triggerPrefixes);
        if (prompt == null) {
            prompt = ask.question;
        }
        JsonObject event = Protocol.message("chat");
        event.addProperty(
            "id",
            UUID.randomUUID()
                .toString());
        event.addProperty("player", online != null ? online.getCommandSenderName() : ask.name);
        event.addProperty("playerUuid", uuidFor(ask.name).toString());
        event.addProperty("dim", dim);
        event.addProperty("x", round(pos[0]));
        event.addProperty("y", round(pos[1]));
        event.addProperty("z", round(pos[2]));
        event.addProperty("hasClientMod", false);
        event.addProperty("message", ask.question);
        event.addProperty("triggered", true);
        event.addProperty("prompt", prompt);
        event.addProperty("source", "console");
        return DaveServer.BRIDGE.broadcast(event);
    }

    private static double round(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
