package com.tuxprogrammer.davebridge.common.eval;

import java.lang.reflect.Array;
import java.util.ArrayList;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.function.Function;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;

/**
 * Turns whatever a script returns into JSON, within limits, never throwing.
 * <p>
 * Scripts return live game objects (worlds, tile entities, recipe maps) whose object graphs are huge and cyclic, so
 * every conversion is bounded: nesting depth, items per collection, string length and an overall character budget.
 * Anything cut short adds a {@code "..."} marker and sets {@link #truncated()}. Objects with no known shape become
 * {@code {"$class": ..., "$str": toString()}}; {@link #register} adds shapes for specific types (the server registers
 * {@code ItemStack}, {@code FluidStack} and others). One instance per conversion; not thread-safe.
 */
public final class JsonDump {

    /** Limits for one conversion. */
    public static final class Limits {

        public int maxDepth = 8;
        public int maxItems = 200;
        public int maxString = 4000;
        /** Rough overall size in characters. */
        public int maxChars = 64 * 1024;

        public Limits() {}

        public Limits(int maxDepth, int maxItems, int maxString, int maxChars) {
            this.maxDepth = maxDepth;
            this.maxItems = maxItems;
            this.maxString = maxString;
            this.maxChars = maxChars;
        }
    }

    private static final class Adapter {

        final Class<?> type;
        final Function<Object, Object> convert;

        Adapter(Class<?> type, Function<Object, Object> convert) {
            this.type = type;
            this.convert = convert;
        }
    }

    private static final List<Adapter> ADAPTERS = new CopyOnWriteArrayList<>();

    private final Limits limits;
    private final Set<Object> path = Collections.newSetFromMap(new IdentityHashMap<>());
    private int budget;
    private boolean truncated;

    public JsonDump(Limits limits) {
        this.limits = limits;
        this.budget = limits.maxChars;
    }

    /**
     * Registers a converter for {@code type} (and subclasses). It returns a simpler value (a Map, List, String,
     * number...) that is then dumped normally. First registered match wins. Converters run inside the dump and may
     * throw; the object is then dumped as an error marker.
     */
    @SuppressWarnings("unchecked")
    public static <T> void register(Class<T> type, Function<? super T, Object> convert) {
        ADAPTERS.add(new Adapter(type, (Function<Object, Object>) convert));
    }

    /** Converts {@code value} with the given limits. */
    public static JsonElement dump(Object value, Limits limits) {
        return new JsonDump(limits).toJson(value);
    }

    public boolean truncated() {
        return truncated;
    }

    public JsonElement toJson(Object value) {
        return convert(value, 0);
    }

    private JsonElement convert(Object value, int depth) {
        if (budget <= 0) {
            truncated = true;
            return new JsonPrimitive("...");
        }
        if (value == null) {
            budget -= 4;
            return JsonNull.INSTANCE;
        }
        if (value instanceof JsonElement) {
            String s = value.toString();
            if (s.length() > budget) {
                truncated = true;
                return new JsonPrimitive(clip(s));
            }
            budget -= s.length();
            return (JsonElement) value;
        }
        if (value instanceof Boolean) {
            budget -= 5;
            return new JsonPrimitive((Boolean) value);
        }
        if (value instanceof Number) {
            return number((Number) value);
        }
        if (value instanceof CharSequence || value instanceof Character) {
            return string(value.toString());
        }
        if (value instanceof Enum) {
            return string(((Enum<?>) value).name());
        }
        if (value instanceof Class) {
            return string(((Class<?>) value).getName());
        }
        if (value instanceof Optional) {
            Optional<?> o = (Optional<?>) value;
            return o.isPresent() ? convert(o.get(), depth) : JsonNull.INSTANCE;
        }
        if (depth >= limits.maxDepth) {
            truncated = true;
            return shallow(value);
        }
        if (!path.add(value)) {
            return string(
                "<cycle: " + value.getClass()
                    .getName() + ">");
        }
        try {
            Adapter adapter = adapterFor(value.getClass());
            if (adapter != null) {
                Object simple;
                try {
                    simple = adapter.convert.apply(value);
                } catch (Throwable t) {
                    return string(
                        "<" + value.getClass()
                            .getName() + ": " + t + ">");
                }
                if (simple == value) {
                    return shallow(value);
                }
                return convert(simple, depth);
            }
            if (value instanceof Map) {
                return map((Map<?, ?>) value, depth);
            }
            if (value instanceof Iterable) {
                return iterate(((Iterable<?>) value).iterator(), -1, depth);
            }
            if (value instanceof Iterator) {
                return iterate((Iterator<?>) value, -1, depth);
            }
            if (value.getClass()
                .isArray()) {
                return array(value, depth);
            }
            return shallow(value);
        } finally {
            path.remove(value);
        }
    }

    private Adapter adapterFor(Class<?> type) {
        for (Adapter a : ADAPTERS) {
            if (a.type.isAssignableFrom(type)) {
                return a;
            }
        }
        return null;
    }

    private JsonElement number(Number n) {
        double d = n.doubleValue();
        if ((n instanceof Double || n instanceof Float) && (Double.isNaN(d) || Double.isInfinite(d))) {
            return string(n.toString());
        }
        budget -= 8;
        return new JsonPrimitive(n);
    }

    private JsonElement string(String s) {
        String clipped = clip(s);
        budget -= clipped.length() + 2;
        return new JsonPrimitive(clipped);
    }

    private String clip(String s) {
        int max = Math.min(limits.maxString, Math.max(16, budget));
        if (s.length() <= max) {
            return s;
        }
        truncated = true;
        return s.substring(0, max) + "...(" + s.length() + " chars)";
    }

    private JsonElement map(Map<?, ?> map, int depth) {
        JsonObject obj = new JsonObject();
        int n = 0;
        for (Map.Entry<?, ?> e : safeEntries(map)) {
            if (n++ >= limits.maxItems || budget <= 0) {
                truncated = true;
                obj.addProperty("...", (map.size() - n + 1) + " more");
                break;
            }
            String key = String.valueOf(e.getKey());
            budget -= key.length() + 3;
            obj.add(key, convert(e.getValue(), depth + 1));
        }
        return obj;
    }

    private static Iterable<? extends Map.Entry<?, ?>> safeEntries(Map<?, ?> map) {
        try {
            return new ArrayList<>(map.entrySet());
        } catch (Throwable t) {
            return Collections.emptyList();
        }
    }

    private JsonElement iterate(Iterator<?> it, int knownSize, int depth) {
        JsonArray arr = new JsonArray();
        int n = 0;
        try {
            while (it.hasNext()) {
                if (n >= limits.maxItems || budget <= 0) {
                    truncated = true;
                    arr.add(new JsonPrimitive("... more"));
                    break;
                }
                arr.add(convert(it.next(), depth + 1));
                n++;
                budget -= 1;
            }
        } catch (ScriptTimeout t) {
            throw t;
        } catch (Throwable t) {
            arr.add(new JsonPrimitive("<iteration failed: " + t + ">"));
        }
        return arr;
    }

    private JsonElement array(Object array, int depth) {
        int len = Array.getLength(array);
        JsonArray arr = new JsonArray();
        for (int i = 0; i < len; i++) {
            if (i >= limits.maxItems || budget <= 0) {
                truncated = true;
                arr.add(new JsonPrimitive("... " + (len - i) + " more"));
                break;
            }
            arr.add(convert(Array.get(array, i), depth + 1));
            budget -= 1;
        }
        return arr;
    }

    /** An object with no known shape: its class and its toString(). */
    private JsonElement shallow(Object value) {
        JsonObject obj = new JsonObject();
        obj.addProperty(
            "$class",
            value.getClass()
                .getName());
        String str;
        try {
            str = String.valueOf(value);
        } catch (Throwable t) {
            str = "<toString failed: " + t + ">";
        }
        obj.add("$str", string(str));
        budget -= value.getClass()
            .getName()
            .length() + 20;
        return obj;
    }
}
