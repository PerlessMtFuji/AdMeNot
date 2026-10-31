package pl.admenot.helper;

import android.content.ContentProviderOperation;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashSet;
import java.util.List;

/**
 * Writes one input file through a Target and reports per line:
 * OK id | ERR id code | DENIED | DONE ok err (FAIL code when the input itself is unusable).
 * The first SecurityException, or a bulkInsert that stores fewer rows than sent
 * (appop "ignore" drops SMS silently), gives DENIED and nothing more is written.
 */
final class Writer {
    interface Out { void line(String s); }

    static final int BATCH = 500;
    static final int CONTACT_OPS = 450;
    static final Uri SMS = Uri.parse("content://sms");
    static final Uri CALLS = Uri.parse("content://call_log/calls");
    static final Uri RAW = Uri.parse("content://com.android.contacts/raw_contacts");
    static final Uri DATA = Uri.parse("content://com.android.contacts/data");
    static final String CONTACTS_AUTHORITY = "com.android.contacts";

    /** Thrown to stop the whole run after DENIED. */
    static final class Denied extends Exception { }

    private final Target t;
    private final Out out;
    private final String accountType, accountName;
    private int ok, err;

    Writer(Target target, Out out, String accountType, String accountName) {
        this.t = target;
        this.out = out;
        this.accountType = accountType;
        this.accountName = accountName;
    }

    void run(File input) {
        JsonLines in;
        try {
            in = new JsonLines(input);
        } catch (Exception e) {
            out.line("FAIL bad_input");
            return;
        }
        try {
            if (in.kind.equals("sms")) bulk(in, SMS, true);
            else if (in.kind.equals("calls")) bulk(in, CALLS, false);
            else if (in.kind.equals("contacts")) contacts(in);
            else if (in.kind.equals("mms")) mms(in);
            else { out.line("FAIL bad_kind"); return; }
        } catch (Denied d) {
            out.line("DENIED");
        } catch (Throwable e) {
            out.line("FAIL " + code(e));
            return;
        } finally {
            in.close();
            t.close();
        }
        out.line("DONE " + ok + " " + err);
    }

    static Throwable unwrap(Throwable e) {
        while (e instanceof java.lang.reflect.InvocationTargetException && e.getCause() != null) e = e.getCause();
        return e;
    }

    /** SecurityException, our own Denied, or applyBatch refused by appop ("App op not allowed"). */
    static boolean isDenial(Throwable e) {
        Throwable u = unwrap(e);
        if (u instanceof SecurityException || u instanceof Denied) return true;
        return u instanceof android.content.OperationApplicationException
                && u.getMessage() != null && u.getMessage().contains("App op not allowed");
    }

    /**
     * An insert ignored by appop is not an error to the caller: ContentProvider.Transport returns
     * rejectInsert(), i.e. the collection URI + "/0". Treat it as a denial, never as written.
     */
    static boolean rejected(Uri u) {
        return u != null && "0".equals(u.getLastPathSegment());
    }

    static String code(Throwable e) {
        return unwrap(e).getClass().getSimpleName();
    }

    private void okId(String id) { ok++; out.line("OK " + id); }

    private void errId(String id, String code) { err++; out.line("ERR " + id + " " + code); }

    // ---------- SMS and calls: bulkInsert ----------

    private void bulk(JsonLines in, Uri uri, boolean sms) throws Exception {
        List<String> ids = new ArrayList<>();
        List<ContentValues> vals = new ArrayList<>();
        JSONObject r;
        while ((r = in.next()) != null) {
            String id = r.optString("id", "");
            if (id.isEmpty()) continue;
            ContentValues v;
            try {
                v = sms ? smsValues(r) : callValues(r);
            } catch (Exception e) {
                errId(id, "bad_record");
                continue;
            }
            ids.add(id);
            vals.add(v);
            if (ids.size() >= BATCH) { flushBulk(uri, ids, vals); ids.clear(); vals.clear(); }
        }
        if (!ids.isEmpty()) flushBulk(uri, ids, vals);
    }

    private void flushBulk(Uri uri, List<String> ids, List<ContentValues> vals) throws Exception {
        int n;
        try {
            n = t.bulkInsert(uri, vals.toArray(new ContentValues[0]));
        } catch (Exception e) {
            if (isDenial(e)) throw new Denied();
            oneByOne(uri, ids, vals);
            return;
        }
        if (n < ids.size()) throw new Denied();
        for (String id : ids) okId(id);
    }

    private void oneByOne(Uri uri, List<String> ids, List<ContentValues> vals) throws Exception {
        for (int i = 0; i < ids.size(); i++) {
            try {
                Uri u = t.insert(uri, vals.get(i));
                if (u == null) errId(ids.get(i), "insert_null");
                else if (rejected(u)) throw new Denied();
                else okId(ids.get(i));
            } catch (Exception e) {
                if (isDenial(e)) throw new Denied();
                errId(ids.get(i), code(e));
            }
        }
    }

    static ContentValues smsValues(JSONObject r) throws Exception {
        ContentValues v = new ContentValues();
        v.put("address", r.getString("address"));
        v.put("date", r.getLong("date"));
        v.put("date_sent", r.optLong("date_sent", 0));
        v.put("type", r.getInt("type"));
        v.put("read", r.optInt("read", 1));
        v.put("seen", 1);
        v.put("status", r.optInt("status", -1));
        if (!r.isNull("subject") && r.has("subject")) v.put("subject", r.getString("subject"));
        v.put("body", r.getString("body"));
        return v; // no sub_id: the phone's default SIM
    }

    static ContentValues callValues(JSONObject r) throws Exception {
        ContentValues v = new ContentValues();
        v.put("number", r.getString("number"));
        v.put("date", r.getLong("date"));
        v.put("duration", r.optLong("duration", 0));
        v.put("type", r.getInt("type"));
        v.put("presentation", r.optInt("presentation", 1));
        if (!r.isNull("name") && r.has("name")) v.put("name", r.getString("name"));
        v.put("new", 0);
        v.put("is_read", 1);
        return v; // no subscription_id
    }

    // ---------- contacts: applyBatch ----------

    private void contacts(JsonLines in) throws Exception {
        List<String> ids = new ArrayList<>();
        List<JSONObject> recs = new ArrayList<>();
        int ops = 0;
        JSONObject r;
        while ((r = in.next()) != null) {
            String id = r.optString("id", "");
            if (id.isEmpty()) continue;
            int size;
            try {
                size = 1 + r.getJSONArray("rows").length();
                addContact(new ArrayList<ContentProviderOperation>(), r); // validates the record
            } catch (Exception e) {
                errId(id, "bad_record");
                continue;
            }
            if (!ids.isEmpty() && (ids.size() >= BATCH || ops + size > CONTACT_OPS)) {
                flushContacts(ids, recs);
                ids.clear(); recs.clear(); ops = 0;
            }
            ids.add(id);
            recs.add(r);
            ops += size;
        }
        if (!ids.isEmpty()) flushContacts(ids, recs);
    }

    private void flushContacts(List<String> ids, List<JSONObject> recs) throws Exception {
        ArrayList<ContentProviderOperation> batch = new ArrayList<>();
        for (JSONObject r : recs) addContact(batch, r);
        try {
            android.content.ContentProviderResult[] res = t.applyBatch(CONTACTS_AUTHORITY, batch);
            if (anyRejected(res)) throw new Denied();
            if (res != null && res.length == batch.size()) {
                for (String id : ids) okId(id);
                return;
            }
        } catch (Exception e) {
            if (isDenial(e)) throw new Denied();
        }
        for (int i = 0; i < ids.size(); i++) { // one contact per batch: a bad one does not sink the rest
            ArrayList<ContentProviderOperation> one = new ArrayList<>();
            addContact(one, recs.get(i));
            try {
                android.content.ContentProviderResult[] res = t.applyBatch(CONTACTS_AUTHORITY, one);
                if (anyRejected(res)) throw new Denied();
                if (res != null && res.length == one.size()) okId(ids.get(i));
                else errId(ids.get(i), "batch_short");
            } catch (Exception e) {
                if (isDenial(e)) throw new Denied();
                errId(ids.get(i), code(e));
            }
        }
    }

    static boolean anyRejected(android.content.ContentProviderResult[] res) {
        if (res == null) return false;
        for (android.content.ContentProviderResult x : res) if (rejected(x.uri)) return true;
        return false;
    }

    private void addContact(ArrayList<ContentProviderOperation> batch, JSONObject r) throws Exception {
        int back = batch.size();
        batch.add(ContentProviderOperation.newInsert(RAW)
                .withValue("account_type", accountType).withValue("account_name", accountName)
                .withValue("starred", r.optInt("starred", 0)).build());
        JSONArray rows = r.getJSONArray("rows");
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.getJSONObject(i);
            ContentProviderOperation.Builder b = ContentProviderOperation.newInsert(DATA)
                    .withValueBackReference("raw_contact_id", back)
                    .withValue("mimetype", row.getString("mimetype"));
            JSONObject vals = row.getJSONObject("values");
            Iterator<String> keys = vals.keys();
            while (keys.hasNext()) {
                String k = keys.next();
                if (!(k.startsWith("data") || k.equals("is_primary"))) continue;
                b.withValue(k, vals.getString(k));
            }
            batch.add(b.build());
        }
    }

    // ---------- MMS: one by one ----------

    private void mms(JsonLines in) throws Exception {
        JSONObject r;
        while ((r = in.next()) != null) {
            String id = r.optString("id", "");
            if (id.isEmpty()) continue;
            try {
                writeMms(in, r);
                okId(id);
            } catch (Exception e) {
                if (isDenial(e)) throw new Denied();
                errId(id, code(e));
            }
        }
    }

    static final class MmsWriteError extends Exception {
        MmsWriteError(String m) { super(m); }
    }

    private void writeMms(JsonLines in, JSONObject r) throws Exception {
        int box = r.optInt("msg_box", 1);
        JSONArray addrs = r.getJSONArray("addrs");
        long thread = threadId(recipients(addrs, box));
        String boxPath = box == 2 ? "sent" : box == 3 ? "drafts" : box == 4 ? "outbox" : "inbox";
        ContentValues pdu = new ContentValues();
        pdu.put("thread_id", thread);
        pdu.put("date", r.getLong("date") / 1000);
        pdu.put("date_sent", r.optLong("date_sent", 0) / 1000);
        pdu.put("msg_box", box);
        pdu.put("read", r.optInt("read", 1));
        pdu.put("seen", 1);
        if (!r.isNull("subject") && r.has("subject")) {
            pdu.put("sub", r.getString("subject"));
            pdu.put("sub_cs", 106);
        }
        pdu.put("ct_t", "application/vnd.wap.multipart.related");
        pdu.put("m_type", box == 1 ? 132 : 128);
        pdu.put("v", 18);
        pdu.put("pri", 129);
        pdu.put("tr_id", "admenot" + r.getString("id").substring(0, Math.min(16, r.getString("id").length())));
        Uri pu = t.insert(Uri.parse("content://mms/" + boxPath), pdu);
        if (pu == null) throw new MmsWriteError("pdu_null");
        if (rejected(pu)) throw new Denied(); // nothing stored, so nothing to roll back
        try {
            writeMmsBody(in, r, pu, addrs);
        } catch (Exception e) {
            // roll back only the pdu row this process has just inserted (its own returned URI)
            int removed;
            try {
                removed = t.delete(pu);
            } catch (Exception d) {
                removed = isDenial(d) ? 0 : -1;
            }
            if (removed == 0) throw new Denied(); // rejectDelete(): the write appop is not allowed
            throw e;
        }
    }

    private void writeMmsBody(JsonLines in, JSONObject r, Uri pu, JSONArray addrs) throws Exception {
        String mid = pu.getLastPathSegment();
        Uri partsUri = Uri.parse("content://mms/" + mid + "/part");
        JSONArray parts = r.getJSONArray("parts");
        for (int i = 0; i < parts.length(); i++) {
            JSONObject p = parts.getJSONObject(i);
            ContentValues pv = new ContentValues();
            pv.put("mid", Long.parseLong(mid));
            pv.put("seq", 0);
            pv.put("ct", p.getString("ct"));
            String name = p.isNull("name") ? null : p.optString("name", null);
            if (name != null) { pv.put("name", name); pv.put("cl", name); pv.put("cid", "<" + name + ">"); }
            if (!p.isNull("text") && p.has("text")) { pv.put("text", p.getString("text")); pv.put("chset", 106); }
            Uri part = t.insert(partsUri, pv);
            if (part == null) throw new MmsWriteError("part_null");
            if (rejected(part)) throw new Denied();
            if (!p.isNull("file") && p.has("file")) copy(in.part(p.getString("file")), t.openOutput(part));
        }
        Uri addrUri = Uri.parse("content://mms/" + mid + "/addr");
        for (int i = 0; i < addrs.length(); i++) {
            JSONArray a = addrs.getJSONArray(i);
            ContentValues av = new ContentValues();
            av.put("address", a.getString(0));
            av.put("type", a.getInt(1));
            av.put("charset", 106);
            Uri au = t.insert(addrUri, av);
            if (au == null) throw new MmsWriteError("addr_null");
            if (rejected(au)) throw new Denied();
        }
    }

    /** The other side of the conversation: sender (+cc) for received, recipients for the rest. */
    static List<String> recipients(JSONArray addrs, int box) throws Exception {
        LinkedHashSet<String> want = new LinkedHashSet<>(), all = new LinkedHashSet<>();
        for (int i = 0; i < addrs.length(); i++) {
            JSONArray a = addrs.getJSONArray(i);
            String addr = a.getString(0);
            int type = a.getInt(1);
            if (addr.isEmpty() || addr.equals("insert-address-token")) continue;
            all.add(addr);
            boolean other = box == 1 ? (type == 137 || type == 130) : (type == 151 || type == 130 || type == 129);
            if (other) want.add(addr);
        }
        return new ArrayList<>(want.isEmpty() ? all : want);
    }

    private long threadId(List<String> recipients) throws Exception {
        if (recipients.isEmpty()) throw new MmsWriteError("no_address");
        Uri.Builder b = Uri.parse("content://mms-sms/threadID").buildUpon();
        for (String a : recipients) b.appendQueryParameter("recipient", a);
        Cursor c = t.query(b.build(), new String[]{"_id"});
        try {
            if (c == null || !c.moveToFirst()) throw new MmsWriteError("no_thread");
            return c.getLong(0);
        } finally {
            if (c != null) c.close();
        }
    }

    static void copy(File src, OutputStream os) throws Exception {
        if (os == null) throw new MmsWriteError("part_stream_null");
        InputStream is = new FileInputStream(src);
        try {
            byte[] buf = new byte[65536];
            int n;
            while ((n = is.read(buf)) > 0) os.write(buf, 0, n);
            os.flush();
        } finally {
            is.close();
            os.close();
        }
    }
}
