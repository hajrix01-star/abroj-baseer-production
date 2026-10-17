package com.baseer.freshchat;

/** Compile adapter for the unused offline entry point; connected decoding does not use this model. */
final class ChatStore {
    static final class Attachment {
        String id, path, mime;
        long size;
    }
}
