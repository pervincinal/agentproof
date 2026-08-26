# Hədəf seçimi: Dify vs Flowise

**Status:** Qərar verildi — **Dify 1.17.0** seçildi.
**Tarix:** 2026-08-26
**Müəllif:** Target Scout
**Qərar meyarları:** `.claude/agents/scout.md` (reproduksiya > real istifadə > ucuzluq > lisenziya > sınanabilən səth)

---

## 1. Yekun qərar

| | Dify | Flowise |
|---|---|---|
| Versiya (qiymətləndirilən) | `1.17.0` (2026-08-25) | `3.1.4` (2026-07-29) |
| GitHub star | 153,586 | 55,394 |
| Son push | 2026-08-26 | 2026-08-13 |
| Lisenziya | Modified Apache 2.0 | Apache 2.0 + Commercial (qismən) |
| Compose image pin | **Bəli** (`langgenius/dify-api:1.17.0`) | Xeyr (`flowiseai/flowise:latest`) |
| RAG API-nin bütövlüyü | **Bəli** — tam CRUD, tək API-key səthində | Var, amma iki auth səthinə bölünüb |
| Retrieval-ı ayrıca ölçmə | **Bəli**, public API-key səthində | Var, amma RBAC-gated admin səthində |
| **Nəticə** | **SEÇİLDİ** | Rədd edildi |

---

## 2. Lisenziya təhlili (bloklayıcı yoxlama)

Tapşırığın əsas sualı: **public benchmark/müqayisə dərcini qadağan edən bənd varmı?**

### Yoxlanan mənbələr

| Sənəd | Nəticə |
|---|---|
| `dify/LICENSE` (1.17.0) | Benchmark bəndi **YOXDUR** |
| `Flowise/LICENSE.md` (3.1.4) | Benchmark bəndi **YOXDUR** |
| `Flowise/packages/server/src/enterprise/LICENSE.md` | Benchmark bəndi **YOXDUR** |
| dify.ai/terms (Cloud ToS) | Benchmark bəndi **YOXDUR** — həm də yalnız Dify Cloud-a aiddir, self-host-a yox |
| flowiseai.com/terms (Cloud ToS) | Benchmark bəndi **YOXDUR** |

**Nəticə: hər iki repo lisenziya baxımından təmizdir. DeWitt-tipli (benchmark dərcini qadağan edən) bənd heç birində yoxdur. Bloklayıcı problem AŞKAR EDİLMƏDİ.**

### Dify lisenziyası — dəqiq şərtlər

Dify "modified Apache 2.0" istifadə edir. Apache 2.0-ın üzərinə **yalnız iki** əlavə məhdudiyyət qoyulub:

1. **Multi-tenant xidmət qadağası** — Dify source kodu ilə multi-tenant mühit işlətmək olmaz (bir tenant = bir workspace).
2. **LOGO/copyright qorunması** — `web/` qovluğundakı frontend-də logo və copyright məlumatını silmək/dəyişmək olmaz.

Bunlardan başqa hər şey Apache 2.0-dır.

**Bizim istifadə ssenarimizə təsiri: SIFIR.**
- Biz tək-tenant lokal instansiya qaldırırıq (multi-tenant deyil) → (1) aid deyil.
- Biz frontend-i yalnız ilkin konfiqurasiya üçün açırıq, logo-ya toxunmuruq, frontend-i yenidən dərc etmirik → (2) aid deyil.
- Ölçmə nəticələrini dərc etmək heç bir bəndlə məhdudlaşdırılmır.

Əlavə qeyd: lisenziyada "The interactive design of this product is protected by appearance patent" yazılıb. Bu **dizayn patentidir** — hesabatda Dify UI-nın screenshot-larını təqdim etmək adi fair-use/nominative istifadədir, lakin **UI dizaynını kopyalayıb öz məhsulumuzda istifadə etmək olmaz**. Biz bunu etmirik.

### Flowise lisenziyası — dəqiq şərtlər

Flowise ikili lisenziyalıdır:
- `packages/server/src/enterprise/**` + açıq copyright qeydi olan fayllar (məs. `IdentityManager.ts`) → **Commercial License**
- Qalan hər şey → Apache 2.0

Commercial License-in mətnində əhəmiyyətli bir bənd var: kodu **production-da** işlətmək üçün abunə tələb olunur, **lakin** "you may copy and modify the Software for development and testing purposes, without requiring a subscription". Bizim eval işi test məqsədlidir → formal olaraq icazəlidir.

Yenə də benchmark dərcinə qadağa yoxdur. Flowise lisenziya səbəbindən rədd edilmədi.

---

## 3. Niyə Dify seçildi

### 3.1. Reproduksiya olunma (ən yüksək prioritet)

**Dify compose faylı image tag-larını dəqiq pin-ləyir:**
```
langgenius/dify-api:1.17.0
langgenius/dify-web:1.17.0
langgenius/dify-plugin-daemon:0.6.10-local
langgenius/dify-sandbox:0.2.15
postgres:15-alpine / redis:6-alpine / semitechnologies/weaviate:1.27.0
```
Altı ay sonra eyni compose faylı eyni sistemi qaldırır.

**Flowise compose faylı `flowiseai/flowise:latest` istifadə edir** — pin yoxdur. Bu düzəldilə bilər (`3.1.4` tag-ı Docker Hub-da mövcuddur, yoxladım), amma bu bizim etməli olduğumuz düzəlişdir, upstream-in verdiyi zəmanət deyil. Reproduksiya olunan benchmark üçün bu mənfi siqnaldır.

### 3.2. RAG konfiqurasiyasının API ilə idarə olunması — həlledici fərq

Eval üçün sənəd bazasını **əl ilə UI-dan yükləmək qəbuledilməzdir** — başqası təkrar edə bilməz. Dify-ın Service API-si bunu tam örtür (mənbədən təsdiqlədim, `api/controllers/service_api/dataset/`):

```
POST   /v1/datasets                                         # knowledge base yarat
POST   /v1/datasets/{id}/document/create-by-text            # sənəd əlavə et
POST   /v1/datasets/{id}/document/create-by-file
GET    /v1/datasets/{id}/documents/{batch}/indexing-status  # indeksləmə gözlə
POST   /v1/datasets/{id}/retrieve                           # RETRIEVAL-I TƏK BAŞINA ÖLÇ
GET/POST/DELETE  /v1/datasets/{id}/documents/{doc}/segments # chunk səviyyəsində nəzarət
```

**`POST /v1/datasets/{id}/retrieve` bizim üçün ən dəyərli endpoint-dir.** O, LLM-i çağırmadan yalnız retrieval nəticəsini qaytarır. Bu, hesabatda **retrieval xətası ilə generation xətasını ayırmağa** imkan verir:
- Düzgün chunk gətirildi, amma cavab yanlış → generation/faithfulness problemi
- Düzgün chunk ümumiyyətlə gətirilmədi → retrieval problemi

Bu ayırma reliability tədqiqatının bütün dəyəridir.

**Flowise-də ekvivalent VAR** — `POST /api/v1/document-store/vectorstore/query`. Fərq funksionallıqda deyil, **autentifikasiya səthindədir**: həmin endpoint `checkPermission('documentStores:view')` ilə qorunur, yəni RBAC icazəsi olan authenticated user sessiyası tələb edir (bu kod isə commercial-lisenziyalı `enterprise/` qovluğundadır). Flowise-də RAG həyat dövrü iki səthə bölünür:

| Əməliyyat | Dify | Flowise |
|---|---|---|
| KB/store yarat | API key | RBAC-gated admin |
| Sənəd yüklə | API key | API key (`/vector/upsert`) |
| İndeksləmə statusu | API key | RBAC-gated admin |
| Retrieval sorğusu | API key | RBAC-gated admin |
| Agent-ə sorğu | API key | API key (`/prediction`) |

Dify-da **bütün RAG həyat dövrü** tək, sənədli, API-key ilə autentifikasiya olunan Service API-dədir. Flowise-də setup skripti iki fərqli auth mexanizmi ilə işləməlidir. Bu, "bir skript sıfırdan hər şeyi qurur" hədəfi üçün real, amma orta səviyyəli üstünlükdür — həlledici deyil.

### 3.3. Prompt/tool konfiqurasiyasının əlçatanlığı

- **Dify DSL export**: bütün app konfiqurasiyası (system prompt, model parametrləri, agent strategiyası, tool bağlantıları, knowledge retrieval ayarları) tək bir YAML faylına export olunur. Bunu repo-ya commit edirik → hesabatda oxucu dəqiq nəyi ölçdüyümüzü görür.
- **Custom tool-lar OpenAPI spesifikasiyasından import olunur** (`api/core/tools/custom_tool/`, `api/core/tools/utils/parser.py` — mənbədən təsdiqləndi). Bizim mock sifariş servisimiz OpenAPI spec verir, Dify onu tool provider kimi qəbul edir. MCP tool dəstəyi də var (`api/core/tools/mcp_tool/`).
- Retrieval parametrləri (top_k, score_threshold, chunk ölçüsü, reranking) həm UI-da, həm DSL-də açıqdır.

### 3.4. Real istifadə

153k star özü arqument deyil, amma Dify-ın CIS və Asiya bazarında real self-host deployment bazası var, repo bu gün push alıb, 1.17.0 dünən buraxılıb. Bu, "ölü repo-nu benchmark etdilər" tənqidini bağlayır.

---

## 4. Flowise niyə rədd edildi

Flowise pis alət deyil — sadəcə **bu iş üçün** zəifdir. Səbəblər prioritet sırası ilə:

### 4.1. Öz eval/dataset funksionallığı ödənişli plan arxasındadır (əsas səbəb)

Mənbədən təsdiqlədim, `packages/server/src/routes/index.ts`:
```ts
router.use('/datasets',    IdentityManager.checkFeatureByPlan('feat:datasets'),    datasetRouter)
router.use('/evaluations', IdentityManager.checkFeatureByPlan('feat:evaluations'), evaluationsRouter)
router.use('/evaluators',  IdentityManager.checkFeatureByPlan('feat:evaluators'),  evaluatorsRouter)
```
`checkFeatureByPlan` (`IdentityManager.ts:277`) plan feature flag-ı olmayan istifadəçiyə **403 Forbidden** qaytarır. `IdentityManager.ts` isə `LICENSE.md`-də açıq şəkildə Commercial License altında sadalanan fayldır.

Bu texniki bloklayıcı deyil (biz onsuz da öz harness-imizi yazırıq), amma **optika problemidir**: "AgentProof, Flowise-in reliability-sini ölçdü — özünün eval funksiyasından istifadə edə bilmədən, çünki o, ödənişlidir" cümləsi hesabatda izahat tələb edən artıq yükdür. Dify-da belə bir qarışıqlıq yoxdur.

### 4.2. Control-plane marşrutları commercial-lisenziyalı koda bağlıdır

`/chatflows`, `/apikey`, `/export-import` marşrutlarının hamısı `checkPermission` / `checkAnyPermission` ilə sarınıb, bu funksiyalar isə `packages/server/src/enterprise/rbac/PermissionCheck.ts`-dən gəlir — yəni LICENSE.md-nin Commercial License altına saldığı qovluqdan. OSS build-də işləyir, amma "hansı kod hansı lisenziya altındadır" sualı public hesabatda izah tələb edir.

### 4.3. Compose faylında versiya pin-i yoxdur

`image: flowiseai/flowise:latest` — yuxarıda izah olundu.

### 4.4. RAG setup-ı iki auth səthinə bölünüb

3.2-də göstərildiyi kimi, Flowise-də store yaratmaq və retrieval sorğulamaq RBAC-gated admin səthindədir, sənəd yükləmək və prediction isə API-key səthində. Sıfırdan skriptlə qurulan reproduksiya üçün bu əlavə sürtünmədir. **Bu, 4.1 və 4.3-dən zəif arqumentdir** — Flowise-in retrieval-ı ayrıca ölçmək imkanı var, sadəcə əlçatanlığı daha çətindir.

### Flowise-in üstünlükləri (dürüstlük üçün)

- **Stack xeyli yüngüldür**: tək konteyner + SQLite. Dify-da 15 uzunömürlü servis + 1 init konteyneri qalxır (ölçdüm: ~10 GB image, ilk qalxma ~20 dəqiqə). Flowise dəqiqələr ərzində qalxır.
- **Agent-in özünü REST ilə yaratmaq mümkündür**: `POST /api/v1/chatflows` chatflow-u proqramatik yaradır. Dify-ın Service API-sində app yaratma endpoint-i **yoxdur** — DSL-i bir dəfə UI-dan import etmək lazımdır. (Qeyd: Flowise-in bu endpoint-i də `checkAnyPermission` ilə RBAC-gated-dir, yəni admin sessiyası tələb edir — amma endpoint heç olmasa mövcuddur.) **Bu, Flowise-in Dify üzərində real və mübahisəsiz üstünlüyüdür.**
- Marketplace asılılığı yoxdur — model provider-lər built-in node-lardır, xarici registry-dən asılı deyil.

Əgər gələcəkdə ikinci hədəf lazım olsa, Flowise məntiqli namizəddir — 4.1 və 4.2-ni hesabatda açıq qeyd etmək şərti ilə.

---

## 5. Bilinən risklər və məhdudiyyətlər (Dify)

| Risk | Təsir | Azaltma |
|---|---|---|
| **Marketplace asılılığı** — Dify 1.x-də model provider-lər plugin-dir, `marketplace.dify.ai`-dən yüklənir (`MARKETPLACE_API_URL` təsdiqləndi) | Offline reproduksiya pozulur; marketplace-dəki plugin versiyası dəyişsə nəticə dəyişə bilər | Plugin-i `.difypkg` faylı kimi yüklə, repo-ya commit et, versiyasını SETUP.md-də pin-lə |
| **Ağır stack** — 16 servis, ~8-10 GB image | İlk qalxma yavaş, RAM tələbi ~8 GB | Birdəfəlik xərcdir; `docker compose` state-i saxlayır |
| **App yaratmaq üçün UI addımı** | Tam avtomatlaşdırma pozulur | DSL YAML-ı repo-ya commit et; import bir dəfəlik və deterministik addımdır. Service API app-in *içini* tam örtür |
| **Embedding provider ayrıca lazımdır** | Anthropic embeddings API təklif etmir | Ayrıca embedding plugin-i (lokal model və ya üçüncü tərəf) konfiqurasiya et; xərci cüzidir (~$0.05) |
| `FORCE_VERIFYING_SIGNATURE=true` default-dur | İmzasız plugin-lər yüklənmir | Rəsmi marketplace plugin-ləri imzalıdır; problem gözlənilmir |

---

## 6. Xərc təxmini

Ətraflı hesablama `SETUP.md` § "Xərc təxmini" bölməsindədir. Xülasə:

| Konfiqurasiya | Bir tam qaçış | 3 seed (tövsiyə olunan) |
|---|---|---|
| SUT `claude-haiku-4-5` + judge `claude-opus-5` | ~$3.85 | ~$11.55 |
| **SUT `claude-sonnet-5` + judge `claude-opus-5`** | **~$5.32** | **~$15.96** |
| SUT `claude-opus-5` + judge `claude-opus-5` | ~$9.73 | ~$29.19 |

**Tövsiyə: SUT = `claude-sonnet-5`, judge = `claude-opus-5`.** 3 seed ilə ~$16 — scout brief-indəki $20 limitinin altında.

`claude-opus-5`-i SUT kimi götürsək 3 seed büdcəni aşır. Reliability tədqiqatı üçün **N=1 qaçış kifayət deyil** (qeyri-determinizmi ölçmək lazımdır), ona görə 3 seed ilə büdcəyə sığan konfiqurasiya seçilir.
