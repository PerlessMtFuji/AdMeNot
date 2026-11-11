package pl.admenot.helper;

import android.content.ContentProviderOperation;
import android.content.ContentProviderResult;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;

import java.io.OutputStream;
import java.util.ArrayList;

/** Provider access used by Writer: shell (Main, no Context) or app (Runner, ContentResolver). */
interface Target {
    int bulkInsert(Uri uri, ContentValues[] values) throws Exception;

    Uri insert(Uri uri, ContentValues values) throws Exception;

    ContentProviderResult[] applyBatch(String authority, ArrayList<ContentProviderOperation> ops) throws Exception;

    /** selection, selectionArgs and sortOrder may be null. */
    Cursor query(Uri uri, String[] projection, String selection, String[] selectionArgs, String sortOrder)
            throws Exception;

    OutputStream openOutput(Uri uri) throws Exception;

    /** Only ever called with a URI this process has just inserted (rollback of a partial MMS). */
    int delete(Uri uri) throws Exception;

    /** The APK of the provider behind `authority` (ApplicationInfo.sourceDir), null when unknown. */
    String providerSourceDir(String authority) throws Exception;

    void close();
}
