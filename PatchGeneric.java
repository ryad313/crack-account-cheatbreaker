import javassist.*;
import javassist.expr.ExprEditor;
import javassist.expr.FieldAccess;
import javassist.expr.MethodCall;
import javassist.bytecode.Bytecode;
import javassist.bytecode.CodeAttribute;
import javassist.bytecode.ConstPool;
import javassist.bytecode.MethodInfo;
import javassist.bytecode.Opcode;
import java.io.*;
import java.util.*;
import java.util.jar.JarFile;
import java.util.jar.JarEntry;

/**
 * Generic title-screen unlocker for the CheatBreaker client jar.
 * Fingerprint-based identification (survives client rebuilds):
 *   1. pool class = the one containing "Authenticating with the server."
 *      and "SINGLEPLAYER" literals;
 *   2. gate getter = the unique 0-arg boolean method used for at least four
 *      button setters and another check in a class referencing the pool;
 *   3. patch = replace the getter BODY with `return true;` (no call-site
 *      edits), preserving the class version and all unrelated stack maps.
 *
 * Usage: java -cp <javassist.jar>:<this> PatchGeneric <client.jar> <outDir>
 * Output: patched classes written to <outDir>, names printed on stdout.
 */
public class PatchGeneric {

    public static void main(String[] args) throws Exception {
        // Javassist's ClassPool refuses archives not named *.jar: copy to a temp jar
        File srcJar = new File(args[0]);
        File jarForPool = srcJar.getName().endsWith(".jar")
                ? srcJar : File.createTempFile("cbclient", ".jar");
        if (!srcJar.getName().endsWith(".jar")) {
            jarForPool.deleteOnExit();
            try (InputStream in = new FileInputStream(srcJar);
                 OutputStream out = new FileOutputStream(jarForPool)) {
                byte[] buf = new byte[65536];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            }
        }
        ClassPool pool = ClassPool.getDefault();
        pool.appendClassPath(jarForPool.getAbsolutePath());

        // ---- 1) locate the string-pool class by fingerprint
        String poolClass = null;
        try (JarFile jar = new JarFile(jarForPool)) {
        Enumeration<JarEntry> entries = jar.entries();
        while (entries.hasMoreElements()) {
            JarEntry je = entries.nextElement();
            if (!je.getName().endsWith(".class")) continue;
            byte[] data = readAll(jar.getInputStream(je));
            if (contains(data, "Authenticating with the server.")
                    && contains(data, "SINGLEPLAYER")) {
                poolClass = je.getName().replace(".class", "").replace('/', '.');
                break;
            }
        }
        if (poolClass == null) {
            if (jar.getJarEntry("net/minecraft/client/main/Main.class") != null
                    && jar.getJarEntry("Start.class") == null) {
                System.out.println("NO_CB_MOD: vanilla client, nothing to patch");
                return;
            }
            throw new Exception("unsupported client: title-screen string pool not found");
        }
        final String fPoolClass = poolClass;
        System.out.println("pool class: " + poolClass);

        CtClass poolCt = pool.get(poolClass);
        CtField poolField = null;
        for (CtField f : poolCt.getDeclaredFields()) {
            if (f.getType().getName().equals("java.lang.String[]")) { poolField = f; break; }
        }
        if (poolField == null) throw new Exception("pool String[] field not found");
        final String fPoolField = poolField.getName();
        System.out.println("pool field: " + fPoolField);

        // ---- 2) find gate getters: 0-arg boolean methods called >= 4 times
        //         from classes that reference the pool field >= 3 times
        Map<String, String> gateGetters = new LinkedHashMap<>(); // "cls.method" -> declaring class
        Map<String, Integer> gateBest = new HashMap<>();

        Enumeration<JarEntry> entries2 = jar.entries();
        List<String> classNames = new ArrayList<>();
        while (entries2.hasMoreElements()) {
            JarEntry je = entries2.nextElement();
            if (je.getName().endsWith(".class")) classNames.add(je.getName().replace(".class", "").replace('/', '.'));
        }

        for (String cn : classNames) {
            if (cn.equals(poolClass)) continue;
            CtClass c;
            try { c = pool.get(cn); } catch (Exception e) { continue; }
            if (c.isFrozen()) continue;
            final int[] poolRefs = {0};
            final Map<String, Integer> boolCalls = new HashMap<>();
            final Map<String, Integer> buttonCalls = new HashMap<>();
            final Map<String, String> boolDecl = new HashMap<>();
            try {
                c.instrument(new ExprEditor() {
                    public void edit(FieldAccess fa) {
                        if (fa.isReader() && fa.getFieldName().equals(fPoolField)
                                && fa.getClassName().equals(fPoolClass)) {
                            poolRefs[0]++;
                        }
                    }
                    public void edit(MethodCall mc) {
                        try {
                            CtMethod m = mc.getMethod();
                            String decl = m.getDeclaringClass().getName();
                            if (m.getReturnType() == CtClass.booleanType
                                    && m.getParameterTypes().length == 0
                                    && !isJdk(decl) && !decl.equals(cn)
                                    && isObfuscated(decl) && isObfuscated(mc.getMethodName())) {
                                String key = decl + "." + mc.getMethodName();
                                boolCalls.merge(key, 1, Integer::sum);
                                boolDecl.putIfAbsent(key, decl);
                                if (feedsBooleanSetter(mc)) {
                                    buttonCalls.merge(key, 1, Integer::sum);
                                }
                            }
                        } catch (Exception e) { /* ignore */ }
                    }
                });
            } catch (Exception e) { continue; }
            if (poolRefs[0] < 3) continue;
            for (Map.Entry<String, Integer> e : boolCalls.entrySet()) {
                int setters = buttonCalls.getOrDefault(e.getKey(), 0);
                if (setters >= 4 && e.getValue() > setters) {
                    String decl = boolDecl.get(e.getKey());
                    String method = e.getKey().substring(e.getKey().lastIndexOf('.') + 1);
                    String gKey = decl + "." + method;
                    Integer prev = gateBest.get(gKey);
                    if (prev == null || e.getValue() > prev) {
                        gateGetters.put(gKey, decl);
                        gateBest.put(gKey, e.getValue());
                    }
                }
            }
        }
        if (gateGetters.isEmpty()) throw new Exception("gate getter not found");
        if (gateGetters.size() != 1) {
            throw new Exception("ambiguous title-screen gate: " + gateGetters.keySet());
        }
        for (Map.Entry<String, String> e : gateGetters.entrySet()) {
            System.out.println("gate getter: " + e.getKey() + " (declares in " + e.getValue() + ")");
        }

        // ---- 3) patch the uniquely identified getter without changing the class format
        int patched = 0;
        for (Map.Entry<String, String> e : gateGetters.entrySet()) {
            String full = e.getKey();
            String declClass = e.getValue();
            String methName = full.substring(full.lastIndexOf('.') + 1);
            CtClass cc = pool.get(declClass);
            cc.defrost();
            CtMethod m = cc.getDeclaredMethod(methName);
            replaceBooleanBody(m);
            cc.writeFile(args[1]);
            patched++;
            System.out.println("patched: " + declClass + "." + methName);
        }
        if (patched == 0) throw new Exception("nothing patched");
        System.out.println("DONE classes=" + patched);
        }
    }

    static boolean feedsBooleanSetter(MethodCall call) {
        CodeAttribute code = call.where().getMethodInfo2().getCodeAttribute();
        byte[] bytes = code.getCode();
        int opcode = bytes[call.indexOfBytecode()] & 0xff;
        int next = call.indexOfBytecode() + (opcode == Opcode.INVOKEINTERFACE ? 5 : 3);
        if (next + 2 >= bytes.length || (bytes[next] & 0xff) != Opcode.INVOKEVIRTUAL) {
            return false;
        }
        int index = ((bytes[next + 1] & 0xff) << 8) | (bytes[next + 2] & 0xff);
        ConstPool constants = code.getConstPool();
        return "(Z)V".equals(constants.getMethodrefType(index));
    }

    static void replaceBooleanBody(CtMethod method) throws Exception {
        if (!"()Z".equals(method.getSignature())
                || Modifier.isAbstract(method.getModifiers())
                || Modifier.isNative(method.getModifiers())) {
            throw new IllegalArgumentException("Expected a concrete zero-argument boolean getter");
        }
        // This straight-line body needs no stack-map frames. Replacing only its
        // Code attribute avoids rebuilding obfuscated methods or downgrading a
        // class that still contains Java 7+ constants such as InvokeDynamic.
        MethodInfo info = method.getMethodInfo();
        int locals = Modifier.isStatic(method.getModifiers()) ? 0 : 1;
        Bytecode body = new Bytecode(info.getConstPool(), 1, locals);
        body.addIconst(1);
        body.addOpcode(Opcode.IRETURN);
        info.setCodeAttribute(body.toCodeAttribute());
    }

    static boolean isObfuscated(String cn) {
        int dot = cn.lastIndexOf('.');
        String simple = dot >= 0 ? cn.substring(dot + 1) : cn;
        if (simple.length() < 8) return false;
        for (int i = 0; i < simple.length(); i++) {
            char c = simple.charAt(i);
            if (c != 'I' && c != 'l') return false;
        }
        return true;
    }

    static boolean isJdk(String cn) {
        return cn.startsWith("java.") || cn.startsWith("javax.") || cn.startsWith("sun.")
                || cn.startsWith("jdk.") || cn.startsWith("com.sun.");
    }

    static boolean contains(byte[] data, String s) {
        byte[] pat = s.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        outer: for (int i = 0; i <= data.length - pat.length; i++) {
            for (int j = 0; j < pat.length; j++) {
                if (data[i + j] != pat[j]) continue outer;
            }
            return true;
        }
        return false;
    }

    static byte[] readAll(InputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[65536];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        in.close();
        return out.toByteArray();
    }
}
