package dev.gtnhplanner.calcoracle;

import cpw.mods.fml.common.FMLCommonHandler;
import cpw.mods.fml.common.Loader;
import cpw.mods.fml.common.Mod;
import cpw.mods.fml.common.event.FMLInitializationEvent;
import cpw.mods.fml.common.event.FMLServerStartedEvent;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

import java.lang.reflect.Method;
import java.util.concurrent.atomic.AtomicBoolean;

@Mod(modid = GtnhCalcOracleMod.MODID, name = "GTNH Calculation Oracle", version = Tags.VERSION)
public final class GtnhCalcOracleMod {

    public static final String MODID = "gtnhcalcoracle";
    public static final Logger LOG = LogManager.getLogger("GTNHCalcOracle");

    private static final AtomicBoolean AUTORUN_STARTED = new AtomicBoolean(false);

    @Mod.EventHandler
    public void init(FMLInitializationEvent event) {
        if (!Boolean.getBoolean("gtnh.oracle.autorun")) {
            return;
        }

        LOG.info("GTNH calculation oracle autorun enabled.");
        if (FMLCommonHandler.instance().getSide().isClient()) {
            registerClientAutorunHandler();
        }
    }

    @Mod.EventHandler
    public void serverStarted(FMLServerStartedEvent event) {
        if (FMLCommonHandler.instance().getSide().isClient()) {
            return;
        }

        requestAutorunExport("server-started");
    }

    public static void requestAutorunExport(String trigger) {
        if (!Boolean.getBoolean("gtnh.oracle.autorun")) {
            return;
        }

        if (!AUTORUN_STARTED.compareAndSet(false, true)) {
            return;
        }

        Runnable task = new Runnable() {
            @Override
            public void run() {
                try {
                    LOG.info("GTNH calculation oracle export started from {}.", trigger);
                    GtnhCalcOracleExporter.ExportResult result = new GtnhCalcOracleExporter().export();
                    LOG.info(
                        "GTNH calculation oracle export wrote {} with {} recipe(s) across {} adapter(s).",
                        result.outputFile,
                        Integer.valueOf(result.recipeCount),
                        Integer.valueOf(result.adapterCount)
                    );
                } catch (Throwable t) {
                    LOG.error("GTNH calculation oracle export failed.", t);
                    FMLCommonHandler.instance().exitJava(2, false);
                    return;
                }

                if (
                    Boolean.getBoolean("gtnh.oracle.renderIcons")
                        && FMLCommonHandler.instance().getSide().isClient()
                ) {
                    exportQueuedIconsThenExit();
                    return;
                }

                FMLCommonHandler.instance().exitJava(0, false);
            }
        };

        Thread thread = new Thread(task);
        thread.setDaemon(false);
        thread.setName("gtnh-calc-oracle-export");
        thread.start();
    }

    private static void registerClientAutorunHandler() {
        try {
            Class<?> handlerClass = Class.forName("dev.gtnhplanner.calcoracle.ClientAutorunHandler");
            Object handler = handlerClass.getConstructor().newInstance();
            FMLCommonHandler.instance().bus().register(handler);
            LOG.info("GTNH calculation oracle client autorun handler registered.");
        } catch (Throwable t) {
            LOG.error("Could not register GTNH calculation oracle client autorun handler.", t);
            FMLCommonHandler.instance().exitJava(2, false);
        }
    }

    private static void exportQueuedIconsThenExit() {
        try {
            Class<?> renderer = Class.forName("dev.gtnhplanner.calcoracle.icons.ClientItemStackIconRenderer");
            Method method = renderer.getMethod("exportQueuedIconsThen", Runnable.class);
            method.invoke(null, new Runnable() {
                @Override
                public void run() {
                    LOG.info("GTNH calculation oracle icon export finished.");
                    FMLCommonHandler.instance().exitJava(0, false);
                }
            });
        } catch (Throwable t) {
            LOG.error("GTNH calculation oracle queued icon export failed.", t);
            FMLCommonHandler.instance().exitJava(2, false);
        }
    }

    static boolean isModLoaded(String modId) {
        try {
            return Loader.isModLoaded(modId);
        } catch (Throwable ignored) {
            return false;
        }
    }
}
