/* Read-only source extract. It returns only active ARZ raw materials, units,
   conversions and the last operational purchase price; never documents, bills,
   custody, suppliers, employees or financial postings. */
SELECT json_build_object(
  'source', 'baseer_erp_test/ARZ/operations-catalog',
  'source_company_id', '7e64301f-c87e-4d98-9881-35328ace117b',
  'items', COALESCE(json_agg(json_build_object(
    'source_id', i.id,
    'code', i.code,
    'name_ar', i."nameAr",
    'name_en', i."nameEn",
    'base_unit_id', i."baseUnitId",
    'units', COALESCE((SELECT json_agg(json_build_object(
      'source_id', u.id, 'code', u.code, 'name_ar', u."nameAr",
      'name_en', u."nameEn", 'dimension', u.dimension
    ) ORDER BY u.code)
    FROM "OperationsUnit" u
    WHERE u.id = i."baseUnitId"
       OR u.id IN (SELECT iu."unitId" FROM "OperationsItemUnit" iu WHERE iu."itemId" = i.id AND iu."isActive")), '[]'::json),
    'options', COALESCE((SELECT json_agg(json_build_object(
      'source_id', iu.id, 'unit_id', iu."unitId", 'is_base', iu."isBase",
      'is_order_enabled', iu."isOrderEnabled", 'last_price', iu."lastPurchaseUnitPrice",
      'last_price_at', iu."lastPurchasePriceAt"
    ) ORDER BY iu."isBase" DESC, iu.id)
    FROM "OperationsItemUnit" iu WHERE iu."itemId" = i.id AND iu."isActive"), '[]'::json),
    'conversions', COALESCE((SELECT json_agg(json_build_object(
      'from_unit_id', e."fromUnitId", 'to_unit_id', e."toUnitId", 'factor', e.factor
    ) ORDER BY e.id)
    FROM "OperationsItemConversionVersion" v
    JOIN "OperationsItemConversionEdge" e ON e."versionId" = v.id
    WHERE v."itemId" = i.id AND v.status = 'PUBLISHED'), '[]'::json)
  ) ORDER BY i."nameAr"), '[]'::json)
) AS payload
FROM "OperationsItem" i
WHERE i."companyId" = '7e64301f-c87e-4d98-9881-35328ace117b'
  AND i.kind = 'RAW_MATERIAL' AND i.status = 'ACTIVE';
