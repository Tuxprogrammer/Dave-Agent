package net.minecraft.davebridgetest;

/**
 * Test double for a vanilla class at runtime outside the dev environment: its members have SRG names only. Lives
 * under {@code net.minecraft.} so {@code SrgMetaClass} treats it as part of the Minecraft hierarchy.
 * <p>
 * {@code field_71071_by} is {@code EntityPlayer.inventory}, {@code func_110143_aJ} is
 * {@code EntityLivingBase.getHealth}, {@code func_70606_j} is {@code setHealth}, and {@code field_70165_t} is
 * {@code Entity.posX} in the MCP 1.7.10 stable_12 mappings.
 */
public class FakeSrgEntity {

    public String field_71071_by = "the inventory";
    public double field_70165_t = 12.5;
    private float health = 20f;
    public static int field_150348_b = 1; // Blocks.stone

    public float func_110143_aJ() {
        return health;
    }

    public void func_70606_j(float value) {
        health = value;
    }

    public String exact() {
        return "exact";
    }
}
