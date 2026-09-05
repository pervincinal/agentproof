"""Ön-audit sorğu büdcəsi — dərc olunmuş qaydanın kodda tətbiqi.

`site/rules.html` üçüncü qaydası ictimai vəd verir: bir sessiya, **≤ 30 sorğu**,
paralellik yoxdur, insan sürəti. Sənəddə yazılmış qayda məşğul bir gündə
pozulur; ona görə hədd burada, sorğunun getdiyi yeganə nöqtədə saxlanır.

İki qərar qəsdəndir:

**Təkrarlar da sayılır.** `send_with_retry` bir case üçün 3 dəfə cəhd edirsə,
hədəfin serveri 3 sorğu görür. «30 sorğu» vədini alan adam bizim daxili
təsnifatımızı deyil, öz loglarını sayır.

**Büdcə fayla yazılır.** Ön-audit iki mərhələlidir — əvvəlcə namizədləri tap,
sonra YALNIZ sınanları təkrarla — və bu iki ayrı çağırışdır. Büdcə yaddaşda
qalsaydı, hər çağırış sıfırdan başlayardı və 30-luq vəd 60-a çevrilərdi.

Büdcə bitəndə sorğu göndərilmir: `HALT` qaldırılır, qalan case-lər `skipped`
olur (yaşıl YOX — false-green mühafizəsi onsuz da bunu təmin edir) və qaçış
sıfırdan fərqli kodla bitir.
"""

from __future__ import annotations

import json
import pathlib
import threading
import time
from typing import Any

#: Büdcə bitəndə `HALT.trip()`-ə verilən səbəb adı.
BUDGET_EXHAUSTED = "preaudit_budget_exhausted"


class RequestBudget:
    """Sorğu sayğacı — silahlanmayıbsa heç nəyə qarışmır.

    Adi audit qaçışlarında (`arm()` çağırılmadan) `spend()` həmişə `True`
    qaytarır və heç bir yavaşlatma tətbiq olunmur, yəni bu modul yalnız
    ön-audit rejimində davranışa təsir edir.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    # ---------------------------------------------------------------- hal
    def reset(self) -> None:
        self._limit: int | None = None
        self._path: pathlib.Path | None = None
        self._spent = 0
        self._min_interval = 0.0
        self._last_sent = 0.0
        self._exceeded = False

    @property
    def armed(self) -> bool:
        return self._limit is not None

    @property
    def limit(self) -> int | None:
        return self._limit

    @property
    def spent(self) -> int:
        return self._spent

    @property
    def remaining(self) -> int | None:
        return None if self._limit is None else max(0, self._limit - self._spent)

    @property
    def exceeded(self) -> bool:
        return self._exceeded

    # ------------------------------------------------------------ qurulus
    def arm(
        self,
        limit: int,
        path: str | pathlib.Path | None = None,
        min_interval_s: float = 0.0,
    ) -> None:
        """Büdcəni işə sal. `path` verilibsə, əvvəlki çağırışların sayı oxunur."""
        if limit < 1:
            raise ValueError("sorğu büdcəsi ən azı 1 olmalıdır")
        self._limit = limit
        self._min_interval = max(0.0, min_interval_s)
        self._path = pathlib.Path(path) if path else None
        self._spent = 0
        if self._path is not None and self._path.exists():
            stored = json.loads(self._path.read_text())
            self._spent = int(stored.get("spent", 0))

    # ------------------------------------------------------------ istifade
    def spend(self, case_id: str = "") -> bool:
        """Bir sorğu yaz. Hədd aşılırsa `False` — sorğu GÖNDƏRİLMƏMƏLİDİR."""
        if self._limit is None:
            return True
        with self._lock:
            if self._spent >= self._limit:
                self._exceeded = True
                return False
            self._spent += 1
            self._persist(case_id)
            wait = self._min_interval - (time.monotonic() - self._last_sent)
        if wait > 0 and self._last_sent:
            time.sleep(wait)
        self._last_sent = time.monotonic()
        return True

    def _persist(self, case_id: str) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {
                    "spent": self._spent,
                    "limit": self._limit,
                    "last_case": case_id,
                    "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                },
                indent=2,
            )
            + "\n"
        )

    # ------------------------------------------------------------ hesabat
    def to_dict(self) -> dict[str, Any]:
        return {
            "armed": self.armed,
            "limit": self._limit,
            "spent": self._spent,
            "remaining": self.remaining,
            "exceeded": self._exceeded,
            "budget_file": str(self._path) if self._path else "",
            "min_interval_s": self._min_interval,
        }

    def detail(self) -> str:
        return (
            f"ön-audit sorğu büdcəsi bitdi: {self._spent}/{self._limit} "
            f"({'fayl: ' + str(self._path) if self._path else 'yaddaşda'}). "
            "Qalan case-lər GÖNDƏRİLMƏDİ."
        )


#: Qaçış boyu ortaq büdcə — `HALT` ilə eyni səbəbdən modul səviyyəsindədir.
BUDGET = RequestBudget()
