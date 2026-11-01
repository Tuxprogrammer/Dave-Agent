package com.tuxprogrammer.davebridge.client.lesson;

import net.minecraft.client.model.ModelBiped;
import net.minecraft.entity.Entity;

/**
 * A plain {@link ModelBiped} on a 64x64 texture (Dave's skin is a 64x64 old-layout biped skin; only the top half is
 * used, so the UVs must be divided by 64, not 32). When Dave points, his right arm follows his head: straight
 * forward plus the head's pitch and turn.
 */
public class GhostDaveModel extends ModelBiped {

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
        }
    }
}
