package dev.gtnhplanner.calcoracle.icons;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;

import net.minecraft.item.ItemStack;

import dev.gtnhplanner.calcoracle.GtnhCalcOracleMod;

public final class ItemStackIconExporter {

    private static boolean warned;

    private ItemStackIconExporter() {}

    public static String captureIcon(ItemStack stack) {
        if (stack == null || !Boolean.getBoolean("gtnh.oracle.renderIcons")) {
            return null;
        }

        try {
            Class<?> renderer = Class.forName("dev.gtnhplanner.calcoracle.icons.ClientItemStackIconRenderer");
            Method method = renderer.getMethod("captureIcon", ItemStack.class);
            Object value = method.invoke(null, stack);
            return value instanceof String ? (String) value : null;
        } catch (InvocationTargetException e) {
            warnOnce(e.getCause());
        } catch (Throwable t) {
            warnOnce(t);
        }

        return null;
    }

    private static void warnOnce(Throwable t) {
        if (warned) {
            return;
        }

        warned = true;
        GtnhCalcOracleMod.LOG.warn("GTNH 1.7.10 icon exporter is unavailable; continuing without item icons.", t);
    }
}
