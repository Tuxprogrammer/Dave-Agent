package com.tuxprogrammer.davebridge.client;

import java.lang.ref.WeakReference;

import net.minecraft.client.Minecraft;

import com.tuxprogrammer.davebridge.DaveBridge;
import com.tuxprogrammer.davebridge.Tags;
import com.tuxprogrammer.davebridge.client.compat.NeiPages;
import com.tuxprogrammer.davebridge.common.network.DaveNetwork;
import com.tuxprogrammer.davebridge.common.protocol.ClientHello;

import cpw.mods.fml.client.event.ConfigChangedEvent;
import cpw.mods.fml.common.eventhandler.SubscribeEvent;
import cpw.mods.fml.common.gameevent.InputEvent;
import cpw.mods.fml.common.gameevent.TickEvent;
import cpw.mods.fml.common.network.FMLNetworkEvent;

/** Client tick (queue drain, hello, opt-in nudge), config screen, disconnect and key handling. */
public class ClientEventHandler {

    private static final long CLIENT_TICK_BUDGET_NANOS = 2_000_000L;

    @SubscribeEvent
    public void onClientTick(TickEvent.ClientTickEvent event) {
        if (event.phase != TickEvent.Phase.END) {
            return;
        }
        try {
            ClientProxy.QUEUE.drain(CLIENT_TICK_BUDGET_NANOS);
            sendHelloIfNewConnection();
            DaveChatRenderer.tick();
            OptIn.tick();
        } catch (Throwable t) {
            DaveBridge.LOG.warn("DaveBridge client tick failed", t);
        }
    }

    /**
     * Says hello once per connection, after the player exists (so the play-state channel is up). Detecting a new
     * connection by the net handler's identity also covers reconnects and singleplayer.
     */
    private static void sendHelloIfNewConnection() {
        Minecraft mc = Minecraft.getMinecraft();
        Object handler = mc.getNetHandler();
        if (mc.thePlayer == null || handler == null || ClientState.helloConnection.get() == handler) {
            return;
        }
        ClientState.helloConnection = new WeakReference<>(handler);
        ClientState.reset();
        ClientHello hello = new ClientHello();
        hello.modVersion = Tags.VERSION;
        // "eval": this client can run client_eval_request (only acted on when clientEvalAllowed is true).
        hello.capabilities = NeiPages.available()
            ? new String[] { "render", "ask", "context", "lesson", "nei", "eval" }
            : new String[] { "render", "ask", "context", "lesson", "eval" };
        hello.clientEvalAllowed = ClientConfig.clientEvalAllowed;
        DaveNetwork.sendToServer(hello);
    }

    /** The config screen was closed with changes: re-read them and tell the server if the opt-in changed. */
    @SubscribeEvent
    public void onConfigChanged(ConfigChangedEvent.OnConfigChangedEvent event) {
        try {
            if (!DaveBridge.MODID.equals(event.modID)) {
                return;
            }
            boolean wasAllowed = ClientConfig.clientEvalAllowed;
            ClientConfig.config.save();
            ClientConfig.sync();
            if (wasAllowed != ClientConfig.clientEvalAllowed) {
                OptIn.tellServer();
            }
        } catch (Throwable t) {
            DaveBridge.LOG.warn("DaveBridge config change failed", t);
        }
    }

    @SubscribeEvent
    public void onDisconnect(FMLNetworkEvent.ClientDisconnectionFromServerEvent event) {
        // netty thread: only touch thread-safe state here
        ClientState.serverHasMod = false;
        DaveNetwork.resetClientStreams();
    }

    @SubscribeEvent
    public void onKeyInput(InputEvent.KeyInputEvent event) {
        try {
            if (!ClientProxy.ASK_KEY.isPressed()) {
                return;
            }
            Minecraft mc = Minecraft.getMinecraft();
            if (mc.thePlayer == null || mc.currentScreen != null) {
                return;
            }
            mc.displayGuiScreen(new GuiDaveChat(ClientConfig.askPrefix, ContextCapture.capture(mc)));
        } catch (Throwable t) {
            DaveBridge.LOG.warn("DaveBridge ask key failed", t);
        }
    }
}
