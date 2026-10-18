/** Isolated native layout fixture. Never imported by the application entry point. */
import React, { useEffect, useState } from 'react';
import { Text } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { registerRootComponent } from 'expo';
import { SessionApp } from '../src/odoo/OdooTrialApp';
import {
  ChatEngine,
  ChatError,
  type Bootstrap,
  type Message,
  type Request,
  type Room,
  type Storage,
} from '../src/odoo/core/ChatEngine';

const marker = 'SYNTHETIC_UI_PREVIEW';
const rooms: Room[] = [
  {
    id: 11,
    company_id: 1,
    membership_id: 21,
    name: 'مجموعة المشتريات — Purchasing',
    is_group: true,
    is_group_admin: true,
    last_message_preview: 'تمت مراجعة الطلب، شكرًا لكم',
    unread_count: 2,
  },
  {
    id: 12,
    company_id: 1,
    membership_id: 22,
    name: 'الإدارة — Management',
    is_group: true,
    last_message_preview: 'اجتماع فريق العمل',
  },
  {
    id: 13,
    company_id: 2,
    membership_id: 23,
    name: 'المبيعات — Sales',
    is_group: true,
    last_message_preview: 'Sales team',
  },
];
const identity: Bootstrap = {
  api_version: 2,
  database: 'synthetic',
  user_id: 7,
  company_ids: [1, 2],
  current_company_id: 1,
  csrf_token: 'synthetic-not-a-credential',
  permissions: { chat_view: true, chat_send: true, media: true, group_create: true, revision: 1 },
  mobile_policy: [
    { api_version: 2, company_id: 1, direct_enabled: true, can_manage: true },
    { api_version: 2, company_id: 2, direct_enabled: false, can_manage: false },
  ],
  profile: {
    name: 'حساب معاينة — Preview User',
    companies: [
      {
        id: 1,
        name: 'Preview One',
        name_ar: 'شركة المعاينة الأولى للمطاعم والخدمات التجارية',
        name_en: 'First Preview Restaurant and Commercial Services Company',
      },
      {
        id: 2,
        name: 'Preview Two',
        name_ar: 'شركة المعاينة الثانية',
        name_en: 'Second Preview Company',
      },
    ],
  },
};
const messages: Message[] = Array.from({ length: 16 }, (_, i) => ({
  id: i + 1,
  author_user_id: i % 2 ? 7 : 8,
  author_name: i % 2 ? 'Preview User' : 'فريق المشتريات',
  text: [
    'مرحبًا، هذا مثال لمحادثة مجموعة المشتريات.',
    'تمت مراجعة الطلب، شكرًا لكم.',
    'A longer English message to check wrapping and the message bubble width on a narrow screen.',
    'نص عربي أطول لاختبار التفاف الرسالة ومساحة القراءة داخل المحادثة دون خروج المحتوى عن عرض الشاشة.',
  ][i % 4]!,
  created_at: `2026-10-18 12:${String(i).padStart(2, '0')}:00`,
  delivery_state: i % 2 ? 'read' : 'sent',
}));
class MemoryStorage implements Storage {
  private data = new Map<string, string>();
  async getItem(key: string) {
    return this.data.get(key) ?? null;
  }
  async setItem(key: string, value: string) {
    this.data.set(key, value);
  }
  async removeItem(key: string) {
    this.data.delete(key);
  }
  async getAllKeys() {
    return [...this.data.keys()];
  }
}
const transport = {
  async request(r: Request): Promise<unknown> {
    if (r.path === '/web/session/destroy') return { result: null };
    if (r.path === '/web/session/authenticate') return { result: { uid: 7, db: 'synthetic' } };
    if (r.path === '/bchat/api/v2/bootstrap') return identity;
    if (r.path === '/bchat/api/v2/rooms' && r.method === 'GET') return { api_version: 2, rooms };
    if (r.path.startsWith('/bchat/api/v2/changes'))
      return { api_version: 2, changes: [], next_after: 0, watermark: 0, reset_required: false };
    const receipt = /messages\/(\d+)\/receipts$/.exec(r.path);
    if (receipt)
      return {
        api_version: 2,
        message_id: Number(receipt[1]),
        delivered_at: '2026-10-18 12:30:00',
        read_at: '2026-10-18 12:30:01',
        unread_count: 0,
        last_message_id: 16,
        replayed: false,
      };
    if (/\/rooms\/\d+\/messages/.test(r.path) && r.method === 'GET')
      return { api_version: 2, messages, next_before_id: null };
    if (/\/rooms\/\d+\/messages$/.test(r.path) && r.method === 'POST') {
      const payload = JSON.parse(r.form!.payload!);
      const id = messages.length + 1;
      const parent = messages.find(message => message.id === payload.reply_to_message_id);
      messages.push({
        id,
        author_user_id: 7,
        author_name: 'Preview User',
        text: payload.text,
        created_at: '2026-10-18 12:31:00',
        delivery_state: 'sent',
        ...(parent ? { reply: { id: parent.id, author_name: parent.author_name, text: parent.text } } : {}),
      });
      return {
        api_version: 2,
        room_id: 11,
        membership_id: 21,
        client_uuid: payload.client_uuid,
        message_id: id,
        state: 'sent',
      };
    }
    throw new ChatError('preview_route_not_supported');
  },
};
const engine = new ChatEngine({
  storage: new MemoryStorage(),
  transport,
  origin: 'https://ui-preview.invalid',
  database: 'synthetic',
});
function PreviewApp() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    void engine.login('synthetic', 'synthetic', true).then(() => setReady(true));
  }, []);
  return (
    <SafeAreaProvider>
      {ready ? <SessionApp engine={engine} /> : <Text>{marker}</Text>}
    </SafeAreaProvider>
  );
}
registerRootComponent(PreviewApp);
