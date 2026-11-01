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

/** {@code /dave status} and {@code /dave reload}. Ops only (permission level 3). */
public class CommandDave extends CommandBase {

    @Override
    public String getCommandName() {
        return "dave";
    }

    @Override
    public String getCommandUsage(ICommandSender sender) {
        return "/dave <status|reload>";
    }

    @Override
    public int getRequiredPermissionLevel() {
        return 3;
    }

    @Override
    public void processCommand(ICommandSender sender, String[] args) {
        String sub = args.length == 0 ? "status" : args[0];
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
        return args.length == 1 ? getListOfStringsMatchingLastWord(args, "status", "reload") : null;
    }
}
