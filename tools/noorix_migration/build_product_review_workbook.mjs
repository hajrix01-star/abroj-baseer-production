import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "outputs/noorix_product_review_20260912";
const outputPath = `${outputDir}/noorix_products_odoo_qa_import_plan.xlsx`;
const sourceDb = "noorix_product_mapping_20260912";
const targetDb = "baseer_noorix_data_migration_qa_20260912";

function docker(args) {
  return execFileSync("docker", args, { encoding: "utf8" }).trim();
}

function psql(containerArgs, database, sql) {
  return docker([...containerArgs, "psql", "-U", "odoo", "-d", database, "-At", "-c", sql]);
}

function queryJson(containerArgs, database, sql) {
  const result = psql(containerArgs, database, sql);
  return result ? JSON.parse(result) : [];
}

function normalize(value) {
  return String(value ?? "")
    .normalize("NFKC")
    .toLowerCase()
    .trim()
    .replace(/[أإآ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .replace(/ـ/g, "")
    .replace(/[^\p{L}\p{N}\u0600-\u06FF]/gu, "");
}

const productTranslations = {
  "أوراق الكيل": "Kale Leaves", "أوراق زعتر طازج": "Fresh Thyme Leaves", "أوراق كيل": "Kale Leaves", "إسفنج غسيل": "Cleaning Sponge",
  "ارز 10 كيلو": "Rice 10 kg", "اكياس ورق": "Paper Bags", "اوبر": "Uber", "ايس تي خوخ": "Peach Iced Tea",
  "ايس تي كوكتيل": "Cocktail Iced Tea", "ايس تي ليمون": "Lemon Iced Tea", "باذنجان اسود متبل": "Marinated Black Eggplant",
  "باذنجان محشي": "Stuffed Eggplant", "باشن فروت مجمد": "Frozen Passion Fruit", "بالونات": "Balloons", "بترول اسامة": "Osama Petroleum",
  "براد شاي": "Tea Kettle", "بصل ابيض": "White Onion", "بصل مشوي وسط": "Medium Grilled Onion", "بصل مصري وسط": "Medium Egyptian Onion",
  "بطاطس امريكانا": "Americana Potato", "بقدونس": "Parsley", "بهارات بروستد": "Broasted Seasoning", "بهارات بروستد بارد": "Mild Broasted Seasoning",
  "بهارات بروستد حار": "Spicy Broasted Seasoning", "بودره ماتشا": "Matcha Powder", "بودره مشروم ماجي": "Maggi Mushroom Powder", "بيبسي": "Pepsi",
  "ثوم": "Garlic", "ثوم عادي": "Regular Garlic", "جبن شيدر": "Cheddar Cheese", "جرجير": "Arugula", "جزر": "Carrot",
  "جوافه مجمده": "Frozen Guava", "حبر طابعه": "Printer Ink", "حبوب ذره فشار": "Popcorn Kernels", "حمص رقم 12 --15 كجم": "Chickpeas No. 12 – 15 kg",
  "حوافه مجمده": "Frozen Hawafah", "خردل جالون": "Mustard Gallon", "خس": "Lettuce", "خس طويل": "Romaine Lettuce", "خيار": "Cucumber",
  "دبس رمان": "Pomegranate Molasses", "دجاج 1000 جرام للبروستد": "1000 g Chicken for Broasted", "دجاج 1100 جم": "1100 g Chicken", "دجاج 900 مبرد": "900 g Chilled Chicken",
  "ديتول": "Dettol", "روز ماري": "Rosemary", "زبادي كبير": "Large Yogurt", "زيت ابو زهرة 9 لتر": "Abu Zahra Oil 9 L",
  "زيت العربي": "Al Arabi Oil", "زيت الوليد": "Al Waleed Oil", "زيت زيتون السوسن": "Al Sousan Olive Oil", "سائل غسيل الصحون": "Dishwashing Liquid",
  "سفرة 110*100": "Table Cover 110 × 100", "سياره": "Car", "سياره اسامه": "Osama Car", "سيرب الحلويات العربيه": "Arabic Sweets Syrup",
  "سيرب ايس تي خوخً": "Peach Iced Tea Syrup", "شحم": "Animal Fat", "شريحه استيل صح اسود": "Black Stainless Steel Sheet", "شفره خلاط 2لتر": "2 L Blender Blade",
  "شموع عيد ميلاد": "Birthday Candles", "صابون أرضيات": "Floor Cleaner", "صابون سائل فيري": "Fairy Liquid Soap", "صحن ألمنيوم طبق المعلم": "Al Muallim Aluminum Plate",
  "صحن بروستد": "Broasted Plate", "صحن بروستد شدة 100 بحة": "Broasted Plate Pack – 100 pcs", "صحن بطاطس": "French Fries Plate", "صحن فتوش": "Fattoush Plate",
  "صحن كفتة": "Kofta Plate", "صحن كيلو": "1 kg Plate", "صحن مقبلات صغير": "Small Appetizer Plate", "صحن مقبلات وسط": "Medium Appetizer Plate",
  "صحن نص كيلو": "Half-Kilo Plate", "صحن نفر-150 حبة": "Individual Plate – 150 pcs", "صدور مجمده": "Frozen Chicken Breasts", "صلصة تركي 5 كيلو": "Turkish Sauce 5 kg",
  "طحين سعودي 45 كيلو": "Saudi Flour 45 kg", "طحين كويتي": "Kuwaiti Flour", "طحينه الجميل 10 لتر": "Al Jameel Tahini 10 L", "طقم ادوات ماتشا": "Matcha Tool Set",
  "طماط شوكة": "Fork Tomato", "عدس احمر": "Red Lentils", "علبة ثوم اسود-2000 حبة": "Black Garlic Container – 2,000 pcs", "علبة حمص صغير بلاستك -50 حبة شدة": "Small Plastic Hummus Container – Pack of 50",
  "علب ثوم أسود": "Black Garlic Containers", "علب صوصات": "Sauce Containers", "علب معسل": "Molasses Tobacco Containers", "غاز": "Gas",
  "فاصل تي الومنيوم عادي": "Standard Aluminum T Divider", "فحم": "Charcoal", "فحم١": "Charcoal 1", "فحممم": "Charcoal", "فحمممم": "Charcoal",
  "فرشه حمام": "Bathroom Brush", "فلفل أبيض بودر": "White Pepper Powder", "فلفل احمر بارد": "Mild Red Pepper", "فلفل اصفر": "Yellow Pepper",
  "فلفل مشوي": "Grilled Pepper", "قصدير ثلاثين سم - 450 متر": "Aluminum Foil 30 cm – 450 m", "قصدير صغير خمس واربعون-150 متر": "Small Aluminum Foil 45 cm – 150 m",
  "قفازات": "Gloves", "كاتشب جالون": "Ketchup Gallon", "كاتشب شفرات سفري": "Ketchup Travel Pack", "كاسات": "Cups",
  "كرات وجرجير": "Leeks and Arugula", "كرتون فحم": "Charcoal Carton", "كركديه": "Hibiscus", "كزبرة": "Coriander", "كزبرة بودر": "Coriander Powder",
  "كمون بودر": "Cumin Powder", "كيس بلاستيك قياس 20M": "Plastic Bag Size 20M", "كيس بلاستيك قياس 20S": "Plastic Bag Size 20S",
  "كيس بلاستيك قياس 20SS": "Plastic Bag Size 20SS", "كيس بلدية قياس 100": "Municipal Bag Size 100", "كيس حمام": "Bathroom Bag", "كيك": "Cake",
  "لحم اوصال خام": "Raw Meat Pieces", "لحم خروف": "Lamb Meat", "لحم خروف بالكيلو": "Lamb Meat per kg", "ليمون": "Lemon",
  "ماء 50": "Water 50", "ماجي": "Maggi", "ماجي مرقه دجاج": "Maggi Chicken Stock", "مايونيز": "Mayonnaise", "مايونيز جالون": "Mayonnaise Gallon",
  "مخلل مشكل 6 كيلو": "Mixed Pickles 6 kg", "معءل": "Muallal", "ملاعق بلاستك بيضاء": "White Plastic Spoons", "مناديل تاير": "Tayer Tissues",
  "مناديل مبلله": "Wet Wipes", "موب مع عصا": "Mop with Handle", "نايلون تغليف": "Packaging Nylon", "نعنع": "Mint",
  "هاجري": "Hajri", "هاجري بيع": "Hajri Sale", "هاربك": "Harpic", "هانيكن": "Heineken", "ورق كيلو": "1 kg Paper", "ورق نص كيلو": "Half-Kilo Paper",
};

const categoryTranslations = {
  "DRINK": "Beverages", "FOOD": "Food", "OFFER": "Offers", "SWEETS": "Sweets", "أدوات تغليف": "Packaging Supplies", "أدوات تقديم": "Serving Supplies",
  "أدوات تنظيف": "Cleaning Supplies", "ألبان": "Dairy Products", "ألبان وبيض": "Dairy and Eggs", "الأطباق الرئيسيه": "Main Dishes", "باستا": "Pasta",
  "بحريات": "Seafood", "بهارات": "Spices", "بهارات وتوابل": "Spices and Seasonings", "بودرة": "Powder", "بوريه": "Puree", "بيتزا": "Pizza",
  "تشغيل": "Operations", "تغليف": "Packaging", "حبوب ودقيق": "Grains and Flour", "خضار": "Vegetables", "خضروات وفواكه": "Vegetables and Fruits",
  "زيوت وسمن": "Oils and Ghee", "ساندوتش": "Sandwiches", "سلطه": "Salads", "سيرب": "Syrups", "شوربة": "Soups",
  "صلصات ومعجنات": "Sauces and Pastries", "صوصات": "Sauces", "عروض": "Offers", "عصائر": "Juices", "فحم": "Charcoal", "فواكه": "Fruits",
  "قهوة": "Coffee", "لحوم": "Meat", "لحوم ودواجن": "Meat and Poultry", "مجمدات": "Frozen Foods", "مخبوزات": "Bakery", "مشروبات": "Beverages",
  "معسل": "Molasses Tobacco", "مقبلات": "Appetizers", "مقبلات باررده": "Cold Appetizers", "مقبلات حاره": "Hot Appetizers", "مكسرات": "Nuts",
  "مناقيش": "Manakish", "مواد أخرى": "Other Materials", "مواد أولية": "Raw Materials", "مواد تنظيف": "Cleaning Materials", "مواد غذائية": "Food Supplies",
};

const misplacedEnglishCategoryArabic = {
  drink: "مشروبات",
  food: "مواد غذائية",
  offer: "عروض",
  shisha: "شيشة",
  sweets: "حلويات",
};

function hasArabic(value) {
  return /[\u0600-\u06FF]/.test(String(value ?? ""));
}

function hasLatin(value) {
  return /[A-Za-z]/.test(String(value ?? ""));
}

function isShisha(categoryName) {
  return ["shisha", "شيشه"].includes(normalize(categoryName));
}

function translatedValue(rawValue, sourceName, categoryName, translations, label) {
  const existing = String(rawValue ?? "").trim();
  if (existing) return { value: existing, status: "موجودة في نوركس" };
  if (isShisha(categoryName)) return { value: "", status: "مستثنى: Shisha" };
  const translated = translations[String(sourceName ?? "").trim()];
  if (!translated) throw new Error(`Missing ${label} translation for: ${sourceName}`);
  return { value: translated, status: "ترجمة مضافة" };
}

function categoryBilingual(category) {
  const sourceArabic = String(category.name_ar ?? "").trim();
  const sourceEnglish = String(category.name_en ?? "").trim();

  // Some Noorix records put an English value in the Arabic field. Move it to
  // its correct column and write the approved Arabic equivalent.
  if (hasLatin(sourceArabic) && !hasArabic(sourceArabic)) {
    const approvedArabic = misplacedEnglishCategoryArabic[sourceArabic.toLowerCase()];
    if (!approvedArabic) throw new Error(`Missing Arabic category correction for: ${sourceArabic}`);
    return {
      arabic: approvedArabic,
      english: sourceEnglish || sourceArabic,
      status: "تصحيح موضع اللغة",
    };
  }

  // Handle the inverse situation defensively if it exists in a later extract.
  if (hasArabic(sourceEnglish) && (!hasArabic(sourceArabic) || !sourceArabic)) {
    return {
      arabic: sourceEnglish,
      english: sourceArabic,
      status: "تصحيح موضع اللغة",
    };
  }

  // Shisha product names remain outside the translation fill rule, but the
  // category master itself must still have its Arabic and English labels.
  if (isShisha(sourceArabic)) {
    return {
      arabic: sourceArabic,
      english: sourceEnglish || "Shisha",
      status: sourceEnglish ? "موجودة في نوركس" : "ترجمة مضافة",
    };
  }

  const translation = translatedValue(sourceEnglish, sourceArabic, sourceArabic, categoryTranslations, "category");
  return { arabic: sourceArabic, english: translation.value, status: translation.status };
}

const foodCategoryNames = new Set([
  "ألبان", "ألبان وبيض", "الأطباق الرئيسيه", "باستا", "بحريات", "بهارات", "بهارات وتوابل", "بودرة", "بوريه", "بيتزا",
  "حبوب ودقيق", "خضار", "خضروات وفواكه", "زيوت وسمن", "ساندوتش", "سلطه", "سيرب", "شوربة", "صلصات ومعجنات", "صوصات",
  "عصائر", "فواكه", "قهوة", "لحوم", "لحوم ودواجن", "مجمدات", "مخبوزات", "مشروبات", "مقبلات", "مقبلات باررده",
  "مقبلات حاره", "مكسرات", "مناقيش", "مواد غذائية", "مواد أولية", "حلويات",
]);

function categoryPlan(bilingual, activeItemCount) {
  if (!activeItemCount) return { root: "", target: "", action: "لا تنشأ", note: "لا يوجد صنف نشط في نطاق الاستيراد" };
  const root = foodCategoryNames.has(bilingual.arabic) ? "Food" : "Goods";
  return {
    root,
    target: `${root} / ${bilingual.arabic}`,
    action: "إنشاء فئة فرعية في QA",
    note: "الفئة التقنية مشتركة؛ المنتجات نفسها تبقى معزولة حسب الشركة",
  };
}

function unitPlan(unit) {
  const name = String(unit.name_ar ?? "").trim();
  const safeMappings = new Map([
    ["حبة", { target: "الوحدات", action: "إعادة استخدام وحدة أودو", note: "وحدة عدّ بمعامل 1" }],
    ["جرام", { target: "g", action: "إعادة استخدام وحدة أودو", note: "كتلة؛ معامل المصدر 1" }],
    ["كيلو", { target: "كجم", action: "إعادة استخدام وحدة أودو", note: "كتلة؛ 1 كجم = 1,000 جرام" }],
    ["لتر", { target: "L", action: "إعادة استخدام وحدة أودو", note: "حجم؛ 1 لتر = 1,000 مل" }],
    ["مل", { target: "مل", action: "إعادة استخدام وحدة أودو", note: "حجم؛ معامل المصدر 1" }],
  ]);
  const mapped = safeMappings.get(name);
  if (mapped) return mapped;
  if (unit.dimension === "package") return {
    target: `وحدة مستقلة: ${name}`,
    action: "إنشاء وحدة مستقلة بلا تحويل في QA",
    note: "لا يوجد معامل تحويل في نوركس؛ يمنع افتراض أنها حبة أو صندوق قياسي",
  };
  throw new Error(`Missing UoM plan for: ${name}`);
}

function setColumnWidths(sheet, widths) {
  widths.forEach((width, index) => {
    sheet.getCell(0, index).format.columnWidth = width;
  });
}

function styleHeader(range) {
  range.format = {
    fill: "#1F4E78",
    font: { name: "Arial", bold: true, color: "#FFFFFF", size: 10 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#17365D" },
  };
  range.format.rowHeight = 30;
}

const sourceItemsSql = `
SELECT COALESCE(json_agg(json_build_object(
  'source_id', i.id,
  'company', co.name_ar,
  'name_ar', i.name_ar,
  'name_en', i.name_en,
  'sku', i.sku,
  'item_type', CASE i.item_type WHEN 'purchased' THEN 'شراء' WHEN 'sale' THEN 'بيع' ELSE COALESCE(i.item_type, '') END,
  'track_inventory', i.track_inventory,
  'active', i.is_active,
  'category_id', i.category_id,
  'category_name', ca.name_ar,
  'category_name_en', ca.name_en,
  'unit_name', un.name_ar,
  'unit_id', i.inventory_unit_id,
  'unit_code', un.code,
  'category_note', CASE WHEN i.category_id IS NULL THEN 'بدون فئة مصدر' ELSE '' END
) ORDER BY co.name_ar, i.name_ar, i.id), '[]'::json)::text
FROM orders_v4_items i
JOIN companies co ON co.id = i.company_id
LEFT JOIN orders_v4_categories ca ON ca.id = i.category_id
LEFT JOIN orders_v4_units un ON un.id = i.inventory_unit_id
WHERE co.name_ar NOT IN ('TEST', 'TEST1');`;

const sourceCategoriesSql = `
SELECT COALESCE(json_agg(json_build_object(
  'source_id', ca.id, 'company', co.name_ar, 'name_ar', ca.name_ar,
  'name_en', ca.name_en, 'active', ca.is_active
) ORDER BY co.name_ar, ca.name_ar), '[]'::json)::text
FROM orders_v4_categories ca
JOIN companies co ON co.id = ca.company_id
WHERE co.name_ar NOT IN ('TEST', 'TEST1');`;

const sourceUnitsSql = `
SELECT COALESCE(json_agg(json_build_object(
  'source_id', un.id, 'company', co.name_ar, 'code', un.code,
  'name_ar', un.name_ar, 'name_en', un.name_en, 'dimension', un.dimension,
  'factor', un.canonical_factor, 'decimal_scale', un.decimal_scale, 'active', un.is_active
) ORDER BY co.name_ar, un.name_ar), '[]'::json)::text
FROM orders_v4_units un
JOIN companies co ON co.id = un.company_id
WHERE co.name_ar NOT IN ('TEST', 'TEST1');`;

const targetProductsSql = `
SELECT COALESCE(json_agg(json_build_object(
  'id', pp.id, 'name', COALESCE(pt.name->>'ar_001', pt.name->>'ar', pt.name->>'en_US', ''), 'default_code', pp.default_code, 'barcode', pp.barcode,
  'active', pt.active, 'type', pt.type, 'company_id', pt.company_id,
  'category_name', pc.complete_name, 'uom_name', COALESCE(u.name->>'ar_001', u.name->>'ar', u.name->>'en_US', '')
) ORDER BY pt.name, pp.id), '[]'::json)::text
FROM product_product pp
JOIN product_template pt ON pt.id = pp.product_tmpl_id
LEFT JOIN product_category pc ON pc.id = pt.categ_id
LEFT JOIN uom_uom u ON u.id = pt.uom_id;`;

const targetCategoriesSql = `
SELECT COALESCE(json_agg(json_build_object('id', id, 'name', name, 'complete_name', complete_name) ORDER BY complete_name), '[]'::json)::text
FROM product_category;`;

const targetUnitsSql = `
SELECT COALESCE(json_agg(json_build_object('id', id, 'name', name, 'active', active) ORDER BY name), '[]'::json)::text
FROM uom_uom;`;

const sourceContainer = ["exec", "baseer_odoo_dev-db-1"];
const targetContainer = ["compose", "exec", "-T", "db"];
const sourceItems = queryJson(sourceContainer, sourceDb, sourceItemsSql);
const sourceCategories = queryJson(sourceContainer, sourceDb, sourceCategoriesSql);
const sourceUnits = queryJson(sourceContainer, sourceDb, sourceUnitsSql);
const targetProducts = queryJson(targetContainer, targetDb, targetProductsSql);
const targetCategories = queryJson(targetContainer, targetDb, targetCategoriesSql);
const targetUnits = queryJson(targetContainer, targetDb, targetUnitsSql);

const targetProductsByName = new Map();
for (const product of targetProducts) {
  const key = normalize(product.name);
  if (!key) continue;
  const rows = targetProductsByName.get(key) ?? [];
  rows.push(product);
  targetProductsByName.set(key, rows);
}
const sourceNameCounts = new Map();
for (const item of sourceItems) {
  const key = normalize(item.name_ar);
  if (key) sourceNameCounts.set(key, (sourceNameCounts.get(key) ?? 0) + 1);
}

const activeItemCountByCategoryId = new Map();
const activeItemCountByUnitId = new Map();
for (const item of sourceItems.filter((item) => item.active)) {
  if (item.category_id) activeItemCountByCategoryId.set(item.category_id, (activeItemCountByCategoryId.get(item.category_id) ?? 0) + 1);
  if (item.unit_id) activeItemCountByUnitId.set(item.unit_id, (activeItemCountByUnitId.get(item.unit_id) ?? 0) + 1);
}

const categoryBySourceId = new Map(
  sourceCategories.map((category) => [category.source_id, categoryBilingual(category)]),
);
const categoryPlanBySourceId = new Map(
  sourceCategories.map((category) => [
    category.source_id,
    categoryPlan(categoryBySourceId.get(category.source_id), activeItemCountByCategoryId.get(category.source_id) ?? 0),
  ]),
);
const unitPlanBySourceId = new Map(sourceUnits.map((unit) => [
  unit.source_id,
  (activeItemCountByUnitId.get(unit.source_id) ?? 0)
    ? unitPlan(unit)
    : { target: "", action: "لا تنشأ", note: "لا يوجد صنف نشط في نطاق الاستيراد" },
]));
const plannedCategoryTargets = new Set(
  sourceCategories
    .filter((category) => (activeItemCountByCategoryId.get(category.source_id) ?? 0) > 0)
    .map((category) => categoryPlanBySourceId.get(category.source_id).target),
);
const activePackageSourceRows = sourceItems.filter((item) => item.active && unitPlanBySourceId.get(item.unit_id)?.action.startsWith("إنشاء"));

const itemRows = sourceItems.map((item) => {
  const key = normalize(item.name_ar);
  const candidates = targetProductsByName.get(key) ?? [];
  const category = categoryBySourceId.get(item.category_id);
  const categoryName = category?.arabic ?? item.category_name;
  const itemCategoryPlan = item.category_id
    ? categoryPlanBySourceId.get(item.category_id)
    : { target: "Goods", action: "استخدام Goods الافتراضية", note: "نوركس لا يحدد فئة المصدر" };
  const itemUnitPlan = unitPlanBySourceId.get(item.unit_id);
  const translation = translatedValue(item.name_en, item.name_ar, categoryName, productTranslations, "product");
  const comparison = !item.active
    ? "غير نشط في نوركس"
    : candidates.length === 1
      ? "تطابق اسم فقط — يحتاج اعتماد"
      : candidates.length > 1
        ? "أكثر من مرشح في أودو"
        : "لا يوجد تطابق تلقائي";
  return [
    item.source_id,
    item.company ?? "",
    item.name_ar ?? "",
    translation.value,
    translation.status,
    item.sku ?? "",
    item.item_type ?? "",
    item.track_inventory ? "نعم" : "لا",
    item.active ? "نشط" : "غير نشط",
    categoryName ?? "",
    itemCategoryPlan.target,
    item.unit_name ?? "",
    itemUnitPlan?.target ?? "",
    item.unit_code ?? "",
    (sourceNameCounts.get(key) ?? 0) > 1 ? "اسم مكرر في نوركس" : "",
    comparison,
    candidates.length === 1 ? candidates[0].name ?? "" : "",
    item.category_note ?? "",
    !item.active
      ? "مستبعد: غير نشط"
      : itemUnitPlan?.action.startsWith("إنشاء")
        ? "معلق: إنشاء وحدة مستقلة"
        : item.category_id
          ? "جاهز بعد إنشاء فئة QA"
          : "جاهز بتحفظ: Goods الافتراضية",
  ];
});

const workbook = Workbook.create();
const summary = workbook.worksheets.add("ملخص");
const itemsSheet = workbook.worksheets.add("أصناف نوركس");
const odooSheet = workbook.worksheets.add("أصناف أودو");
const categoriesSheet = workbook.worksheets.add("الفئات");
const unitsSheet = workbook.worksheets.add("وحدات القياس");

for (const sheet of [summary, itemsSheet, odooSheet, categoriesSheet, unitsSheet]) {
  sheet.showGridLines = false;
}

summary.getRange("A1:F1").merge();
summary.getRange("A1").values = [["مقارنة أصناف نوركس مع أودو QA"]];
summary.getRange("A1").format = { font: { name: "Arial", bold: true, size: 16, color: "#1F1F1F" }, verticalAlignment: "center" };
summary.getRange("A1").format.rowHeight = 28;
summary.getRange("A2:F2").merge();
summary.getRange("A2").values = [["نطاق الفحص: شركات نوركس التشغيلية فقط، مع استبعاد TEST وTEST1. لا يحتوي الملف على أي تعديل في أودو."]];
summary.getRange("A2").format = { font: { name: "Arial", italic: true, size: 10, color: "#595959" }, wrapText: true };
summary.getRange("A4:B4").values = [["المؤشر", "العدد"]];
styleHeader(summary.getRange("A4:B4"));
summary.getRange("A5:B15").values = [
  ["إجمالي أصناف نوركس", sourceItems.length],
  ["الأصناف النشطة في نوركس", sourceItems.filter((item) => item.active).length],
  ["الأصناف غير النشطة في نوركس", sourceItems.filter((item) => !item.active).length],
  ["أصناف نوركس برقم SKU", sourceItems.filter((item) => String(item.sku ?? "").trim()).length],
  ["أصناف أودو QA", targetProducts.length],
  ["أصناف أودو QA النشطة", targetProducts.filter((product) => product.active).length],
  ["فئات نوركس", sourceCategories.length],
  ["فئات أودو", targetCategories.length],
  ["وحدات نوركس", sourceUnits.length],
  ["وحدات أودو", targetUnits.length],
  ["أصناف نشطة بلا فئة مصدر", sourceItems.filter((item) => item.active && !item.category_name).length],
];
summary.getRange("B5:B15").format.numberFormat = "#,##0";
summary.getRange("A4:B15").format.borders = { preset: "outside", style: "thin", color: "#B7C9D6" };
summary.getRange("D4:F4").values = [["قاعدة المطابقة", "النتيجة", "الإجراء"]];
styleHeader(summary.getRange("D4:F4"));
summary.getRange("D5:F9").values = [
  ["رقم الصنف (SKU)", "لا يوجد SKU مملوء في نوركس", "لا مطابقة تلقائية بالكود"],
  ["الاسم العربي", "لا يوجد تطابق فريد ضمن الأصناف النشطة", "لا دمج تلقائي بالاسم"],
  ["الفئة", `${plannedCategoryTargets.size} فئة فرعية مقترحة تحت Food/Goods`, "إنشاءها في QA قبل الأصناف"],
  ["وحدة القياس", `${sourceItems.filter((item) => item.active).length - activePackageSourceRows.length} صفًا بمطابقة مباشرة`, "إعادة استخدام وحدات أودو القائمة"],
  ["عبوات بلا معامل", `${activePackageSourceRows.length} صنفًا`, "إنشاء وحدة مستقلة بلا تحويل؛ لا افتراض تحويل"],
];
summary.getRange("D4:F9").format.borders = { preset: "outside", style: "thin", color: "#B7C9D6" };
summary.getRange("A17:F17").merge();
summary.getRange("A17").values = [["المصدر: أرشيف نوركس النظامي (db.dump)؛ الهدف: قاعدة Odoo QA المحلية؛ تاريخ الإعداد: 2026-09-12."]];
summary.getRange("A17").format = { font: { name: "Arial", italic: true, size: 9, color: "#595959" }, wrapText: true };
setColumnWidths(summary, [34, 14, 4, 25, 28, 28]);

const itemHeaders = [["معرف نوركس", "الشركة", "اسم الصنف العربي", "الاسم الإنجليزي", "حالة الترجمة", "SKU", "النوع", "يتتبع المخزون", "الحالة", "فئة نوركس", "خطة فئة أودو", "وحدة المخزون", "خطة وحدة أودو", "رمز الوحدة", "ملاحظة التكرار", "نتيجة المقارنة مع أودو", "مرشح أودو", "ملاحظة المصدر", "جاهزية الاستيراد"]];
itemsSheet.getRange(`A1:S${itemRows.length + 1}`).write([itemHeaders[0], ...itemRows]);
styleHeader(itemsSheet.getRange("A1:S1"));
itemsSheet.freezePanes.freezeRows(1);
itemsSheet.getRange(`A2:S${itemRows.length + 1}`).format.font = { name: "Arial", size: 10, color: "#1F1F1F" };
itemsSheet.getRange(`A2:S${itemRows.length + 1}`).format.verticalAlignment = "center";
itemsSheet.getRange(`C2:E${itemRows.length + 1}`).format.wrapText = true;
itemsSheet.getRange(`P2:P${itemRows.length + 1}`).conditionalFormats.add("containsText", { text: "لا يوجد تطابق", format: { fill: "#FFF2CC", font: { color: "#7F6000" } } });
itemsSheet.getRange(`O2:O${itemRows.length + 1}`).conditionalFormats.add("containsText", { text: "مكرر", format: { fill: "#FCE4D6", font: { color: "#C00000" } } });
itemsSheet.getRange(`E2:E${itemRows.length + 1}`).conditionalFormats.add("containsText", { text: "ترجمة مضافة", format: { fill: "#E2F0D9", font: { color: "#375623" } } });
itemsSheet.getRange(`S2:S${itemRows.length + 1}`).conditionalFormats.add("containsText", { text: "معلق", format: { fill: "#FCE4D6", font: { color: "#C00000" } } });
setColumnWidths(itemsSheet, [18, 20, 30, 28, 18, 16, 12, 15, 12, 22, 26, 18, 26, 14, 20, 28, 28, 20, 28]);

const odooHeaders = [["معرف أودو", "اسم الصنف", "الكود الداخلي", "الباركود", "النوع", "الحالة", "شركة أودو", "الفئة", "وحدة القياس"]];
const odooRows = targetProducts.map((product) => [
  product.id, product.name ?? "", product.default_code ?? "", product.barcode ?? "", product.type ?? "",
  product.active ? "نشط" : "غير نشط", product.company_id ?? "مشترك", product.category_name ?? "", product.uom_name ?? "",
]);
odooSheet.getRange(`A1:I${odooRows.length + 1}`).write([odooHeaders[0], ...odooRows]);
styleHeader(odooSheet.getRange("A1:I1"));
odooSheet.freezePanes.freezeRows(1);
odooSheet.getRange(`A2:I${odooRows.length + 1}`).format.font = { name: "Arial", size: 10, color: "#1F1F1F" };
odooSheet.getRange(`B2:I${odooRows.length + 1}`).format.wrapText = true;
setColumnWidths(odooSheet, [15, 32, 18, 18, 13, 12, 16, 32, 18]);

const categoryHeaders = [["معرف نوركس", "الشركة", "اسم نوركس الأصلي", "العربية المعتمدة", "الإنجليزية المعتمدة", "حالة الترجمة", "الأصناف النشطة", "الجذر القائم في أودو", "فئة أودو المقترحة", "قرار الخريطة", "ملاحظة", "الحالة"]];
const categoryRows = sourceCategories.map((category) => {
  const bilingual = categoryBySourceId.get(category.source_id);
  const plan = categoryPlanBySourceId.get(category.source_id);
  const activeItemCount = activeItemCountByCategoryId.get(category.source_id) ?? 0;
  return [category.source_id, category.company ?? "", category.name_ar ?? "", bilingual.arabic, bilingual.english, bilingual.status, activeItemCount, plan.root, plan.target, plan.action, plan.note, category.active ? "نشط" : "غير نشط"];
});
categoriesSheet.getRange(`A1:L${categoryRows.length + 1}`).write([categoryHeaders[0], ...categoryRows]);
styleHeader(categoriesSheet.getRange("A1:L1"));
categoriesSheet.freezePanes.freezeRows(1);
categoriesSheet.getRange(`A2:L${categoryRows.length + 1}`).format.font = { name: "Arial", size: 10, color: "#1F1F1F" };
categoriesSheet.getRange(`F2:F${categoryRows.length + 1}`).conditionalFormats.add("containsText", { text: "ترجمة مضافة", format: { fill: "#E2F0D9", font: { color: "#375623" } } });
categoriesSheet.getRange(`F2:F${categoryRows.length + 1}`).conditionalFormats.add("containsText", { text: "تصحيح موضع اللغة", format: { fill: "#DDEBF7", font: { color: "#1F4E78" } } });
categoriesSheet.getRange(`J2:J${categoryRows.length + 1}`).conditionalFormats.add("containsText", { text: "لا تنشأ", format: { fill: "#E7E6E6", font: { color: "#595959" } } });
setColumnWidths(categoriesSheet, [18, 22, 28, 28, 28, 18, 14, 20, 30, 26, 42, 12]);

const unitHeaders = [["معرف نوركس", "الشركة", "رمز الوحدة", "اسم الوحدة", "الاسم الإنجليزي", "البعد", "معامل التحويل", "المنازل العشرية", "الأصناف النشطة", "وحدة أودو المقترحة", "قرار الخريطة", "ملاحظة", "الحالة"]];
const unitRows = sourceUnits.map((unit) => {
  const plan = unitPlanBySourceId.get(unit.source_id);
  return [unit.source_id, unit.company ?? "", unit.code ?? "", unit.name_ar ?? "", unit.name_en ?? "", unit.dimension ?? "", unit.factor ?? "", unit.decimal_scale ?? "", activeItemCountByUnitId.get(unit.source_id) ?? 0, plan.target, plan.action, plan.note, unit.active ? "نشط" : "غير نشط"];
});
unitsSheet.getRange(`A1:M${unitRows.length + 1}`).write([unitHeaders[0], ...unitRows]);
styleHeader(unitsSheet.getRange("A1:M1"));
unitsSheet.freezePanes.freezeRows(1);
unitsSheet.getRange(`A2:M${unitRows.length + 1}`).format.font = { name: "Arial", size: 10, color: "#1F1F1F" };
unitsSheet.getRange(`G2:H${unitRows.length + 1}`).format.numberFormat = "#,##0.###";
unitsSheet.getRange(`K2:K${unitRows.length + 1}`).conditionalFormats.add("containsText", { text: "إنشاء", format: { fill: "#FFF2CC", font: { color: "#7F6000" } } });
setColumnWidths(unitsSheet, [18, 22, 16, 28, 26, 16, 18, 16, 14, 28, 32, 52, 12]);

for (const sheet of [itemsSheet, odooSheet, categoriesSheet, unitsSheet]) {
  const used = sheet.getUsedRange();
  used.format.borders = { preset: "outside", style: "thin", color: "#D9E2F3" };
}

await fs.mkdir(outputDir, { recursive: true });
const preview = await workbook.render({ sheetName: "ملخص", range: "A1:F17", scale: 1.5, format: "png" });
await fs.writeFile(`${outputDir}/summary-preview.png`, new Uint8Array(await preview.arrayBuffer()));
const inspect = await workbook.inspect({ kind: "table", range: "أصناف نوركس!A1:S12", include: "values,formulas", tableMaxRows: 12, tableMaxCols: 19 });
console.log(inspect.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 50 }, summary: "final formula error scan" });
console.log(errors.ndjson);
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, sourceItems: sourceItems.length, targetProducts: targetProducts.length }));
