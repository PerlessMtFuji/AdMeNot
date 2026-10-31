package pl.admenot.helper;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.ContentProviderOperation;
import android.content.ContentProviderResult;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;

import java.io.File;
import java.io.OutputStream;
import java.util.ArrayList;

/**
 * Companion path, runs in the helper app with its own permissions (and the SMS role when granted):
 *   am instrument -w -r -e cmd write -e input PATH [-e account_type T -e account_name N] pl.admenot.helper/.Runner
 * Every protocol line is one status bundle with the single key "line" (am prints keys sorted).
 */
public final class Runner extends Instrumentation {
    private Bundle args;

    @Override public void onCreate(Bundle arguments) {
        args = arguments == null ? new Bundle() : arguments;
        start();
    }

    @Override public void onStart() {
        Writer.Out out = new Writer.Out() {
            @Override public void line(String s) {
                Bundle b = new Bundle();
                b.putString("line", s);
                sendStatus(1, b);
            }
        };
        try {
            if (!"write".equals(args.getString("cmd"))) {
                out.line("FAIL usage");
            } else {
                Context ctx = getTargetContext();
                new Writer(new ResolverTarget(ctx.getContentResolver()), out,
                        args.getString("account_type"), args.getString("account_name"))
                        .run(resolve(ctx, args.getString("input", "")));
            }
        } catch (Throwable e) {
            out.line("FAIL " + Writer.code(e));
        }
        finish(Activity.RESULT_OK, new Bundle());
    }

    /** /sdcard/Android/data/<pkg>/files/... -> the app's own external files dir (same storage, app view). */
    static File resolve(Context ctx, String input) {
        String prefix = "/sdcard/Android/data/" + ctx.getPackageName() + "/files/";
        File ext = ctx.getExternalFilesDir(null);
        if (ext != null && input.startsWith(prefix)) return new File(ext, input.substring(prefix.length()));
        return new File(input);
    }

    static final class ResolverTarget implements Target {
        final ContentResolver cr;

        ResolverTarget(ContentResolver cr) { this.cr = cr; }

        @Override public int bulkInsert(Uri uri, ContentValues[] values) { return cr.bulkInsert(uri, values); }

        @Override public Uri insert(Uri uri, ContentValues values) { return cr.insert(uri, values); }

        @Override public ContentProviderResult[] applyBatch(String authority, ArrayList<ContentProviderOperation> ops)
                throws Exception {
            return cr.applyBatch(authority, ops);
        }

        @Override public Cursor query(Uri uri, String[] projection) {
            return cr.query(uri, projection, null, null, null);
        }

        @Override public OutputStream openOutput(Uri uri) throws Exception { return cr.openOutputStream(uri); }

        @Override public int delete(Uri uri) { return cr.delete(uri, null, null); }

        @Override public void close() { }
    }
}
