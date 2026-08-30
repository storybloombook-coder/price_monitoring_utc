from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import quote_plus


def search_phrase(model: str) -> str:
    """Use the TCL brand in discovery queries without duplicating it."""
    value = " ".join(str(model or "").strip().split())
    upper = value.upper()
    if upper == "TCL":
        return "TCL"
    if upper.startswith("TCL ") or upper.startswith("TCL-") or upper.startswith("TCL_"):
        value = value[4:].strip()
    elif upper.startswith("TCL") and len(value) > 3 and any(char.isdigit() for char in value[3:]):
        value = value[3:].strip()
    return f"TCL {value}".strip()


@dataclass(frozen=True)
class MonitoringSource:
    key: str
    name: str
    kind: str
    country: str
    base_url: str
    search_template: str | None = None

    def search_url(self, model: str) -> str | None:
        if not self.search_template:
            return None
        return self.search_template.format(query=quote_plus(search_phrase(model)))

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)


SOURCES = (
    MonitoringSource("kaina24", "Kaina24", "marketplace", "Lithuania", "https://www.kaina24.lt/"),
    MonitoringSource(
        "salidzini", "Salidzini", "marketplace", "Latvia", "https://www.salidzini.lv/",
        "https://www.salidzini.lv/cena?q={query}",
    ),
    MonitoringSource("hinnavaatlus", "Hinnavaatlus", "marketplace", "Estonia", "https://www.hinnavaatlus.ee/"),
    MonitoringSource("senukai", "Senukai", "shop", "Lithuania", "https://www.senukai.lt/", "https://www.senukai.lt/paieska?q={query}"),
    MonitoringSource("bite", "Bite", "shop", "Lithuania", "https://www.bite.lt/", "https://www.bite.lt/tcl"),
    MonitoringSource("varle", "Varle", "shop", "Lithuania", "https://www.varle.lt/", "https://www.varle.lt/search/?q={query}"),
    MonitoringSource("elesen", "Elesen", "shop", "Lithuania", "https://www.elesen.lt/", "https://www.elesen.lt/rezultatus/{query}"),
    MonitoringSource("elisa", "Elisa", "shop", "Estonia", "https://www.elisa.ee/", "https://www.elisa.ee/et/otsing?search={query}"),
    MonitoringSource("euronics", "Euronics", "shop", "Estonia", "https://www.euronics.ee/", "https://www.euronics.ee/otsing/{query}"),
    MonitoringSource("rde", "RDE", "shop", "Estonia", "https://www.rde.ee/", "https://www.rde.ee/search/et/word/{query}"),
    MonitoringSource("smartech", "Smartech", "shop", "Estonia", "https://www.smartech.ee/en/", "https://www.smartech.ee/en/search/?userSearchQuery={query}"),
)

SOURCE_BY_KEY = {source.key: source for source in SOURCES}
MARKETPLACES = tuple(source for source in SOURCES if source.kind == "marketplace")
SHOPS = tuple(source for source in SOURCES if source.kind == "shop")
