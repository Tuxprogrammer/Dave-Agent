package com.tuxprogrammer.davebridge.common;

import com.tuxprogrammer.davebridge.DaveBridge;
import com.tuxprogrammer.davebridge.Tags;
import com.tuxprogrammer.davebridge.common.network.DaveNetwork;
import com.tuxprogrammer.davebridge.server.DaveServer;

import cpw.mods.fml.common.event.FMLInitializationEvent;
import cpw.mods.fml.common.event.FMLPreInitializationEvent;
import cpw.mods.fml.common.event.FMLServerStartedEvent;
import cpw.mods.fml.common.event.FMLServerStartingEvent;
import cpw.mods.fml.common.event.FMLServerStoppingEvent;

/**
 * Proxy used on the dedicated server, and the base of {@code client.ClientProxy}. Everything here is safe on both
 * physical sides; the logical-server part lives in {@link DaveServer}, which a client also needs for singleplayer.
 */
public class CommonProxy {

    public void preInit(FMLPreInitializationEvent event) {
        Config.init(event.getSuggestedConfigurationFile());
        DaveBridge.LOG.info("DaveBridge {} loading", Tags.VERSION);
        DaveNetwork.init();
        DaveServer.init();
    }

    public void init(FMLInitializationEvent event) {}

    public void serverStarting(FMLServerStartingEvent event) {
        DaveServer.serverStarting(event);
    }

    public void serverStarted(FMLServerStartedEvent event) {
        DaveServer.serverStarted();
    }

    public void serverStopping(FMLServerStoppingEvent event) {
        DaveServer.serverStopping();
    }
}
