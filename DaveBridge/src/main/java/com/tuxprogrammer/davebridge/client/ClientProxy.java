package com.tuxprogrammer.davebridge.client;

import java.io.File;

import net.minecraft.client.settings.KeyBinding;
import net.minecraftforge.client.ClientCommandHandler;

import com.tuxprogrammer.davebridge.DaveBridge;
import com.tuxprogrammer.davebridge.common.CommonProxy;
import com.tuxprogrammer.davebridge.common.network.DaveNetwork;
import com.tuxprogrammer.davebridge.common.protocol.ClientEvalRequest;
import com.tuxprogrammer.davebridge.common.protocol.DaveMessage;
import com.tuxprogrammer.davebridge.common.protocol.DavePackets;
import com.tuxprogrammer.davebridge.common.protocol.ServerHello;
import com.tuxprogrammer.davebridge.common.protocol.Thinking;
import com.tuxprogrammer.davebridge.common.tasks.MainThreadQueue;

import cpw.mods.fml.client.registry.ClientRegistry;
import cpw.mods.fml.common.FMLCommonHandler;
import cpw.mods.fml.common.event.FMLInitializationEvent;
import cpw.mods.fml.common.event.FMLPreInitializationEvent;

/**
 * Client half. Only ever loaded through {@code @SidedProxy} on a physical client. Adds packet handlers that render
 * Dave's messages, the "Ask Dave" key and the client hello, on top of everything {@link CommonProxy} does (a client
 * still needs the server half for singleplayer).
 */
public class ClientProxy extends CommonProxy {

    /** Client-thread work queue, drained on the client tick. Packet handlers may run off-thread and submit here. */
    public static final MainThreadQueue QUEUE = new MainThreadQueue();

    /** Unbound by default: the GTNH keymap is crowded, players pick a key in Controls. */
    public static final KeyBinding ASK_KEY = new KeyBinding("key.davebridge.ask", 0, "key.categories.davebridge");

    @Override
    public void preInit(FMLPreInitializationEvent event) {
        super.preInit(event);
        ClientConfig.init(new File(event.getModConfigurationDirectory(), "davebridge-client.cfg"));

        DaveNetwork.onClient(ServerHello.class, packet -> QUEUE.submit("server_hello", () -> {
            if (packet.protocol != DavePackets.PROTOCOL_VERSION) {
                // The server treats us as a plain client too, so both sides fall back to ordinary chat.
                DaveBridge.LOG.warn(
                    "Server runs DaveBridge {} with packet protocol {}, this client speaks {}: using plain chat",
                    packet.modVersion,
                    packet.protocol,
                    DavePackets.PROTOCOL_VERSION);
                DaveChatRenderer.notice(
                    "DaveBridge: this server runs a different DaveBridge version (protocol " + packet.protocol
                        + "); the Ask key and links fall back to plain chat.");
                return;
            }
            ClientState.serverHasMod = true;
            if (packet.botName != null) {
                ClientState.botName = packet.botName;
            }
            if (packet.triggerPrefixes != null) {
                ClientState.triggerPrefixes = packet.triggerPrefixes;
            }
            ClientState.maxAskLength = ClientState.askLimit(packet.maxAskLength);
            DaveBridge.LOG.info("Server runs DaveBridge {}", packet.modVersion);
            OptIn.onServerHello();
        }));
        DaveNetwork.onClient(
            DaveMessage.class,
            packet -> QUEUE.submit("dave_message", () -> DaveChatRenderer.showMessage(packet)));
        DaveNetwork.onClient(Thinking.class, packet -> QUEUE.submit("thinking", () -> {
            if (packet.clear) {
                DaveChatRenderer.clearThinking(); // the answer arrived
            } else {
                DaveChatRenderer.showThinking(packet.botName);
            }
        }));
        DaveNetwork.onClient(ClientEvalRequest.class, packet -> {
            // Reserved for milestone 2. Never executed in milestone 1, whatever clientEvalAllowed says.
            DaveBridge.LOG.warn("Ignoring client_eval_request {}: client eval is not implemented", packet.id);
        });

        FMLCommonHandler.instance()
            .bus()
            .register(new ClientEventHandler());
    }

    @Override
    public void init(FMLInitializationEvent event) {
        super.init(event);
        ClientRegistry.registerKeyBinding(ASK_KEY);
        ClientCommandHandler.instance.registerCommand(new ClientCommandDaveBridge());
    }
}
