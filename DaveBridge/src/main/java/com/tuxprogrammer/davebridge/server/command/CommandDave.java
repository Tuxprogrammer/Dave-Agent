package com.tuxprogrammer.davebridge.server.command;

import java.util.List;

import net.minecraft.command.CommandBase;
import net.minecraft.command.ICommandSender;
import net.minecraft.command.WrongUsageException;
import net.minecraft.util.ChatComponentText;
import net.minecraft.util.ChatStyle;
import net.minecraft.util.EnumChatFormatting;
import net.minecraft.util.IChatComponent;

import com.tuxprogrammer.davebridge.Tags;
import com.tuxprogrammer.davebridge.common.Config;
import com.tuxprogrammer.davebridge.common.tasks.MainThreadQueue;
import com.tuxprogrammer.davebridge.server.DaveServer;
import com.tuxprogrammer.davebridge.server.bridge.BridgeService;
import com.tuxprogrammer.davebridge.server.bridge.ClientSession;
import com.tuxprogrammer.davebridge.server.eval.EvalService;

/**
 * {@code /dave status} and {@code /dave reload} (ops only, permission level 3), and {@code /dave confirm|cancel <id>},
 * the targets of the Confirm and Cancel buttons for world-changing scripts, which any player may run (only the asked
 * player's click counts; see {@code EvalService}).
 */
public class CommandDave extends CommandBase {

    @Override
    public String getCommandName() {
        return "dave";
    }

    @Override
    public String getCommandUsage(ICommandSender sender) {
        return "/dave <status|reload|pending|ask <asName> [@x,y,z,dim] <question>|confirm <id>|cancel <id>>";
    }

    /** Everyone may run the command; status and reload check for op level 3 themselves. */
    @Override
    public boolean canCommandSenderUseCommand(ICommandSender sender) {
        return true;
    }

    @Override
    public int getRequiredPermissionLevel() {
        return 3;
    }

    @Override
    public void processCommand(ICommandSender sender, String[] args) {
        String sub = args.length == 0 ? "status" : args[0];
        if ("confirm".equalsIgnoreCase(sub) || "cancel".equalsIgnoreCase(sub)) {
            if (args.length < 2) {
                throw new WrongUsageException("/dave " + sub.toLowerCase(java.util.Locale.ROOT) + " <id>");
            }
            sender.addChatMessage(EvalService.onConfirmCommand(sender, args[1], "confirm".equalsIgnoreCase(sub)));
            return;
        }
        if (!sender.canCommandSenderUseCommand(getRequiredPermissionLevel(), getCommandName())) {
            throw new net.minecraft.command.CommandException("commands.generic.permission");
        }
        if ("status".equalsIgnoreCase(sub)) {
            status(sender);
        } else if ("reload".equalsIgnoreCase(sub)) {
            if (DaveServer.reload()) {
                send(sender, "DaveBridge config reloaded.", EnumChatFormatting.GREEN);
            } else {
                send(
                    sender,
                    "davebridge.cfg could not be parsed; kept the previous settings. See the server log.",
                    EnumChatFormatting.RED);
            }
            status(sender);
        } else if ("ask".equalsIgnoreCase(sub)) {
            TestHooks.Ask ask = TestHooks.parseAsk(args, 1);
            if (ask == null) {
                throw new WrongUsageException("/dave ask <asName> [@x,y,z[,dim]] <question...>");
            }
            int agents = TestHooks.sendAsk(ask);
            send(
                sender,
                agents == 0 ? "No agent is connected; nothing was sent."
                    : "Sent to " + agents + " agent(s) as " + ask.name + ": " + ask.question,
                agents == 0 ? EnumChatFormatting.RED : EnumChatFormatting.GRAY);
        } else if ("pending".equalsIgnoreCase(sub)) {
            java.util.List<String> lines = EvalService.describePending();
            send(sender, lines.size() + " change(s) waiting for a confirm", EnumChatFormatting.AQUA);
            for (String line : lines) {
                send(sender, " " + line, null);
            }
        } else {
            throw new WrongUsageException(getCommandUsage(sender));
        }
    }

    private static void status(ICommandSender sender) {
        BridgeService bridge = DaveServer.BRIDGE;
        MainThreadQueue queue = DaveServer.QUEUE;
        send(sender, "DaveBridge " + Tags.VERSION, EnumChatFormatting.AQUA);
        String socket;
        if (bridge.isListening()) {
            socket = "listening on " + Config.bindAddress + ":" + Config.port;
        } else if (bridge.isStarted()) {
            socket = "starting on " + Config.bindAddress + ":" + Config.port;
        } else if (bridge.lastError() != null) {
            socket = "FAILED: " + bridge.lastError();
        } else {
            socket = Config.enabled ? "stopped" : "disabled in config";
        }
        send(sender, " Socket: " + socket, null);
        send(
            sender,
            " Agents: " + bridge.authenticatedCount() + " authenticated, " + bridge.connectionCount() + " connected",
            null);
        for (ClientSession session : bridge.sessions()) {
            send(sender, "  - " + session + (session.isAuthenticated() ? "" : " (not authenticated)"), null);
        }
        send(
            sender,
            String.format(
                " Queue: %d/%d pending, %d run, %d failed, last tick %d tasks in %.2f ms",
                queue.depth(),
                queue.maxDepth(),
                queue.executedCount(),
                queue.failedCount(),
                queue.lastDrainCount(),
                queue.lastDrainNanos() / 1_000_000.0),
            null);
        send(sender, " Players with the client mod: " + DaveServer.CLIENTS.count(), null);
        send(sender, " Changes waiting for a confirm: " + EvalService.pendingConfirms(), null);
    }

    private static void send(ICommandSender sender, String text, EnumChatFormatting color) {
        IChatComponent c = new ChatComponentText(text);
        if (color != null) {
            c.setChatStyle(new ChatStyle().setColor(color));
        }
        sender.addChatMessage(c);
    }

    @Override
    public List<String> addTabCompletionOptions(ICommandSender sender, String[] args) {
        return args.length == 1 ? getListOfStringsMatchingLastWord(args, "status", "reload", "pending", "ask") : null;
    }
}
