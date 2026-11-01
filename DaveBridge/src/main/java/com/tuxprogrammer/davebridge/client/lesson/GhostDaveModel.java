package com.tuxprogrammer.davebridge.client.lesson;

import net.minecraft.client.model.ModelBiped;
import net.minecraft.entity.Entity;
import net.minecraft.util.MathHelper;

/**
 * A plain {@link ModelBiped} on a 64x64 texture (Dave's skin is a 64x64 old-layout biped skin; only the top half is
 * used, so the UVs must be divided by 64, not 32). When Dave points, his right arm follows his head: straight
 * forward plus the head's pitch and turn. Otherwise, holding a gun, he carries it at the hip like GregGuns' Dictator
 * Dave.
 */
public class GhostDaveModel extends ModelBiped {

    /** Right-arm pitch while carrying a gun at the hip (GregGuns' HipCarry.ARM_X_DEGREES), in radians. */
    static final float HIP_CARRY_ARM = (float) Math.toRadians(-25.0);

    /** Holding a gun: set by {@link GhostDaveRenderer} before each draw. */
    public boolean carrying;

    public GhostDaveModel() {
        super(0.0F, 0.0F, 64, 64);
    }

    @Override
    public void setRotationAngles(float limbSwing, float limbSwingAmount, float age, float headYaw, float headPitch,
        float scale, Entity entity) {
        super.setRotationAngles(limbSwing, limbSwingAmount, age, headYaw, headPitch, scale, entity);
        if (entity instanceof GhostDave && ((GhostDave) entity).pointing && onGround <= 0.0F) {
            bipedRightArm.rotateAngleX = -(float) (Math.PI / 2) + bipedHead.rotateAngleX;
            bipedRightArm.rotateAngleY = bipedHead.rotateAngleY;
            bipedRightArm.rotateAngleZ = 0.0F;
        } else if (carrying) {
            // Hip carry, as GregGuns' Dictator Dave holds his revolver: the arm tipped forward, a little walk swing.
            bipedRightArm.rotateAngleX = HIP_CARRY_ARM + MathHelper.cos(limbSwing * 0.6662F) * 0.3F * limbSwingAmount;
            bipedRightArm.rotateAngleY = 0.0F;
        }
    }
}
