package com.tuxprogrammer.davebridge.client.lesson;

import net.minecraft.client.renderer.entity.RenderBiped;
import net.minecraft.client.renderer.entity.RenderManager;
import net.minecraft.entity.EntityLiving;
import net.minecraft.entity.EntityLivingBase;
import net.minecraft.util.ResourceLocation;

import org.lwjgl.opengl.GL11;

/**
 * Draws {@link GhostDave} with vanilla's biped renderer, translucent. Not registered with the RenderManager: there is
 * no entity class for it to find, {@link LessonRenderer} calls {@link #doRender} directly.
 * <p>
 * Translucency follows the {@code client-rendering-shaders} skill: blended with {@code SRC_ALPHA,
 * ONE_MINUS_SRC_ALPHA}, no depth writes (so water, clouds and stained glass drawn later aren't cut out), alpha test
 * kept for the skin's transparent pixels. The caller saves and restores GL state around the whole draw.
 */
public class GhostDaveRenderer extends RenderBiped {

    /** GregGuns' Dictator Dave skin; provenance in THIRD-PARTY-NOTICES.md. */
    public static final ResourceLocation SKIN = new ResourceLocation("davebridge", "textures/entity/dave.png");
    static final float ALPHA = 0.6F;

    public GhostDaveRenderer() {
        super(new GhostDaveModel(), 0.0F);
        setRenderManager(RenderManager.instance);
    }

    @Override
    protected ResourceLocation getEntityTexture(EntityLiving entity) {
        return SKIN;
    }

    @Override
    protected void renderModel(EntityLivingBase entity, float limbSwing, float limbSwingAmount, float age,
        float headYaw, float headPitch, float scale) {
        bindEntityTexture(entity);
        GL11.glColor4f(1.0F, 1.0F, 1.0F, ALPHA);
        GL11.glDepthMask(false);
        GL11.glEnable(GL11.GL_BLEND);
        GL11.glBlendFunc(GL11.GL_SRC_ALPHA, GL11.GL_ONE_MINUS_SRC_ALPHA);
        GL11.glEnable(GL11.GL_ALPHA_TEST);
        GL11.glAlphaFunc(GL11.GL_GREATER, 0.004F);
        mainModel.render(entity, limbSwing, limbSwingAmount, age, headYaw, headPitch, scale);
        // The held item that follows is drawn normally (opaque), so it reads clearly.
        GL11.glAlphaFunc(GL11.GL_GREATER, 0.1F);
        GL11.glColor4f(1.0F, 1.0F, 1.0F, 1.0F);
        GL11.glDepthMask(true);
    }

    /** No name tag: the lesson draws its own labels. */
    @Override
    protected boolean func_110813_b(EntityLiving entity) {
        return false;
    }
}
