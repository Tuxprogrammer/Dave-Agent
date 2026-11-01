package com.tuxprogrammer.davebridge.client.lesson;

import net.minecraft.command.ICommandSender;
import net.minecraft.util.ChatComponentTranslation;
import net.minecraft.util.ChatStyle;
import net.minecraft.util.EnumChatFormatting;

/**
 * {@code /davebridge stop} and {@code /davebridge pause}, the targets of the lesson's chat buttons. Kept out of
 * {@code ClientCommandDaveBridge} so that class only needs one call.
 */
public final class LessonCommands {

    private LessonCommands() {}

    /** Handles {@code sub} if it is a lesson subcommand. Returns false otherwise. */
    public static boolean handle(String sub, ICommandSender sender) {
        if ("stop".equals(sub)) {
            if (!LessonClient.stopByPlayer()) {
                sender.addChatMessage(gray("davebridge.lesson.none"));
            }
            return true;
        }
        if ("pause".equals(sub)) {
            Boolean paused = LessonClient.togglePause();
            sender.addChatMessage(
                gray(
                    paused == null ? "davebridge.lesson.none"
                        : paused ? "davebridge.lesson.paused" : "davebridge.lesson.resumed"));
            return true;
        }
        return false;
    }

    private static ChatComponentTranslation gray(String key) {
        ChatComponentTranslation c = new ChatComponentTranslation(key);
        c.setChatStyle(new ChatStyle().setColor(EnumChatFormatting.GRAY));
        return c;
    }
}
