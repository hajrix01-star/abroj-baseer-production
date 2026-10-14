package com.baseer.freshchat;

import android.content.Context;
import android.content.ContextWrapper;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.media.ExifInterface;
import android.os.Looper;
import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import java.util.zip.CRC32;
import java.util.zip.DeflaterOutputStream;

/**
 * Public Android API native-decoder kernel; no Activity, hidden API, UI, provider, installation or key.
 * Must run only under the coordinator's authorized ordinary raw-dalvik test process.
 */
public final class MediaKernelMain {
    private static final int[] COLORS = {Color.RED, Color.GREEN, Color.BLUE, Color.YELLOW};
    private static final int[][] CORNERS = {
            {0,1,2,3}, {1,0,3,2}, {3,2,1,0}, {2,3,0,1},
            {0,2,1,3}, {2,0,3,1}, {3,1,2,0}, {1,3,0,2}
    };
    private static volatile String stage = "argument-validation";
    private static int checks;

    /** A test-owned files root, using only public ContextWrapper overrides needed by the decoder. */
    private static final class FilesContext extends ContextWrapper {
        private final File files;
        FilesContext(File files) { super(null); this.files = files; }
        @Override public Context getApplicationContext() { return this; }
        @Override public File getFilesDir() { return files; }
    }

    public static void main(String[] args) {
        File root = null;
        List<File> owned = new ArrayList<>();
        Thread worker = null;
        int code = 1;
        try {
            if (args.length != 1) throw new IllegalArgumentException("Provide an owned /data/local/tmp fixture parent");
            File parent = new File(args[0]).getCanonicalFile();
            if (!parent.getPath().startsWith("/data/local/tmp/"))
                throw new IllegalArgumentException("Fixture parent must be below /data/local/tmp/");
            if (!parent.isDirectory()) throw new IOException("Coordinator must create the owned fixture parent first");
            root = Files.createTempDirectory(parent.toPath(), "media-kernel-").toFile();
            File files = new File(root, "files");
            File attachments = new File(files, "attachments");
            if (!attachments.mkdirs()) throw new IOException("Cannot create owned fixture directory");
            FilesContext context = new FilesContext(files);
            stage = "public-Looper.prepareMainLooper";
            // Raw dalvik normally has no Looper. Do not replace an already prepared public main Looper.
            if (Looper.getMainLooper() == null) Looper.prepareMainLooper();
            check(Looper.myLooper() != null && Looper.myLooper() == Looper.getMainLooper(),
                    "Public main Looper prepared on entry thread");
            AtomicReference<Throwable> failure = new AtomicReference<>();
            worker = new Thread(() -> {
                try {
                    check(Looper.myLooper() != Looper.getMainLooper(), "Native decoding runs on a non-main worker");
                    tallPng(context, attachments, owned);
                    jpegOrientations(context, attachments, owned);
                } catch (Throwable error) { failure.set(error); }
            }, "bchat-public-media-kernel");
            worker.start();
            worker.join(90_000);
            if (worker.isAlive()) throw new IOException("Ordinary decoder worker exceeded 90 seconds at " + stage);
            if (failure.get() != null) throw failure.get();
            code = 0;
            System.out.println("PASS " + checks + " public-API native media kernel checks");
            System.out.println("LIMITS: Decoder/EXIF/pixels only. No UI gestures, PDF, provider, playback, physical-device or signed-upgrade acceptance.");
        } catch (Throwable failure) {
            System.out.println("ERROR stage=" + stage + " checks=" + checks + " type=" + failure.getClass().getName()
                    + " message=" + String.valueOf(failure.getMessage()));
            failure.printStackTrace(System.out);
            System.out.println("STOP: No hidden API, ActivityThread/system context, registration or runtime bypass is attempted.");
        } finally {
            // Do not unlink fixtures beneath an operation still running. System.exit ends the test process.
            if (root != null && (worker == null || !worker.isAlive())) {
                for (File file : owned) file.delete();
                new File(root, "files/attachments").delete();
                new File(root, "files").delete();
                root.delete();
            }
        }
        System.exit(code);
    }

    private static void tallPng(Context context, File directory, List<File> owned) throws Exception {
        stage = "generate-valid-tall-PNG";
        File file = new File(directory, "ordinary-tall.png"); owned.add(file);
        writeTallPng(file, 1200, 20000);
        byte[] before = digest(file);
        ChatStore.Attachment attachment = attachment(file, "image/png");

        stage = "ImagePreviews.decodeDetail-PNG-metadata";
        ImagePreviews.DetailResult metadata = ImagePreviews.decodeDetail(context, attachment, null, 1);
        check(metadata.info.width == 1200 && metadata.info.height == 20000, "Tall source header remains 1200x20000");

        stage = "ImagePreviews.decodeDetail-PNG-original-region";
        Rect region = new Rect(120, 8000, 1120, 8700);
        ImagePreviews.DetailResult result = ImagePreviews.decodeDetail(context, attachment, region, 1);
        Bitmap tile = result.bitmap;
        try {
            check(tile != null && tile.getWidth() == 1000 && tile.getHeight() == 700,
                    "Valid tall PNG yields an exact 1000x700 original-resolution tile");
            check(tile.getAllocationByteCount() <= 8 * 1024 * 1024 && tile.getConfig() != Bitmap.Config.HARDWARE,
                    "Region output is software allocated within 8 MiB");
            check(region.equals(result.region), "Decoded tile identifies the requested source region");
            for (int[] pixel : new int[][]{{0,0},{100,100},{999,699}}) {
                check(tile.getPixel(pixel[0], pixel[1]) == sourceColor(region.left + pixel[0], region.top + pixel[1]),
                        "Exact original PNG pixel at tile " + pixel[0] + "," + pixel[1]);
            }
        } finally { if (tile != null) tile.recycle(); }

        stage = "ImagePreviews.decodeDetail-PNG-whole-image-fit";
        Bitmap whole = ImagePreviews.decodeDetail(context, attachment, new Rect(0, 0, 1200, 20000), 1).bitmap;
        try {
            check(whole != null && Math.max(whole.getWidth(), whole.getHeight()) <= 1400
                            && whole.getAllocationByteCount() <= 8 * 1024 * 1024,
                    "Normal whole-image region fits the 1400-pixel/8-MiB output budget");
        } finally { if (whole != null) whole.recycle(); }

        stage = "ImagePreviews.decode-PNG-overview";
        Bitmap overview = ImagePreviews.decode(context, attachment, 1400);
        try {
            check(overview != null && overview.getWidth() < overview.getHeight()
                            && Math.max(overview.getWidth(), overview.getHeight()) <= 1400,
                    "Ordinary overview path retains tall orientation and bounded dimensions");
        } finally { if (overview != null) overview.recycle(); }
        check(Arrays.equals(before, digest(file)), "All PNG decoding leaves exact original bytes unchanged");
    }

    private static void jpegOrientations(Context context, File directory, List<File> owned) throws Exception {
        for (int orientation = 1; orientation <= 8; orientation++) {
            stage = "generate-valid-JPEG-EXIF-" + orientation;
            File file = new File(directory, "ordinary-exif-" + orientation + ".jpg"); owned.add(file);
            Bitmap pixels = Bitmap.createBitmap(320, 180, Bitmap.Config.ARGB_8888);
            try {
                Canvas canvas = new Canvas(pixels); Paint paint = new Paint();
                for (int corner = 0; corner < 4; corner++) {
                    paint.setColor(COLORS[corner]);
                    canvas.drawRect(corner % 2 * 160, corner / 2 * 90,
                            corner % 2 * 160 + 160, corner / 2 * 90 + 90, paint);
                }
                try (FileOutputStream output = new FileOutputStream(file)) {
                    if (!pixels.compress(Bitmap.CompressFormat.JPEG, 100, output)) throw new IOException("Valid JPEG creation failed");
                }
            } finally { pixels.recycle(); }
            ExifInterface exif = new ExifInterface(file.getPath());
            exif.setAttribute(ExifInterface.TAG_ORIENTATION, String.valueOf(orientation)); exif.saveAttributes();
            byte[] before = digest(file); ChatStore.Attachment attachment = attachment(file, "image/jpeg");

            stage = "ImagePreviews.decodeDetail-JPEG-EXIF-" + orientation;
            ImagePreviews.DetailResult result = ImagePreviews.decodeDetail(context, attachment, new Rect(0, 0, 320, 180), 1);
            Bitmap upright = Bitmap.createBitmap(result.info.displayWidth, result.info.displayHeight, Bitmap.Config.ARGB_8888);
            try {
                Canvas canvas = new Canvas(upright); canvas.concat(result.info.orientationMatrix()); canvas.drawBitmap(result.bitmap, 0, 0, null);
                check((upright.getWidth() > upright.getHeight()) == (orientation <= 4), "Detail EXIF " + orientation + " dimensions");
                assertCorners(upright, orientation, "detail");
            } finally { upright.recycle(); if (result.bitmap != null) result.bitmap.recycle(); }

            stage = "ImagePreviews.decode-JPEG-EXIF-" + orientation;
            Bitmap overview = ImagePreviews.decode(context, attachment, 650);
            try {
                check((overview.getWidth() > overview.getHeight()) == (orientation <= 4), "Overview EXIF " + orientation + " dimensions");
                assertCorners(overview, orientation, "overview");
            } finally { if (overview != null) overview.recycle(); }
            check(Arrays.equals(before, digest(file)), "EXIF " + orientation + " inspection leaves original JPEG unchanged");
        }
    }

    private static void assertCorners(Bitmap bitmap, int orientation, String path) {
        int width = bitmap.getWidth(), height = bitmap.getHeight();
        int[] actual = {bitmap.getPixel(width/4,height/4),bitmap.getPixel(width*3/4,height/4),
                bitmap.getPixel(width/4,height*3/4),bitmap.getPixel(width*3/4,height*3/4)};
        for (int corner = 0; corner < 4; corner++) {
            int expected = COLORS[CORNERS[orientation - 1][corner]];
            check(Math.abs(Color.red(actual[corner]) - Color.red(expected)) < 20
                            && Math.abs(Color.green(actual[corner]) - Color.green(expected)) < 20
                            && Math.abs(Color.blue(actual[corner]) - Color.blue(expected)) < 20,
                    path + " EXIF " + orientation + " corner " + corner);
        }
    }

    private static ChatStore.Attachment attachment(File file, String mime) throws IOException {
        return new ChatStore.Attachment(java.util.UUID.randomUUID().toString(), file.getCanonicalPath(), file.getName(), mime, file.length());
    }
    private static int sourceColor(int x, int y) { return ((x / 3 + y / 5) & 1) == 0 ? Color.rgb(24,80,133) : Color.rgb(243,215,69); }
    private static void writeTallPng(File file, int width, int height) throws IOException {
        ByteArrayOutputStream compressed = new ByteArrayOutputStream();
        try (DeflaterOutputStream output = new DeflaterOutputStream(compressed)) {
            byte[] row = new byte[1 + width * 3];
            for (int y = 0; y < height; y++) {
                for (int x = 0; x < width; x++) {
                    int color = sourceColor(x,y); row[1+x*3]=(byte)Color.red(color);row[2+x*3]=(byte)Color.green(color);row[3+x*3]=(byte)Color.blue(color);
                }
                output.write(row);
            }
        }
        try (DataOutputStream output = new DataOutputStream(new FileOutputStream(file))) {
            output.write(new byte[]{(byte)137,80,78,71,13,10,26,10});
            ByteArrayOutputStream bytes = new ByteArrayOutputStream(); DataOutputStream header = new DataOutputStream(bytes);
            header.writeInt(width);header.writeInt(height);header.write(new byte[]{8,2,0,0,0});
            chunk(output,"IHDR",bytes.toByteArray());chunk(output,"IDAT",compressed.toByteArray());chunk(output,"IEND",new byte[0]);
        }
    }
    private static void chunk(DataOutputStream output, String name, byte[] bytes) throws IOException {
        byte[] type = name.getBytes(java.nio.charset.StandardCharsets.US_ASCII);
        output.writeInt(bytes.length);output.write(type);output.write(bytes);CRC32 crc=new CRC32();crc.update(type);crc.update(bytes);output.writeInt((int)crc.getValue());
    }
    private static byte[] digest(File file) throws Exception { return MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file.toPath())); }
    private static void check(boolean condition, String label) {
        if (!condition) throw new AssertionError(label); checks++; System.out.println("PASS " + label);
    }
}
