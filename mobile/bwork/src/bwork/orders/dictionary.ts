import type { Language } from '../ui/dictionary';

const en = {
  serverUpdateRequired: 'This workflow requires a server update.', chooseCompany: 'Choose a company to create orders.', noWarehouse: 'No warehouse is available for this company.',
  orderSettings: 'Order settings', filters: 'Product filters', quoting: 'Updating estimate',
  orderSavedShare: 'Order saved. Choose a conversation to share it.', orderShared: 'Order shared', chooseRoom: 'Choose a conversation', searchRooms: 'Search conversations',
  noRooms: 'No eligible conversations. Try another search.', roomsLimit: 'Showing up to 200 conversations. Search to find another.',
  rememberRoom: 'Remember this conversation', clearDefault: 'Clear default conversation', defaultUnavailable: 'The saved conversation is unavailable. Choose another.',
  shareOrder: 'Share order', retryShare: 'Retry sharing', sharePermission: 'Sharing requires send permission.',
  orderShareFailed: 'The order is saved, but sharing failed. Retry sharing only.', receiptShareFailed: 'The receipt is confirmed, but sharing failed. Retry sharing only.',
  roomUnavailable: 'This conversation is unavailable. Choose another.', shareConflict: 'The order is already linked to another conversation.',
  messageTooLong: 'The order is saved, but its message exceeds the conversation limit.',
  preferenceInvalid: 'The saved conversation preference is invalid. Clear it or choose another.',
  estimatedUnitPrice: 'Estimated unit price', lineTotal: 'Line total',
  orders: 'Orders', purchaseRequests: 'Purchase requests', catalog: 'Catalog', allOrders: 'All orders', receiving: 'Receiving',
  company: 'Order company', receiptCompany: 'Receiving company', allCompanies: 'All authorized companies', warehouse: 'Warehouse',
  search: 'Search products', searchHint: 'Product name', all: 'All', lastPrice: 'Last price', add: 'Add', cart: 'Cart',
  reviewCart: 'Review cart', estimated: 'Estimated total', pendingQuote: 'Awaiting Odoo quote', quote: 'Get Odoo quote',
  estimateNote: 'An estimate only. Odoo reprices the order when submitted.', back: 'Back', reviewOrder: 'Review order',
  method: 'Purchase route', representative: 'Representative', cash: 'Cash', bank_transfer: 'Transfer', representativeLabel: 'Purchase representative',
  routeNote: 'The route does not execute a payment or bank transfer.', conversation: 'Order conversation', none: 'No conversation',
  noRoomNote: 'Without a conversation, the receipt result cannot later be shared to an original room.', sendOrder: 'Submit order',
  quoteRequired: 'The changed cart needs a fresh Odoo quote before submission.', returnOrders: 'Go to all orders', details: 'Order details',
  requestedTotal: 'Requested total', requested: 'Requested', requester: 'Requested by', orderDate: 'Order date',
  sent: 'Awaiting receipt', received: 'Manager received', purchased: 'Completed', cancel: 'Cancelled', draft: 'Draft',
  historical: 'Original request values, not the actual receipt amounts.', openReceipt: 'Enter receipt', receiptTitle: 'Receive order',
  actualQty: 'Actual quantity', actualPrice: 'Actual unit price', reviewReceipt: 'Review receipt', confirmReceipt: 'Confirm receipt',
  receiptWarning: 'Confirmation records the actual purchase and updates price and cost. Stock movement follows the product’s inventory settings.',
  actualTotal: 'Actual total', afterOdoo: 'Returned by Odoo after confirmation', shareReceipt: 'Share receipt result',
  shareNote: 'Sharing is separate and never confirms the receipt again.', shareHelp: 'Sharing requires the original room, send permission, and current membership.',
  noAccess: 'No permission to view orders', permissionHelp: 'Permissions come from the Odoo user settings.', offline: 'Connect to open orders',
  offlineHelp: 'Orders and receipt confirmations are not submitted offline.', error: 'Could not load orders. Try again.', retry: 'Try again',
  empty: 'No orders here', emptyHelp: 'Authorized BWork orders will appear here when available.', noResults: 'No matching products',
  noResultsHelp: 'Try another name or category.', noReceipts: 'No orders awaiting receipt', noReceiptsHelp: 'Choose another company or check back later.',
  cartEmpty: 'Your cart is empty', cartEmptyHelp: 'Add products from the catalog.', orderScope: 'All employees’ BWork orders across your authorized companies',
  receiptsScope: 'Orders available to receive across your authorized companies', menu: 'Menu', close: 'Close', remove: 'Remove', undo: 'Undo removal',
  validation: 'Enter quantity and price with up to 2 decimals. Zero quantity requires zero price; received items need a positive price.',
  quantityValidation: 'Enter a positive quantity with up to 2 decimals.', needPositive: 'Enter a positive quantity and price for at least one item.',
  unknown: 'Result unknown. Retry the saved attempt to check the same operation.', pending: 'Unresolved attempts', retryAttempt: 'Retry saved attempt',
  quantity: 'Quantity', unit: 'Purchase unit', loadMore: 'Load more', loading: 'Loading', select: 'Select', status: 'Status',
  created: 'Order submitted', confirmed: 'Receipt confirmed', shared: 'Receipt result shared', forbidden: 'Order access changed. Reopen orders after your permissions are checked.',
  stale: 'The session or company changed. Reopen orders to load current data.', storage: 'Could not safely save the attempt. Try again before submitting.',
  cartLimit: 'The cart supports up to 100 lines.', listLimit: 'Showing up to 200 recent orders. Reload to return to the newest orders.',
  refresh: 'Reload', noOptions: 'No available options', choose: 'Choose an option', missingSelection: 'Choose a warehouse and purchase route, and a representative when required.',
  pendingBlock: 'Resolve the saved attempt before submitting another operation.', unavailable: 'Unavailable', noPrice: 'No recorded price',
} as const;

const ar: Record<keyof typeof en, string> = {
  serverUpdateRequired: 'يتطلب هذا التدفق تحديث الخادم.', chooseCompany: 'اختر شركة لإنشاء الطلبات.', noWarehouse: 'لا يوجد مستودع متاح لهذه الشركة.',
  orderSettings: 'إعدادات الطلب', filters: 'تصفية الأصناف', quoting: 'جارٍ تحديث التقدير',
  orderSavedShare: 'الطلب محفوظ. اختر محادثة لمشاركته.', orderShared: 'الطلب مشارك', chooseRoom: 'اختر محادثة', searchRooms: 'البحث عن محادثة',
  noRooms: 'لا توجد محادثات متاحة. جرّب بحثًا آخر.', roomsLimit: 'نعرض 200 محادثة كحد أقصى. ابحث عن المحادثة المطلوبة.',
  rememberRoom: 'تذكر هذه المحادثة', clearDefault: 'إلغاء المحادثة الافتراضية', defaultUnavailable: 'المحادثة المحفوظة غير متاحة. اختر أخرى.',
  shareOrder: 'مشاركة الطلب', retryShare: 'إعادة المشاركة', sharePermission: 'تتطلب المشاركة صلاحية الإرسال.',
  orderShareFailed: 'الطلب محفوظ، وتعذّرت مشاركته. أعد المشاركة فقط.', receiptShareFailed: 'الاستلام مؤكد، وتعذّرت مشاركته. أعد المشاركة فقط.',
  roomUnavailable: 'المحادثة غير متاحة. اختر أخرى.', shareConflict: 'الطلب مرتبط بمحادثة أخرى.',
  messageTooLong: 'الطلب محفوظ، لكن رسالته تتجاوز الحد المسموح في المحادثة.',
  preferenceInvalid: 'اختيار المحادثة المحفوظ غير صالح. ألغِه أو اختر محادثة أخرى.',
  estimatedUnitPrice: 'سعر الوحدة التقديري', lineTotal: 'إجمالي السطر',
  orders: 'الطلبات', purchaseRequests: 'طلبات المشتريات', catalog: 'المنيو', allOrders: 'كل الطلبات', receiving: 'الاستلام',
  company: 'شركة الطلب', receiptCompany: 'شركة الاستلام', allCompanies: 'كل الشركات المصرح بها', warehouse: 'المستودع',
  search: 'البحث عن صنف', searchHint: 'اسم الصنف', all: 'الكل', lastPrice: 'آخر سعر', add: 'إضافة', cart: 'السلة',
  reviewCart: 'مراجعة السلة', estimated: 'الإجمالي التقديري', pendingQuote: 'بانتظار تقدير أودو', quote: 'طلب تقدير أودو',
  estimateNote: 'السعر تقديري. يعيد أودو التسعير عند الإرسال.', back: 'رجوع', reviewOrder: 'مراجعة الطلب',
  method: 'مسار الشراء', representative: 'مندوب', cash: 'نقد', bank_transfer: 'تحويل', representativeLabel: 'مندوب المشتريات',
  routeNote: 'المسار لا ينفّذ دفعة أو تحويلًا ماليًا.', conversation: 'محادثة الطلب', none: 'بدون محادثة',
  noRoomNote: 'بدون محادثة، لن تتاح مشاركة نتيجة الاستلام في غرفة لاحقًا.', sendOrder: 'إرسال الطلب',
  quoteRequired: 'تحتاج السلة المعدّلة تقديرًا حديثًا من أودو قبل الإرسال.', returnOrders: 'الانتقال إلى كل الطلبات', details: 'تفاصيل الطلب',
  requestedTotal: 'الإجمالي المطلوب', requested: 'المطلوب', requester: 'صاحب الطلب', orderDate: 'تاريخ الطلب',
  sent: 'بانتظار الاستلام', received: 'استلام إداري', purchased: 'مكتمل', cancel: 'ملغى', draft: 'مسودة',
  historical: 'هذه بيانات الطلب الأصلية، وليست مبالغ الاستلام الفعلي.', openReceipt: 'إدخال الاستلام', receiptTitle: 'استلام الطلب',
  actualQty: 'الكمية الفعلية', actualPrice: 'سعر الوحدة الفعلي', reviewReceipt: 'مراجعة الاستلام', confirmReceipt: 'تأكيد الاستلام',
  receiptWarning: 'التأكيد يسجل الشراء الفعلي ويحدّث السعر والتكلفة. حركة المخزون حسب إعداد الصنف وتفعيل تتبعه.',
  actualTotal: 'الإجمالي الفعلي', afterOdoo: 'يظهر في رد أودو بعد التأكيد', shareReceipt: 'مشاركة نتيجة الاستلام',
  shareNote: 'المشاركة مستقلة ولا تؤكد الاستلام مرة أخرى.', shareHelp: 'تتطلب المشاركة الغرفة الأصلية وحق الإرسال والعضوية الحالية.',
  noAccess: 'ليس لديك صلاحية عرض الطلبات', permissionHelp: 'الصلاحيات من إعدادات المستخدم في أودو.', offline: 'اتصل لفتح الطلبات',
  offlineHelp: 'لا تُرسل الطلبات أو تأكيدات الاستلام دون اتصال.', error: 'تعذّر تحميل الطلبات. حاول مرة أخرى.', retry: 'إعادة المحاولة',
  empty: 'لا توجد طلبات', emptyHelp: 'ستظهر طلبات BWork المصرح بها عند توفرها.', noResults: 'لا توجد أصناف مطابقة',
  noResultsHelp: 'جرّب اسمًا آخر أو غيّر الفئة.', noReceipts: 'لا توجد طلبات بانتظار الاستلام', noReceiptsHelp: 'اختر شركة أخرى أو عُد لاحقًا.',
  cartEmpty: 'السلة فارغة', cartEmptyHelp: 'أضف أصنافًا من المنيو.', orderScope: 'طلبات BWork لجميع الموظفين عبر الشركات المصرح بها',
  receiptsScope: 'الطلبات المتاحة للاستلام عبر الشركات المصرح بها', menu: 'القائمة', close: 'إغلاق', remove: 'حذف', undo: 'تراجع عن الحذف',
  validation: 'أدخل الكمية والسعر بمنزلتين عشريتين كحد أقصى. الكمية صفر تتطلب سعرًا صفرًا، والأصناف المستلمة تتطلب سعرًا موجبًا.',
  quantityValidation: 'أدخل كمية موجبة بمنزلتين عشريتين كحد أقصى.', needPositive: 'أدخل كمية وسعرًا موجبين لصنف واحد على الأقل.',
  unknown: 'النتيجة غير محسومة. أعد المحاولة المحفوظة للتحقق من العملية نفسها.', pending: 'محاولات غير محسومة', retryAttempt: 'إعادة المحاولة المحفوظة',
  quantity: 'الكمية', unit: 'وحدة الشراء', loadMore: 'تحميل المزيد', loading: 'جارٍ التحميل', select: 'اختيار', status: 'الحالة',
  created: 'أُرسل الطلب', confirmed: 'الاستلام مؤكد', shared: 'شوركت نتيجة الاستلام', forbidden: 'تغيرت صلاحية الطلبات. افتح القسم بعد التحقق من حقوقك.',
  stale: 'تغيرت الجلسة أو الشركة. افتح الطلبات لتحميل البيانات الحالية.', storage: 'تعذّر حفظ المحاولة بأمان. أعد المحاولة قبل الإرسال.',
  cartLimit: 'تدعم السلة 100 سطر كحد أقصى.', listLimit: 'نعرض أحدث 200 طلب كحد أقصى. أعد التحميل للعودة إلى أحدث الطلبات.',
  refresh: 'إعادة التحميل', noOptions: 'لا توجد خيارات متاحة', choose: 'اختر أحد الخيارات', missingSelection: 'اختر المستودع ومسار الشراء والمندوب إذا كان مطلوبًا.',
  pendingBlock: 'احسم المحاولة المحفوظة قبل إرسال عملية أخرى.', unavailable: 'غير متاح', noPrice: 'لا يوجد سعر مسجل',
};

export type OrderWord = keyof typeof en;
export const orderTranslator = (language: Language) => (key: OrderWord): string => (language === 'ar' ? ar : en)[key];

/** Preserve Odoo's decimal text: never parse, add, round or substitute another total. */
export const displayNumber = (value: string | number | null | undefined): string => String(value ?? '')
  .replace(/[٠-٩]/g, digit => String('٠١٢٣٤٥٦٧٨٩'.indexOf(digit)))
  .replace(/[۰-۹]/g, digit => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(digit)));

export function orderErrorWord(error: unknown): OrderWord {
  const code = typeof error === 'object' && error !== null && 'code' in error ? String(error.code) : '';
  if (code === 'unknown') return 'unknown';
  if (code === 'server_update_required') return 'serverUpdateRequired';
  if (code === 'room_unavailable') return 'roomUnavailable';
  if (code === 'order_share_conflict') return 'shareConflict';
  if (code === 'room_message_too_long') return 'messageTooLong';
  if (code === 'preference_corrupt') return 'preferenceInvalid';
  if (code === 'stale') return 'stale';
  if (['forbidden', 'unauthorized', 'company_forbidden'].includes(code)) return 'forbidden';
  if (code.includes('storage') || code.includes('journal')) return 'storage';
  if (['invalid_payload', 'invalid_decimal'].includes(code)) return 'validation';
  return 'error';
}
