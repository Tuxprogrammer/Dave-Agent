package com.tuxprogrammer.davebridge;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

import com.tuxprogrammer.davebridge.common.CommonProxy;

import cpw.mods.fml.common.Mod;
import cpw.mods.fml.common.SidedProxy;
import cpw.mods.fml.common.event.FMLInitializationEvent;
import cpw.mods.fml.common.event.FMLPreInitializationEvent;
import cpw.mods.fml.common.event.FMLServerStartedEvent;
import cpw.mods.fml.common.event.FMLServerStartingEvent;
import cpw.mods.fml.common.event.FMLServerStoppingEvent;

/**
 * Bridge between the game and an external AI agent ("Dave").
 * <p>
 * The server half owns a local WebSocket the agent connects to and is the only thing that talks to the agent. The
 * optional client half talks to the server over the {@code davebridge} packet channel and never to the agent.
 * {@code acceptableRemoteVersions = "*"} lets players without the mod join and use Dave through plain chat, and lets
 * clients with the mod join servers without it.
 * <p>
 * Side split: {@code common} is loaded everywhere, {@code server} holds the logical-server code (also used by an
 * integrated server) and {@code client} is only ever reached through the {@link SidedProxy}.
 */
@Mod(
    modid = DaveBridge.MODID,
    version = Tags.VERSION,
    name = "DaveBridge",
    acceptedMinecraftVersions = "[1.7.10]",
    acceptableRemoteVersions = "*",
    guiFactory = "com.tuxprogrammer.davebridge.client.GuiFactory")
public class DaveBridge {

    public static final String MODID = "davebridge";
    public static final Logger LOG = LogManager.getLogger(MODID);

    @SidedProxy(
        clientSide = "com.tuxprogrammer.davebridge.client.ClientProxy",
        serverSide = "com.tuxprogrammer.davebridge.common.CommonProxy")
    public static CommonProxy proxy;

    @Mod.EventHandler
    public void preInit(FMLPreInitializationEvent event) {
        proxy.preInit(event);
    }

    @Mod.EventHandler
    public void init(FMLInitializationEvent event) {
        proxy.init(event);
    }

    @Mod.EventHandler
    public void serverStarting(FMLServerStartingEvent event) {
        proxy.serverStarting(event);
    }

    @Mod.EventHandler
    public void serverStarted(FMLServerStartedEvent event) {
        proxy.serverStarted(event);
    }

    @Mod.EventHandler
    public void serverStopping(FMLServerStoppingEvent event) {
        proxy.serverStopping(event);
    }
}
