package io.metor.platform.license;

import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;

/** Test-only reflection bridges the two real product assemblies, never licensing protocols. */
public final class MetorUpgradeProbe {
  static Object call(Object target, String name, Object... args) throws Exception {
    Class<?> type = target instanceof Class<?> c ? c : target.getClass();
    for (Method m : type.getDeclaredMethods()) {
      if (!m.getName().equals(name) || m.getParameterCount() != args.length) continue;
      boolean match = true;
      for (int i = 0; i < args.length; i++)
        if (args[i] != null && !m.getParameterTypes()[i].isInstance(args[i])
            && !(m.getParameterTypes()[i] == boolean.class && args[i] instanceof Boolean)) match = false;
      if (!match) continue;
      m.setAccessible(true);
      try { return m.invoke(target instanceof Class<?> ? null : target, args); }
      catch (InvocationTargetException e) { throw (Exception) e.getCause(); }
    }
    throw new NoSuchMethodException(type.getName() + "." + name);
  }
  public static void main(String[] args) throws Exception {
    var loader = MetorUpgradeProbe.class.getClassLoader();
    Object mapper = Class.forName("com.fasterxml.jackson.databind.ObjectMapper").getConstructor().newInstance();
    call(mapper, "findAndRegisterModules");
    Object config = Class.forName("io.metor.platform.license.LicenseConfiguration").getConstructor().newInstance();
    Object metadata = call(config, "licenseReleaseMetadata", mapper);
    if (!call(metadata, "mode").toString().equals("CUSTOMER_REQUIRED")) throw new AssertionError("customer metadata rejected");
    Object routes = call(config, "licenseHttpProperties", metadata, mapper);
    if (!((Boolean) call(routes, "valid"))) throw new AssertionError("product API policy rejected");
    Object paths = Class.forName("io.metor.platform.license.LicensePathProperties")
        .getConstructor(Path.class, Path.class).newInstance(Path.of("/license"), Path.of(args[1]));
    Object local = call(config, "metorLicenseService", metadata, paths, routes);
    Object manager;
    try { manager = call(config, "licenseManagementService", local); }
    catch (NoSuchMethodException old) { manager = call(config, "licenseManagementService", local, paths); }
    Map<String, Object> result = new LinkedHashMap<>();
    try {
      switch (args[0]) {
        case "request" -> result.putAll((Map) call(manager, "request"));
        case "import" -> {
          Map state = (Map) call(manager, "status", true);
          Object digest = state.get("fileDigest");
          Object applied = call(manager, "importLicense", Files.readAllBytes(Path.of(args[2])), digest == null ? "NONE" : digest);
          result.put("actionStatus", call(applied, "actionStatus"));
          result.put("state", ((Map) call(applied, "status")).get("state"));
        }
        case "recovery-request" -> result.putAll((Map) call(manager, "recoveryRequest"));
        case "recover" -> {
          byte[] raw = Files.readAllBytes(Path.of(args[2]));
          Object first = call(manager, "applyRecovery", raw);
          result.put("actionStatus", call(first, "actionStatus"));
          result.put("state", ((Map) call(first, "status")).get("state"));
          result.put("refreshedState", ((Map) call(manager, "status", true)).get("state"));
          result.put("repeatStatus", call(call(manager, "applyRecovery", raw), "actionStatus"));
        }
        default -> {
          if (args[0].equals("worker")) { call(local, "initializeObservation"); Thread.sleep(31000); }
          result.put("state", call(call(local, "status"), "state"));
          boolean allowed = true;
          try { call(local, "requireValid"); } catch (Exception denied) { allowed = false; }
          result.put("allowed", allowed);
        }
      }
    } catch (Exception error) {
      result.put("error", error.getClass().getSimpleName());
      try { result.put("code", call(error, "code")); } catch (Exception ignored) { }
    } finally {
      try { call(local, "close"); } catch (NoSuchMethodException old) { }
    }
    System.out.println(call(mapper, "writeValueAsString", result));
  }
}
