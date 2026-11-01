package com.tuxprogrammer.davebridge.common;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.SecureRandom;
import java.util.regex.Pattern;

import net.minecraftforge.common.config.Configuration;
import net.minecraftforge.common.config.Property;

import com.tuxprogrammer.davebridge.DaveBridge;

/**
 * Server-side config ({@code config/davebridge.cfg}). Loaded on both physical sides because an integrated
 * (singleplayer) server runs the same server code; client-only options live in {@code ClientConfig}.
 * <p>
 * Fields are volatile because socket and netty threads read them while {@code /dave reload} rewrites them from the
 * server thread.
 */
public final class Config {

    public static final String CATEGORY_NETWORK = "network";
    public static final String CATEGORY_CHAT = "chat";
    public static final String CATEGORY_QUEUE = "queue";

    // network
    public static volatile boolean enabled = true;
    public static volatile boolean startOnIntegratedServer = false;
    public static volatile String bindAddress = "127.0.0.1";
    public static volatile int port = 25580;
    public static volatile String authToken = "";
    public static volatile int authTimeoutSeconds = 10;
    public static volatile int maxClients = 4;
    public static volatile int maxMessageBytes = 1 << 20;

    // chat
    public static volatile String[] triggerPrefixes = { "dave,", "@dave", "!dave" };
    public static volatile boolean forwardAllChat = false;
    public static volatile String botName = "Dave";
    public static volatile String botNameColor = "aqua";
    public static volatile int maxLineLength = 200;
    public static volatile int maxLinesPerMessage = 40;
    public static volatile boolean notifyWhenOffline = true;
    public static volatile int askCooldownMillis = 1000;
    public static volatile String[] urlAllowlist = new String[0];
    public static volatile String[] commandAllowlist = { "/dave", "/davebridge", "/bq_client", "/nei_bookmark",
        "/savewaypoint", "/guidenhc" };
    public static volatile String replySound = "random.orb";
    public static volatile float replySoundVolume = 0.5f;
    public static volatile float replySoundPitch = 1.4f;
    public static volatile int maxAskLength = 2000;

    // queue
    public static volatile int tickBudgetMillis = 5;
    public static volatile int maxQueueDepth = 1000;

    // eval (milestone 2)
    public static final String CATEGORY_EVAL = "eval";
    public static volatile boolean evalEnabled = true;
    public static volatile int evalTimeoutMillis = 500;
    public static volatile int evalMaxTimeoutMillis = 5000;
    public static volatile int evalMaxResultChars = 64 * 1024;
    public static volatile int evalMaxOutputChars = 16 * 1024;
    public static volatile int confirmTimeoutSeconds = 120;
    public static volatile int confirmMaxTimeoutSeconds = 600;
    public static volatile String backupCommand = "";
    public static volatile boolean clientEvalRelay = true;
    public static volatile int clientEvalTimeoutSeconds = 30;

    /** A non-empty {@code authToken} line as Forge writes it, e.g. {@code S:authToken=...}. */
    private static final Pattern TOKEN_LINE = Pattern.compile("(?m)^\\s*S:\"?authToken\"?\\s*=\\s*\\S");

    private static File configFile;
    /** True once the file has been read successfully at least once. */
    private static boolean loaded;

    private Config() {}

    public static void init(File file) {
        configFile = file;
        reload();
    }

    /**
     * Re-reads the config file. Writes back defaults and a generated token if they were missing.
     * <p>
     * If the file cannot be parsed, Forge renames it to {@code *.errored} and starts from an empty file, which would
     * silently replace the token and reset {@code bindAddress}. Instead this restores the file, keeps every current
     * value (at startup: keeps the bridge off) and returns false.
     *
     * @return true if the file was applied, false if it could not be parsed and the previous settings were kept
     */
    public static synchronized boolean reload() {
        File file = configFile;
        byte[] before = readIfPresent(file);
        Configuration cfg;
        try {
            cfg = new Configuration(file);
            cfg.load();
        } catch (RuntimeException e) {
            return parseFailed(file, before, e.toString());
        }
        if (before != null && before.length > 0 && file.length() == 0) {
            return parseFailed(file, before, "Forge could not parse it");
        }
        Property token = cfg.get(
            CATEGORY_NETWORK,
            "authToken",
            "",
            "Shared secret the agent must present. Generated randomly on first run if empty. Treat like a password.");
        boolean tokenMissing = token.getString() == null || token.getString()
            .trim()
            .isEmpty();
        if (tokenMissing && before != null
            && TOKEN_LINE.matcher(new String(before, StandardCharsets.UTF_8))
                .find()) {
            // The file has a token but it did not come through: never replace it with a generated one.
            return parseFailed(file, before, "its authToken could not be read");
        }

        cfg.setCategoryComment(
            CATEGORY_NETWORK,
            "WebSocket server the external agent connects to. Changes apply on /dave reload (the socket restarts).");
        enabled = cfg.getBoolean("enabled", CATEGORY_NETWORK, true, "Start the WebSocket bridge at all.");
        startOnIntegratedServer = cfg.getBoolean(
            "startOnIntegratedServer",
            CATEGORY_NETWORK,
            false,
            "Also open the socket when running a singleplayer/LAN world (normally only dedicated servers do).");
        bindAddress = cfg.getString(
            "bindAddress",
            CATEGORY_NETWORK,
            "127.0.0.1",
            "Address to bind. 127.0.0.1 for a local agent. In Docker, use 0.0.0.0 so the agent's container can reach "
                + "it over the stack network, and do not publish this port to the host or LAN.");
        port = cfg.getInt("port", CATEGORY_NETWORK, 25580, 1, 65535, "TCP port of the WebSocket server.");

        if (tokenMissing) {
            token.set(generateToken());
            DaveBridge.LOG.info("Generated a new authToken in {}", configFile);
        }
        authToken = token.getString()
            .trim();

        authTimeoutSeconds = cfg.getInt(
            "authTimeoutSeconds",
            CATEGORY_NETWORK,
            10,
            1,
            300,
            "Connections that have not authenticated within this many seconds are dropped.");
        maxClients = cfg
            .getInt("maxClients", CATEGORY_NETWORK, 4, 1, 64, "Maximum simultaneous WebSocket connections.");
        maxMessageBytes = cfg.getInt(
            "maxMessageBytes",
            CATEGORY_NETWORK,
            1 << 20,
            1024,
            64 << 20,
            "Largest inbound WebSocket frame accepted, in bytes.");

        cfg.setCategoryComment(CATEGORY_CHAT, "Chat forwarding and how Dave's replies look in game.");
        triggerPrefixes = cfg.getStringList(
            "triggerPrefixes",
            CATEGORY_CHAT,
            new String[] { "dave,", "@dave", "!dave" },
            "Chat messages starting with one of these (case-insensitive) are forwarded with triggered=true.");
        forwardAllChat = cfg.getBoolean(
            "forwardAllChat",
            CATEGORY_CHAT,
            false,
            "Forward every chat message (non-matching ones with triggered=false), not just triggered ones.");
        botName = cfg.getString("botName", CATEGORY_CHAT, "Dave", "Name shown in <...> before Dave's chat lines.");
        botNameColor = cfg.getString(
            "botNameColor",
            CATEGORY_CHAT,
            "aqua",
            "Color of the bot name: a Minecraft color name such as aqua, gold, light_purple.");
        maxLineLength = cfg
            .getInt("maxLineLength", CATEGORY_CHAT, 200, 20, 1000, "Longer lines are wrapped into several chat lines.");
        maxLinesPerMessage = cfg.getInt(
            "maxLinesPerMessage",
            CATEGORY_CHAT,
            40,
            1,
            500,
            "A single say message is cut off after this many chat lines.");

        notifyWhenOffline = cfg.getBoolean(
            "notifyWhenOffline",
            CATEGORY_CHAT,
            true,
            "Tell a player privately when they address Dave but no agent is connected.");
        askCooldownMillis = cfg.getInt(
            "askCooldownMillis",
            CATEGORY_CHAT,
            1000,
            0,
            60000,
            "Minimum time between Ask packets from one player's client mod. Extra asks are dropped.");
        urlAllowlist = cfg.getStringList(
            "urlAllowlist",
            CATEGORY_CHAT,
            new String[0],
            "Hosts Dave may link to with {url:}, matched as domain suffixes (example.org also allows wiki.example.org). "
                + "Empty: any http/https host.");
        commandAllowlist = cfg.getStringList(
            "commandAllowlist",
            CATEGORY_CHAT,
            new String[] { "/dave", "/davebridge", "/bq_client", "/nei_bookmark", "/savewaypoint", "/guidenhc" },
            "Commands a {cmd:} button (or a run_command in raw components) may run when a player clicks it.");
        replySound = cfg.getString(
            "replySound",
            CATEGORY_CHAT,
            "random.orb",
            "Sound played to each recipient when Dave replies (only they hear it). Empty to disable.");
        replySoundVolume = (float) cfg
            .get(CATEGORY_CHAT, "replySoundVolume", 0.5, "Volume of the reply sound (0-1).", 0.0, 1.0)
            .getDouble();
        replySoundPitch = (float) cfg
            .get(CATEGORY_CHAT, "replySoundPitch", 1.4, "Pitch of the reply sound (0.5-2).", 0.5, 2.0)
            .getDouble();
        maxAskLength = cfg
            .getInt("maxAskLength", CATEGORY_CHAT, 2000, 16, 32000, "Longest question accepted from the client mod.");

        cfg.setCategoryComment(CATEGORY_QUEUE, "Main-thread task queue that runs agent actions during server ticks.");
        tickBudgetMillis = cfg.getInt(
            "tickBudgetMillis",
            CATEGORY_QUEUE,
            5,
            1,
            45,
            "Time per server tick spent running queued tasks. At least one task runs per tick regardless.");
        maxQueueDepth = cfg
            .getInt("maxQueueDepth", CATEGORY_QUEUE, 1000, 10, 100000, "Further tasks are rejected while this full.");

        loadEval(cfg);

        if (cfg.hasChanged()) {
            cfg.save();
        }
        loaded = true;
        return true;
    }

    private static void loadEval(Configuration cfg) {
        cfg.setCategoryComment(
            CATEGORY_EVAL,
            "Live eval: Groovy scripts from the agent, run on the server thread (PROTOCOL.md 1.8). Trusted players only.");
        evalEnabled = cfg
            .getBoolean("evalEnabled", CATEGORY_EVAL, true, "Accept eval and describe requests from the agent.");
        evalTimeoutMillis = cfg.getInt(
            "evalTimeoutMillis",
            CATEGORY_EVAL,
            500,
            10,
            60000,
            "Default time limit of one script. It holds the server tick while it runs.");
        evalMaxTimeoutMillis = cfg.getInt(
            "evalMaxTimeoutMillis",
            CATEGORY_EVAL,
            5000,
            10,
            60000,
            "Largest time limit a request may ask for (timeoutMs).");
        evalMaxResultChars = cfg.getInt(
            "evalMaxResultChars",
            CATEGORY_EVAL,
            64 * 1024,
            1024,
            4 * 1024 * 1024,
            "Approximate size cap of a script's JSON result.");
        evalMaxOutputChars = cfg
            .getInt("evalMaxOutputChars", CATEGORY_EVAL, 16 * 1024, 0, 1024 * 1024, "Printed output kept per script.");
        confirmTimeoutSeconds = cfg.getInt(
            "confirmTimeoutSeconds",
            CATEGORY_EVAL,
            120,
            5,
            3600,
            "How long a world-changing script waits for the player's Confirm click by default.");
        confirmMaxTimeoutSeconds = cfg.getInt(
            "confirmMaxTimeoutSeconds",
            CATEGORY_EVAL,
            600,
            5,
            3600,
            "Longest confirm wait a request may ask for.");
        backupCommand = cfg.getString(
            "backupCommand",
            CATEGORY_EVAL,
            "",
            "Server command run (as the server) right before a confirmed world-changing script, e.g. 'backup start' "
                + "(ServerUtilities; it copies in the background). Empty: none.");
        clientEvalRelay = cfg.getBoolean(
            "clientEvalRelay",
            CATEGORY_EVAL,
            true,
            "Relay client_eval to players who opted in on their own client. Players who did not opt in never get it.");
        clientEvalTimeoutSeconds = cfg.getInt(
            "clientEvalTimeoutSeconds",
            CATEGORY_EVAL,
            30,
            1,
            600,
            "How long to wait for a client's eval result.");
    }

    private static byte[] readIfPresent(File file) {
        try {
            return file != null && file.isFile() ? Files.readAllBytes(file.toPath()) : null;
        } catch (IOException e) {
            DaveBridge.LOG.warn("Could not read {} before loading it", file, e);
            return null;
        }
    }

    /** Puts the unparseable file back so it can be fixed in place, and keeps the current settings. */
    private static boolean parseFailed(File file, byte[] before, String why) {
        DaveBridge.LOG.error(
            "Could not load {} ({}). Kept the previous settings, including authToken and bindAddress; "
                + "fix the file and run /dave reload.",
            file,
            why);
        if (before != null) {
            try {
                Files.write(file.toPath(), before);
            } catch (IOException e) {
                DaveBridge.LOG.error("Could not restore {}; Forge left a copy next to it as *.errored", file, e);
            }
        }
        if (!loaded) {
            enabled = false;
            DaveBridge.LOG.error("The agent bridge stays off until {} loads.", file);
        }
        return false;
    }

    private static String generateToken() {
        byte[] bytes = new byte[24];
        new SecureRandom().nextBytes(bytes);
        StringBuilder sb = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) {
            sb.append(String.format("%02x", b & 0xff));
        }
        return sb.toString();
    }
}
