package com.tuxprogrammer.davebridge.server.network;

import java.util.Arrays;
import java.util.UUID;

import net.minecraft.entity.player.EntityPlayerMP;
import net.minecraft.server.MinecraftServer;
import net.minecraft.util.ChatComponentTranslation;
import net.minecraftforge.common.ForgeHooks;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import com.tuxprogrammer.davebridge.DaveBridge;
import com.tuxprogrammer.davebridge.Tags;
import com.tuxprogrammer.davebridge.common.Config;
import com.tuxprogrammer.davebridge.common.network.DaveNetwork;
import com.tuxprogrammer.davebridge.common.protocol.Ask;
import com.tuxprogrammer.davebridge.common.protocol.ClientEvalResult;
import com.tuxprogrammer.davebridge.common.protocol.ClientHello;
import com.tuxprogrammer.davebridge.common.protocol.ClientSettings;
import com.tuxprogrammer.davebridge.common.protocol.DavePackets;
import com.tuxprogrammer.davebridge.common.protocol.ServerHello;
import com.tuxprogrammer.davebridge.server.ClientModTracker;
import com.tuxprogrammer.davebridge.server.DaveServer;
import com.tuxprogrammer.davebridge.server.PlayerJson;
import com.tuxprogrammer.davebridge.server.bridge.Protocol;
import com.tuxprogrammer.davebridge.server.chat.ChatRelay;
import com.tuxprogrammer.davebridge.server.chat.DaveChat;
import com.tuxprogrammer.davebridge.server.chat.TriggerMatcher;
import com.tuxprogrammer.davebridge.server.eval.ClientEvalRelay;

/**
 * Server handlers for packets from the client half. Thread-agnostic (FML may call them off the server thread); clients
 * are untrusted, so every field is validated and bounded here, and game-state work is queued to the server thread.
 */
public final class ServerPacketHandlers {

    static final int MAX_CAPABILITIES = 32;
    static final int MAX_SHORT_STRING = 64;
    static final int MAX_CONTEXT_CHARS = 16 * 1024;

    /** Client capability: has the {@code /davebridge nei} client command, so chat may link to it. */
    public static final String CAP_NEI = "nei";

    private ServerPacketHandlers() {}

    public static void register() {
        DaveNetwork.onServer(ClientHello.class, ServerPacketHandlers::onClientHello);
        DaveNetwork.onServer(Ask.class, ServerPacketHandlers::onAsk);
        DaveNetwork.onServer(ClientSettings.class, ServerPacketHandlers::onClientSettings);
        // Relayed to the agent only if it answers a client_eval this server sent to this player (ClientEvalRelay).
        DaveNetwork.onServer(ClientEvalResult.class, ClientEvalRelay::onResult);
    }

    /**
     * Whether Dave's chat lines for {@code player} may use client-command links ({@code /davebridge nei ...}): the
     * player's client half speaks our protocol and reported the {@value #CAP_NEI} capability.
     */
    public static boolean canUseModLinks(UUID player) {
        return supportsModLinks(DaveServer.CLIENTS.get(player));
    }

    static boolean supportsModLinks(ClientModTracker.Info info) {
        if (info == null || info.protocol != DavePackets.PROTOCOL_VERSION || info.capabilities == null) {
            return false;
        }
        for (String capability : info.capabilities) {
            if (CAP_NEI.equals(capability)) {
                return true;
            }
        }
        return false;
    }

    private static void onClientHello(ClientHello hello, EntityPlayerMP player) {
        String version = clip(hello.modVersion, MAX_SHORT_STRING);
        String[] caps = hello.capabilities == null ? new String[0]
            : Arrays.copyOf(hello.capabilities, Math.min(hello.capabilities.length, MAX_CAPABILITIES));
        for (int i = 0; i < caps.length; i++) {
            caps[i] = clip(caps[i], MAX_SHORT_STRING);
        }
        int protocol = hello.protocol;
        boolean clientEvalAllowed = hello.clientEvalAllowed;

        // Record the player in the same task that answers, so a dropped task (full queue) leaves both sides on plain
        // chat instead of the server assuming a client half that never heard back.
        DaveServer.QUEUE.submit("client_hello", () -> {
            UUID id = player.getUniqueID();
            if (!isOnline(player) || DaveServer.CLIENTS.hasClientMod(id)) {
                return; // left before we got here, or a repeat hello (one per login)
            }
            ServerHello reply = new ServerHello();
            reply.modVersion = Tags.VERSION;
            reply.botName = Config.botName;
            reply.triggerPrefixes = Config.triggerPrefixes;
            reply.maxAskLength = Config.maxAskLength;
            DaveNetwork.sendTo(reply, player);

            if (protocol != DavePackets.PROTOCOL_VERSION) {
                // The client sees our protocol in server_hello and falls back to plain chat as well.
                DaveBridge.LOG.warn(
                    "{} has DaveBridge client {} with packet protocol {} (server: {}); treating it as a plain client",
                    player.getCommandSenderName(),
                    version,
                    protocol,
                    DavePackets.PROTOCOL_VERSION);
                return;
            }
            ClientModTracker.Info info = DaveServer.CLIENTS.put(id, version, protocol, caps, clientEvalAllowed);
            DaveBridge.LOG.info(
                "{} has the DaveBridge client {} (capabilities {}, clientEval {})",
                player.getCommandSenderName(),
                version,
                Arrays.toString(caps),
                info.clientEvalAllowed);
            announceClientMod(player, info);
        });
    }

    /** A player opted in or out mid-session: update the record and tell the agent with a fresh client_mod. */
    private static void onClientSettings(ClientSettings settings, EntityPlayerMP player) {
        boolean allowed = settings.clientEvalAllowed;
        DaveServer.QUEUE.submit("client_settings", () -> {
            if (!isOnline(player)) {
                return;
            }
            ClientModTracker.Info info = DaveServer.CLIENTS.setClientEvalAllowed(player.getUniqueID(), allowed);
            if (info == null) {
                return; // no hello yet, or nothing changed
            }
            DaveBridge.LOG
                .info("{} {} client eval", player.getCommandSenderName(), allowed ? "opted in to" : "opted out of");
            announceClientMod(player, info);
        });
    }

    /** The {@code client_mod} event (PROTOCOL.md 1.3), sent after a hello and again when the opt-in changes. */
    private static void announceClientMod(EntityPlayerMP player, ClientModTracker.Info info) {
        JsonObject event = Protocol.message("client_mod");
        PlayerJson.describe(player, event);
        event.addProperty("modVersion", info.modVersion);
        event.addProperty("protocol", info.protocol);
        JsonArray capArray = new JsonArray();
        for (String c : info.capabilities) {
            capArray.add(new JsonPrimitive(c == null ? "" : c));
        }
        event.add("capabilities", capArray);
        event.addProperty("clientEvalAllowed", info.clientEvalAllowed);
        DaveServer.BRIDGE.broadcast(event);
    }

    private static void onAsk(Ask ask, EntityPlayerMP player) {
        if (!DaveServer.CLIENTS.hasClientMod(player.getUniqueID())) {
            return; // must say hello first
        }
        AskCheck check = checkAsk(ask.text, Config.maxAskLength, Config.triggerPrefixes);
        if (check.error != null) {
            DaveBridge.LOG.debug("Rejecting ask from {}: {}", player.getCommandSenderName(), check.error);
            DaveServer.QUEUE.submit("ask_rejected", () -> player.addChatMessage(DaveChat.notice(check.error)));
            return;
        }
        if (!DaveServer.CLIENTS.tryAsk(player.getUniqueID(), System.currentTimeMillis(), Config.askCooldownMillis)) {
            DaveServer.QUEUE.submit(
                "ask_cooldown",
                () -> player.addChatMessage(
                    DaveChat
                        .notice("Slow down a little, " + Config.botName + " is still reading your last question.")));
            return;
        }
        JsonObject context = null;
        if (ask.context != null && ask.context.isJsonObject()
            && ask.context.toString()
                .length() <= MAX_CONTEXT_CHARS) {
            context = ask.context.getAsJsonObject();
        }
        final JsonObject safeContext = context;
        DaveServer.QUEUE.submit("ask", () -> {
            broadcastQuestion(player, check.text);
            ChatRelay.relay(player, check.text, "client", true, check.prompt, safeContext);
        });
    }

    /**
     * Shows an Ask-key question to everyone exactly like vanilla shows a chat line ({@code <Player> text}): replies
     * are public, so the question must be too, or nobody else can follow or join in. Not posted as a
     * {@code ServerChatEvent}, which would relay it to the agent a second time. Server thread.
     */
    private static void broadcastQuestion(EntityPlayerMP player, String text) {
        MinecraftServer server = MinecraftServer.getServer();
        if (server == null || server.getConfigurationManager() == null) {
            return;
        }
        server.getConfigurationManager()
            .sendChatMsgImpl(
                new ChatComponentTranslation(
                    "chat.type.text",
                    player.func_145748_c_(),
                    ForgeHooks.newChatWithLinks(text)),
                false);
    }

    private static boolean isOnline(EntityPlayerMP player) {
        MinecraftServer server = MinecraftServer.getServer();
        return server != null && server.getConfigurationManager() != null
            && server.getConfigurationManager().playerEntityList.contains(player);
    }

    /** The outcome of validating an ask: either {@link #error} (shown to the asker) or the text and prompt. */
    static final class AskCheck {

        final String text;
        final String prompt;
        final String error;

        private AskCheck(String text, String prompt, String error) {
            this.text = text;
            this.prompt = prompt;
            this.error = error;
        }
    }

    /**
     * Validates an ask's text. {@code text} is the trimmed original (shown to everyone, trigger prefix included);
     * {@code prompt} is the question for the agent, without a trigger prefix.
     */
    static AskCheck checkAsk(String raw, int maxLength, String[] triggerPrefixes) {
        String text = raw == null ? "" : raw.trim();
        if (text.isEmpty()) {
            return new AskCheck(null, null, "Your question is empty.");
        }
        if (text.length() > maxLength) {
            return new AskCheck(
                null,
                null,
                "Your question is too long (" + text.length() + " characters, at most " + maxLength + ").");
        }
        String stripped = TriggerMatcher.match(text, triggerPrefixes);
        String prompt = stripped != null ? stripped : text;
        if (prompt.trim()
            .isEmpty()) {
            return new AskCheck(null, null, "Type your question after \"" + text + "\".");
        }
        return new AskCheck(text, prompt, null);
    }

    private static String clip(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.length() > max ? s.substring(0, max) : s;
    }
}
