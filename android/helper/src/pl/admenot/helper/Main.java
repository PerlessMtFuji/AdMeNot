package pl.admenot.helper;

import android.content.ContentProviderOperation;
import android.content.ContentProviderResult;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;
import android.os.Binder;
import android.os.Build;
import android.os.Bundle;
import android.os.IBinder;
import android.os.ParcelFileDescriptor;
import android.os.Process;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;

/**
 * app_process entry, runs as shell (uid 2000) without any Context:
 *   CLASSPATH=/data/local/tmp/admenot/admenot-helper.dex app_process / pl.admenot.helper.Main write IN [--account TYPE NAME]
 * Providers come from IActivityManager.getContentProviderExternal (like the `content` command) and are
 * called with the identity of com.android.shell. ActivityThread.systemMain() is never called: on MIUI it
 * prints stack traces to stdout, which is the protocol channel.
 */
public final class Main {
    static final String SHELL = "com.android.shell";

    public static void main(String[] args) {
        int rc = 0;
        try {
            if (args.length < 2 || !args[0].equals("write")) {
                System.out.println("FAIL usage");
                rc = 2;
            } else {
                String type = null, name = null;
                if (args.length >= 5 && args[2].equals("--account")) { type = args[3]; name = args[4]; }
                Writer.Out out = new Writer.Out() {
                    @Override public void line(String s) { System.out.println(s); System.out.flush(); }
                };
                new Writer(new ShellTarget(), out, type, name).run(new File(args[1]));
            }
        } catch (Throwable e) {
            System.out.println("FAIL " + Writer.code(e));
            rc = 1;
        }
        System.out.flush();
        System.exit(rc);
    }

    /** IContentProvider by reflection, one holder per authority, released in close(). */
    static final class ShellTarget implements Target {
        final Object am;
        final IBinder token = new Binder();
        final Object attribution;
        final Map<String, Object> providers = new HashMap<>();

        ShellTarget() throws Exception {
            am = Class.forName("android.app.ActivityManager").getMethod("getService").invoke(null);
            attribution = Build.VERSION.SDK_INT >= 31 ? attribution31() : null;
        }

        static Object attribution31() {
            return new android.content.AttributionSource.Builder(Process.myUid()).setPackageName(SHELL).build();
        }

        Object provider(String authority) throws Exception {
            Object p = providers.get(authority);
            if (p != null) return p;
            Object h = null;
            for (Method m : am.getClass().getMethods()) {
                if (!m.getName().equals("getContentProviderExternal")) continue;
                Class<?>[] t = m.getParameterTypes();
                if (t.length == 4) h = m.invoke(am, authority, 0, token, "admenot-helper");
                else if (t.length == 3) h = m.invoke(am, authority, 0, token);
                else continue;
                break;
            }
            if (h == null) throw new IllegalStateException("no provider " + authority);
            p = h.getClass().getField("provider").get(h);
            providers.put(authority, p);
            return p;
        }

        @Override public void close() {
            for (String authority : providers.keySet()) {
                try {
                    boolean done = false;
                    for (Method m : am.getClass().getMethods()) {
                        if (m.getName().equals("removeContentProviderExternalAsUser")) {
                            m.invoke(am, authority, token, 0); done = true; break;
                        }
                    }
                    if (!done) for (Method m : am.getClass().getMethods()) {
                        if (m.getName().equals("removeContentProviderExternal")) { m.invoke(am, authority, token); break; }
                    }
                } catch (Throwable ignored) { }
            }
            providers.clear();
        }

        static Class<?> box(Class<?> c) {
            if (!c.isPrimitive()) return c;
            if (c == int.class) return Integer.class;
            if (c == long.class) return Long.class;
            if (c == boolean.class) return Boolean.class;
            return c;
        }

        /** Calls a provider method; `tail` are the real arguments, the leading ones carry the caller identity. */
        Object call(String authority, String name, Object... tail) throws Exception {
            Object p = provider(authority);
            for (Method m : p.getClass().getMethods()) {
                if (!m.getName().equals(name)) continue;
                Class<?>[] t = m.getParameterTypes();
                int pre = t.length - tail.length;
                if (pre < 0) continue;
                boolean fits = true;
                for (int i = 0; i < tail.length; i++) {
                    if (tail[i] != null && !box(t[pre + i]).isInstance(tail[i])) { fits = false; break; }
                }
                if (!fits) continue;
                Object[] a = new Object[t.length];
                int strings = 0;
                for (int i = 0; i < pre; i++) {
                    if (t[i].getName().equals("android.content.AttributionSource")) a[i] = attribution;
                    else if (t[i] == String.class) a[i] = (strings++ == 0) ? SHELL : null; // callingPkg, featureId
                    else a[i] = null;
                }
                System.arraycopy(tail, 0, a, pre, tail.length);
                return m.invoke(p, a);
            }
            throw new NoSuchMethodException(name + "/" + tail.length);
        }

        @Override public int bulkInsert(Uri uri, ContentValues[] values) throws Exception {
            return (Integer) call(uri.getAuthority(), "bulkInsert", uri, values);
        }

        @Override public Uri insert(Uri uri, ContentValues values) throws Exception {
            try {
                return (Uri) call(uri.getAuthority(), "insert", uri, values, (Bundle) null);
            } catch (NoSuchMethodException e) {
                return (Uri) call(uri.getAuthority(), "insert", uri, values);
            }
        }

        @Override public int delete(Uri uri) throws Exception {
            try {
                return (Integer) call(uri.getAuthority(), "delete", uri, (Bundle) null); // SDK 30+
            } catch (NoSuchMethodException e) {
                return (Integer) call(uri.getAuthority(), "delete", uri, (String) null, (String[]) null);
            }
        }

        @SuppressWarnings("unchecked")
        @Override public ContentProviderResult[] applyBatch(String authority, ArrayList<ContentProviderOperation> ops)
                throws Exception {
            return (ContentProviderResult[]) call(authority, "applyBatch", authority, ops);
        }

        @Override public Cursor query(Uri uri, String[] projection, String selection, String[] selectionArgs,
                                      String sortOrder) throws Exception {
            // ContentResolver.QUERY_ARG_SQL_*: ContentProvider.query(Bundle) hands them to the old-style query
            Bundle args = new Bundle();
            if (selection != null) args.putString("android:query-arg-sql-selection", selection);
            if (selectionArgs != null) args.putStringArray("android:query-arg-sql-selection-args", selectionArgs);
            if (sortOrder != null) args.putString("android:query-arg-sql-sort-order", sortOrder);
            try {
                return (Cursor) call(uri.getAuthority(), "query", uri, projection, args, null); // SDK 26+
            } catch (NoSuchMethodException e) {
                return (Cursor) call(uri.getAuthority(), "query", uri, projection, selection, selectionArgs,
                        sortOrder, null);
            }
        }

        @Override public OutputStream openOutput(Uri uri) throws Exception {
            Object p = provider(uri.getAuthority());
            for (Method m : p.getClass().getMethods()) {
                if (!m.getName().equals("openFile")) continue;
                Class<?>[] t = m.getParameterTypes();
                Object[] a = new Object[t.length];
                int before = 0, after = 0; // strings before the Uri: callingPkg, featureId; after it: mode
                boolean uriSeen = false;
                for (int i = 0; i < t.length; i++) {
                    if (t[i].getName().equals("android.content.AttributionSource")) a[i] = attribution;
                    else if (t[i] == Uri.class) { a[i] = uri; uriSeen = true; }
                    else if (t[i] == String.class) {
                        if (uriSeen) a[i] = (after++ == 0) ? "w" : null;
                        else a[i] = (before++ == 0) ? SHELL : null;
                    } else a[i] = null;
                }
                final ParcelFileDescriptor fd = (ParcelFileDescriptor) m.invoke(p, a);
                return new FileOutputStream(fd.getFileDescriptor()) {
                    @Override public void close() throws java.io.IOException {
                        try { super.close(); } finally { fd.close(); }
                    }
                };
            }
            throw new NoSuchMethodException("openFile");
        }
    }
}
