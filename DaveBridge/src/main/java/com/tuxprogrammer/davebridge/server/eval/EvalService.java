package com.tuxprogrammer.davebridge.server.eval;

import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.CompletionException;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

import net.minecraft.command.ICommandSender;
import net.minecraft.entity.player.EntityPlayerMP;
import net.minecraft.server.MinecraftServer;
import net.minecraft.util.ChatComponentText;
import net.minecraft.util.ChatStyle;
import net.minecraft.util.EnumChatFormatting;
import net.minecraft.util.IChatComponent;
import net.minecraft.world.World;
import net.minecraftforge.common.DimensionManager;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import com.tuxprogrammer.davebridge.DaveBridge;
import com.tuxprogrammer.davebridge.common.Config;
import com.tuxprogrammer.davebridge.common.eval.EvalHelpers;
import com.tuxprogrammer.davebridge.common.eval.JsonDump;
import com.tuxprogrammer.davebridge.common.eval.ScriptEngine;
import com.tuxprogrammer.davebridge.server.DaveServer;
import com.tuxprogrammer.davebridge.server.bridge.MessageRouter;
import com.tuxprogrammer.davebridge.server.bridge.Protocol;
import com.tuxprogrammer.davebridge.server.bridge.ProtocolException;
import com.tuxprogrammer.davebridge.server.bridge.Request;
import com.tuxprogrammer.davebridge.server.chat.DaveChat;
import com.tuxprogrammer.davebridge.server.chat.markup.ChatStyles;
import com.tuxprogrammer.davebridge.server.command.TestHooks;

/**
 * Agent requests for live eval (PROTOCOL.md 1.8): {@code eval} and {@code describe}.
 * <p>
 * An {@code eval} is compiled on a background thread, then run on the server thread through the main-thread queue,
 * so it sees a consistent world and its time limit bounds how long it holds the tick. A {@code mode:"write"} script
 * first waits for the asking player to click Confirm in chat ({@link PendingConfirms}); a {@code mode:"read"}
 * script that obviously changes the world is refused with {@code needs_confirm}. Script failures are reported as
 * {@code eval_result} with {@code ok:false}; they never reach the server.
 */
public final class EvalService {

    static final int MAX_SCRIPT_CHARS = 64 * 1024;
    static final int MAX_SUMMARY_CHARS = 300;
    static final int MAX_CONFIRMS_PER_PLAYER = 5;

    private static final Gson GSON = new Gson();
    private static final PendingConfirms<WriteJob> CONFIRMS = new PendingConfirms<>(MAX_CONFIRMS_PER_PLAYER);
    private static final ScheduledExecutorService TIMER = Executors.newSingleThreadScheduledExecutor(r -> {
        Thread t = new Thread(r, "DaveBridge-eval-timer");
        t.setDaemon(true);
        return t;
    });

    private EvalService() {}

    /** A write-mode script waiting for its confirm. */
    static final class WriteJob {

        final Request request;
        final String id;
        final ScriptEngine.Compiled compiled;
        final Object params;
        final long timeoutMs;
        final String summary;

        WriteJob(Request request, String id, ScriptEngine.Compiled compiled, Object params, long timeoutMs,
            String summary) {
            this.request = request;
            this.id = id;
            this.compiled = compiled;
            this.params = params;
            this.timeoutMs = timeoutMs;
            this.summary = summary;
        }
    }

    public static void register(MessageRouter router) {
        EvalHelpers.registerAdapters();
        router.register("eval", request -> handleEval(router, request));
        router.register("describe", request -> handleDescribe(router, request));
        ClientEvalRelay.register(router);
    }

    // ------------------------------------------------------------------ eval

    private static void handleEval(MessageRouter router, Request request) throws ProtocolException {
        if (!Config.evalEnabled) {
            throw new ProtocolException("disabled", "eval is disabled on this server (eval.evalEnabled)");
        }
        String script = request.requireString("script");
        if (script.length() > MAX_SCRIPT_CHARS) {
            throw new ProtocolException(
                Protocol.ERR_BAD_REQUEST,
                "script too long (" + script.length() + " chars, at most " + MAX_SCRIPT_CHARS + ")");
        }
        String id = request.optString("id", null);
        String mode = request.optString("mode", "read")
            .toLowerCase(Locale.ROOT);
        if (!"read".equals(mode) && !"write".equals(mode)) {
            throw new ProtocolException(Protocol.ERR_BAD_REQUEST, "mode must be \"read\" or \"write\"");
        }
        String playerName = request.optString("player", null);
        String summary = request.optString("summary", null);
        long timeoutMs = clampTimeout(optLong(request.body(), "timeoutMs", Config.evalTimeoutMillis));
        long confirmSeconds = Math.max(
            5,
            Math.min(
                Config.confirmMaxTimeoutSeconds,
                optLong(request.body(), "confirmTimeoutSeconds", Config.confirmTimeoutSeconds)));
        Object params = toJava(
            request.body()
                .get("params"));
        if ("write".equals(mode)) {
            if (playerName == null) {
                throw new ProtocolException(
                    Protocol.ERR_BAD_REQUEST,
                    "mode \"write\" needs \"player\": the asking player, who confirms it in chat");
            }
            if (summary == null || summary.trim()
                .isEmpty()) {
                throw new ProtocolException(
                    Protocol.ERR_BAD_REQUEST,
                    "mode \"write\" needs \"summary\": one line telling the player what will change");
            }
        }
        String summaryText = summary == null ? null : clip(summary.trim(), MAX_SUMMARY_CHARS);

        ScriptEngine.shared()
            .compileAsync(script)
            .whenComplete((compiled, failure) -> {
                try {
                    if (failure != null) {
                        request.reply(compileFailure(id, mode, failure));
                        return;
                    }
                    if ("read".equals(mode) && !compiled.mutators.isEmpty()) {
                        JsonObject r = result(id, mode);
                        r.addProperty("ok", false);
                        r.addProperty("errorType", "needs_confirm");
                        r.addProperty(
                            "error",
                            "this looks like it changes the world (" + String.join(", ", compiled.mutators)
                                + "). Send it again with mode \"write\" and a summary; the player confirms it in chat.");
                        request.reply(r);
                        return;
                    }
                    if ("write".equals(mode)) {
                        onMain(
                            request,
                            "eval_confirm",
                            () -> askToConfirm(
                                request,
                                id,
                                compiled,
                                params,
                                timeoutMs,
                                playerName,
                                summaryText,
                                confirmSeconds,
                                script));
                        return;
                    }
                    router.runOnMainThread(
                        request,
                        "eval",
                        () -> runNow(id, mode, compiled, params, timeoutMs, playerName, false));
                } catch (Throwable t) {
                    DaveBridge.LOG.warn("eval request failed", t);
                    request.error(Protocol.ERR_INTERNAL, t.toString());
                }
            });
    }

    private static long clampTimeout(long requested) {
        return Math.max(10, Math.min(Config.evalMaxTimeoutMillis, requested));
    }

    /** Runs a compiled script now (server thread) and builds its {@code eval_result}. */
    static JsonObject runNow(String id, String mode, ScriptEngine.Compiled compiled, Object params, long timeoutMs,
        String playerName, boolean confirmed) {
        EntityPlayerMP player = playerName == null ? null : findPlayer(playerName);
        Map<String, Object> bindings = bindings(player, playerName, params);
        JsonDump.Limits limits = new JsonDump.Limits(8, 500, 8000, Config.evalMaxResultChars);
        JsonObject outcome = ScriptEngine.shared()
            .run(compiled, bindings, timeoutMs, limits, Config.evalMaxOutputChars);
        JsonObject r = result(id, mode);
        if (confirmed) {
            r.addProperty("confirmed", true);
        }
        for (Map.Entry<String, JsonElement> e : outcome.entrySet()) {
            r.add(e.getKey(), e.getValue());
        }
        if (playerName != null && player == null) {
            addWarning(r, "player " + playerName + " is not online: `player` is null");
        }
        return r;
    }

    static Map<String, Object> bindings(EntityPlayerMP player, String playerName, Object params) {
        Map<String, Object> b = new HashMap<>();
        MinecraftServer server = MinecraftServer.getServer();
        World world = player != null ? player.worldObj : DimensionManager.getWorld(0);
        b.put("server", server);
        b.put("player", player);
        b.put("asker", playerName);
        b.put("world", world);
        b.put("params", params == null ? new HashMap<String, Object>() : params);
        b.put("dave", new ServerEvalHelpers());
        b.put("log", DaveBridge.LOG);
        return b;
    }

    private static JsonObject result(String id, String mode) {
        JsonObject r = Protocol.message("eval_result");
        if (id != null) {
            r.addProperty("id", id);
        }
        r.addProperty("mode", mode);
        r.addProperty("side", "server");
        return r;
    }

    private static JsonObject compileFailure(String id, String mode, Throwable failure) {
        Throwable cause = failure instanceof CompletionException && failure.getCause() != null ? failure.getCause()
            : failure;
        JsonObject r = result(id, mode);
        r.addProperty("ok", false);
        if (cause instanceof ScriptEngine.CompileError) {
            r.addProperty("errorType", ((ScriptEngine.CompileError) cause).kind);
            r.addProperty("error", cause.getMessage());
        } else {
            r.addProperty("errorType", "compile");
            r.addProperty("error", String.valueOf(cause));
        }
        return r;
    }

    private static void addWarning(JsonObject r, String warning) {
        JsonArray w = r.has("warnings") ? r.getAsJsonArray("warnings") : new JsonArray();
        w.add(new JsonPrimitive(warning));
        r.add("warnings", w);
    }

    // ------------------------------------------------------------------ confirm (write mode)

    /**
     * Shows the asking player what will change, with Confirm and Cancel buttons, and parks the script. The reply to
     * the agent comes later: when the player clicks, or when the confirm expires. Server thread.
     *
     * @return null (the reply is sent later), or an immediate error result
     */
    private static JsonObject askToConfirm(Request request, String id, ScriptEngine.Compiled compiled, Object params,
        long timeoutMs, String playerName, String summary, long confirmSeconds, String script) throws Exception {
        EntityPlayerMP player = findPlayer(playerName);
        // An asker who is not online (left, or a /dave ask test name) can still be confirmed from the console.
        String name = player != null ? player.getCommandSenderName() : playerName;
        java.util.UUID uuid = player != null ? player.getUniqueID() : TestHooks.uuidFor(playerName);
        WriteJob job = new WriteJob(request, id, compiled, params, timeoutMs, summary);
        PendingConfirms.Pending<WriteJob> pending = CONFIRMS.create(uuid, name, now(), confirmSeconds * 1000L, job);
        if (pending == null) {
            JsonObject r = result(id, "write");
            r.addProperty("ok", false);
            r.addProperty("errorType", "too_many_pending");
            r.addProperty("error", name + " already has " + MAX_CONFIRMS_PER_PLAYER + " changes waiting for a confirm");
            return r;
        }
        if (player != null) {
            player.addChatMessage(confirmLine1(summary, script));
            player.addChatMessage(confirmLine2(pending.token, confirmSeconds));
        }
        TIMER.schedule(
            () -> DaveServer.QUEUE.submit("eval_confirm_expiry", EvalService::expireConfirms),
            confirmSeconds * 1000L + 50,
            TimeUnit.MILLISECONDS);

        JsonObject event = Protocol.message("eval_pending");
        if (id != null) {
            event.addProperty("id", id);
        }
        event.addProperty("player", name);
        event.addProperty("playerOnline", player != null);
        event.addProperty("confirmId", pending.token);
        event.addProperty("summary", summary);
        event.addProperty("expiresInSeconds", confirmSeconds);
        request.session()
            .send(event); // no reqId: the request's reply is the eval_result after the click
        DaveBridge.LOG.info(
            "Eval {} waits for {} to confirm{}: {}",
            pending.token,
            name,
            player == null ? " (not online: use /dave confirm from the console)" : "",
            summary);
        return PENDING;
    }

    /** Marker: the request is answered later. */
    static final JsonObject PENDING = new JsonObject();

    /** Runs {@code task} later on the eval timer thread (it must queue any game work itself). */
    static void schedule(Runnable task, long delay, TimeUnit unit) {
        TIMER.schedule(() -> {
            try {
                task.run();
            } catch (Throwable t) {
                DaveBridge.LOG.warn("eval timer task failed", t);
            }
        }, delay, unit);
    }

    private static IChatComponent confirmLine1(String summary, String script) {
        IChatComponent line = new ChatComponentText("[" + Config.botName + "] ");
        line.setChatStyle(new ChatStyle().setColor(EnumChatFormatting.AQUA));
        IChatComponent text = new ChatComponentText("wants to change the world: ");
        text.setChatStyle(new ChatStyle().setColor(EnumChatFormatting.GOLD));
        IChatComponent what = new ChatComponentText(summary);
        what.setChatStyle(
            new ChatStyle().setColor(EnumChatFormatting.WHITE)
                .setChatHoverEvent(ChatStyles.hoverText("Script:\n" + clip(script, 800))));
        line.appendSibling(text);
        line.appendSibling(what);
        return line;
    }

    private static IChatComponent confirmLine2(String token, long seconds) {
        IChatComponent line = new ChatComponentText("");
        line.appendSibling(
            ChatStyles.button(
                "Confirm",
                EnumChatFormatting.GREEN,
                null,
                ChatStyles.hoverText("Run it now"),
                ChatStyles.run("/dave confirm " + token)));
        line.appendSibling(new ChatComponentText(" "));
        line.appendSibling(
            ChatStyles.button(
                "Cancel",
                EnumChatFormatting.RED,
                null,
                ChatStyles.hoverText("Do nothing"),
                ChatStyles.run("/dave cancel " + token)));
        IChatComponent note = new ChatComponentText(" (expires in " + formatSeconds(seconds) + ")");
        note.setChatStyle(new ChatStyle().setColor(EnumChatFormatting.GRAY));
        line.appendSibling(note);
        return line;
    }

    private static String formatSeconds(long s) {
        return s >= 120 && s % 60 == 0 ? (s / 60) + " min" : s + " s";
    }

    /**
     * {@code /dave confirm|cancel <token>}: the Confirm and Cancel buttons, or the console. A player may answer only
     * their own confirm; the console (any non-player sender) may answer any. Server thread (commands run there).
     *
     * @return the message for whoever ran it
     */
    public static IChatComponent onConfirmCommand(ICommandSender sender, String token, boolean confirm) {
        EntityPlayerMP clicker = sender instanceof EntityPlayerMP ? (EntityPlayerMP) sender : null;
        String who = sender.getCommandSenderName();
        PendingConfirms.Resolution<WriteJob> res = CONFIRMS
            .resolve(token, clicker == null ? null : clicker.getUniqueID(), confirm, now());
        switch (res.outcome) {
            case WRONG_PLAYER:
                return DaveChat.notice("Only " + res.pending.playerName + " can confirm or cancel that.");
            case UNKNOWN:
                return DaveChat.notice("That change was already handled or has expired.");
            case CANCELLED: {
                WriteJob job = res.pending.payload;
                JsonObject r = result(job.id, "write");
                r.addProperty("ok", false);
                r.addProperty("errorType", "cancelled");
                r.addProperty("error", who + " clicked Cancel; nothing was run");
                job.request.reply(r);
                DaveBridge.LOG.info("{} cancelled eval {}: {}", who, res.pending.token, job.summary);
                return DaveChat.notice("Cancelled. Nothing was changed.");
            }
            case CONFIRMED:
            default: {
                WriteJob job = res.pending.payload;
                String asker = res.pending.playerName;
                runBackupCommand();
                DaveBridge.LOG.info("{} confirmed eval {} for {}: {}", who, res.pending.token, asker, job.summary);
                DaveServer.QUEUE.submit("eval_confirmed", () -> {
                    JsonObject r = runNow(job.id, "write", job.compiled, job.params, job.timeoutMs, asker, true);
                    r.addProperty("confirmedBy", who);
                    job.request.reply(r);
                    boolean ok = r.has("ok") && r.get("ok")
                        .getAsBoolean();
                    String outcome = ok ? "Done."
                        : "That change failed: " + clip(
                            r.get("error")
                                .getAsString(),
                            200);
                    EntityPlayerMP askerPlayer = findPlayer(asker);
                    if (askerPlayer != null) {
                        askerPlayer.addChatMessage(DaveChat.notice(outcome));
                    }
                    if (clicker == null) {
                        sender.addChatMessage(DaveChat.notice("Eval " + res.pending.token + ": " + outcome));
                    }
                });
                return DaveChat.notice("Confirmed. Running it now...");
            }
        }
    }

    /** {@code /dave pending}: every change waiting for a confirm, one line each. */
    public static List<String> describePending() {
        List<String> out = new java.util.ArrayList<>();
        long now = now();
        for (PendingConfirms.Pending<WriteJob> p : CONFIRMS.list()) {
            out.add(
                p.token + "  "
                    + p.playerName
                    + "  "
                    + Math.max(0, (p.expiresAt - now) / 1000)
                    + " s left  "
                    + p.payload.summary);
        }
        return out;
    }

    /** Runs {@code backupCommand} as the server, if configured. Best effort; a failure is logged, not fatal. */
    private static void runBackupCommand() {
        String cmd = Config.backupCommand == null ? "" : Config.backupCommand.trim();
        if (cmd.isEmpty()) {
            return;
        }
        try {
            MinecraftServer server = MinecraftServer.getServer();
            server.getCommandManager()
                .executeCommand(server, cmd.startsWith("/") ? cmd.substring(1) : cmd);
            DaveBridge.LOG.info("Ran backup command before a confirmed change: {}", cmd);
        } catch (Throwable t) {
            DaveBridge.LOG.warn("Backup command '{}' failed", cmd, t);
        }
    }

    /** Server thread: answers and tells the player about every confirm past its time. */
    static void expireConfirms() {
        List<PendingConfirms.Pending<WriteJob>> expired = CONFIRMS.expire(now());
        for (PendingConfirms.Pending<WriteJob> p : expired) {
            JsonObject r = result(p.payload.id, "write");
            r.addProperty("ok", false);
            r.addProperty("errorType", "expired");
            r.addProperty("error", p.playerName + " did not confirm in time; nothing was run");
            p.payload.request.reply(r);
            EntityPlayerMP player = findPlayer(p.playerName);
            if (player != null) {
                player.addChatMessage(DaveChat.notice("Dave's change expired without a confirm; nothing was changed."));
            }
        }
    }

    /** Server stopping: answers every waiting confirm. */
    public static void serverStopping() {
        ClientEvalRelay.serverStopping();
        for (PendingConfirms.Pending<WriteJob> p : CONFIRMS.clear()) {
            p.payload.request.error(Protocol.ERR_CANCELLED, "server stopping before the confirm");
        }
    }

    // ------------------------------------------------------------------ describe

    private static void handleDescribe(MessageRouter router, Request request) throws ProtocolException {
        String target = request.optString("target", "looking")
            .toLowerCase(Locale.ROOT);
        String playerName = request.optString("player", null);
        JsonObject body = request.body();
        router.runOnMainThread(request, "describe", () -> {
            EntityPlayerMP player = playerName == null ? null : findPlayer(playerName);
            Object described;
            switch (target) {
                case "looking":
                    described = Describe.looking(requirePlayer(player, playerName), optLong(body, "reach", 64));
                    break;
                case "held":
                    described = Describe.item(requirePlayer(player, playerName).getHeldItem());
                    if (described == null) {
                        described = "empty hand";
                    }
                    break;
                case "player":
                    described = Describe.entity(requirePlayer(player, playerName));
                    break;
                case "block": {
                    int dim = (int) optLong(body, "dim", player != null ? player.dimension : 0);
                    World world = DimensionManager.getWorld(dim);
                    if (world == null) {
                        throw new ProtocolException(Protocol.ERR_NOT_FOUND, "dimension " + dim + " is not loaded");
                    }
                    described = Describe.block(
                        world,
                        (int) requireLong(body, "x"),
                        (int) requireLong(body, "y"),
                        (int) requireLong(body, "z"));
                    break;
                }
                case "entity": {
                    int dim = (int) optLong(body, "dim", player != null ? player.dimension : 0);
                    World world = DimensionManager.getWorld(dim);
                    net.minecraft.entity.Entity e = world == null ? null
                        : world.getEntityByID((int) requireLong(body, "entityId"));
                    if (e == null) {
                        throw new ProtocolException(Protocol.ERR_NOT_FOUND, "no such entity in dimension " + dim);
                    }
                    described = Describe.entity(e);
                    break;
                }
                default:
                    throw new ProtocolException(
                        Protocol.ERR_BAD_REQUEST,
                        "target must be looking, held, player, block or entity");
            }
            JsonObject reply = Protocol.message("description");
            reply.addProperty("target", target);
            reply.add("description", JsonDump.dump(described, new JsonDump.Limits(8, 200, 4000, 64 * 1024)));
            return reply;
        });
    }

    private static EntityPlayerMP requirePlayer(EntityPlayerMP player, String name) throws ProtocolException {
        if (player == null) {
            throw new ProtocolException(
                name == null ? Protocol.ERR_BAD_REQUEST : Protocol.ERR_NOT_FOUND,
                name == null ? "this target needs \"player\"" : "player " + name + " is not online");
        }
        return player;
    }

    // ------------------------------------------------------------------ helpers

    static long now() {
        return System.currentTimeMillis();
    }

    /** An online player by name, case-insensitive, or null. Server thread. */
    static EntityPlayerMP findPlayer(String name) {
        if (name == null) {
            return null;
        }
        for (EntityPlayerMP p : DaveChat.onlinePlayers()) {
            if (p.getCommandSenderName()
                .equalsIgnoreCase(name)) {
                return p;
            }
        }
        return null;
    }

    /**
     * Like {@link MessageRouter#runOnMainThread}, but a task may return {@link #PENDING} to answer later itself.
     * Failures become {@code error} replies with the request's reqId.
     */
    static void onMain(Request request, String label, java.util.concurrent.Callable<JsonObject> work) {
        DaveServer.QUEUE.submit(label, work)
            .whenComplete((result, failure) -> {
                try {
                    if (failure == null) {
                        if (result == PENDING) {
                            return;
                        }
                        if (result != null) {
                            request.reply(result);
                        } else {
                            request.ack();
                        }
                        return;
                    }
                    Throwable cause = failure instanceof CompletionException && failure.getCause() != null
                        ? failure.getCause()
                        : failure;
                    if (cause instanceof ProtocolException) {
                        request.error(((ProtocolException) cause).code(), cause.getMessage());
                    } else if (cause instanceof java.util.concurrent.RejectedExecutionException) {
                        request.error(Protocol.ERR_QUEUE_FULL, cause.getMessage());
                    } else if (cause instanceof java.util.concurrent.CancellationException) {
                        request.error(Protocol.ERR_CANCELLED, String.valueOf(cause.getMessage()));
                    } else {
                        DaveBridge.LOG.warn("Main-thread task '{}' failed", label, cause);
                        request.error(Protocol.ERR_INTERNAL, cause.toString());
                    }
                } catch (Throwable t) {
                    DaveBridge.LOG.warn("Failed to report result of '{}'", label, t);
                }
            });
    }

    static long optLong(JsonObject body, String key, long def) throws ProtocolException {
        JsonElement el = body.get(key);
        if (el == null || el.isJsonNull()) {
            return def;
        }
        try {
            return el.getAsLong();
        } catch (RuntimeException e) {
            throw new ProtocolException(Protocol.ERR_BAD_REQUEST, "'" + key + "' must be a number");
        }
    }

    static long requireLong(JsonObject body, String key) throws ProtocolException {
        if (!body.has(key) || body.get(key)
            .isJsonNull()) {
            throw new ProtocolException(Protocol.ERR_BAD_REQUEST, "missing '" + key + "'");
        }
        return optLong(body, key, 0);
    }

    /** JSON params as plain Java maps, lists, strings, doubles and booleans. */
    static Object toJava(JsonElement el) {
        return el == null || el.isJsonNull() ? null : GSON.fromJson(el, Object.class);
    }

    static String clip(String s, int max) {
        return s == null || s.length() <= max ? s : s.substring(0, max) + "...";
    }

    /** For status: how many confirms are waiting. */
    public static int pendingConfirms() {
        return CONFIRMS.size();
    }
}
