package com.tuxprogrammer.davebridge.client.lesson;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

import net.minecraft.block.Block;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.FontRenderer;
import net.minecraft.client.renderer.OpenGlHelper;
import net.minecraft.client.renderer.RenderBlocks;
import net.minecraft.client.renderer.RenderHelper;
import net.minecraft.client.renderer.Tessellator;
import net.minecraft.client.renderer.entity.RenderManager;
import net.minecraft.client.renderer.texture.DynamicTexture;
import net.minecraft.client.renderer.texture.TextureMap;
import net.minecraft.init.Blocks;

import org.lwjgl.opengl.GL11;
import org.lwjgl.opengl.GL14;

import com.tuxprogrammer.davebridge.DaveBridge;

import cpw.mods.fml.common.registry.GameData;

/**
 * Draws a playing lesson in the world: the ghost Dave, ghost blocks, highlight boxes and floating labels. Called from
 * {@code RenderWorldLastEvent} on the client thread.
 * <p>
 * GL rules from the {@code client-rendering-shaders} skill:
 * <ul>
 * <li>every draw is wrapped in {@code glPushAttrib}/{@code glPopAttrib} plus a matrix push, so state is restored from
 * the saved values, never to assumed defaults; the color is reset to opaque white at the end;</li>
 * <li>translucent things never write depth;</li>
 * <li>flat-colored quads bind a 1x1 white texture instead of disabling {@code GL_TEXTURE_2D};</li>
 * <li>every quad has a normal; state is set before {@code startDrawing}, never between vertices (Angelica may
 * capture tessellator output).</li>
 * </ul>
 * Ghost blocks are drawn with the block's own inventory renderer ({@link RenderBlocks#renderBlockAsItem}), which
 * covers vanilla blocks and GT machines (GT's inventory renderer takes the meta tile entity id as the meta). Some
 * inventory renderers set an opaque color themselves, so the ghost's translucency comes from a constant blend alpha
 * ({@code GL_CONSTANT_ALPHA}), not from the vertex color.
 * <p>
 * StructureLib's hint particles ({@code StructureLibAPI.hintParticle*}, StructureLib 1.4.47) were considered for
 * ghost blocks and rejected for lessons: they can't be removed when a lesson stops (they live for the
 * {@code hintLifespan} config, 20 s by default), and with the default {@code maxCoexisting = 1} a lesson's hints
 * would erase the hologram the player is building from. See docs/plans/guided-demos.md.
 */
public final class LessonRenderer {

    private static final int ATTRIBS = GL11.GL_ENABLE_BIT | GL11.GL_COLOR_BUFFER_BIT
        | GL11.GL_DEPTH_BUFFER_BIT
        | GL11.GL_LIGHTING_BIT
        | GL11.GL_CURRENT_BIT
        | GL11.GL_LINE_BIT
        | GL11.GL_TEXTURE_BIT;

    private static final float GHOST_BLOCK_ALPHA = 0.55F;
    private static final double LABEL_SCALE = 0.025;

    private final GhostDaveRenderer daveRenderer = new GhostDaveRenderer();
    private final RenderBlocks renderBlocks = new RenderBlocks();
    private final Set<String> brokenBlocks = new HashSet<>();
    private DynamicTexture white;
    private boolean daveBroken;

    /** Draws everything for one frame. Never throws. */
    void render(LessonPlayback p, GhostDave dave, float partialTicks) {
        Minecraft mc = Minecraft.getMinecraft();
        if (mc.theWorld == null || mc.thePlayer == null) return;
        double cx = RenderManager.renderPosX, cy = RenderManager.renderPosY, cz = RenderManager.renderPosZ;
        float time = (mc.thePlayer.ticksExisted + partialTicks);

        for (LessonPlayback.Ghost g : p.ghosts) {
            guarded(() -> drawGhostBlock(g, cx, cy, cz, partialTicks));
        }
        for (LessonPlayback.Highlight h : p.highlights) {
            guarded(() -> drawHighlight(h, cx, cy, cz, time));
        }
        if (dave != null && !daveBroken) {
            guarded(() -> drawDave(dave, cx, cy, cz, partialTicks));
        }
        for (LessonPlayback.Highlight h : p.highlights) {
            if (!h.label.isEmpty()) {
                guarded(() -> drawLabel(h.label, h.x + 0.5, h.y + 1.35, h.z + 0.5, cx, cy, cz, h.color));
            }
        }
        if (p.sayText != null) {
            double x = p.prevX + (p.x - p.prevX) * partialTicks;
            double y = p.prevY + (p.y - p.prevY) * partialTicks;
            double z = p.prevZ + (p.z - p.prevZ) * partialTicks;
            guarded(() -> drawLabel(p.sayText, x, y + 2.35, z, cx, cy, cz, 0xFFFFFF));
        }
    }

    /** Runs one self-contained draw with GL state and the matrix saved and restored. */
    private void guarded(Runnable draw) {
        GL11.glPushAttrib(ATTRIBS);
        GL11.glPushMatrix();
        try {
            draw.run();
        } catch (Throwable t) {
            DaveBridge.LOG.warn("Lesson render failed", t);
            endStrayDraw();
        } finally {
            GL11.glPopMatrix();
            GL11.glPopAttrib();
            GL14.glBlendColor(0F, 0F, 0F, 0F); // default; not every GL state tracker saves the blend color
            GL11.glColor4f(1F, 1F, 1F, 1F);
        }
    }

    /** A draw that threw halfway leaves the tessellator drawing, which would break every later draw. */
    private static void endStrayDraw() {
        try {
            Tessellator.instance.draw();
        } catch (Throwable ignored) {
            // it wasn't drawing
        }
    }

    private void drawDave(GhostDave dave, double cx, double cy, double cz, float pt) {
        Minecraft mc = Minecraft.getMinecraft();
        double x = dave.prevPosX + (dave.posX - dave.prevPosX) * pt;
        double y = dave.prevPosY + (dave.posY - dave.prevPosY) * pt;
        double z = dave.prevPosZ + (dave.posZ - dave.prevPosZ) * pt;
        int light = dave.getBrightnessForRender(pt);
        mc.entityRenderer.enableLightmap(pt);
        OpenGlHelper.setLightmapTextureCoords(OpenGlHelper.lightmapTexUnit, light & 0xFFFF, light >>> 16);
        RenderHelper.enableStandardItemLighting();
        GL11.glColor4f(1F, 1F, 1F, 1F);
        try {
            daveRenderer.doRender(dave, x - cx, y - cy, z - cz, dave.rotationYaw, pt);
        } catch (Throwable t) {
            daveBroken = true; // don't spam the log every frame
            DaveBridge.LOG.warn("Ghost Dave render failed; hiding him for this lesson", t);
        } finally {
            RenderHelper.disableStandardItemLighting();
            mc.entityRenderer.disableLightmap(pt);
        }
    }

    private void drawGhostBlock(LessonPlayback.Ghost g, double cx, double cy, double cz, float pt) {
        Block block = (Block) GameData.getBlockRegistry()
            .getObject(g.block);
        String key = g.block + ":" + g.meta;
        if (block == null || block == Blocks.air || brokenBlocks.contains(key)) {
            drawBox(g.x, g.y, g.z, cx, cy, cz, 0x88CCFF, 0.3F, false);
            return;
        }
        Minecraft mc = Minecraft.getMinecraft();
        float fade = Math.min(1F, (g.age + pt) / 10F);
        GL11.glTranslated(g.x + 0.5 - cx, g.y + 0.5 - cy, g.z + 0.5 - cz);
        rotateToFacing(g.facing);
        GL11.glScalef(0.98F, 0.98F, 0.98F); // inset: no z-fighting with neighboring blocks

        mc.getTextureManager()
            .bindTexture(TextureMap.locationBlocksTexture);
        mc.entityRenderer.enableLightmap(pt);
        OpenGlHelper.setLightmapTextureCoords(OpenGlHelper.lightmapTexUnit, 240F, 240F);
        RenderHelper.enableStandardItemLighting();
        GL11.glEnable(GL11.GL_BLEND);
        GL14.glBlendColor(1F, 1F, 1F, GHOST_BLOCK_ALPHA * fade);
        GL11.glBlendFunc(GL11.GL_CONSTANT_ALPHA, GL11.GL_ONE_MINUS_CONSTANT_ALPHA);
        GL11.glDepthMask(false);
        GL11.glEnable(GL11.GL_ALPHA_TEST);
        GL11.glAlphaFunc(GL11.GL_GREATER, 0.1F);
        GL11.glColor4f(1F, 1F, 1F, 1F);
        try {
            renderBlocks.useInventoryTint = true;
            renderBlocks.renderBlockAsItem(block, g.meta, 1.0F);
        } catch (Throwable t) {
            brokenBlocks.add(key);
            DaveBridge.LOG.warn("Can't draw ghost block {}; showing a box instead", key, t);
            endStrayDraw();
        } finally {
            RenderHelper.disableStandardItemLighting();
            mc.entityRenderer.disableLightmap(pt);
        }
    }

    /** Inventory rendering shows a block's front to the south (+Z); turn it to face {@code facing}. */
    static void rotateToFacing(String facing) {
        if (facing == null) return;
        switch (facing) {
            case "east":
                GL11.glRotatef(90F, 0F, 1F, 0F);
                break;
            case "north":
                GL11.glRotatef(180F, 0F, 1F, 0F);
                break;
            case "west":
                GL11.glRotatef(-90F, 0F, 1F, 0F);
                break;
            case "up":
                GL11.glRotatef(-90F, 1F, 0F, 0F);
                break;
            case "down":
                GL11.glRotatef(90F, 1F, 0F, 0F);
                break;
            default:
                break; // south
        }
    }

    private void drawHighlight(LessonPlayback.Highlight h, double cx, double cy, double cz, float time) {
        float pulse = 0.22F + 0.12F * (float) Math.sin(time * 0.15F);
        drawBox(h.x, h.y, h.z, cx, cy, cz, h.color, pulse, true);
    }

    /** A translucent colored box around a block, with an outline that shows through walls. */
    private void drawBox(int bx, int by, int bz, double cx, double cy, double cz, int rgb, float alpha,
        boolean outline) {
        float r = (rgb >> 16 & 255) / 255F, g = (rgb >> 8 & 255) / 255F, b = (rgb & 255) / 255F;
        double e = 0.003;
        double x0 = bx - e - cx, y0 = by - e - cy, z0 = bz - e - cz;
        double x1 = bx + 1 + e - cx, y1 = by + 1 + e - cy, z1 = bz + 1 + e - cz;

        bindWhite();
        GL11.glDisable(GL11.GL_LIGHTING);
        GL11.glEnable(GL11.GL_BLEND);
        GL11.glBlendFunc(GL11.GL_SRC_ALPHA, GL11.GL_ONE_MINUS_SRC_ALPHA);
        GL11.glDepthMask(false);
        GL11.glDisable(GL11.GL_CULL_FACE);
        GL11.glColor4f(r, g, b, alpha);
        Tessellator t = Tessellator.instance;
        t.startDrawingQuads();
        t.setColorRGBA_F(r, g, b, alpha);
        boxFaces(t, x0, y0, z0, x1, y1, z1);
        t.draw();

        if (outline) {
            // Faint through walls, so the player can find it, then solid where visible.
            GL11.glLineWidth(2.0F);
            GL11.glDisable(GL11.GL_DEPTH_TEST);
            lines(t, x0, y0, z0, x1, y1, z1, r, g, b, 0.35F);
            GL11.glEnable(GL11.GL_DEPTH_TEST);
            lines(t, x0, y0, z0, x1, y1, z1, r, g, b, 0.9F);
        }
    }

    private static void boxFaces(Tessellator t, double x0, double y0, double z0, double x1, double y1, double z1) {
        t.setNormal(0F, -1F, 0F);
        t.addVertexWithUV(x0, y0, z0, 0, 0);
        t.addVertexWithUV(x1, y0, z0, 1, 0);
        t.addVertexWithUV(x1, y0, z1, 1, 1);
        t.addVertexWithUV(x0, y0, z1, 0, 1);
        t.setNormal(0F, 1F, 0F);
        t.addVertexWithUV(x0, y1, z0, 0, 0);
        t.addVertexWithUV(x0, y1, z1, 0, 1);
        t.addVertexWithUV(x1, y1, z1, 1, 1);
        t.addVertexWithUV(x1, y1, z0, 1, 0);
        t.setNormal(0F, 0F, -1F);
        t.addVertexWithUV(x0, y0, z0, 0, 0);
        t.addVertexWithUV(x0, y1, z0, 0, 1);
        t.addVertexWithUV(x1, y1, z0, 1, 1);
        t.addVertexWithUV(x1, y0, z0, 1, 0);
        t.setNormal(0F, 0F, 1F);
        t.addVertexWithUV(x0, y0, z1, 0, 0);
        t.addVertexWithUV(x1, y0, z1, 1, 0);
        t.addVertexWithUV(x1, y1, z1, 1, 1);
        t.addVertexWithUV(x0, y1, z1, 0, 1);
        t.setNormal(-1F, 0F, 0F);
        t.addVertexWithUV(x0, y0, z0, 0, 0);
        t.addVertexWithUV(x0, y0, z1, 1, 0);
        t.addVertexWithUV(x0, y1, z1, 1, 1);
        t.addVertexWithUV(x0, y1, z0, 0, 1);
        t.setNormal(1F, 0F, 0F);
        t.addVertexWithUV(x1, y0, z0, 0, 0);
        t.addVertexWithUV(x1, y1, z0, 0, 1);
        t.addVertexWithUV(x1, y1, z1, 1, 1);
        t.addVertexWithUV(x1, y0, z1, 1, 0);
    }

    private static void lines(Tessellator t, double x0, double y0, double z0, double x1, double y1, double z1, float r,
        float g, float b, float a) {
        GL11.glColor4f(r, g, b, a);
        t.startDrawing(GL11.GL_LINES);
        t.setColorRGBA_F(r, g, b, a);
        t.setNormal(0F, 1F, 0F);
        double[][] corners = { { x0, y0, z0 }, { x1, y0, z0 }, { x1, y0, z1 }, { x0, y0, z1 } };
        for (int i = 0; i < 4; i++) {
            double[] c = corners[i], n = corners[(i + 1) % 4];
            t.addVertex(c[0], y0, c[2]);
            t.addVertex(n[0], y0, n[2]);
            t.addVertex(c[0], y1, c[2]);
            t.addVertex(n[0], y1, n[2]);
            t.addVertex(c[0], y0, c[2]);
            t.addVertex(c[0], y1, c[2]);
        }
        t.draw();
    }

    /** A camera-facing text label (wrapped to a few lines) over a dark backing, readable through blocks. */
    private void drawLabel(String text, double x, double y, double z, double cx, double cy, double cz, int rgb) {
        Minecraft mc = Minecraft.getMinecraft();
        FontRenderer font = mc.fontRenderer;
        RenderManager rm = RenderManager.instance;
        @SuppressWarnings("unchecked")
        List<String> lines = font.listFormattedStringToWidth(text, 180);
        if (lines.isEmpty()) return;
        int width = 0;
        for (String line : lines) width = Math.max(width, font.getStringWidth(line));
        int height = lines.size() * 10;

        GL11.glTranslated(x - cx, y - cy, z - cz);
        GL11.glNormal3f(0F, 1F, 0F);
        GL11.glRotatef(-rm.playerViewY, 0F, 1F, 0F);
        GL11.glRotatef(rm.playerViewX, 1F, 0F, 0F);
        GL11.glScaled(-LABEL_SCALE, -LABEL_SCALE, LABEL_SCALE);
        GL11.glDisable(GL11.GL_LIGHTING);
        GL11.glDepthMask(false);
        GL11.glDisable(GL11.GL_DEPTH_TEST);
        GL11.glEnable(GL11.GL_BLEND);
        GL11.glBlendFunc(GL11.GL_SRC_ALPHA, GL11.GL_ONE_MINUS_SRC_ALPHA);

        bindWhite();
        GL11.glColor4f(0F, 0F, 0F, 0.4F);
        Tessellator t = Tessellator.instance;
        int half = width / 2;
        int top = -height;
        t.startDrawingQuads();
        t.setColorRGBA_F(0F, 0F, 0F, 0.4F);
        t.setNormal(0F, 0F, -1F);
        t.addVertexWithUV(-half - 2, top - 1, 0, 0, 0);
        t.addVertexWithUV(-half - 2, 1, 0, 0, 1);
        t.addVertexWithUV(half + 2, 1, 0, 1, 1);
        t.addVertexWithUV(half + 2, top - 1, 0, 1, 0);
        t.draw();

        GL11.glColor4f(1F, 1F, 1F, 1F);
        for (int i = 0; i < lines.size(); i++) {
            String line = lines.get(i);
            font.drawString(line, -font.getStringWidth(line) / 2, top + i * 10, 0xFF000000 | rgb);
        }
    }

    /** Binds a 1x1 white texture for flat-colored geometry. */
    private void bindWhite() {
        if (white == null) {
            white = new DynamicTexture(1, 1);
            white.getTextureData()[0] = 0xFFFFFFFF;
            white.updateDynamicTexture();
        }
        GL11.glBindTexture(GL11.GL_TEXTURE_2D, white.getGlTextureId());
    }

    /** A new lesson: give renderers that failed another chance. */
    void reset() {
        daveBroken = false;
        brokenBlocks.clear();
    }
}
