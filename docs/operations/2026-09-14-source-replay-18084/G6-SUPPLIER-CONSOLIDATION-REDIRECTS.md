# دليل تحويل الموردين المدموجين قبل إزالة runtime

**قاعدة الدليل:** `baseer_integrated_release_rehearsal_20260914`  
**أرشيف المصدر المختوم:** `024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2`  
**الحالة:** تصدير ثابت قبل حذف جداول runtime من نسخة promotion فقط.

حُذفت 22 جهة مصدر مكررة بعد إثبات عدم وجود مراجع أعمال عليها، مع بقاء 35
خريطة consolidation تشير إلى 11 مورداً حيًا مشتركًا. الجدول يسجل مفتاح الصف
المصدري المختصر (الجزء الأخير من هوية Noorix) والكيان القانوني النهائي في
Odoo؛ يمكن ربطه بالهوية الكاملة وبصمة الصف من backup rehearsal المختوم.

| المورد القانوني النهائي في Odoo | صفوف Noorix المحوّلة إليه |
|---|---|
| غاز | `cmnvur8070066etuf74o1yajx`, `cmtllx7ta028man2wi1qwvalf` |
| مؤسسة دوحة المستهلك | `cmnvutr8h006cetufy0hrl3mi` |
| GOSI | `cmolfv7sf000j12dg6251kqn1`, `cmolfvjsc000l12dgqu6f7ha5`, `cmolfvy4o000n12dgu60mb945` |
| اقامات | `cmolhjtac000513foxpgdv0cy`, `cmpibtgr000zem8wr08aqsb46` |
| هيئة الزكاة والدخل | `cmolqmm140005pidysr78p2fl`, `cmolqrmbf000ipidyr9mx1gqd`, `cmolrha3b0014pidypq9mdlyr` |
| خضار | `cmp5jl9de02nj10yt00dta76o` |
| اوفر تايم | `cmpr3wzw20009qp9ff8tuz7kt` |
| وزارة العدل | `cmq5ampeq000911srhzv6obzg` |
| المديرية العامة للجوازات | `cms542atz000nu3uo5hzkpi65`, `cms542azi000wu3uo04q4ntlh`, `cms542b130012u3uoutcumyyk` |
| وزارة الموارد البشرية والتنمية الاجتماعية | `cms542awb000i11zs66cbfmhs`, `cms542b0m000zu3uojv112bpp`, `cms542b1l0015u3uo5ba0piig` |
| وزارة البلديات والإسكان | `cms542ayk000tu3uo62dvibwg`, `cms542b250018u3uoxzglcgqt` |

**المحصلة:** 22 صفًا محولًا إلى 11 مورداً حيًا. لا تعد هذه القائمة سبباً
لإعادة إنشاء جهات الاتصال المحذوفة؛ المورد الناجي هو المشترك لكل الشركات.
