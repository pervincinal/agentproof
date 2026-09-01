#!/usr/bin/env python3
"""CANONICAL.yaml sxemi — korpusdan ASILI OLMAYAN tərif, validator və JSON Schema.

PROBLEM. Sxem `verify_fixtures.py`-nin içində gizli idi: "hansı sahələr
məcburidir" sualının cavabı Python oxumaqdan keçirdi, üstəlik həmin skript
Aurora parametr adlarını (`WINDOW_PARAM`) sabit kodladığı üçün başqa korpusda
ümumiyyətlə qaçmırdı. Müştəri korpusu qurmağa başlayan an bu iki problem
birlikdə auditin ilk gününü yeyir.

HƏLL. Sxem burada — bir yerdə, üç formada, hamısı EYNİ cədvəldən doğur:

  1. `FieldSpec` cədvəlləri — sahə, tip, məcburilik və **niyə** lazımdır;
  2. `json_schema()` — JSON Schema 2020-12 (müştəri istənilən alətlə qaçırır);
  3. `validate()` — struktur + çarpaz istinad yoxlaması (JSON Schema-nın
     ifadə edə bilmədiyi qaydalar: `superseded_index` mövcud parametrə
     baxırmı, `precedence_rank` nərdivanda varmı, `doc` meta-da varmı).

`target/corpus/CANONICAL.yaml` bu sxemin BİR NÜMUNƏSİDİR, tərifi deyil.
Modul heç bir Aurora adı bilmir; `validate()` istənilən CANONICAL.yaml üzərində
qaçır. Aurora-ya xas hesablamalar `verify_fixtures.py`-də qalır.

İstifadə:
    python target/corpus/schema.py validate [YOL ...]
    python target/corpus/schema.py emit-json-schema [--out YOL]
    python target/corpus/schema.py fields                # sənəd üçün cədvəl

Sənəd: docs/CANONICAL-SCHEMA.md (bu cədvəllərdən yazılıb).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "1.0"
SCHEMA_ID = "https://agentproof.dev/schema/canonical-1.0.json"

HERE = Path(__file__).resolve().parent
DEFAULT_JSON_SCHEMA_PATH = HERE / "canonical.schema.json"


# ============================================================================
# Sahə tərifləri — sənəd, JSON Schema və validator eyni mənbədən qidalanır.
# ============================================================================
@dataclass(frozen=True)
class FieldSpec:
    """Bir sahənin tam tərifi.

    `why` sahəsi bəzək deyil: sxemi oxuyan adam sahəni buraxmaq qərarını
    məhz orada verir. `supersedes` olmadan bayat bənd tələsi qurula bilmir —
    bunu cədvəldə yazmasan, müştəri korpusu tələsiz çıxır.
    """

    name: str
    json: dict[str, Any]
    required: bool
    why: str
    example: str = ""

    @property
    def type_label(self) -> str:
        t = self.json.get("type")
        if isinstance(t, list):
            return " | ".join(t)
        if t == "array":
            return f"array<{self.json.get('items', {}).get('type', 'any')}>"
        return str(t or "any")


def _fields(*specs: FieldSpec) -> dict[str, FieldSpec]:
    return {s.name: s for s in specs}


_DATE = {"type": "string", "format": "date"}
_SCALAR = {"type": ["string", "number", "integer", "boolean", "null"]}
#: `value` skalyar OLMAYA da bilər: `[4, 7]` "4-7 iş günü" intervalını bildirir.
#: İnterval dəyəri tək rəqəmə yuvarlaqlaşdırmaq sərhəd testini məhv edərdi.
_VALUE = {"type": ["string", "number", "integer", "boolean", "null", "array"],
          "items": {"type": ["string", "number", "integer", "boolean"]}}
_STR = {"type": "string", "minLength": 1}
_STRLIST = {"type": "array", "items": {"type": "string"}, "minItems": 1}

# ------------------------------------------------------------------- meta
META_FIELDS = _fields(
    FieldSpec("company", _STR, True,
              "Hesabatın kimə aid olduğunu göstərir; birdən çox müştəri korpusu "
              "eyni maşında qarışmasın deyə."),
    FieldSpec("corpus_version", _STR, True,
              "Korpus dəyişdikdə baseline diff-in nəyə qarşı müqayisə etdiyi "
              "bilinsin — versiyasız korpusda reqressiya izah oluna bilmir.",
              '"1.0"'),
    FieldSpec("currency", {"type": "string", "pattern": "^[A-Z]{3}$"}, True,
              "Pul vahidli parametrlərin vahidi bununla tutuşdurulur; "
              "səhv valyuta astanası səssiz yanlış cavab verir.", '"AZN"'),
    FieldSpec("evaluation_reference_date", _DATE, True,
              "PİNLƏNMİŞ qiymətləndirmə saatı. Bu olmasa 'neçə gün keçib' "
              "sualının cavabı divar saatından asılı olur və eyni case sabah "
              "başqa nəticə verir — reproduksiya itir.", "2026-09-01"),
    FieldSpec("timezone", _STR, False,
              "Gün sərhədi (`23:59`) hansı zonada bağlanır. Cut-off tipli "
              "parametrlərdə sərhəd testi bundan asılıdır.", '"Asia/Baku"'),
    FieldSpec("language", _STR, False, "Sənədlərin əsas dili — çoxdilli çıxarışda vahid seçimi."),
    FieldSpec("generated", _DATE, False, "Cədvəlin yığıldığı tarix — auditin izi."),
    FieldSpec("documents", {"type": "array", "minItems": 1}, True,
              "Korpusun sənəd reyestri. Hər parametrin `doc` sahəsi bura "
              "baxır; reyestrsiz 'hansı versiya qüvvədədir' sualı cavabsızdır."),
)

DOCUMENT_FIELDS = _fields(
    FieldSpec("file", _STR, True, "Sənəd faylının adı — parametrlərin `doc` sahəsi bununla eyni yazılır.",
              "returns-and-refunds.md"),
    FieldSpec("id", _STR, True, "Sabit sənəd kodu; fayl adı dəyişsə də istinad qırılmır.", "AG-POL-RET"),
    FieldSpec("version", _STR, True,
              "Qüvvədə olan versiya. Parametrin `doc_version` sahəsi bununla "
              "tutuşdurulur — uyğunsuzluq korpusun yarısının bayat olduğunu göstərir.",
              '"4.0"'),
    FieldSpec("effective_from", _DATE, True,
              "Bu versiyanın qüvvəyə mindiyi tarix. Temporal sual ('sifariş "
              "keçən il verilib') yalnız bununla cavablandırıla bilər."),
    FieldSpec("supersedes_version", _STR, False,
              "Əvəz olunan versiya — sənəd əlavəsindəki bayat bəndlərin hansı "
              "versiyaya aid olduğunu bağlayır."),
)

# ------------------------------------------------------------- parameters
PARAMETER_FIELDS = _fields(
    FieldSpec("id", {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"}, True,
              "Sabit maşın açarı. Bütün çarpaz istinadlar (`superseded_index`, "
              "`colliding_values`, `resolved_*`) buna baxır.",
              "return_window_standard"),
    FieldSpec("name", _STR, False, "İnsan üçün ad — hesabatda göstərilir."),
    FieldSpec("value", _VALUE, True,
              "DOĞRU cavab. Qiymətləndirici agentin cavabını bununla tutuşdurur, "
              "agentin tapdığı mətnlə YOX — bütün korpusun mövcudluq səbəbi budur. "
              "İnterval dəyər siyahı kimi yazılır: `[4, 7]` = 4-7 vahid.",
              "14"),
    FieldSpec("unit", _STR, True,
              "Vahid ailəsi. Vahidsiz `14` cavabı `14 gün`, `14 %` və `14 AZN` "
              "ilə eyni sayılardı — ölçmə mənasını itirərdi.", '"days"'),
    FieldSpec("status", {"enum": ["active", "superseded"]}, True,
              "`active` HƏQİQƏTİ, `superseded` TƏLƏNİ təyin edir. Bu sahə "
              "olmadan 'sədaqətlə sitat gətirilmiş bayat cavab' düzgün sayılır.",
              "active"),
    FieldSpec("doc", _STR, True,
              "Dəyərin yaşadığı sənəd — `meta.documents[].file` ilə eyni. "
              "Retrieval lövbəri və auditorun yoxlaması bundan asılıdır."),
    FieldSpec("section", _STR, True,
              "Bənd nömrəsi (`§2.1`). Auditorun bir dəqiqədə yoxlaya bilməsi "
              "üçün; həm də `doc#clause` lövbərinə çevrilir.", '"§2.1"'),
    FieldSpec("doc_version", _STR, True,
              "Dəyərin götürüldüyü sənəd versiyası. Sənəd yenilənəndə hansı "
              "parametrlərin yenidən oxunmalı olduğu yalnız bununla bilinir.",
              '"4.0"'),
    FieldSpec("applies_when", _STR, True,
              "Dəyərin QÜVVƏDƏ OLDUĞU şərtlər — nəsr dilində, tam. Eyni rəqəm "
              "korpusda bir neçə yerdə olur; şərt yazılmasa 'hansı 14 gün' "
              "sualı cavabsız qalır və case şərt seçməsini deyil, sətir "
              "uyğunluğunu ölçür."),
    FieldSpec("effective_from", _DATE, False,
              "Bu dəyərin qüvvəyə mindiyi tarix — versiyalar arası keçiddə "
              "hansı dəyərin tətbiq olunduğunu təyin edir."),
    FieldSpec("supersedes", {"type": "object"}, False,
              "ƏVƏZ OLUNMUŞ dəyər. Bu blok olmadan bayat-bənd tələsi (korpusun "
              "ən dəyərli hissəsi) ümumiyyətlə qurula bilmir: agentin sənəd "
              "əlavəsindən tapdığı köhnə rəqəmin yanlış olduğunu maşın bilməz."),
    FieldSpec("boundary", {"type": "object"}, False,
              "Sərhəd zondu. Astana parametrində səhvlərin böyük hissəsi "
              "off-by-one-dır; N-1/N/N+1 nöqtələri olmadan bu sinif ölçülmür."),
    FieldSpec("precedence_rank", {"type": "integer", "minimum": 1}, False,
              "`precedence_ladder`-dəki pillə. Bir neçə qayda eyni anda tətbiq "
              "olunanda hansının qazandığını determinist edir."),
    FieldSpec("basis", _STR, False, "Faiz/pul dəyərinin nəyin üzərindən hesablandığı.",
              "price_actually_paid"),
    FieldSpec("timezone", _STR, False, "Yalnız vaxt tipli dəyərlər üçün zona."),
    FieldSpec("note", _STR, False, "Auditor üçün qeyd — qiymətləndirməyə təsir etmir."),
    FieldSpec("anchor", _STR, False, "Retrieval gold lövbəri (`doc.md#2.1`), varsa."),
    FieldSpec("cross_reference", _SCALAR, False, "Digər sənədə istinad."),
    FieldSpec("derived_from", {"type": ["string", "array"], "items": {"type": "string"}}, False,
              "Dəyər başqa parametrlərdən çıxırsa, mənbə `id`-ləri. Mənbə "
              "dəyişəndə hansı törəmə dəyərin yenidən hesablanacağını göstərir."),
    FieldSpec("derived_totals", {"type": ["object", "array"]}, False, "Hesablanmış cəmlər."),
    FieldSpec("version_governed_by", _STR, False,
              "Hansı tarixdəki versiyanın hökm sürdüyü (`temporal_applicability` qarşılığı)."),
)

SUPERSEDES_FIELDS = _fields(
    FieldSpec("value", _VALUE, True,
              "KÖHNƏ dəyər — sənəd əlavəsində hələ də yazılı olan rəqəm. "
              "Tələnin özü budur.", "30"),
    FieldSpec("doc_version", _STR, True,
              "Köhnə dəyərin aid olduğu versiya — tələnin hansı mətn parçasından "
              "gəldiyini auditor yoxlaya bilsin.", '"3.2"'),
    FieldSpec("effective_until", _DATE, False,
              "Köhnə dəyərin son qüvvədə olduğu gün. Temporal case-lər "
              "('2025-də verilən sifariş') yalnız bununla qurulur."),
    FieldSpec("unit", _STR, False, "Köhnə dəyərin vahidi, aktivdən fərqlidirsə."),
    FieldSpec("note", _STR, False,
              "Köhnə dəyər rəqəm deyilsə (`əvvəllər limit yox idi`) izah burada."),
)

BOUNDARY_FIELDS = _fields(
    FieldSpec("dimension", _STR, True,
              "Sərhədin ölçüldüyü kəmiyyət — hansı girişi dəyişdiyimizi "
              "adlandırır, yoxsa nöqtələr şərhsiz rəqəmdir.", "days_since_delivery"),
    FieldSpec("points", {"type": "array", "minItems": 3}, True,
              "Ən azı 3 zond nöqtəsi (N-1, N, N+1) və ən azı 2 fərqli nəticə. "
              "Hamısı eyni nəticə verirsə bu sərhəd deyil — sınmayan testdir."),
)

BOUNDARY_POINT_FIELDS = _fields(
    FieldSpec("value", _VALUE, True, "Zond nöqtəsinin girişi.", "14"),
    FieldSpec("expected", _SCALAR, True, "Həmin girişdə gözlənilən nəticə.", "eligible"),
)

# ---------------------------------------------------------------- bölmələr
LADDER_FIELDS = _fields(
    FieldSpec("rank", {"type": "integer", "minimum": 1}, True,
              "Pillə nömrəsi; 1-dən başlayır və boşluqsuz artır. İlk uyğun "
              "pillə qazanır, aşağıdakılar heç qiymətləndirilmir."),
    FieldSpec("rule", _STR, True, "Pillənin maşın adı — parametrlər buna istinad edir."),
    FieldSpec("source", _STR, True,
              "Pillənin sənəddəki mənbəyi. Mənbəsiz nərdivan auditorun deyil, "
              "korpus müəllifinin fikridir."),
)

COUNTING_RULE_FIELDS = _fields(
    FieldSpec("anchor", _STR, True,
              "Saymanın başladığı hadisə (çatdırılma/sifariş/göndəriş tarixi). "
              "Eyni 14 gün fərqli lövbərdən sayılanda fərqli cavab verir — "
              "korpusun ən çox yayılan gizli ziddiyyəti budur."),
    FieldSpec("anchor_is_day", {"type": "integer"}, False, "Lövbər günü 0-dırmı, 1-dirmi."),
    FieldSpec("inclusive_final_day", {"type": "boolean"}, False, "Son gün daxildirmi."),
    FieldSpec("calendar_or_business", {"enum": ["calendar", "business"]}, False,
              "Təqvim, yoxsa iş günü. Bu seçim 5 günlük pəncərəni 7 günə çevirir."),
    FieldSpec("closes_at", _STR, False, "Pəncərənin bağlandığı yerli vaxt."),
    FieldSpec("unit", _STR, False, "Saymanın vahidi (gün/ay)."),
    FieldSpec("note", _STR, False, "İnsan üçün izah."),
)

SUPERSEDED_INDEX_FIELDS = _fields(
    FieldSpec("parameter", _STR, True,
              "Tələnin bağlandığı aktiv parametrin `id`-si. Mövcud olmayan "
              "parametrə baxan tələ heç vaxt qiymətləndirilmir."),
    FieldSpec("stale_value", _VALUE, True, "Sənəddə hələ də yazılı olan köhnə dəyər."),
    FieldSpec("doc", _STR, True, "Köhnə dəyərin oxunduğu sənəd."),
    FieldSpec("appendix", _STR, False, "Sənəd əlavəsindəki dəqiq yer."),
    FieldSpec("not_true_from", _DATE, False, "Köhnə dəyərin yanlış olduğu ilk gün."),
    FieldSpec("unit", _STR, False, "Köhnə dəyərin vahidi."),
    FieldSpec("trap", _STR, False, "Tələ kodu — hesabatda case ilə bağlanır."),
)

COLLIDING_FIELDS = _fields(
    FieldSpec("value", _VALUE, True, "Korpusda bir neçə mənası olan rəqəm.", "30"),
    FieldSpec("unit", _STR, False, "Ortaq vahid; mənalar fərqli vahiddədirsə `mixed`."),
    FieldSpec("meanings", {"type": "array", "minItems": 2}, True,
              "Həmin rəqəmin ən azı 2 fərqli mənası. Bir mənası olan rəqəm "
              "toqquşma deyil — case sətir uyğunluğu ilə keçərdi."),
)

MEANING_FIELDS = _fields(
    FieldSpec("parameter", _STR, True, "Mənanın aid olduğu parametr `id`-si."),
    FieldSpec("status", _STR, False, "Bu mənanın aktiv, yoxsa bayat olduğu."),
    FieldSpec("correct_for", _STR, False, "Bu mənanın doğru olduğu şərt."),
    FieldSpec("unit", _STR, False, "Mənaya xas vahid (`unit: mixed` halında)."),
)

RESOLVED_CASE_FIELDS = _fields(
    FieldSpec("id", _STR, True,
              "Kombinasiyanın sabit kodu — fixture-lar buna istinad edir."),
    FieldSpec("deciding_parameter", _STR, False,
              "Kombinasiyanı həll edən parametr. İnsan mühakiməsi olmadan "
              "çox şərtli sualı qiymətləndirməyə imkan verən sahə budur."),
    FieldSpec("deciding_rank", {"type": "integer"}, False, "Qazanan nərdivan pilləsi."),
    FieldSpec("note", _STR, False, "Nə üçün məhz bu pillənin qazandığı."),
)

GAP_FIELDS = _fields(
    FieldSpec("id", _STR, True, "Boşluğun sabit kodu."),
    FieldSpec("topic", _STR, True, "Korpusda CAVABI OLMAYAN mövzu."),
    FieldSpec("question_examples", _STRLIST, True,
              "Boşluğu tetikləyən real suallar — uydurma (hallüsinasiya) "
              "yalnız konkret sual verildikdə ölçülə bilir."),
    FieldSpec("correct_behaviour", _STRLIST, True,
              "Yeganə doğru davranışlar (məlumat yoxdur / insana ötür). "
              "Yazılmasa qiymətləndirici 'boş cavab'la 'düzgün imtina'nı ayıra bilmir."),
    FieldSpec("forbidden_in_answer", _STRLIST, False,
              "Cavabda görünsə uydurma sayılan şeylər."),
    FieldSpec("why_it_retrieves_something", _STR, False,
              "Boşluğun QONŞU məzmunu olduğunu göstərir — boş retrieval verən "
              "boşluq çox asandır və heç nə ölçmür."),
    FieldSpec("nearest_distractor", _STR, False, "Agentin yanlış ümumiləşdirə biləcəyi ən yaxın fakt."),
)

SECTION_SPECS: dict[str, dict[str, FieldSpec]] = {
    "meta": META_FIELDS,
    "meta.documents[]": DOCUMENT_FIELDS,
    "parameters[]": PARAMETER_FIELDS,
    "parameters[].supersedes": SUPERSEDES_FIELDS,
    "parameters[].boundary": BOUNDARY_FIELDS,
    "parameters[].boundary.points[]": BOUNDARY_POINT_FIELDS,
    "precedence_ladder[]": LADDER_FIELDS,
    "counting_rules.<name>": COUNTING_RULE_FIELDS,
    "superseded_index[]": SUPERSEDED_INDEX_FIELDS,
    "colliding_values[]": COLLIDING_FIELDS,
    "colliding_values[].meanings[]": MEANING_FIELDS,
    "resolved_<combination>[]": RESOLVED_CASE_FIELDS,
    "gaps[]": GAP_FIELDS,
}

#: Məcburi top-level bölmələr. `resolved_*` və `temporal_applicability`,
#: `value_measurement` opsionaldır — hər domendə olmur.
REQUIRED_SECTIONS = ("meta", "parameters", "precedence_ladder", "counting_rules")
OPTIONAL_SECTIONS = ("superseded_index", "colliding_values", "gaps",
                     "temporal_applicability", "value_measurement")


# ============================================================================
# Nəticə tipləri
# ============================================================================
@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str
    severity: str = "error"  # "error" | "warn"

    def __str__(self) -> str:  # pragma: no cover - sadə format
        return f"[{self.severity}] {self.path}: {self.message}  ({self.code})"


#: `verify_fixtures.py`-nin köçürülən hissəsindəki ORİJİNAL assertion-lar.
#: Say dəyişməsin deyə ayrıca sayılır — reqressiya testi buna baxır.
LEGACY_CHECK_CODES = frozenset({
    "parameter.required_field",
    "boundary.min_points",
    "boundary.ascending",
    "boundary.distinct_expected",
    "superseded_index.parameter_known",
})


@dataclass
class SchemaReport:
    checks: int = 0
    legacy_checks: int = 0
    findings: list[Finding] = field(default_factory=list)

    def add(self, ok: bool, code: str, path: str, message: str, severity: str = "error") -> bool:
        self.checks += 1
        if code in LEGACY_CHECK_CODES:
            self.legacy_checks += 1
        if not ok:
            self.findings.append(Finding(code, path, message, severity))
        return ok

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warn"]

    @property
    def ok(self) -> bool:
        return not self.errors


# ============================================================================
# Köməkçilər
# ============================================================================
_SECTION_RE = re.compile(r"^(?:§\s*[0-9]+(?:\.[0-9]+)*|Appendix\s+[A-Za-z](?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)*)",
                         re.IGNORECASE)
_CURRENCY_UNIT_RE = re.compile(r"^[A-Z]{3}$")


def section_key(section: str) -> str | None:
    """`§2.1` → `2.1`, `Appendix A.3` → `appendix-a.3`. Tanınmasa None.

    Lövbər qatı (`anchors.py`) eyni açar formasını gözləyir; parametr
    cədvəlindən retrieval gold-una keçid buradan olur.
    """
    if not isinstance(section, str):
        return None
    s = section.strip().replace("§", "").strip()
    m = re.match(r"^Appendix\s+([A-Za-z])(?:\.(\d+))?$", s, re.IGNORECASE)
    if m:
        return f"appendix-{m.group(1).lower()}" + (f".{m.group(2)}" if m.group(2) else "")
    if re.fullmatch(r"\d+(?:\.\d+)*", s):
        return s
    return None


def _is_value(v: Any) -> bool:
    """Skalyar, yaxud interval (`[4, 7]`) — mapping/nested siyahı qəbul edilmir."""
    if isinstance(v, (str, int, float, bool)) or v is None:
        return True
    if isinstance(v, list):
        return bool(v) and all(isinstance(x, (str, int, float, bool)) for x in v)
    return False


def _is_date(v: Any) -> bool:
    if isinstance(v, _dt.date):
        return True
    try:
        _dt.date.fromisoformat(str(v))
        return True
    except (ValueError, TypeError):
        return False


def _sortable(values: list[Any]) -> bool:
    try:
        sorted(values)
        return True
    except TypeError:
        return False


def _check_fields(rep: SchemaReport, obj: Any, specs: dict[str, FieldSpec], path: str,
                  code_prefix: str, required_code: str | None = None,
                  unknown_severity: str = "warn") -> None:
    """Bir obyektin məcburi sahələri + tanınmayan sahələr."""
    if not isinstance(obj, dict):
        rep.add(False, f"{code_prefix}.not_a_mapping", path, f"mapping gözlənilirdi, {type(obj).__name__} gəldi")
        return
    for name, spec in specs.items():
        if not spec.required:
            continue
        rep.add(name in obj, required_code or f"{code_prefix}.required_field", path,
                f"məcburi sahə yoxdur: '{name}' — {spec.why.split('.')[0]}")
    unknown = sorted(set(obj) - set(specs))
    if unknown:
        rep.add(False, f"{code_prefix}.unknown_field", path,
                f"sxemdə olmayan sahə(lər): {', '.join(unknown)}", severity=unknown_severity)


# ============================================================================
# Validator — korpusdan asılı deyil
# ============================================================================
def validate(doc: Any) -> SchemaReport:
    """İstənilən CANONICAL sənədini yoxlayır. Aurora adı bilmir."""
    rep = SchemaReport()

    if not isinstance(doc, dict):
        rep.add(False, "root.not_a_mapping", "<root>", "sənədin kökü mapping olmalıdır")
        return rep

    for name in REQUIRED_SECTIONS:
        rep.add(name in doc, "root.required_section", "<root>",
                f"məcburi bölmə yoxdur: '{name}'")

    known = set(REQUIRED_SECTIONS) | set(OPTIONAL_SECTIONS)
    unknown = sorted(k for k in doc if k not in known and not str(k).startswith("resolved_"))
    if unknown:
        rep.add(False, "root.unknown_section", "<root>",
                f"tanınmayan top-level bölmə(lər): {', '.join(unknown)} "
                f"(`resolved_*` prefiksi sərbəstdir)", severity="warn")

    documents = _validate_meta(rep, doc.get("meta"))
    ranks = _validate_ladder(rep, doc.get("precedence_ladder"))
    _validate_counting_rules(rep, doc.get("counting_rules"))
    params = _validate_parameters(rep, doc.get("parameters"), documents, ranks,
                                  currency=(doc.get("meta") or {}).get("currency"))
    _validate_superseded_index(rep, doc.get("superseded_index"), params, documents)
    _validate_colliding(rep, doc.get("colliding_values"), params)
    _validate_resolved(rep, doc, params, ranks)
    _validate_gaps(rep, doc.get("gaps"))
    return rep


def _validate_meta(rep: SchemaReport, meta: Any) -> dict[str, dict]:
    if meta is None:
        return {}
    _check_fields(rep, meta, META_FIELDS, "meta", "meta")
    if not isinstance(meta, dict):
        return {}

    if "evaluation_reference_date" in meta:
        rep.add(_is_date(meta["evaluation_reference_date"]), "meta.date_format",
                "meta.evaluation_reference_date",
                f"ISO tarix gözlənilirdi: {meta['evaluation_reference_date']!r}")
    if "currency" in meta:
        rep.add(bool(_CURRENCY_UNIT_RE.fullmatch(str(meta["currency"]))), "meta.currency_format",
                "meta.currency", f"3 hərfli ISO-4217 kodu gözlənilirdi: {meta['currency']!r}")

    documents: dict[str, dict] = {}
    raw = meta.get("documents")
    if not isinstance(raw, list) or not raw:
        rep.add(False, "meta.documents_empty", "meta.documents",
                "ən azı bir sənəd olmalıdır — parametrlərin `doc` sahəsi bura baxır")
        return documents
    for i, d in enumerate(raw):
        p = f"meta.documents[{i}]"
        _check_fields(rep, d, DOCUMENT_FIELDS, p, "meta.document")
        if not isinstance(d, dict):
            continue
        if "effective_from" in d:
            rep.add(_is_date(d["effective_from"]), "meta.date_format", f"{p}.effective_from",
                    f"ISO tarix gözlənilirdi: {d['effective_from']!r}")
        f = d.get("file")
        if isinstance(f, str):
            rep.add(f not in documents, "meta.document_duplicate", p,
                    f"eyni fayl iki dəfə reyestrdədir: {f}")
            documents[f] = d
    return documents


def _validate_ladder(rep: SchemaReport, ladder: Any) -> set[int]:
    ranks: set[int] = set()
    if ladder is None:
        return ranks
    if not isinstance(ladder, list) or not ladder:
        rep.add(False, "ladder.empty", "precedence_ladder",
                "boş nərdivan hər ziddiyyəti həll olunmamış qoyur")
        return ranks
    for i, r in enumerate(ladder):
        p = f"precedence_ladder[{i}]"
        _check_fields(rep, r, LADDER_FIELDS, p, "ladder")
        if isinstance(r, dict) and isinstance(r.get("rank"), int):
            rep.add(r["rank"] not in ranks, "ladder.duplicate_rank", p,
                    f"pillə {r['rank']} təkrarlanır — 'ilk uyğun qazanır' qaydası qeyri-müəyyən olur")
            ranks.add(r["rank"])
    if ranks:
        rep.add(ranks == set(range(1, max(ranks) + 1)), "ladder.rank_gap", "precedence_ladder",
                f"pillələr 1..{max(ranks)} boşluqsuz olmalıdır, var: {sorted(ranks)}")
    return ranks


def _validate_counting_rules(rep: SchemaReport, rules: Any) -> None:
    if rules is None:
        return
    if not isinstance(rules, dict) or not rules:
        rep.add(False, "counting.empty", "counting_rules",
                "ən azı bir sayma qaydası lazımdır — 'N gün' hardan sayılır sualı cavabsız qalmasın")
        return
    for name, r in rules.items():
        _check_fields(rep, r, COUNTING_RULE_FIELDS, f"counting_rules.{name}", "counting")


def _validate_parameters(rep: SchemaReport, parameters: Any, documents: dict[str, dict],
                         ranks: set[int], currency: Any) -> dict[str, dict]:
    params: dict[str, dict] = {}
    if not isinstance(parameters, list) or not parameters:
        rep.add(False, "parameters.empty", "parameters",
                "parametr cədvəli boşdur — qiymətləndiriləcək həqiqət yoxdur")
        return params

    for p in parameters:
        pid = p.get("id") if isinstance(p, dict) else None
        path = f"parameters[{pid or '?'}]"
        if not isinstance(p, dict):
            rep.add(False, "parameter.not_a_mapping", path, "parametr mapping olmalıdır")
            continue

        # ---- ORİJİNAL 7 məcburi sahə (legacy assertion-lar) -----------------
        for k in ("value", "unit", "status", "doc", "section", "doc_version", "applies_when"):
            rep.add(k in p, "parameter.required_field", path, f"missing required field '{k}'")
        rep.add("id" in p, "parameter.missing_id", path, "parametrin `id` sahəsi yoxdur")

        if pid is not None:
            rep.add(pid not in params, "parameter.duplicate_id", path,
                    f"eyni `id` iki dəfədir: {pid} — çarpaz istinadlar qeyri-müəyyən olur")
            params[str(pid)] = p

        unknown = sorted(set(p) - set(PARAMETER_FIELDS))
        if unknown:
            rep.add(False, "parameter.unknown_field", path,
                    f"sxemdə olmayan sahə(lər): {', '.join(unknown)}", severity="warn")

        if "value" in p:
            v = p["value"]
            rep.add(_is_value(v), "parameter.value_type", path,
                    f"`value` skalyar və ya skalyar siyahısı olmalıdır, gəldi: {type(v).__name__}")

        st = p.get("status")
        if st is not None:
            rep.add(st in ("active", "superseded"), "parameter.status_enum", path,
                    f"status yalnız active|superseded ola bilər, gəldi: {st!r}")

        d = p.get("doc")
        if documents and isinstance(d, str):
            rep.add(d in documents, "parameter.doc_registered", path,
                    f"`doc` meta.documents reyestrində yoxdur: {d}")
            if d in documents and "doc_version" in p and "version" in documents[d]:
                rep.add(str(p["doc_version"]) == str(documents[d]["version"]),
                        "parameter.doc_version_matches", path,
                        f"doc_version {p['doc_version']!r} ≠ reyestrdəki cari versiya "
                        f"{documents[d]['version']!r} — parametr bayat sənəddən oxunub")

        if "section" in p:
            rep.add(section_key(str(p["section"])) is not None, "parameter.section_format", path,
                    f"bənd nömrəsi tanınmadı: {p['section']!r} (gözlənilən: `§2.1`, `2.1`, `Appendix A.3`)",
                    severity="warn")

        if "effective_from" in p:
            rep.add(_is_date(p["effective_from"]), "parameter.date_format", path,
                    f"effective_from ISO tarix olmalıdır: {p['effective_from']!r}")

        if isinstance(p.get("unit"), str) and _CURRENCY_UNIT_RE.fullmatch(p["unit"]) and currency:
            rep.add(p["unit"] == currency, "parameter.currency_matches_meta", path,
                    f"valyuta vahidi {p['unit']!r} meta.currency {currency!r} ilə uyğun deyil")

        if "precedence_rank" in p and ranks:
            rep.add(p["precedence_rank"] in ranks, "parameter.precedence_rank_known", path,
                    f"precedence_rank {p['precedence_rank']} nərdivanda yoxdur: {sorted(ranks)}")

        if "supersedes" in p:
            _validate_supersedes(rep, p, path)
        if "boundary" in p:
            _validate_boundary(rep, p["boundary"], path)

    return params


def _validate_supersedes(rep: SchemaReport, p: dict, path: str) -> None:
    s = p["supersedes"]
    sp = f"{path}.supersedes"
    _check_fields(rep, s, SUPERSEDES_FIELDS, sp, "supersedes")
    if not isinstance(s, dict):
        return
    if "effective_until" in s and s["effective_until"] is not None:
        rep.add(_is_date(s["effective_until"]), "supersedes.date_format", sp,
                f"effective_until ISO tarix olmalıdır: {s['effective_until']!r}")
    if s.get("value") is None:
        rep.add(bool(s.get("note")), "supersedes.null_value_needs_note", sp,
                "köhnə dəyər null-dursa `note` izahı məcburidir — "
                "auditor tələnin nədən ibarət olduğunu başqa cür bilə bilməz")
    else:
        rep.add(str(s["value"]) != str(p.get("value")), "supersedes.value_differs", sp,
                f"köhnə dəyər aktiv dəyərlə eynidir ({s['value']!r}) — bu tələ deyil")


def _validate_boundary(rep: SchemaReport, b: Any, path: str) -> None:
    bp = f"{path}.boundary"
    _check_fields(rep, b, BOUNDARY_FIELDS, bp, "boundary")
    if not isinstance(b, dict):
        return
    pts = b.get("points")
    if not isinstance(pts, list):
        rep.add(False, "boundary.points_not_a_list", bp, "`points` siyahı olmalıdır")
        return
    for i, pt in enumerate(pts):
        _check_fields(rep, pt, BOUNDARY_POINT_FIELDS, f"{bp}.points[{i}]", "boundary.point")

    # ---- ORİJİNAL 3 sərhəd assertion-u (legacy) --------------------------
    rep.add(len(pts) >= 3, "boundary.min_points", bp,
            f"boundary needs at least 3 points, has {len(pts)}")
    vals = [pt.get("value") for pt in pts if isinstance(pt, dict)]
    rep.add(_sortable(vals) and vals == sorted(vals), "boundary.ascending", bp,
            "boundary points not in ascending order")
    exp = {str(pt.get("expected")) for pt in pts if isinstance(pt, dict)}
    rep.add(len(exp) >= 2, "boundary.distinct_expected", bp,
            "boundary points all share one expected outcome — not a boundary")


def _validate_superseded_index(rep: SchemaReport, index: Any, params: dict[str, dict],
                               documents: dict[str, dict]) -> None:
    if index is None:
        return
    if not isinstance(index, list):
        rep.add(False, "superseded_index.not_a_list", "superseded_index", "siyahı olmalıdır")
        return
    for i, s in enumerate(index):
        p = f"superseded_index[{i}]"
        _check_fields(rep, s, SUPERSEDED_INDEX_FIELDS, p, "superseded_index")
        if not isinstance(s, dict):
            continue
        pid = s.get("parameter")
        # ---- ORİJİNAL assertion (legacy) --------------------------------
        rep.add(pid in params, "superseded_index.parameter_known", p,
                f"superseded_index references unknown parameter {pid}")
        if pid in params:
            rep.add("supersedes" in params[pid], "superseded_index.parameter_has_supersedes", p,
                    f"`{pid}` tələ indeksindədir, amma parametrdə `supersedes` bloku yoxdur — "
                    f"qiymətləndirici köhnə dəyəri tanıya bilməz")
        if documents and isinstance(s.get("doc"), str):
            rep.add(s["doc"] in documents, "superseded_index.doc_registered", p,
                    f"`doc` reyestrdə yoxdur: {s['doc']}")


def _validate_colliding(rep: SchemaReport, colliding: Any, params: dict[str, dict]) -> None:
    if colliding is None:
        return
    if not isinstance(colliding, list):
        rep.add(False, "colliding.not_a_list", "colliding_values", "siyahı olmalıdır")
        return
    for i, c in enumerate(colliding):
        p = f"colliding_values[{i}]"
        _check_fields(rep, c, COLLIDING_FIELDS, p, "colliding")
        if not isinstance(c, dict):
            continue
        meanings = c.get("meanings")
        if not isinstance(meanings, list):
            continue
        rep.add(len(meanings) >= 2, "colliding.min_meanings", p,
                f"toqquşma ən azı 2 məna tələb edir, var: {len(meanings)}")
        for j, m in enumerate(meanings):
            mp = f"{p}.meanings[{j}]"
            _check_fields(rep, m, MEANING_FIELDS, mp, "colliding.meaning")
            if isinstance(m, dict) and params:
                rep.add(m.get("parameter") in params, "colliding.parameter_known", mp,
                        f"tanınmayan parametr: {m.get('parameter')}")


def _validate_resolved(rep: SchemaReport, doc: dict, params: dict[str, dict],
                       ranks: set[int]) -> None:
    for key in sorted(k for k in doc if str(k).startswith("resolved_")):
        cases = doc[key]
        if not isinstance(cases, list):
            rep.add(False, "resolved.not_a_list", key, "siyahı olmalıdır")
            continue
        seen: set[str] = set()
        for i, c in enumerate(cases):
            p = f"{key}[{i}]"
            if not isinstance(c, dict):
                rep.add(False, "resolved.not_a_mapping", p, "mapping olmalıdır")
                continue
            rep.add("id" in c, "resolved.required_field", p, "məcburi sahə yoxdur: 'id'")
            cid = str(c.get("id"))
            rep.add(cid not in seen, "resolved.duplicate_id", p, f"təkrar id: {cid}")
            seen.add(cid)
            dp = c.get("deciding_parameter")
            if dp is not None and params:
                # Xəbərdarlıq, xəta deyil: bəzi kombinasiyanı parametr yox,
                # nərdivan qaydası həll edir (`non_returnable_category` kimi).
                rep.add(dp in params, "resolved.deciding_parameter_known", p,
                        f"`deciding_parameter` parametr cədvəlində yoxdur: {dp} — "
                        f"fixture bu case-i parametrə bağlaya bilməz", severity="warn")
            if "deciding_rank" in c and ranks:
                rep.add(c["deciding_rank"] in ranks, "resolved.deciding_rank_known", p,
                        f"deciding_rank {c['deciding_rank']} nərdivanda yoxdur")


def _validate_gaps(rep: SchemaReport, gaps: Any) -> None:
    if gaps is None:
        return
    if not isinstance(gaps, list):
        rep.add(False, "gaps.not_a_list", "gaps", "siyahı olmalıdır")
        return
    seen: set[str] = set()
    for i, g in enumerate(gaps):
        p = f"gaps[{i}]"
        _check_fields(rep, g, GAP_FIELDS, p, "gap")
        if not isinstance(g, dict):
            continue
        gid = str(g.get("id"))
        rep.add(gid not in seen, "gap.duplicate_id", p, f"təkrar id: {gid}")
        seen.add(gid)
        qs = g.get("question_examples")
        if isinstance(qs, list):
            rep.add(len(qs) >= 1, "gap.needs_question", p,
                    "boşluq ən azı bir sual nümunəsi olmadan ölçülə bilmir")


# ============================================================================
# JSON Schema — eyni cədvəllərdən yığılır
# ============================================================================
def _object_schema(specs: dict[str, FieldSpec], *, additional: bool = False,
                   overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    props = {name: dict(s.json, description=s.why) for name, s in specs.items()}
    if overrides:
        for k, v in overrides.items():
            props[k] = {**props.get(k, {}), **v}
    out: dict[str, Any] = {
        "type": "object",
        "properties": props,
        "additionalProperties": additional,
    }
    req = [n for n, s in specs.items() if s.required]
    if req:
        out["required"] = req
    return out


def json_schema() -> dict[str, Any]:
    """JSON Schema 2020-12 — müştəri onu istənilən validatorla qaçıra bilər.

    DİQQƏT: JSON Schema yalnız FORMANI ifadə edir. Çarpaz istinadlar
    (`superseded_index.parameter` mövcud parametrə baxırmı) JSON Schema-da
    ifadə oluna bilmir — onlar `validate()`-dədir. İkisi bir yerdə tam sxemdir.
    """
    boundary = _object_schema(BOUNDARY_FIELDS, overrides={
        "points": {"type": "array", "minItems": 3,
                   "items": _object_schema(BOUNDARY_POINT_FIELDS, additional=True)},
    })
    parameter = _object_schema(PARAMETER_FIELDS, overrides={
        "supersedes": _object_schema(SUPERSEDES_FIELDS, additional=True),
        "boundary": boundary,
    })
    colliding = _object_schema(COLLIDING_FIELDS, overrides={
        "meanings": {"type": "array", "minItems": 2,
                     "items": _object_schema(MEANING_FIELDS, additional=True)},
    })
    meta = _object_schema(META_FIELDS, additional=True, overrides={
        "documents": {"type": "array", "minItems": 1,
                      "items": _object_schema(DOCUMENT_FIELDS, additional=True)},
    })
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": "AgentProof CANONICAL policy-parameter table",
        "description": (
            "Audit üçün həqiqət cədvəli. Bu fayl target/corpus/schema.py-dən "
            "GENERASİYA OLUNUR — əl ilə redaktə etmə. Çarpaz istinad qaydaları "
            "JSON Schema-da ifadə oluna bilmir; onlar üçün "
            "`python target/corpus/schema.py validate <fayl>` qaçırılmalıdır."
        ),
        "x-schema-version": SCHEMA_VERSION,
        "type": "object",
        "required": list(REQUIRED_SECTIONS),
        "properties": {
            "meta": meta,
            "parameters": {"type": "array", "minItems": 1, "items": parameter},
            "precedence_ladder": {"type": "array", "minItems": 1,
                                  "items": _object_schema(LADDER_FIELDS, additional=True)},
            "counting_rules": {"type": "object", "minProperties": 1,
                               "additionalProperties": _object_schema(COUNTING_RULE_FIELDS,
                                                                      additional=True)},
            "superseded_index": {"type": "array",
                                 "items": _object_schema(SUPERSEDED_INDEX_FIELDS, additional=True)},
            "colliding_values": {"type": "array", "items": colliding},
            "gaps": {"type": "array", "items": _object_schema(GAP_FIELDS, additional=True)},
            "temporal_applicability": {"type": "object"},
            "value_measurement": {"type": "object"},
        },
        "patternProperties": {
            "^resolved_[a-z0-9_]+$": {
                "type": "array",
                "items": _object_schema(RESOLVED_CASE_FIELDS, additional=True),
            },
        },
        "additionalProperties": False,
    }


def write_json_schema(path: Path = DEFAULT_JSON_SCHEMA_PATH) -> Path:
    path.write_text(json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


# ============================================================================
# Yükləmə + CLI
# ============================================================================
def load_yaml(path: Path) -> Any:
    import yaml  # lokal import: sxem cədvəlini oxumaq üçün yaml lazım deyil
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def validate_file(path: Path) -> SchemaReport:
    return validate(load_yaml(path))


def _print_report(path: Path, rep: SchemaReport) -> None:
    print(f"{path}")
    print(f"  schema assertions : {rep.checks}  (legacy subset: {rep.legacy_checks})")
    for f in rep.warnings:
        print(f"  WARN  {f.path}: {f.message}  [{f.code}]")
    if rep.errors:
        print(f"  FAILED — {len(rep.errors)} schema violation(s):")
        for f in rep.errors:
            print(f"    - {f.path}: {f.message}  [{f.code}]")
    else:
        print("  OK — schema valid.")


def _cmd_validate(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="schema.py validate")
    ap.add_argument("paths", nargs="*", default=[str(HERE / "CANONICAL.yaml")])
    args = ap.parse_args(argv)
    paths = [Path(p) for p in (args.paths or [HERE / "CANONICAL.yaml"])]
    bad = 0
    for p in paths:
        rep = validate_file(p)
        _print_report(p, rep)
        bad += 0 if rep.ok else 1
    return 1 if bad else 0


def _cmd_emit(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="schema.py emit-json-schema")
    ap.add_argument("--out", default=str(DEFAULT_JSON_SCHEMA_PATH))
    args = ap.parse_args(argv)
    out = write_json_schema(Path(args.out))
    print(f"JSON Schema yazıldı: {out}")
    return 0


def _cmd_fields(argv: list[str]) -> int:
    for section, specs in SECTION_SPECS.items():
        print(f"\n## {section}")
        for name, s in specs.items():
            flag = "məcburi" if s.required else "opsional"
            print(f"  {name:<26} {s.type_label:<28} {flag}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmds = {"validate": _cmd_validate, "emit-json-schema": _cmd_emit, "fields": _cmd_fields}
    if not argv or argv[0] not in cmds:
        print(__doc__)
        return 2
    return cmds[argv[0]](argv[1:])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
