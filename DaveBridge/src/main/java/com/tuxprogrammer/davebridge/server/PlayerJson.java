package com.tuxprogrammer.davebridge.server;

import net.minecraft.entity.player.EntityPlayerMP;

import com.google.gson.JsonObject;

/** Builds the player fields shared by chat, join and leave events. Reads only plain fields; no world access. */
public final class PlayerJson {

    private PlayerJson() {}

    public static JsonObject describe(EntityPlayerMP player, JsonObject into) {
        into.addProperty("player", player.getCommandSenderName());
        into.addProperty(
            "playerUuid",
            player.getUniqueID()
                .toString());
        into.addProperty("dim", player.dimension);
        into.addProperty("x", round(player.posX));
        into.addProperty("y", round(player.posY));
        into.addProperty("z", round(player.posZ));
        into.addProperty("hasClientMod", DaveServer.CLIENTS.hasClientMod(player.getUniqueID()));
        return into;
    }

    private static double round(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
