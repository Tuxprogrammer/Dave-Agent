package com.tuxprogrammer.davebridge.common.eval;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import net.minecraft.item.Item;
import net.minecraft.item.ItemStack;
import net.minecraftforge.fluids.FluidStack;
import net.minecraftforge.oredict.OreDictionary;

/**
 * The {@code dave} variable in scripts: reflection that speaks MCP names, item and fluid summaries, and markup
 * helpers. Common to both sides; the server and client add their own helpers in subclasses.
 * <p>
 * Reflection here reads private members too ({@code setAccessible}), because a script exploring a mod's internals
 * needs exactly that. Every lookup accepts MCP or SRG names and reports both.
 */
public class EvalHelpers {

    protected final SrgNames names = SrgNames.get();

    // ---- classes and names

    /** Loads a class by its full name through the game's class loader. */
    public Class<?> cls(String name) throws ClassNotFoundException {
        return Class.forName(name, false, EvalHelpers.class.getClassLoader());
    }

    /** The MCP name of an SRG member name (or the name itself). */
    public String mcp(String srg) {
        return names.readable(srg);
    }

    /** The SRG names an MCP member name stands for. */
    public List<String> srg(String mcp) {
        return names.srg(mcp);
    }

    // ---- reflection

    /** Fields of an object (or a Class: its static fields) up the hierarchy, with readable names and short values. */
    public List<Map<String, Object>> fields(Object target) {
        Class<?> type = target instanceof Class ? (Class<?>) target : target.getClass();
        boolean statics = target instanceof Class;
        List<Map<String, Object>> out = new ArrayList<>();
        for (Class<?> c = type; c != null && c != Object.class; c = c.getSuperclass()) {
            for (Field f : c.getDeclaredFields()) {
                if (Modifier.isStatic(f.getModifiers()) != statics || f.isSynthetic()) {
                    continue;
                }
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("name", names.readable(f.getName()));
                if (SrgNames.isSrg(f.getName())) {
                    row.put("srg", f.getName());
                }
                row.put(
                    "type",
                    f.getType()
                        .getName());
                row.put("declaredIn", c.getName());
                row.put("value", preview(read(f, statics ? null : target)));
                out.add(row);
            }
        }
        return out;
    }

    /**
     * Method signatures of an object or class up the hierarchy, readable names, filtered by a case-insensitive
     * substring of the (MCP) name; {@code null} or empty lists all.
     */
    public List<String> methods(Object target, String filter) {
        Class<?> type = target instanceof Class ? (Class<?>) target : target.getClass();
        String f = filter == null ? "" : filter.toLowerCase(Locale.ROOT);
        List<String> out = new ArrayList<>();
        for (Class<?> c = type; c != null && c != Object.class; c = c.getSuperclass()) {
            for (Method m : c.getDeclaredMethods()) {
                if (m.isSynthetic() || m.isBridge()) {
                    continue;
                }
                String readable = names.readable(m.getName());
                if (!f.isEmpty() && !readable.toLowerCase(Locale.ROOT)
                    .contains(f)
                    && !m.getName()
                        .toLowerCase(Locale.ROOT)
                        .contains(f)) {
                    continue;
                }
                StringBuilder sb = new StringBuilder();
                if (Modifier.isStatic(m.getModifiers())) {
                    sb.append("static ");
                }
                sb.append(readable);
                if (!readable.equals(m.getName())) {
                    sb.append(" [")
                        .append(m.getName())
                        .append(']');
                }
                sb.append('(');
                Class<?>[] params = m.getParameterTypes();
                for (int i = 0; i < params.length; i++) {
                    sb.append(i > 0 ? ", " : "")
                        .append(params[i].getSimpleName());
                }
                sb.append(") -> ")
                    .append(
                        m.getReturnType()
                            .getSimpleName())
                    .append("  (")
                    .append(c.getSimpleName())
                    .append(')');
                out.add(sb.toString());
            }
        }
        return out;
    }

    public List<String> methods(Object target) {
        return methods(target, null);
    }

    /** Reads a field (private too) by MCP or SRG name, searching up the hierarchy. Static if target is a Class. */
    public Object get(Object target, String name) throws NoSuchFieldException {
        Field f = findField(target instanceof Class ? (Class<?>) target : target.getClass(), name);
        return read(f, Modifier.isStatic(f.getModifiers()) ? null : target);
    }

    /** Writes a field (private too). Changing game state this way still needs write mode. */
    public void set(Object target, String name, Object value) throws Exception {
        Field f = findField(target instanceof Class ? (Class<?>) target : target.getClass(), name);
        f.setAccessible(true);
        f.set(Modifier.isStatic(f.getModifiers()) ? null : target, value);
    }

    /** Calls a method (private too) by MCP or SRG name, picking the first whose parameters fit the arguments. */
    public Object call(Object target, String name, Object... args) throws Exception {
        Class<?> type = target instanceof Class ? (Class<?>) target : target.getClass();
        Object[] a = args == null ? new Object[0] : args;
        List<String> candidates = new ArrayList<>();
        candidates.add(name);
        candidates.addAll(names.srgMethods(name));
        for (Class<?> c = type; c != null; c = c.getSuperclass()) {
            for (Method m : c.getDeclaredMethods()) {
                if (candidates.contains(m.getName()) && fits(m.getParameterTypes(), a)) {
                    m.setAccessible(true);
                    try {
                        return m.invoke(Modifier.isStatic(m.getModifiers()) ? null : target, a);
                    } catch (java.lang.reflect.InvocationTargetException e) {
                        Throwable cause = e.getCause();
                        if (cause instanceof Exception) {
                            throw (Exception) cause;
                        }
                        throw e;
                    }
                }
            }
        }
        throw new NoSuchMethodException(type.getName() + "." + name + " with " + a.length + " argument(s)");
    }

    private Field findField(Class<?> type, String name) throws NoSuchFieldException {
        List<String> candidates = new ArrayList<>();
        candidates.add(name);
        candidates.addAll(names.srgFields(name));
        for (Class<?> c = type; c != null; c = c.getSuperclass()) {
            for (String n : candidates) {
                try {
                    Field f = c.getDeclaredField(n);
                    f.setAccessible(true);
                    return f;
                } catch (NoSuchFieldException ignored) {
                    // try the next name or superclass
                }
            }
        }
        throw new NoSuchFieldException(type.getName() + "." + name);
    }

    private static Object read(Field f, Object target) {
        try {
            f.setAccessible(true);
            return f.get(target);
        } catch (Throwable t) {
            return "<unreadable: " + t + ">";
        }
    }

    private static boolean fits(Class<?>[] params, Object[] args) {
        if (params.length != args.length) {
            return false;
        }
        for (int i = 0; i < params.length; i++) {
            Class<?> p = wrap(params[i]);
            if (args[i] != null && !p.isInstance(args[i])) {
                if (!(Number.class.isAssignableFrom(p) && args[i] instanceof Number)) {
                    return false;
                }
            }
        }
        return true;
    }

    private static Class<?> wrap(Class<?> c) {
        if (!c.isPrimitive()) {
            return c;
        }
        if (c == int.class) return Integer.class;
        if (c == long.class) return Long.class;
        if (c == boolean.class) return Boolean.class;
        if (c == double.class) return Double.class;
        if (c == float.class) return Float.class;
        if (c == short.class) return Short.class;
        if (c == byte.class) return Byte.class;
        if (c == char.class) return Character.class;
        return Void.class;
    }

    /** A short, safe string for a value (used in field listings). */
    public static String preview(Object v) {
        if (v == null) {
            return "null";
        }
        String s;
        try {
            if (v.getClass()
                .isArray()) {
                s = v.getClass()
                    .getComponentType()
                    .getSimpleName() + "["
                    + java.lang.reflect.Array.getLength(v)
                    + "]";
            } else {
                s = String.valueOf(v);
            }
        } catch (Throwable t) {
            s = "<" + v.getClass()
                .getName() + ">";
        }
        return s.length() > 200 ? s.substring(0, 200) + "..." : s;
    }

    // ---- items, fluids, markup

    /** Registry id {@code modid:name} of an item, or null. */
    public static String itemId(Item item) {
        Object name = item == null ? null : Item.itemRegistry.getNameForObject(item);
        return name == null ? null : name.toString();
    }

    /** An item stack as {@code id, meta, count, name, ore, nbt}; also how {@link JsonDump} shows stacks. */
    public static Map<String, Object> item(ItemStack stack) {
        if (stack == null) {
            return null;
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", itemId(stack.getItem()));
        m.put("meta", stack.getItemDamage());
        m.put("count", stack.stackSize);
        try {
            m.put("name", stack.getDisplayName());
        } catch (Throwable t) {
            m.put("name", null);
        }
        try {
            int[] ids = OreDictionary.getOreIDs(stack);
            if (ids.length > 0) {
                List<String> ores = new ArrayList<>();
                for (int id : ids) {
                    ores.add(OreDictionary.getOreName(id));
                }
                m.put("ore", ores);
            }
        } catch (Throwable ignored) {
            // some stacks (null items, wildcard meta) have no ore ids
        }
        if (stack.hasTagCompound()) {
            String nbt = String.valueOf(stack.getTagCompound());
            m.put("nbt", nbt.length() > 300 ? nbt.substring(0, 300) + "..." : nbt);
        }
        return m;
    }

    /** {@code id:meta} markup id of a stack (for {@code {item:...}} links), or null. */
    public static String markupId(ItemStack stack) {
        String id = stack == null ? null : itemId(stack.getItem());
        if (id == null) {
            return null;
        }
        return stack.getItemDamage() == 0 ? id : id + ":" + stack.getItemDamage();
    }

    /** A fluid stack as {@code fluid, amount, name}. */
    public static Map<String, Object> fluid(FluidStack stack) {
        if (stack == null || stack.getFluid() == null) {
            return null;
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put(
            "fluid",
            stack.getFluid()
                .getName());
        m.put("amount", stack.amount);
        try {
            m.put("name", stack.getLocalizedName());
        } catch (Throwable t) {
            m.put("name", null);
        }
        return m;
    }

    /** A Dave markup waypoint link: {@code {waypoint:x,y,z,dim|label}}. */
    public static String waypoint(int x, int y, int z, int dim, String label) {
        String l = label == null ? ""
            : "|" + label.replace("}", "")
                .replace("|", "/");
        return "{waypoint:" + x + "," + y + "," + z + (dim == 0 ? "" : "," + dim) + l + "}";
    }

    public static String waypoint(int x, int y, int z, int dim) {
        return waypoint(x, y, z, dim, null);
    }

    /** Converts any value as eval results are converted (default limits), e.g. to inspect a part of a big object. */
    public Object dump(Object value) {
        return JsonDump.dump(value, new JsonDump.Limits());
    }

    /** Registers the JSON shapes of common game objects. Safe to call more than once per JVM: only the first counts. */
    public static synchronized void registerAdapters() {
        if (adaptersRegistered) {
            return;
        }
        adaptersRegistered = true;
        JsonDump.register(ItemStack.class, EvalHelpers::item);
        JsonDump.register(FluidStack.class, EvalHelpers::fluid);
        JsonDump.register(Item.class, i -> "item " + itemId(i));
        JsonDump.register(net.minecraft.nbt.NBTBase.class, Object::toString);
        JsonDump.register(net.minecraft.tileentity.TileEntity.class, te -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put(
                "$class",
                te.getClass()
                    .getName());
            m.put("x", te.xCoord);
            m.put("y", te.yCoord);
            m.put("z", te.zCoord);
            m.put("dim", te.getWorldObj() == null ? null : te.getWorldObj().provider.dimensionId);
            return m;
        });
        JsonDump.register(net.minecraft.entity.Entity.class, e -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put(
                "$class",
                e.getClass()
                    .getName());
            m.put("entityId", e.getEntityId());
            m.put("name", e.getCommandSenderName());
            m.put("dim", e.dimension);
            m.put("x", Math.round(e.posX * 100) / 100.0);
            m.put("y", Math.round(e.posY * 100) / 100.0);
            m.put("z", Math.round(e.posZ * 100) / 100.0);
            return m;
        });
        JsonDump.register(net.minecraft.world.World.class, w -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put(
                "$class",
                w.getClass()
                    .getName());
            m.put("dim", w.provider.dimensionId);
            m.put("name", w.provider.getDimensionName());
            return m;
        });
    }

    private static boolean adaptersRegistered;
}
