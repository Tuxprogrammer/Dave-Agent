package dev.gtnhplanner.calcoracle.icons;

import java.awt.image.BufferedImage;
import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;

import javax.imageio.ImageIO;

import dev.gtnhplanner.calcoracle.GtnhCalcOracleMod;

import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiScreen;
import net.minecraft.client.renderer.Tessellator;
import net.minecraft.client.renderer.texture.TextureMap;
import net.minecraft.client.shader.Framebuffer;
import net.minecraft.util.IIcon;
import net.minecraftforge.fluids.Fluid;
import net.minecraftforge.fluids.FluidStack;
import org.lwjgl.BufferUtils;
import org.lwjgl.opengl.GL11;

public final class ClientFluidStackIconRenderer {

    private static final int ICON_SIZE = Integer.getInteger("gtnh.oracle.iconSize", 256);
    private static final int GUI_ICON_CANVAS_SIZE = 32;
    private static final int GUI_ITEM_SIZE = 16;
    private static final int ICON_EXPORT_BATCH_SIZE = Integer.getInteger("gtnh.oracle.iconExportBatchSize", 64);
    private static final int ICON_PROGRESS_EVERY = Integer.getInteger("gtnh.oracle.iconProgressEvery", 256);
    private static final int MAX_RENDER_WARNINGS = Integer.getInteger("gtnh.oracle.maxFluidIconRenderWarnings", 50);
    private static final Map<String, String> ICONS_BY_FLUID_KEY = new LinkedHashMap<String, String>();
    private static final Map<String, FluidStack> PENDING_FLUIDS_BY_KEY = new LinkedHashMap<String, FluidStack>();
    private static int renderWarnings;

    private ClientFluidStackIconRenderer() {}

    public static String captureIcon(FluidStack stack) {
        if (stack == null || stack.getFluid() == null) {
            return null;
        }

        String key = fluidKey(stack);
        if (ICONS_BY_FLUID_KEY.containsKey(key)) {
            String value = ICONS_BY_FLUID_KEY.get(key);
            return value != null && value.length() > 0 ? value : null;
        }

        try {
            String filename = safeName(stack) + "-" + sha1(key).substring(0, 12) + ".png";
            ICONS_BY_FLUID_KEY.put(key, filename);
            PENDING_FLUIDS_BY_KEY.put(key, stack.copy());
            return filename;
        } catch (Throwable t) {
            ICONS_BY_FLUID_KEY.put(key, "");
            warnRenderFailure(stack, t);
            return null;
        } finally {
            ClientItemStackIconRenderer.resetTessellator();
        }
    }

    public static void exportQueuedIconsThen(Runnable afterExport) {
        Minecraft minecraft = Minecraft.getMinecraft();
        if (minecraft == null) {
            afterExport.run();
            return;
        }

        minecraft.displayGuiScreen(new QueuedFluidIconExportScreen(afterExport));
    }

    private static final class QueuedFluidIconExportScreen extends GuiScreen {

        private final Runnable afterExport;
        private final Iterator<Map.Entry<String, FluidStack>> iterator;
        private final int total;
        private int processed;
        private int rendered;
        private int cacheHits;
        private int skipped;
        private boolean finished;

        private QueuedFluidIconExportScreen(Runnable afterExport) {
            this.afterExport = afterExport;
            this.iterator = PENDING_FLUIDS_BY_KEY.entrySet().iterator();
            this.total = PENDING_FLUIDS_BY_KEY.size();
            GtnhCalcOracleMod.LOG.info(
                "GTNH 1.7.10 fluid icon batch started: "
                    + total
                    + " queued, size "
                    + ICON_SIZE
                    + "px, batch "
                    + ICON_EXPORT_BATCH_SIZE
                    + "."
            );
        }

        @Override
        public void drawScreen(int mouseX, int mouseY, float partialTicks) {
            if (finished) {
                return;
            }

            int batch = 0;
            while (batch < ICON_EXPORT_BATCH_SIZE && iterator.hasNext()) {
                Map.Entry<String, FluidStack> entry = iterator.next();
                processed++;
                batch++;
                try {
                    MaterializedFluidIconResult result = materializeIcon(entry.getKey(), entry.getValue());
                    if (result == MaterializedFluidIconResult.RENDERED) {
                        rendered++;
                    } else if (result == MaterializedFluidIconResult.CACHE_HIT) {
                        cacheHits++;
                    } else {
                        skipped++;
                    }
                } catch (Throwable t) {
                    skipped++;
                    ICONS_BY_FLUID_KEY.put(entry.getKey(), "");
                    warnRenderFailure(entry.getValue(), t);
                }

                if (processed % ICON_PROGRESS_EVERY == 0 || processed == total) {
                    GtnhCalcOracleMod.LOG.info(
                        "GTNH fluid icon progress "
                            + processed
                            + "/"
                            + total
                            + " (rendered "
                            + rendered
                            + ", cache "
                            + cacheHits
                            + ", skipped "
                            + skipped
                            + ")."
                    );
                }
            }

            if (!iterator.hasNext()) {
                finished = true;
                writeIconMap();
                GtnhCalcOracleMod.LOG.info(
                    "GTNH fluid icon batch finished: rendered "
                        + rendered
                        + ", cache "
                        + cacheHits
                        + ", skipped "
                        + skipped
                        + "."
                );
                afterExport.run();
            }
        }
    }

    private enum MaterializedFluidIconResult {
        RENDERED,
        CACHE_HIT,
        SKIPPED
    }

    private static MaterializedFluidIconResult materializeIcon(String key, FluidStack stack) throws Exception {
        String filename = ICONS_BY_FLUID_KEY.get(key);
        if (filename == null || filename.length() == 0) {
            return MaterializedFluidIconResult.SKIPPED;
        }

        File outDir = ClientItemStackIconRenderer.iconDir();
        if (!outDir.exists() && !outDir.mkdirs()) {
            return MaterializedFluidIconResult.SKIPPED;
        }

        File outFile = new File(outDir, filename);
        if (outFile.isFile()) {
            return MaterializedFluidIconResult.SKIPPED;
        }

        File cachedFile = ClientItemStackIconRenderer.cacheFileForKey("fluid:" + key, filename);
        if (cachedFile.isFile()) {
            Files.copy(cachedFile.toPath(), outFile.toPath(), StandardCopyOption.REPLACE_EXISTING);
            return MaterializedFluidIconResult.CACHE_HIT;
        }
        File legacyCachedFile = ClientItemStackIconRenderer.cacheFile(filename);
        if (legacyCachedFile.isFile()) {
            Files.copy(legacyCachedFile.toPath(), outFile.toPath(), StandardCopyOption.REPLACE_EXISTING);
            Files.copy(legacyCachedFile.toPath(), cachedFile.toPath(), StandardCopyOption.REPLACE_EXISTING);
            return MaterializedFluidIconResult.CACHE_HIT;
        }

        BufferedImage image = renderFluidToImage(stack);
        if (!ClientItemStackIconRenderer.imageHasVisiblePixels(image)) {
            ICONS_BY_FLUID_KEY.put(key, "");
            return MaterializedFluidIconResult.SKIPPED;
        }

        ImageIO.write(image, "png", outFile);
        File cacheDir = ClientItemStackIconRenderer.cacheDir();
        if (!cacheDir.exists()) {
            cacheDir.mkdirs();
        }
        ImageIO.write(image, "png", cachedFile);
        return MaterializedFluidIconResult.RENDERED;
    }

    private static BufferedImage renderFluidToImage(FluidStack stack) throws Exception {
        Minecraft minecraft = Minecraft.getMinecraft();
        if (minecraft == null || minecraft.getTextureManager() == null) {
            throw new IllegalStateException("Minecraft client is not ready.");
        }

        IIcon icon = fluidIcon(stack);
        if (icon == null) {
            throw new IllegalStateException("Fluid has no still icon: " + stack.getFluid().getName());
        }

        Framebuffer framebuffer = new Framebuffer(ICON_SIZE, ICON_SIZE, true);
        ByteBuffer buffer;
        boolean projectionPushed = false;
        boolean modelViewPushed = false;

        try {
            ClientItemStackIconRenderer.resetTessellator();
            framebuffer.bindFramebuffer(true);

            GL11.glViewport(0, 0, ICON_SIZE, ICON_SIZE);
            GL11.glClearColor(0.0F, 0.0F, 0.0F, 0.0F);
            GL11.glClear(GL11.GL_COLOR_BUFFER_BIT | GL11.GL_DEPTH_BUFFER_BIT);

            GL11.glMatrixMode(GL11.GL_PROJECTION);
            GL11.glPushMatrix();
            projectionPushed = true;
            GL11.glLoadIdentity();
            GL11.glOrtho(0.0D, GUI_ICON_CANVAS_SIZE, GUI_ICON_CANVAS_SIZE, 0.0D, -1.0D, 1.0D);

            GL11.glMatrixMode(GL11.GL_MODELVIEW);
            GL11.glPushMatrix();
            modelViewPushed = true;
            GL11.glLoadIdentity();

            minecraft.getTextureManager().bindTexture(TextureMap.locationBlocksTexture);
            int color = stack.getFluid().getColor(stack);
            float red = ((color >> 16) & 255) / 255.0F;
            float green = ((color >> 8) & 255) / 255.0F;
            float blue = (color & 255) / 255.0F;
            float alpha = ((color >>> 24) & 255) / 255.0F;
            if (alpha <= 0.0F) {
                alpha = 1.0F;
            }
            GL11.glColor4f(red, green, blue, alpha);

            double min = (GUI_ICON_CANVAS_SIZE - GUI_ITEM_SIZE) / 2.0D;
            double max = min + GUI_ITEM_SIZE;
            Tessellator tessellator = Tessellator.instance;
            tessellator.startDrawingQuads();
            tessellator.addVertexWithUV(min, max, 0.0D, icon.getMinU(), icon.getMaxV());
            tessellator.addVertexWithUV(max, max, 0.0D, icon.getMaxU(), icon.getMaxV());
            tessellator.addVertexWithUV(max, min, 0.0D, icon.getMaxU(), icon.getMinV());
            tessellator.addVertexWithUV(min, min, 0.0D, icon.getMinU(), icon.getMinV());
            tessellator.draw();
            GL11.glColor4f(1.0F, 1.0F, 1.0F, 1.0F);
            GL11.glFlush();

            buffer = BufferUtils.createByteBuffer(ICON_SIZE * ICON_SIZE * 4);
            GL11.glReadPixels(0, 0, ICON_SIZE, ICON_SIZE, GL11.GL_RGBA, GL11.GL_UNSIGNED_BYTE, buffer);
        } finally {
            ClientItemStackIconRenderer.resetTessellator();
            GL11.glColor4f(1.0F, 1.0F, 1.0F, 1.0F);
            if (modelViewPushed) {
                GL11.glMatrixMode(GL11.GL_MODELVIEW);
                GL11.glPopMatrix();
            }
            if (projectionPushed) {
                GL11.glMatrixMode(GL11.GL_PROJECTION);
                GL11.glPopMatrix();
            }
            GL11.glMatrixMode(GL11.GL_MODELVIEW);
            framebuffer.unbindFramebuffer();
            framebuffer.deleteFramebuffer();
        }

        return ClientItemStackIconRenderer.imageFromRgbaBuffer(buffer);
    }

    private static IIcon fluidIcon(FluidStack stack) {
        Fluid fluid = stack.getFluid();
        IIcon icon = null;
        try {
            icon = fluid.getIcon(stack);
        } catch (Throwable ignored) {
            icon = null;
        }
        if (icon == null) {
            try {
                icon = fluid.getStillIcon();
            } catch (Throwable ignored) {
                icon = null;
            }
        }
        return icon;
    }

    private static void warnRenderFailure(FluidStack stack, Throwable throwable) {
        renderWarnings++;
        if (renderWarnings <= MAX_RENDER_WARNINGS || renderWarnings % 1000 == 0) {
            GtnhCalcOracleMod.LOG.warn(
                "GTNH 1.7.10 fluid icon exporter failed for "
                    + stack.getFluid().getName()
                    + " ("
                    + renderWarnings
                    + " failures): "
                    + throwable.toString()
            );
        }
    }

    private static String fluidKey(FluidStack stack) {
        String nbt = stack.tag == null ? "" : stack.tag.toString();
        return stack.getFluid().getName() + "#" + nbt;
    }

    private static String safeName(FluidStack stack) {
        String raw;
        try {
            raw = String.valueOf(stack.getLocalizedName());
        } catch (Throwable t) {
            raw = stack.getFluid().getName();
        }
        String safe = raw.toLowerCase().replaceAll("[^a-z0-9._-]+", "_").replaceAll("^_+|_+$", "");
        return safe.length() > 0 ? safe.substring(0, Math.min(safe.length(), 60)) : "fluid";
    }

    private static String sha1(String value) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-1");
        byte[] bytes = digest.digest(value.getBytes("UTF-8"));
        StringBuilder builder = new StringBuilder();
        for (byte b : bytes) {
            builder.append(String.format("%02x", b & 255));
        }
        return builder.toString();
    }

    private static void writeIconMap() {
        File file = new File(ClientItemStackIconRenderer.iconDir(), "fluid-icon-map.json");
        FileWriter writer = null;
        try {
            writer = new FileWriter(file);
            writer.write("{\n");
            int index = 0;
            for (Map.Entry<String, String> entry : ICONS_BY_FLUID_KEY.entrySet()) {
                if (index > 0) {
                    writer.write(",\n");
                }
                writer.write("  \"" + jsonEscape(entry.getKey()) + "\": \"" + jsonEscape(entry.getValue()) + "\"");
                index++;
            }
            writer.write("\n}\n");
        } catch (IOException e) {
            GtnhCalcOracleMod.LOG.warn("Could not write GTNH fluid icon map.", e);
        } finally {
            if (writer != null) {
                try {
                    writer.close();
                } catch (IOException ignored) {
                }
            }
        }
    }

    private static String jsonEscape(String value) {
        return String.valueOf(value)
            .replace("\\", "\\\\")
            .replace("\"", "\\\"")
            .replace("\n", "\\n")
            .replace("\r", "\\r");
    }
}
