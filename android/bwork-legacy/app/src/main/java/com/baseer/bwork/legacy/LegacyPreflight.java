package com.baseer.bwork.legacy;
import com.baseer.bwork.legacy.compat.LegacyIdentity;

import java.io.BufferedInputStream;
import java.io.ByteArrayInputStream;
import java.io.DataInputStream;
import java.io.EOFException;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Read-only structural gate for the known ChatStore v1/v2/v3 ObjectStream format.
 * This parser never loads a stream-selected class or constructs its object graph.
 * Run it before the existing restricted ObjectInputStream and domain validation.
 * It is deliberately not a general Java serialization reader. Unsupported input
 * fails without rewriting, truncating, or replacing the original bytes.
 *
 * Bounds are checked before descent, element loops, and variable allocation.
 * Already-completed references carry graph height, so sharing cannot evade the
 * depth bound. Active references/cycles and non-string map keys are unsupported.
 * Keep the validated bytes stable until deserialization; validate(byte[]) permits
 * the caller to validate and deserialize the same private byte snapshot.
 */
public final class LegacyPreflight {
    public static final long MAX_FILE_BYTES = 32L * 1024L * 1024L;
    private static final int MAX_DEPTH = 32;
    private static final int MAX_DESCRIPTOR_DEPTH = 8;
    private static final int MAX_DESCRIPTORS = 32;
    private static final int MAX_FIELDS = 32;
    private static final int MAX_HANDLES = 250000;
    private static final int MAX_REFERENCES = 500000;
    private static final int MAX_COLLECTION_ITEMS = 100000;
    private static final int MAX_MAP_CAPACITY = 262144;
    private static final long MAX_TOTAL_COLLECTION_SLOTS = 500000;
    private static final int MAX_STRING_BYTES = 60000;
    private static final int MAX_STRING_CHARS = 20000;
    private static final int RETAIN_STRING_CHARS = 256;
    private static final int BASE_HANDLE = 0x7e0000;
    private static final int TC_NULL = 0x70, TC_REFERENCE = 0x71, TC_CLASSDESC = 0x72;
    private static final int TC_OBJECT = 0x73, TC_STRING = 0x74, TC_ARRAY = 0x75;
    private static final int TC_BLOCKDATA = 0x77, TC_ENDBLOCKDATA = 0x78;
    private static final int TC_BLOCKDATALONG = 0x7a, TC_LONGSTRING = 0x7c;
    private static final String DOMAIN = LegacyIdentity.SERIALIZATION_DOMAIN;
    private static final String STRING = "java.lang.String";
    private static final String OBJECT_ARRAY = "[Ljava.lang.Object;";
    private static final String HASH_MAP = "java.util.HashMap";
    private static final String LINKED_MAP = "java.util.LinkedHashMap";
    private static final String ARRAY_LIST = "java.util.ArrayList";
    private static final String UNMOD_COLLECTION = "java.util.Collections$UnmodifiableCollection";
    private static final String UNMOD_LIST = "java.util.Collections$UnmodifiableList";
    private static final String UNMOD_RANDOM = "java.util.Collections$UnmodifiableRandomAccessList";
    private static final Map<String, Shape> SHAPES = shapes();

    private LegacyPreflight() { }

    public static void validate(File file) throws IOException {
        if (file == null || !Files.isRegularFile(file.toPath(), LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Legacy history is missing or is not a regular file");
        long size = Files.size(file.toPath());
        checkFileSize(size);
        try (InputStream input = new BufferedInputStream(new FileInputStream(file))) {
            new Parser(input, size).validate();
        }
    }

    /** Does not copy, modify, or retain the supplied bytes after validation. */
    public static void validate(byte[] bytes) throws IOException {
        if (bytes == null) throw new IOException("Missing legacy history bytes");
        checkFileSize(bytes.length);
        new Parser(new ByteArrayInputStream(bytes), bytes.length).validate();
    }

    private static void checkFileSize(long size) throws IOException {
        if (size < 5 || size > MAX_FILE_BYTES) throw new IOException("Legacy history byte limit exceeded");
    }

    private static final class Parser {
        final InputStream raw;
        final BoundedInputStream bounded;
        final DataInputStream in;
        final List<Node> handles = new ArrayList<Node>();
        final Set<String> descriptorNames = new HashSet<String>();
        int references;
        long collectionSlots;
        long stringCharacters;

        Parser(InputStream raw, long size) {
            this.raw = raw;
            bounded = new BoundedInputStream(raw, size);
            in = new DataInputStream(bounded);
        }
        void validate() throws IOException {
            if (in.readInt() != 0xaced0005) throw invalid("stream header");
            Node root = object(0);
            if (root == null || root.kind != Kind.OBJECT || !root.type.equals(DOMAIN + "State"))
                throw invalid("root object");
            if (bounded.remaining != 0 || raw.read() != -1) throw invalid("trailing contents");
        }
        Node object(int depth) throws IOException {
            depth(depth, MAX_DEPTH);
            int token = in.readUnsignedByte();
            if (token == TC_NULL) return null;
            if (token == TC_REFERENCE) {
                Node value = reference();
                if (value.kind == Kind.DESCRIPTOR) throw invalid("descriptor used as a value");
                return value;
            }
            if (token == TC_STRING || token == TC_LONGSTRING) return string(token, MAX_STRING_BYTES, MAX_STRING_CHARS);
            if (token == TC_OBJECT) return newObject(depth);
            if (token == TC_ARRAY) return array(depth);
            // Class, proxy, enum, reset, exception, and free block records are not this format.
            throw invalid("object token");
        }
        Node newObject(int depth) throws IOException {
            Descriptor descriptor = descriptor(0);
            if (descriptor == null || descriptor.shape.name.equals(OBJECT_ARRAY)) throw invalid("object descriptor");
            Node node = new Node(Kind.OBJECT, descriptor.shape.name);
            register(node);
            List<Descriptor> hierarchy = new ArrayList<Descriptor>();
            for (Descriptor current = descriptor; current != null; current = current.parent) {
                if (hierarchy.size() >= MAX_DESCRIPTOR_DEPTH) throw invalid("class hierarchy depth");
                hierarchy.add(current);
            }
            for (int i = hierarchy.size() - 1; i >= 0; i--) classData(node, hierarchy.get(i), depth);
            node.complete = true;
            return node;
        }
        void classData(Node node, Descriptor descriptor, int depth) throws IOException {
            int listSize = -1;
            for (Field field : descriptor.fields) {
                char type = field.type;
                if (type == 'L' || type == '[') {
                    Node value = object(depth + 1);
                    if (!assignable(field.signature, value)) throw invalid("field value type");
                    link(node, value);
                } else {
                    long value = primitive(type);
                    if (descriptor.shape.name.equals(ARRAY_LIST) && field.name.equals("size")) {
                        listSize = (int) value;
                        count(listSize, 1);
                    } else if (descriptor.shape.name.equals(HASH_MAP)) {
                        if (field.name.equals("loadFactor") && (int) value != Float.floatToIntBits(0.75f))
                            throw invalid("map load factor");
                        if (field.name.equals("threshold") && (value < 0 || value > MAX_MAP_CAPACITY))
                            throw invalid("map threshold");
                    } else if (descriptor.shape.name.equals(DOMAIN + "State") && field.name.equals("version")
                            && (value < 1 || value > 3)) throw invalid("snapshot version");
                }
            }
            if (descriptor.shape.name.equals(ARRAY_LIST)) {
                if (listSize < 0) throw invalid("list size field");
                DataInputStream block = new DataInputStream(new ByteArrayInputStream(block(4)));
                int capacity = block.readInt();
                if (capacity < listSize || capacity > MAX_COLLECTION_ITEMS) throw invalid("list capacity");
                for (int i = 0; i < listSize; i++) link(node, object(depth + 1));
                endBlock();
            } else if (descriptor.shape.name.equals(HASH_MAP)) {
                DataInputStream block = new DataInputStream(new ByteArrayInputStream(block(8)));
                int capacity = block.readInt();
                int size = block.readInt();
                if (capacity < 0 || capacity > MAX_MAP_CAPACITY || (capacity != 0 && (capacity & (capacity - 1)) != 0))
                    throw invalid("map capacity");
                count(size, 2);
                for (int i = 0; i < size; i++) {
                    Node key = object(depth + 1);
                    if (key == null || key.kind != Kind.STRING) throw invalid("map key type");
                    link(node, key);
                    link(node, object(depth + 1));
                }
                endBlock();
            } else if (descriptor.shape.flags != 2) throw invalid("custom class data");
        }
        Node array(int depth) throws IOException {
            Descriptor descriptor = descriptor(0);
            if (descriptor == null || !descriptor.shape.name.equals(OBJECT_ARRAY)) throw invalid("array descriptor");
            Node node = new Node(Kind.ARRAY, OBJECT_ARRAY);
            register(node);
            int size = in.readInt();
            count(size, 1);
            // No array allocation: scan each element only after the declared count is bounded.
            for (int i = 0; i < size; i++) link(node, object(depth + 1));
            node.complete = true;
            return node;
        }
        Descriptor descriptor(int depth) throws IOException {
            depth(depth, MAX_DESCRIPTOR_DEPTH);
            int token = in.readUnsignedByte();
            if (token == TC_NULL) return null;
            if (token == TC_REFERENCE) {
                Node node = reference();
                if (!(node instanceof Descriptor)) throw invalid("class descriptor reference");
                return (Descriptor) node;
            }
            if (token != TC_CLASSDESC) throw invalid("class descriptor token");
            String name = LegacyIdentity.wireClass(utf(in.readUnsignedShort(), 128, 128));
            Shape shape = SHAPES.get(name);
            if (shape == null || descriptorNames.size() >= MAX_DESCRIPTORS || !descriptorNames.add(name))
                throw invalid("class vocabulary");
            long uid = in.readLong();
            if (uid != shape.uid) throw invalid("class version");
            Descriptor descriptor = new Descriptor(shape);
            register(descriptor); // Wire handle is assigned before descriptor fields.
            if (in.readUnsignedByte() != shape.flags) throw invalid("class flags");
            int fields = in.readUnsignedShort();
            if (fields > MAX_FIELDS || fields > shape.fields.size() || fields > bounded.remaining / 3)
                throw invalid("field count");
            Set<String> seen = new HashSet<String>();
            boolean objectsStarted = false;
            String previousPrimitive = "", previousObject = "";
            for (int i = 0; i < fields; i++) {
                char type = (char) in.readUnsignedByte();
                String fieldName = utf(in.readUnsignedShort(), 64, 64);
                Field expected = shape.fields.get(fieldName);
                if (expected == null || expected.type != type || !seen.add(fieldName)) throw invalid("field vocabulary");
                boolean objectField = type == 'L' || type == '[';
                if (objectField) {
                    objectsStarted = true;
                    if (fieldName.compareTo(previousObject) <= 0) throw invalid("field order");
                    previousObject = fieldName;
                    String signature = typeString();
                    if (!expected.signature.equals(signature)) throw invalid("field signature");
                } else {
                    if (objectsStarted || fieldName.compareTo(previousPrimitive) <= 0) throw invalid("field order");
                    previousPrimitive = fieldName;
                }
                descriptor.fields.add(expected);
            }
            for (Field field : shape.fields.values()) if (!field.optional && !seen.contains(field.name))
                throw invalid("required field");
            // Default ObjectOutputStream does not attach arbitrary class annotations.
            endBlock();
            descriptor.parent = descriptor(depth + 1);
            String actualParent = descriptor.parent == null ? null : descriptor.parent.shape.name;
            if (!(shape.parent == null ? actualParent == null : shape.parent.equals(actualParent)))
                throw invalid("class hierarchy");
            descriptor.complete = true;
            return descriptor;
        }
        String typeString() throws IOException {
            int token = in.readUnsignedByte();
            Node node;
            if (token == TC_REFERENCE) node = reference();
            else if (token == TC_STRING) node = string(token, 256, 256);
            else throw invalid("field type token");
            if (node.kind != Kind.STRING || node.text == null) throw invalid("field type reference");
            return LegacyIdentity.wireType(node.text);
        }
        Node string(int token, int maxBytes, int maxCharacters) throws IOException {
            Node node = new Node(Kind.STRING, STRING);
            register(node);
            long length = token == TC_LONGSTRING ? in.readLong() : in.readUnsignedShort();
            if (length < 0 || length > maxBytes || length > bounded.remaining) throw invalid("string length");
            node.text = utf((int) length, maxBytes, maxCharacters);
            node.complete = true;
            return node;
        }
        String utf(int length, int maxBytes, int maxCharacters) throws IOException {
            if (length < 0 || length > maxBytes || length > bounded.remaining) throw invalid("UTF length");
            StringBuilder small = new StringBuilder(Math.min(length, RETAIN_STRING_CHARS));
            int chars = 0;
            for (int used = 0; used < length; ) {
                int first = in.readUnsignedByte(); used++;
                int character;
                if (first >= 1 && first <= 127) character = first;
                else if ((first & 0xe0) == 0xc0) {
                    if (length - used < 1) throw invalid("UTF continuation");
                    int next = in.readUnsignedByte(); used++;
                    if ((next & 0xc0) != 0x80) throw invalid("UTF continuation");
                    character = ((first & 31) << 6) | (next & 63);
                    if (character < 128 && character != 0) throw invalid("UTF encoding");
                } else if ((first & 0xf0) == 0xe0) {
                    if (length - used < 2) throw invalid("UTF continuation");
                    int second = in.readUnsignedByte(), third = in.readUnsignedByte(); used += 2;
                    if ((second & 0xc0) != 0x80 || (third & 0xc0) != 0x80) throw invalid("UTF continuation");
                    character = ((first & 15) << 12) | ((second & 63) << 6) | (third & 63);
                    if (character < 2048) throw invalid("UTF encoding");
                } else throw invalid("UTF encoding");
                if (++chars > maxCharacters || ++stringCharacters > MAX_FILE_BYTES) throw invalid("string character budget");
                if (chars <= RETAIN_STRING_CHARS) small.append((char) character);
            }
            return chars <= RETAIN_STRING_CHARS ? small.toString() : null;
        }
        Node reference() throws IOException {
            if (++references > MAX_REFERENCES) throw invalid("reference budget");
            long index = (long) in.readInt() - BASE_HANDLE;
            if (index < 0 || index >= handles.size()) throw invalid("unknown reference");
            Node node = handles.get((int) index);
            if (!node.complete) throw invalid("active or cyclic reference");
            return node;
        }
        void register(Node node) throws IOException {
            if (handles.size() >= MAX_HANDLES) throw invalid("handle budget");
            handles.add(node);
        }
        void link(Node parent, Node child) throws IOException {
            if (child == null) return;
            int height = child.height + 1;
            if (height > MAX_DEPTH) throw invalid("referenced graph depth");
            parent.height = Math.max(parent.height, height);
        }
        void count(int count, int slotsPerItem) throws IOException {
            if (count < 0 || count > MAX_COLLECTION_ITEMS) throw invalid("collection size");
            long slots = (long) count * slotsPerItem;
            if (slots > bounded.remaining || slots > MAX_TOTAL_COLLECTION_SLOTS - collectionSlots)
                throw invalid("collection allocation budget");
            collectionSlots += slots;
        }
        byte[] block(int expected) throws IOException {
            byte[] data = new byte[expected]; // Only fixed 4/8-byte headers call this method.
            int offset = 0;
            while (offset < expected) {
                int token = in.readUnsignedByte();
                int length;
                if (token == TC_BLOCKDATA) length = in.readUnsignedByte();
                else if (token == TC_BLOCKDATALONG) length = in.readInt();
                else throw invalid("collection header");
                if (length < 1 || length > expected - offset || length > bounded.remaining) throw invalid("block length");
                in.readFully(data, offset, length);
                offset += length;
            }
            return data;
        }
        void endBlock() throws IOException { if (in.readUnsignedByte() != TC_ENDBLOCKDATA) throw invalid("end-of-block marker"); }
        long primitive(char type) throws IOException {
            switch (type) {
                case 'Z': int value = in.readUnsignedByte(); if (value > 1) throw invalid("boolean value"); return value;
                case 'B': return in.readByte();
                case 'C': return in.readUnsignedShort();
                case 'S': return in.readShort();
                case 'I': case 'F': return in.readInt();
                case 'J': case 'D': return in.readLong();
                default: throw invalid("primitive type");
            }
        }
    }

    private static boolean assignable(String signature, Node node) {
        if (node == null) return true;
        if (signature.equals("Ljava/lang/String;")) return node.kind == Kind.STRING;
        if (signature.equals("[Ljava/lang/Object;")) return node.kind == Kind.ARRAY;
        if (node.kind != Kind.OBJECT) return false;
        if (signature.equals("Ljava/util/List;") || signature.equals("Ljava/util/Collection;"))
            return node.type.equals(ARRAY_LIST) || node.type.equals(UNMOD_LIST) || node.type.equals(UNMOD_RANDOM)
                    || (signature.equals("Ljava/util/Collection;") && node.type.equals(UNMOD_COLLECTION));
        return signature.equals("L" + node.type.replace('.', '/') + ";");
    }
    private static void depth(int depth, int maximum) throws IOException {
        if (depth < 0 || depth >= maximum) throw invalid("recursion depth");
    }
    private static IOException invalid(String detail) { return new IOException("Unsupported or out-of-bounds legacy " + detail); }
    private enum Kind { STRING, DESCRIPTOR, OBJECT, ARRAY }
    private static class Node {
        final Kind kind; final String type;
        boolean complete;
        int height = 1;
        String text;
        Node(Kind kind, String type) { this.kind = kind; this.type = type; }
    }
    private static final class Descriptor extends Node {
        final Shape shape;
        final List<Field> fields = new ArrayList<Field>();
        Descriptor parent;
        Descriptor(Shape shape) { super(Kind.DESCRIPTOR, shape.name); this.shape = shape; }
    }
    private static final class Field {
        final char type; final String name; final String signature; final boolean optional;
        Field(String encoded) {
            optional = encoded.charAt(0) == '?';
            if (optional) encoded = encoded.substring(1);
            type = encoded.charAt(0);
            int split = encoded.indexOf(':', 2);
            name = split < 0 ? encoded.substring(2) : encoded.substring(2, split);
            signature = split < 0 ? null : encoded.substring(split + 1);
        }
    }
    private static final class Shape {
        final String name, parent;
        final long uid; final int flags;
        final Map<String, Field> fields = new HashMap<String, Field>();
        Shape(String name, long uid, int flags, String parent, String... encodedFields) {
            this.name = name; this.uid = uid; this.flags = flags; this.parent = parent;
            for (String encoded : encodedFields) { Field field = new Field(encoded); fields.put(field.name, field); }
        }
    }
    private static Map<String, Shape> shapes() {
        Map<String, Shape> shapes = new HashMap<String, Shape>();
        add(shapes, new Shape(DOMAIN + "State", 1L, 2, null,
                "I:version", "L:companies:Ljava/util/LinkedHashMap;", "L:conversations:Ljava/util/LinkedHashMap;",
                "?L:deletedMessages:Ljava/util/LinkedHashMap;", "?L:demoGroupMembers:Ljava/util/LinkedHashMap;",
                "L:drafts:Ljava/util/LinkedHashMap;", "L:messages:Ljava/util/LinkedHashMap;",
                "L:pendingShare:L" + DOMAIN.replace('.', '/') + "PendingShare;",
                "?L:readMarkers:Ljava/util/LinkedHashMap;", "?L:resolvedShares:Ljava/util/LinkedHashMap;"));
        add(shapes, new Shape(DOMAIN + "Company", 1L, 2, null,
                "I:avatarHue", "L:id:Ljava/lang/String;", "L:name:Ljava/lang/String;", "L:subtitle:Ljava/lang/String;"));
        add(shapes, new Shape(DOMAIN + "Conversation", 1L, 2, null,
                "I:avatarHue", "I:unread", "L:companyId:Ljava/lang/String;", "L:id:Ljava/lang/String;",
                "L:kind:Ljava/lang/String;", "L:subtitle:Ljava/lang/String;", "L:title:Ljava/lang/String;"));
        add(shapes, new Shape(DOMAIN + "Attachment", 1L, 2, null,
                "J:size", "L:id:Ljava/lang/String;", "L:mime:Ljava/lang/String;", "L:name:Ljava/lang/String;",
                "L:path:Ljava/lang/String;", "?L:sha256:Ljava/lang/String;"));
        add(shapes, new Shape(DOMAIN + "Draft", 1L, 2, null,
                "L:attachments:Ljava/util/List;", "?L:replyToMessageId:Ljava/lang/String;", "L:text:Ljava/lang/String;"));
        add(shapes, new Shape(DOMAIN + "PendingShare", 1L, 2, null,
                "?Z:previewEdited", "L:attachments:Ljava/util/List;", "L:id:Ljava/lang/String;", "L:text:Ljava/lang/String;"));
        add(shapes, new Shape(DOMAIN + "Message", 1L, 2, null,
                "J:createdAt", "?Z:deleted", "Z:mine", "L:attachments:Ljava/util/List;", "L:companyId:Ljava/lang/String;",
                "L:conversationId:Ljava/lang/String;", "L:id:Ljava/lang/String;", "?L:replyToMessageId:Ljava/lang/String;",
                "L:senderName:Ljava/lang/String;", "L:sourceShareId:Ljava/lang/String;", "L:status:Ljava/lang/String;", "L:text:Ljava/lang/String;"));
        add(shapes, new Shape(HASH_MAP, 362498820763181265L, 3, null, "F:loadFactor", "I:threshold"));
        add(shapes, new Shape(LINKED_MAP, 3801124242820219131L, 2, HASH_MAP, "Z:accessOrder"));
        add(shapes, new Shape(ARRAY_LIST, 8683452581122892189L, 3, null, "I:size"));
        add(shapes, new Shape(UNMOD_COLLECTION, 1820017752578914078L, 2, null, "L:c:Ljava/util/Collection;"));
        add(shapes, new Shape(UNMOD_LIST, -283967356065247728L, 2, UNMOD_COLLECTION, "L:list:Ljava/util/List;"));
        add(shapes, new Shape(UNMOD_RANDOM, -2542308836966382001L, 2, UNMOD_LIST));
        add(shapes, new Shape(OBJECT_ARRAY, -8012369246846506644L, 2, null));
        return shapes;
    }
    private static void add(Map<String, Shape> shapes, Shape shape) { shapes.put(shape.name, shape); }
    private static final class BoundedInputStream extends InputStream {
        final InputStream input; long remaining;
        BoundedInputStream(InputStream input, long length) { this.input = input; remaining = length; }
        public int read() throws IOException {
            if (remaining == 0) return -1;
            int value = input.read(); if (value < 0) throw new EOFException("Incomplete legacy history");
            remaining--; return value;
        }
        public int read(byte[] bytes, int offset, int length) throws IOException {
            if (length == 0) return 0;
            if (remaining == 0) return -1;
            int count = input.read(bytes, offset, (int) Math.min((long) length, remaining));
            if (count < 0) throw new EOFException("Incomplete legacy history"); remaining -= count; return count;
        }
    }
}
