package android.app;

import android.content.Context;
import java.util.ArrayList;
import java.util.List;

/** Records only the renderer API boundary. No framework/OS behavior is simulated. */
public final class Notification {
    public static final class Builder {
        public final String channel;
        public CharSequence title, text;
        public long when;
        public MessagingStyle style;
        public Builder(Context context, String channel) { this.channel = channel; }
        public Builder setContentTitle(CharSequence title) { this.title = title; return this; }
        public Builder setContentText(CharSequence text) { this.text = text; return this; }
        public Builder setWhen(long when) { this.when = when; return this; }
        public Builder setStyle(MessagingStyle style) { this.style = style; return this; }
    }
    public static final class MessagingStyle {
        public final CharSequence user;
        public CharSequence title;
        public final List<Message> messages = new ArrayList<>();
        public MessagingStyle(CharSequence user) { this.user = user; }
        public MessagingStyle(Person user) { throw new AssertionError("API28 Person constructor reached"); }
        public MessagingStyle setConversationTitle(CharSequence title) { this.title = title; return this; }
        public MessagingStyle setGroupConversation(boolean group) { throw new AssertionError("API28 group setter reached"); }
        public MessagingStyle addMessage(CharSequence text, long at, CharSequence sender) {
            messages.add(new Message(text, at, sender)); return this;
        }
        public MessagingStyle addMessage(CharSequence text, long at, Person sender) {
            throw new AssertionError("API28 addMessage reached");
        }
        public static final class Message {
            public final CharSequence text, sender;
            public final long at;
            Message(CharSequence text, long at, CharSequence sender) { this.text = text; this.at = at; this.sender = sender; }
        }
    }
}
