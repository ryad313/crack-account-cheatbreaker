import javassist.*;
import javassist.expr.ExprEditor;
import javassist.expr.FieldAccess;
import javassist.expr.MethodCall;
import java.io.*;
import java.util.*;
import java.util.jar.JarFile;
import java.util.jar.JarEntry;

/**
 * Generic title-screen unlocker for the CheatBreaker client jar.
 * Fingerprint-based identification (survives client rebuilds):
 *   1. pool class = the one containing "Authenticating with the server."
 *      and "SINGLEPLAYER" literals;
 *   2. gate getter = the 0-arg boolean method called >= 4 times from a class
 *      that references the pool's String[] field >= 3 times;
 *   3. patch = replace the getter BODY with `return true;` (no call-site
 *      edits, no stack-map rebuild issues).
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
        JarFile jar = new JarFile(jarForPool);
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
        if (poolClass == null) throw new Exception("string pool class not found");
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
            try { c.getClassFile().setMajorVersion(48); } catch (Exception e) { }
            final int[] poolRefs = {0};
            final Map<String, Integer> boolCalls = new HashMap<>();
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
                            }
                        } catch (Exception e) { /* ignore */ }
                    }
                });
            } catch (Exception e) { continue; }
            if (poolRefs[0] < 3) continue;
            for (Map.Entry<String, Integer> e : boolCalls.entrySet()) {
                if (e.getValue() >= 4) {
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
        for (Map.Entry<String, String> e : gateGetters.entrySet()) {
            System.out.println("gate getter: " + e.getKey() + " (declares in " + e.getValue() + ")");
        }

        // ---- 3) patch each gate getter body: return true (no call-site edits)
        int patched = 0;
        for (Map.Entry<String, String> e : gateGetters.entrySet()) {
            String full = e.getKey();
            String declClass = e.getValue();
            String methName = full.substring(full.lastIndexOf('.') + 1);
            CtClass cc = pool.get(declClass);
            cc.defrost();
            try { cc.getClassFile().setMajorVersion(48); } catch (Exception ex) { }
            CtMethod m = cc.getDeclaredMethod(methName);
            m.setBody("return true;");
            cc.writeFile(args[1]);
            patched++;
            System.out.println("patched: " + declClass + "." + methName);
        }
        if (patched == 0) throw new Exception("nothing patched");
        System.out.println("DONE classes=" + patched);
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
