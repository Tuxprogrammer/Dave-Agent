package com.tuxprogrammer.davebridge.common.eval;

import java.util.List;
import java.util.Locale;

import groovy.lang.DelegatingMetaClass;
import groovy.lang.GroovySystem;
import groovy.lang.MetaClass;
import groovy.lang.MetaClassRegistry;
import groovy.lang.MissingFieldException;
import groovy.lang.MissingMethodException;
import groovy.lang.MissingPropertyException;

/**
 * The "Groovy MetaClass hook": lets scripts use MCP names for vanilla members that only exist under their SRG names
 * at runtime. Wraps the normal metaclass of every class in the Minecraft or Forge hierarchy (mod classes that extend
 * {@code TileEntity}, {@code Entity}, ... included). Normal lookups go first and are untouched; only when one fails
 * with a missing property or method of exactly that name does it retry with each SRG name of that MCP name. So
 * {@code player.inventory} becomes {@code player.field_71071_by}, {@code entity.getHealth()} becomes
 * {@code func_110143_aJ()}, and {@code entity.health} tries the field, then the getter.
 * <p>
 * In the dev environment the MCP names exist and nothing is translated. Static members ({@code Blocks.stone}) work
 * the same way, since Groovy asks the class's own metaclass.
 */
public final class SrgMetaClass extends DelegatingMetaClass {

    private static final Object[] NO_ARGS = new Object[0];
    private static volatile boolean installed;

    private final SrgNames names;

    public SrgMetaClass(MetaClass delegate, SrgNames names) {
        super(delegate);
        this.names = names;
    }

    /** Installs the hook into Groovy's registry. Idempotent; call before compiling the first script. */
    public static synchronized void install(SrgNames names) {
        if (installed) {
            return;
        }
        GroovySystem.getMetaClassRegistry()
            .setMetaClassCreationHandle(new Handle(names));
        installed = true;
    }

    /** True for classes whose hierarchy includes a vanilla or Forge class: those may have SRG-named members. */
    static boolean inMinecraftHierarchy(Class<?> type) {
        for (Class<?> c = type; c != null; c = c.getSuperclass()) {
            if (isMinecraft(c)) {
                return true;
            }
            for (Class<?> i : c.getInterfaces()) {
                if (isMinecraft(i)) {
                    return true;
                }
            }
        }
        return false;
    }

    private static boolean isMinecraft(Class<?> c) {
        String n = c.getName();
        return n.startsWith("net.minecraft.") || n.startsWith("net.minecraftforge.");
    }

    // ---- properties

    @Override
    public Object getProperty(Object object, String property) {
        try {
            return super.getProperty(object, property);
        } catch (MissingPropertyException e) {
            if (!property.equals(e.getProperty())) {
                throw e;
            }
            return translatedGet(object, property, e);
        }
    }

    @Override
    public Object getProperty(Class sender, Object receiver, String property, boolean isCallToSuper,
        boolean fromInsideClass) {
        try {
            return super.getProperty(sender, receiver, property, isCallToSuper, fromInsideClass);
        } catch (MissingPropertyException e) {
            if (!property.equals(e.getProperty())) {
                throw e;
            }
            return translatedGet(receiver, property, e);
        }
    }

    @Override
    public void setProperty(Object object, String property, Object newValue) {
        try {
            super.setProperty(object, property, newValue);
        } catch (MissingPropertyException e) {
            if (!property.equals(e.getProperty())) {
                throw e;
            }
            translatedSet(object, property, newValue, e);
        }
    }

    @Override
    public void setProperty(Class sender, Object receiver, String property, Object value, boolean isCallToSuper,
        boolean fromInsideClass) {
        try {
            super.setProperty(sender, receiver, property, value, isCallToSuper, fromInsideClass);
        } catch (MissingPropertyException e) {
            if (!property.equals(e.getProperty())) {
                throw e;
            }
            translatedSet(receiver, property, value, e);
        }
    }

    @Override
    public Object getAttribute(Object object, String attribute) {
        try {
            return super.getAttribute(object, attribute);
        } catch (MissingPropertyException | MissingFieldException e) {
            return translatedAttribute(object, attribute, e, null, false);
        }
    }

    @Override
    public Object getAttribute(Class sender, Object receiver, String messageName, boolean useSuper) {
        try {
            return super.getAttribute(sender, receiver, messageName, useSuper);
        } catch (MissingPropertyException | MissingFieldException e) {
            return translatedAttribute(receiver, messageName, e, null, false);
        }
    }

    @Override
    public void setAttribute(Object object, String attribute, Object newValue) {
        try {
            super.setAttribute(object, attribute, newValue);
        } catch (MissingPropertyException | MissingFieldException e) {
            translatedAttribute(object, attribute, e, newValue, true);
        }
    }

    @Override
    public void setAttribute(Class sender, Object receiver, String messageName, Object messageValue, boolean useSuper,
        boolean fromInsideClass) {
        try {
            super.setAttribute(sender, receiver, messageName, messageValue, useSuper, fromInsideClass);
        } catch (MissingPropertyException | MissingFieldException e) {
            translatedAttribute(receiver, messageName, e, messageValue, true);
        }
    }

    /** {@code obj.@name}: direct field access, retried with each SRG field name. */
    private Object translatedAttribute(Object receiver, String name, RuntimeException original, Object value,
        boolean set) {
        if (!name.equals(missingName(original))) {
            throw original;
        }
        for (String srg : names.srgFields(name)) {
            try {
                if (set) {
                    super.setAttribute(receiver, srg, value);
                    return null;
                }
                return super.getAttribute(receiver, srg);
            } catch (MissingPropertyException | MissingFieldException e) {
                if (!srg.equals(missingName(e))) {
                    throw e;
                }
            }
        }
        throw original;
    }

    private static String missingName(RuntimeException e) {
        if (e instanceof MissingPropertyException) {
            return ((MissingPropertyException) e).getProperty();
        }
        if (e instanceof MissingFieldException) {
            return ((MissingFieldException) e).getField();
        }
        return null;
    }

    private Object translatedGet(Object receiver, String property, MissingPropertyException original) {
        for (String srg : names.srgFields(property)) {
            try {
                return super.getProperty(receiver, srg);
            } catch (MissingPropertyException e) {
                if (!srg.equals(e.getProperty())) {
                    throw e;
                }
            }
        }
        if (!property.isEmpty()) {
            String cap = property.substring(0, 1)
                .toUpperCase(Locale.ROOT) + property.substring(1);
            for (String getter : new String[] { "get" + cap, "is" + cap }) {
                for (String srg : names.srgMethods(getter)) {
                    Object[] out = new Object[1];
                    if (tryInvoke(receiver, srg, NO_ARGS, out)) {
                        return out[0];
                    }
                }
            }
        }
        throw original;
    }

    private void translatedSet(Object receiver, String property, Object value, MissingPropertyException original) {
        for (String srg : names.srgFields(property)) {
            try {
                super.setProperty(receiver, srg, value);
                return;
            } catch (MissingPropertyException e) {
                if (!srg.equals(e.getProperty())) {
                    throw e;
                }
            }
        }
        if (!property.isEmpty()) {
            String setter = "set" + property.substring(0, 1)
                .toUpperCase(Locale.ROOT) + property.substring(1);
            for (String srg : names.srgMethods(setter)) {
                if (tryInvoke(receiver, srg, new Object[] { value }, new Object[1])) {
                    return;
                }
            }
        }
        throw original;
    }

    // ---- methods

    @Override
    public Object invokeMethod(Object object, String methodName, Object[] arguments) {
        try {
            return super.invokeMethod(object, methodName, arguments);
        } catch (MissingMethodException e) {
            return translatedInvoke(object, methodName, arguments, e);
        }
    }

    @Override
    public Object invokeMethod(Object object, String methodName, Object arguments) {
        try {
            return super.invokeMethod(object, methodName, arguments);
        } catch (MissingMethodException e) {
            Object[] args = arguments == null ? NO_ARGS
                : arguments instanceof Object[] ? (Object[]) arguments : new Object[] { arguments };
            return translatedInvoke(object, methodName, args, e);
        }
    }

    @Override
    public Object invokeMethod(Class sender, Object receiver, String methodName, Object[] arguments,
        boolean isCallToSuper, boolean fromInsideClass) {
        try {
            return super.invokeMethod(sender, receiver, methodName, arguments, isCallToSuper, fromInsideClass);
        } catch (MissingMethodException e) {
            return translatedInvoke(receiver, methodName, arguments, e);
        }
    }

    @Override
    public Object invokeStaticMethod(Object object, String methodName, Object[] arguments) {
        try {
            return super.invokeStaticMethod(object, methodName, arguments);
        } catch (MissingMethodException e) {
            if (!methodName.equals(e.getMethod())) {
                throw e;
            }
            for (String srg : names.srgMethods(methodName)) {
                try {
                    return super.invokeStaticMethod(object, srg, arguments);
                } catch (MissingMethodException e2) {
                    if (!srg.equals(e2.getMethod())) {
                        throw e2;
                    }
                }
            }
            throw e;
        }
    }

    private Object translatedInvoke(Object receiver, String methodName, Object[] arguments,
        MissingMethodException original) {
        if (!methodName.equals(original.getMethod())) {
            throw original;
        }
        List<String> candidates = names.srgMethods(methodName);
        for (String srg : candidates) {
            Object[] out = new Object[1];
            if (tryInvoke(receiver, srg, arguments, out)) {
                return out[0];
            }
        }
        throw original;
    }

    /** Calls {@code srg} if the receiver has it (true, result in out[0]); false if it has no such method. */
    private boolean tryInvoke(Object receiver, String srg, Object[] args, Object[] out) {
        try {
            out[0] = super.invokeMethod(receiver, srg, args);
            return true;
        } catch (MissingMethodException e) {
            if (!srg.equals(e.getMethod())) {
                throw e;
            }
            return false;
        }
    }

    /** Wraps the metaclasses of Minecraft-hierarchy classes as Groovy creates them. */
    static final class Handle extends MetaClassRegistry.MetaClassCreationHandle {

        private final SrgNames names;

        Handle(SrgNames names) {
            this.names = names;
        }

        @Override
        protected MetaClass createNormalMetaClass(Class theClass, MetaClassRegistry registry) {
            MetaClass normal = super.createNormalMetaClass(theClass, registry);
            if (theClass != null && inMinecraftHierarchy(theClass)) {
                return new SrgMetaClass(normal, names);
            }
            return normal;
        }
    }
}
