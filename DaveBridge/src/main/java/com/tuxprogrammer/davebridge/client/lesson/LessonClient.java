package com.tuxprogrammer.davebridge.client.lesson;

import java.lang.ref.WeakReference;

import net.minecraft.client.Minecraft;
import net.minecraft.client.entity.EntityClientPlayerMP;
import net.minecraft.client.gui.FontRenderer;
import net.minecraft.client.gui.ScaledResolution;
import net.minecraft.client.settings.GameSettings;
import net.minecraft.client.settings.KeyBinding;
import net.minecraft.entity.boss.BossStatus;
import net.minecraft.event.ClickEvent;
import net.minecraft.event.HoverEvent;
import net.minecraft.item.Item;
import net.minecraft.item.ItemStack;
import net.minecraft.nbt.NBTTagCompound;
import net.minecraft.util.ChatComponentText;
import net.minecraft.util.ChatComponentTranslation;
import net.minecraft.util.ChatStyle;
import net.minecraft.util.EnumChatFormatting;
import net.minecraft.util.IChatComponent;
import net.minecraft.util.StatCollector;
import net.minecraft.world.World;
import net.minecraftforge.client.event.RenderGameOverlayEvent;
import net.minecraftforge.client.event.RenderWorldLastEvent;
import net.minecraftforge.common.MinecraftForge;

import com.tuxprogrammer.davebridge.DaveBridge;
import com.tuxprogrammer.davebridge.client.ClientProxy;
import com.tuxprogrammer.davebridge.client.ClientState;
import com.tuxprogrammer.davebridge.common.lesson.LessonLimits;
import com.tuxprogrammer.davebridge.common.network.DaveNetwork;
import com.tuxprogrammer.davebridge.common.protocol.Lesson;
import com.tuxprogrammer.davebridge.common.protocol.LessonStatus;
import com.tuxprogrammer.davebridge.common.protocol.LessonStop;

import cpw.mods.fml.client.registry.ClientRegistry;
import cpw.mods.fml.common.FMLCommonHandler;
import cpw.mods.fml.common.Loader;
import cpw.mods.fml.common.eventhandler.SubscribeEvent;
import cpw.mods.fml.common.gameevent.InputEvent;
import cpw.mods.fml.common.gameevent.TickEvent;
import cpw.mods.fml.common.registry.GameData;

/**
 * Client half of guided demonstrations: receives {@code lesson} / {@code lesson_stop} packets, plays one lesson at a
 * time (a new one replaces the old), and owns the controls: the chat buttons, the stop key (unbound by default, like
 * the Ask key), {@code /davebridge stop|pause}, and auto-stop when the player walks away or changes dimension. Tells
 * the server how each lesson ended ({@code lesson_status}).
 * <p>
 * Everything here runs on the client thread: packet handlers only queue onto {@link ClientProxy#QUEUE}.
 */
public final class LessonClient {

    /** Unbound by default: the GTNH keymap is crowded. */
    public static final KeyBinding STOP_KEY = new KeyBinding(
        "key.davebridge.lessonStop",
        0,
        "key.categories.davebridge");

    /** GregGuns' Golden Revolver: Dave's idle item when GregGuns is installed. Soft dependency, looked up by name. */
    static final String REVOLVER = "gregguns:golden_revolver";

    /**
     * GregGuns' Dictator Dave outfit, so the ghost looks like Dave in game: equipment slot (1 boots .. 4 helmet), item,
     * camo. The same pieces as his GregGuns NPC profile: the red Beret, the Soldier's Vest and Boots, and the Bandit
     * Pants in camo 2. The camo is the armor item's "camo" NBT integer. Soft dependency, looked up by name.
     */
    // Source: GregGuns entity/npc/loot/NpcProfiles.java ("DictatorDave") and entity/npc/NpcEquipment.java (MIT, our
    // mod)
    static final Object[][] OUTFIT = { { 4, "gregguns:t2_beret", 0 }, { 3, "gregguns:t1_combat_chestplate", 0 },
        { 2, "gregguns:t1_scout_leggings", 2 }, { 1, "gregguns:t1_combat_boots", 0 } };

    private static final LessonRenderer RENDERER = new LessonRenderer();
    private static LessonPlayback playing;
    private static GhostDave dave;
    private static WeakReference<World> world = new WeakReference<>(null);
    private static int lastSwings;
    private static String heldKey;
    private static ItemStack heldStack;

    private LessonClient() {}

    /** Packet handlers and event subscriptions. Call from {@code ClientProxy.preInit}. */
    public static void preInit() {
        DaveNetwork.onClient(Lesson.class, packet -> ClientProxy.QUEUE.submit("lesson", () -> start(packet)));
        DaveNetwork.onClient(LessonStop.class, packet -> ClientProxy.QUEUE.submit("lesson_stop", () -> {
            if (playing != null && (packet.id == null || packet.id.isEmpty() || packet.id.equals(playing.id))) {
                stop(LessonStatus.STATE_STOPPED, LessonStatus.REASON_AGENT, "davebridge.lesson.stopped.agent");
            }
        }));
        Events events = new Events();
        FMLCommonHandler.instance()
            .bus()
            .register(events);
        MinecraftForge.EVENT_BUS.register(events);
    }

    /** The stop key. Call from {@code ClientProxy.init}. */
    public static void init() {
        ClientRegistry.registerKeyBinding(STOP_KEY);
    }

    // ---- control ----

    static void start(Lesson packet) {
        Minecraft mc = Minecraft.getMinecraft();
        EntityClientPlayerMP player = mc.thePlayer;
        if (player == null || mc.theWorld == null) {
            return;
        }
        LessonPlayback next;
        try {
            next = new LessonPlayback(packet);
        } catch (IllegalArgumentException e) {
            DaveBridge.LOG.warn("Ignoring lesson {}: {}", packet.id, e.getMessage());
            sendStatus(packet.id, LessonStatus.STATE_STOPPED, LessonStatus.REASON_REJECTED);
            return;
        }
        if (next.dim != player.dimension) {
            sendStatus(next.id, LessonStatus.STATE_STOPPED, LessonStatus.REASON_REJECTED);
            return;
        }
        if (playing != null) {
            sendStatus(playing.id, LessonStatus.STATE_STOPPED, LessonStatus.REASON_REPLACED);
        }
        playing = next;
        world = new WeakReference<>(mc.theWorld);
        dave = new GhostDave(mc.theWorld); // never spawned: see GhostDave
        dressDave(dave);
        lastSwings = 0;
        heldKey = null;
        RENDERER.reset();
        dave.follow(playing, idleItem());
        mc.ingameGUI.getChatGUI()
            .printChatMessage(startedLine(playing.title));
    }

    /** {@code /davebridge stop} and the stop key. Returns false if nothing was playing. */
    public static boolean stopByPlayer() {
        if (playing == null) return false;
        stop(LessonStatus.STATE_STOPPED, LessonStatus.REASON_PLAYER, "davebridge.lesson.stopped.player");
        return true;
    }

    /** {@code /davebridge pause}: toggles pause. Returns the new state, or null if nothing is playing. */
    public static Boolean togglePause() {
        if (playing == null) return null;
        playing.setPaused(!playing.isPaused());
        return playing.isPaused();
    }

    public static boolean isPlaying() {
        return playing != null;
    }

    private static void stop(String state, String reason, String messageKey) {
        LessonPlayback ended = playing;
        playing = null;
        dave = null;
        if (ended == null) return;
        sendStatus(ended.id, state, reason);
        if (messageKey != null) {
            Minecraft mc = Minecraft.getMinecraft();
            if (mc.ingameGUI != null) {
                mc.ingameGUI.getChatGUI()
                    .printChatMessage(gray(new ChatComponentTranslation(messageKey, ClientState.botName)));
            }
        }
    }

    private static void sendStatus(String id, String state, String reason) {
        if (!ClientState.serverHasMod) return;
        LessonStatus status = new LessonStatus();
        status.id = id;
        status.state = state;
        status.reason = reason;
        try {
            DaveNetwork.sendToServer(status);
        } catch (Throwable t) {
            DaveBridge.LOG.debug("Could not send lesson_status", t);
        }
    }

    // ---- per tick ----

    static void tick() {
        if (playing == null) return;
        Minecraft mc = Minecraft.getMinecraft();
        EntityClientPlayerMP player = mc.thePlayer;
        if (player == null || mc.theWorld == null || mc.theWorld != world.get()) {
            playing = null; // left the server or the world: nobody to tell
            dave = null;
            return;
        }
        if (player.dimension != playing.dim) {
            stop(LessonStatus.STATE_STOPPED, LessonStatus.REASON_DIMENSION, "davebridge.lesson.stopped.away");
            return;
        }
        double dx = player.posX - playing.anchor[0], dy = player.posY - playing.anchor[1],
            dz = player.posZ - playing.anchor[2];
        if (dx * dx + dy * dy + dz * dz > LessonLimits.STOP_DISTANCE * LessonLimits.STOP_DISTANCE) {
            stop(LessonStatus.STATE_STOPPED, LessonStatus.REASON_WALKED_AWAY, "davebridge.lesson.stopped.away");
            return;
        }
        playing.tick();
        switch (playing.end()) {
            case FINISHED:
                stop(LessonStatus.STATE_FINISHED, LessonStatus.REASON_DONE, null);
                return;
            case TIMEOUT:
                stop(LessonStatus.STATE_STOPPED, LessonStatus.REASON_TIMEOUT, "davebridge.lesson.stopped.timeout");
                return;
            default:
                break;
        }
        dave.follow(playing, heldItem(playing));
        if (playing.swings != lastSwings) {
            lastSwings = playing.swings;
            dave.swing();
        }
    }

    /** The item Dave holds now: the lesson's, or his revolver when the lesson never said. */
    private static ItemStack heldItem(LessonPlayback p) {
        if (p.held == null) return idleItem();
        String key = p.held + "@" + p.heldMeta;
        if (!key.equals(heldKey)) {
            heldKey = key;
            heldStack = null;
            if (!p.held.isEmpty()) {
                Item item = (Item) GameData.getItemRegistry()
                    .getObject(p.held);
                heldStack = item == null ? null : new ItemStack(item, 1, p.heldMeta);
            }
        }
        return heldStack;
    }

    /** Puts Dave's GregGuns outfit on the ghost; any piece that isn't registered is left off. */
    private static void dressDave(GhostDave ghost) {
        if (!Loader.isModLoaded("gregguns")) return;
        for (Object[] piece : OUTFIT) {
            Item item = (Item) GameData.getItemRegistry()
                .getObject((String) piece[1]);
            if (item == null) continue;
            ItemStack stack = new ItemStack(item);
            NBTTagCompound tag = new NBTTagCompound();
            tag.setInteger("camo", (Integer) piece[2]);
            stack.setTagCompound(tag);
            ghost.setCurrentItemOrArmor((Integer) piece[0], stack);
        }
    }

    private static ItemStack idleItem() {
        if (!Loader.isModLoaded("gregguns")) return null;
        Item revolver = (Item) GameData.getItemRegistry()
            .getObject(REVOLVER);
        return revolver == null ? null : new ItemStack(revolver);
    }

    // ---- chat and HUD text ----

    private static IChatComponent startedLine(String title) {
        IChatComponent line = new ChatComponentText("[" + ClientState.botName + "] ")
            .setChatStyle(new ChatStyle().setColor(EnumChatFormatting.AQUA));
        IChatComponent text = title.isEmpty()
            ? new ChatComponentTranslation("davebridge.lesson.started", ClientState.botName)
            : new ChatComponentTranslation("davebridge.lesson.startedTitled", ClientState.botName, title);
        line.appendSibling(text.setChatStyle(new ChatStyle().setColor(EnumChatFormatting.GRAY)));
        line.appendText(" ");
        line.appendSibling(button("davebridge.lesson.button.pause", "/davebridge pause", EnumChatFormatting.YELLOW));
        line.appendText(" ");
        line.appendSibling(button("davebridge.lesson.button.stop", "/davebridge stop", EnumChatFormatting.RED));
        return line;
    }

    private static IChatComponent button(String key, String command, EnumChatFormatting color) {
        return new ChatComponentTranslation(key).setChatStyle(
            new ChatStyle().setColor(color)
                .setChatClickEvent(new ClickEvent(ClickEvent.Action.RUN_COMMAND, command))
                .setChatHoverEvent(new HoverEvent(HoverEvent.Action.SHOW_TEXT, new ChatComponentText(command))));
    }

    private static IChatComponent gray(IChatComponent c) {
        return c.setChatStyle(new ChatStyle().setColor(EnumChatFormatting.GRAY));
    }

    /** "Title · Step 3/7 · [K] stop" (or the pause state). */
    static String hudText(LessonPlayback p) {
        String control;
        if (p.isPaused()) {
            control = StatCollector.translateToLocal("davebridge.lesson.hud.paused");
        } else if (STOP_KEY.getKeyCode() != 0) {
            control = StatCollector.translateToLocalFormatted(
                "davebridge.lesson.hud.stopKey",
                GameSettings.getKeyDisplayString(STOP_KEY.getKeyCode()));
        } else {
            control = StatCollector.translateToLocal("davebridge.lesson.hud.stopCommand");
        }
        String title = p.title.isEmpty() ? ClientState.botName : p.title;
        return StatCollector
            .translateToLocalFormatted("davebridge.lesson.hud", title, p.stepNumber(), p.stepCount(), control);
    }

    /** Event subscriptions. Public, with public methods: FML generates the dispatcher in another package. */
    public static final class Events {

        @SubscribeEvent
        public void onClientTick(TickEvent.ClientTickEvent event) {
            if (event.phase != TickEvent.Phase.END) return;
            try {
                tick();
            } catch (Throwable t) {
                DaveBridge.LOG.warn("Lesson tick failed; stopping the lesson", t);
                playing = null;
                dave = null;
            }
        }

        @SubscribeEvent
        public void onKeyInput(InputEvent.KeyInputEvent event) {
            try {
                if (STOP_KEY.isPressed() && Minecraft.getMinecraft().currentScreen == null) {
                    stopByPlayer();
                }
            } catch (Throwable t) {
                DaveBridge.LOG.warn("Lesson stop key failed", t);
            }
        }

        @SubscribeEvent
        public void onRenderWorldLast(RenderWorldLastEvent event) {
            LessonPlayback p = playing;
            if (p == null) return;
            try {
                RENDERER.render(p, dave, event.partialTicks);
            } catch (Throwable t) {
                DaveBridge.LOG.warn("Lesson render failed", t);
            }
        }

        @SubscribeEvent
        public void onOverlay(RenderGameOverlayEvent.Post event) {
            LessonPlayback p = playing;
            if (p == null || event.type != RenderGameOverlayEvent.ElementType.ALL) return;
            try {
                Minecraft mc = Minecraft.getMinecraft();
                FontRenderer font = mc.fontRenderer;
                ScaledResolution res = event.resolution;
                String text = hudText(p);
                int y = BossStatus.bossName != null && BossStatus.statusBarTime > 0 ? 22 : 3;
                int x = (res.getScaledWidth() - font.getStringWidth(text)) / 2;
                font.drawStringWithShadow(text, x, y, 0xFFE0E0E0);
            } catch (Throwable t) {
                DaveBridge.LOG.debug("Lesson HUD failed", t);
            }
        }
    }
}
