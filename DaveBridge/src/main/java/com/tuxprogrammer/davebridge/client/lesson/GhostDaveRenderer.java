package com.tuxprogrammer.davebridge.client.lesson;

import java.util.UUID;

import net.minecraft.client.entity.EntityOtherPlayerMP;
import net.minecraft.client.model.ModelBiped;
import net.minecraft.client.model.ModelRenderer;
import net.minecraft.client.renderer.entity.RenderBiped;
import net.minecraft.client.renderer.entity.RenderManager;
import net.minecraft.entity.Entity;
import net.minecraft.entity.EntityLiving;
import net.minecraft.entity.EntityLivingBase;
import net.minecraft.item.ItemBlock;
import net.minecraft.item.ItemStack;
import net.minecraft.util.ResourceLocation;
import net.minecraftforge.client.IItemRenderer;
import net.minecraftforge.client.MinecraftForgeClient;

import org.lwjgl.opengl.GL11;

import com.mojang.authlib.GameProfile;

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
    /** Hip carry: the gun's lift about the hand while the arm hangs (GregGuns' HipCarry.GUN_LIFT_DEGREES). */
    static final float GUN_LIFT_DEGREES = -45.0F;

    /**
     * The holder the gun's item renderer is told about. GregGuns gives a gun its aimed pre-rotation only when the
     * holder is a player or one of its NPCs (AimedHold); without it the gun is drawn stock up, muzzle back. The ghost
     * is neither, so the renderer gets this stand-in player instead: never spawned, holding nothing, so it adds no
     * fire or reload animation. One per world.
     */
    private static final GameProfile HOLDER_PROFILE = new GameProfile(
        UUID.nameUUIDFromBytes("davebridge:ghost-dave".getBytes(java.nio.charset.StandardCharsets.UTF_8)),
        "Dave");
    private EntityOtherPlayerMP holder;

    public GhostDaveRenderer() {
        super(new GhostDaveModel(), 0.0F);
        setRenderManager(RenderManager.instance);
        ((PosedArmorModel) field_82423_g).source = (ModelBiped) mainModel;
        ((PosedArmorModel) field_82425_h).source = (ModelBiped) mainModel;
    }

    /**
     * The armor layers take Dave's own pose. Vanilla poses each armor model with its own ModelBiped math, so while
     * Dave points or carries his gun the vest's sleeve would hang at vanilla's angle and his arm would show through
     * it. Called from RenderBiped's constructor, before this class's fields are set.
     */
    // Same fix as GregGuns' NPCs (D310): client/mob/RenderDataBiped.func_82421_b and client/mob/ArmorPose.
    @Override
    protected void func_82421_b() {
        field_82423_g = new PosedArmorModel(1.0F);
        field_82425_h = new PosedArmorModel(0.5F);
    }

    /** A vanilla armor layer that copies the ghost's pose after vanilla posed it. */
    static final class PosedArmorModel extends ModelBiped {

        ModelBiped source;

        PosedArmorModel(float inflate) {
            super(inflate);
        }

        @Override
        public void setRotationAngles(float limbSwing, float limbSwingAmount, float age, float headYaw, float headPitch,
            float scale, Entity entity) {
            super.setRotationAngles(limbSwing, limbSwingAmount, age, headYaw, headPitch, scale, entity);
            if (source != null) copyPose(source, this);
        }
    }

    /** Copies the six biped parts' angles and pivots, and the head onto the headwear. */
    static void copyPose(ModelBiped from, ModelBiped to) {
        copyPart(from.bipedHead, to.bipedHead);
        copyPart(from.bipedHead, to.bipedHeadwear);
        copyPart(from.bipedBody, to.bipedBody);
        copyPart(from.bipedRightArm, to.bipedRightArm);
        copyPart(from.bipedLeftArm, to.bipedLeftArm);
        copyPart(from.bipedRightLeg, to.bipedRightLeg);
        copyPart(from.bipedLeftLeg, to.bipedLeftLeg);
    }

    private static void copyPart(ModelRenderer from, ModelRenderer to) {
        to.rotateAngleX = from.rotateAngleX;
        to.rotateAngleY = from.rotateAngleY;
        to.rotateAngleZ = from.rotateAngleZ;
        to.rotationPointX = from.rotationPointX;
        to.rotationPointY = from.rotationPointY;
        to.rotationPointZ = from.rotationPointZ;
    }

    /**
     * GregGuns' own armor models (the beret, box armor) follow GregGuns' ArmorPose source instead: while the ghost is
     * drawn, that source is Dave's model. Soft dependency through reflection; without GregGuns this does nothing.
     */
    @Override
    public void doRender(EntityLiving entity, double x, double y, double z, float yaw, float partial) {
        boolean posing = GregGunsArmorPose.begin((ModelBiped) mainModel);
        try {
            super.doRender(entity, x, y, z, yaw, partial);
        } finally {
            if (posing) GregGunsArmorPose.end();
        }
    }

    /** Reflective access to com.gregguns.client.mob.ArmorPose begin/end; looked up once. */
    static final class GregGunsArmorPose {

        private static boolean looked;
        private static java.lang.reflect.Method begin, end;

        static boolean begin(ModelBiped model) {
            if (!looked) {
                looked = true;
                try {
                    Class<?> c = Class.forName("com.gregguns.client.mob.ArmorPose");
                    begin = c.getMethod("begin", ModelBiped.class);
                    end = c.getMethod("end");
                } catch (ReflectiveOperationException | LinkageError e) {
                    begin = end = null;
                }
            }
            if (begin == null) return false;
            try {
                begin.invoke(null, model);
                return true;
            } catch (ReflectiveOperationException | RuntimeException e) {
                begin = end = null;
                return false;
            }
        }

        static void end() {
            try {
                if (end != null) end.invoke(null);
            } catch (ReflectiveOperationException | RuntimeException e) {
                begin = end = null;
            }
        }
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

    @Override
    protected void preRenderCallback(EntityLivingBase entity, float partial) {
        ((GhostDaveModel) mainModel).carrying = isGun(entity.getHeldItem());
    }

    /** Armor (Dave's beret and uniform) is drawn as translucent as his body. */
    @Override
    protected int shouldRenderPass(EntityLiving entity, int pass, float partial) {
        int result = super.shouldRenderPass(entity, pass, partial);
        if (result > 0) {
            GL11.glColor4f(1.0F, 1.0F, 1.0F, ALPHA);
            GL11.glDepthMask(false);
            GL11.glEnable(GL11.GL_BLEND);
            GL11.glBlendFunc(GL11.GL_SRC_ALPHA, GL11.GL_ONE_MINUS_SRC_ALPHA);
        }
        return result;
    }

    /**
     * A held item drawn with the 3D render helper (a gun) gets the frame a player's would. RenderBiped gives that frame
     * to block items only, so a gun would land in the tool frame and point backwards. While the arm hangs (hip carry)
     * the gun is lifted to point forward; while Dave points, it follows his arm.
     */
    @Override
    protected void renderEquippedItems(EntityLivingBase living, float partial) {
        GL11.glDepthMask(true);
        GL11.glColor4f(1.0F, 1.0F, 1.0F, 1.0F);
        ItemStack held = living.getHeldItem();
        if (!isGun(held) || !(living instanceof GhostDave)) {
            super.renderEquippedItems(living, partial);
            return;
        }
        GhostDave dave = (GhostDave) living;
        // Vanilla draws the helmet in the same call as the held item: hide the gun from it for the call.
        dave.setCurrentItemOrArmor(0, null);
        try {
            super.renderEquippedItems(living, partial);
        } finally {
            dave.setCurrentItemOrArmor(0, held);
        }
        GL11.glPushMatrix();
        try {
            modelBipedMain.bipedRightArm.postRender(0.0625F);
            GL11.glTranslatef(-0.0625F, 0.4375F, 0.0625F);
            if (!dave.pointing) {
                GL11.glRotatef(GUN_LIFT_DEGREES, 1.0F, 0.0F, 0.0F);
            }
            // RenderPlayer.renderEquippedItems' frame for items drawn with the 3D render helper (Forge 10.13.4.1614).
            GL11.glTranslatef(0.0F, 0.1875F, -0.3125F);
            GL11.glRotatef(20.0F, 1.0F, 0.0F, 0.0F);
            GL11.glRotatef(45.0F, 0.0F, 1.0F, 0.0F);
            float scale = 0.375F;
            GL11.glScalef(-scale, -scale, scale);
            if (holder == null || holder.worldObj != living.worldObj) {
                holder = new EntityOtherPlayerMP(living.worldObj, HOLDER_PROFILE);
            }
            renderManager.itemRenderer.renderItem(holder, held, 0);
        } finally {
            GL11.glPopMatrix();
        }
    }

    /** True for a non-block item whose EQUIPPED renderer asks for the 3D render helper (GregGuns' guns do). */
    static boolean isGun(ItemStack held) {
        if (held == null || held.getItem() == null || held.getItem() instanceof ItemBlock) {
            return false;
        }
        IItemRenderer r = MinecraftForgeClient.getItemRenderer(held, IItemRenderer.ItemRenderType.EQUIPPED);
        return r != null && r.shouldUseRenderHelper(
            IItemRenderer.ItemRenderType.EQUIPPED,
            held,
            IItemRenderer.ItemRendererHelper.BLOCK_3D);
    }

    /** No name tag: the lesson draws its own labels. */
    @Override
    protected boolean func_110813_b(EntityLiving entity) {
        return false;
    }
}
