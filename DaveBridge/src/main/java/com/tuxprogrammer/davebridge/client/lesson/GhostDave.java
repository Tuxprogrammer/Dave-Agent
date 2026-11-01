package com.tuxprogrammer.davebridge.client.lesson;

import net.minecraft.entity.EntityLiving;
import net.minecraft.item.ItemStack;
import net.minecraft.world.World;

/**
 * The ghost Dave a lesson shows. A client-only object: it is never spawned into the world, never ticked by it, never
 * synced and never seen by anyone else. It exists only so vanilla's biped renderer (walk cycle, head turn, swing,
 * held item, including other mods' held-item renderers) can draw it. {@link LessonClient} moves it every client tick
 * from {@link LessonPlayback}; {@link LessonRenderer} draws it from {@code RenderWorldLastEvent}.
 */
public class GhostDave extends EntityLiving {

    /** Raise the right arm toward where the head looks. Read by {@link GhostDaveModel}. */
    public boolean pointing;

    public GhostDave(World world) {
        super(world);
        this.noClip = true;
        this.setSize(0.6F, 1.8F);
    }

    /** Copies one tick of playback state, keeping the previous values for interpolation. */
    void follow(LessonPlayback p, ItemStack held) {
        prevPosX = lastTickPosX = posX;
        prevPosY = lastTickPosY = posY;
        prevPosZ = lastTickPosZ = posZ;
        setPosition(p.x, p.y, p.z);
        if (p.prevX == p.x && p.prevY == p.y && p.prevZ == p.z) {
            // A jump (start of a pass): don't interpolate across it.
            prevPosX = lastTickPosX = posX;
            prevPosY = lastTickPosY = posY;
            prevPosZ = lastTickPosZ = posZ;
        }
        prevRenderYawOffset = renderYawOffset;
        prevRotationYawHead = rotationYawHead;
        prevRotationYaw = rotationYaw;
        prevRotationPitch = rotationPitch;
        renderYawOffset = p.bodyYaw;
        rotationYaw = p.bodyYaw;
        rotationYawHead = p.headYaw;
        rotationPitch = p.pitch;

        // Same limb update as a walking mob, from the distance moved this tick.
        prevLimbSwingAmount = limbSwingAmount;
        double dx = posX - prevPosX, dz = posZ - prevPosZ;
        float speed = Math.min(1.0F, (float) Math.sqrt(dx * dx + dz * dz) * 4.0F);
        limbSwingAmount += (speed - limbSwingAmount) * 0.4F;
        limbSwing += limbSwingAmount;

        pointing = p.pointing;
        setCurrentItemOrArmor(0, held);
        updateArmSwingProgress();
        ticksExisted++;
    }

    /** Starts the arm swing animation. */
    void swing() {
        swingItem();
    }

    @Override
    public int getBrightnessForRender(float partialTicks) {
        // At least block light 10, so he stays visible at night and in dark rooms.
        int light = super.getBrightnessForRender(partialTicks);
        int block = Math.max(light & 0xFFFF, 10 << 4);
        return (light & 0xFFFF0000) | block;
    }

    @Override
    public boolean canBePushed() {
        return false;
    }

    @Override
    public boolean canBeCollidedWith() {
        return false;
    }
}
