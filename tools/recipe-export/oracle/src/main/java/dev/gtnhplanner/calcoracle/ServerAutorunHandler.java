package dev.gtnhplanner.calcoracle;

import cpw.mods.fml.common.eventhandler.SubscribeEvent;
import cpw.mods.fml.common.gameevent.TickEvent;

/**
 * Dave patch: on a dedicated server, export after the server has ticked, not on FMLServerStarted.
 *
 * Some mods change recipes on the first server tick. GTNHRates divides the duration of every recipe in every
 * GregTech recipe map (and the assembly line's research time) in its first ServerTickEvent, so an export started
 * on FMLServerStarted shows stock durations, and its export thread raced the tick that rewrites them. Waiting
 * gtnh.oracle.serverDelayTicks (default 20) completed ticks exports what the server actually runs. 0 restores the
 * old behaviour.
 */
public final class ServerAutorunHandler {

    private final int delayTicks;
    private int ticks;
    private boolean started;

    public ServerAutorunHandler(int delayTicks) {
        this.delayTicks = delayTicks;
    }

    @SubscribeEvent
    public void onServerTick(TickEvent.ServerTickEvent event) {
        if (event.phase != TickEvent.Phase.END || started) {
            return;
        }

        ticks++;
        if (ticks < delayTicks) {
            return;
        }

        started = true;
        GtnhCalcOracleMod.LOG.info("GTNH calculation oracle server export after {} tick(s).", Integer.valueOf(ticks));
        GtnhCalcOracleMod.requestAutorunExport("server-tick");
    }
}
