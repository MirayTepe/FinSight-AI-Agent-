
from __future__ import annotations

import datetime
import logging
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import yaml

logger = logging.getLogger("edgar_cleaner")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class EdgarCleanerError(Exception):
    pass


class UnitConsistencyError(EdgarCleanerError):
    pass


class FinancialSanityError(EdgarCleanerError):
    pass


@dataclass
class CleanMetricPoint:
    fy: int
    fp: str
    val: float
    unit: str
    source_tag: str
    form: str
    filed: str
    start: Optional[str] = None
    end: Optional[str] = None
    frame: Optional[str] = None
    accn: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class UnitValidator:

    ALLOWED_UNITS: Dict[str, List[str]] = {
        "USD": ["USD", "iso4217:USD"],
        "USD/shares": ["USD/shares", "usd/shares", "iso4217:USD/shares"],
        "shares": ["shares", "pure", "shares/shares"],
        "%": ["%", "pure", "ratio"],
    }

    @classmethod
    def normalize_unit(cls, unit: str) -> str:
        if not unit:
            return ""
        clean = unit.strip()
        for standard, aliases in cls.ALLOWED_UNITS.items():
            if clean in aliases or clean.lower() == standard.lower():
                return standard
        return clean

    @classmethod
    def validate_unit(
        cls,
        actual_unit: str,
        expected_unit: str,
        metric_name: str = "",
        tag_name: str = "",
        strict: bool = True,
    ) -> bool:
        norm_actual = cls.normalize_unit(actual_unit)
        norm_expected = cls.normalize_unit(expected_unit)

        if norm_actual != norm_expected:
            msg = (
                f"Birim Uyuşmazlığı [{metric_name} | {tag_name}]: "
                f"Beklenen '{expected_unit}', gelen '{actual_unit}'!"
            )
            logger.warning(msg)
            if strict:
                raise UnitConsistencyError(msg)
            return False
        return True

    @staticmethod
    def validate_sanity(
        metric_name: str,
        val: float,
        strict: bool = False,
    ) -> bool:
        if metric_name in ["revenue", "cost_of_revenue", "shares_outstanding"]:
            if val < 0:
                msg = f"Aykırı Finansal Değer: '{metric_name}' değeri negatif olamaz! (val={val})"
                logger.warning(msg)
                if strict:
                    raise FinancialSanityError(msg)
                return False
        return True


class EdgarFactsCleaner:

    FORM_PRIORITY_WEIGHT = {
        "10-K/A": 100,
        "10-K": 90,
        "20-F/A": 85,
        "20-F": 80,
        "10-Q/A": 60,
        "10-Q": 50,
    }

    def __init__(self, metrics_yaml_path: Optional[Union[str, Path]] = None):
        if metrics_yaml_path is None:
            root_dir = Path(__file__).resolve().parent.parent.parent
            metrics_yaml_path = root_dir / "metrics.yaml"

        self.yaml_path = Path(metrics_yaml_path)
        self.config = self._load_yaml(self.yaml_path)
        self.metrics_config: Dict[str, Any] = self.config.get("metrics", {})
        self.validator = UnitValidator()

    @staticmethod
    def _load_yaml(path: Path) -> Dict[str, Any]:
        if not path.is_file():
            raise FileNotFoundError(f"metrics.yaml bulunamadı: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def get_metric_config(self, metric_name: str) -> Dict[str, Any]:
        if metric_name not in self.metrics_config:
            raise KeyError(f"'{metric_name}' metriği metrics.yaml dosyasında tanımlı değil!")
        return self.metrics_config[metric_name]

    def clean_single_tag(
        self,
        tag_data: Dict[str, Any],
        expected_unit: str = "USD",
        metric_name: str = "",
        tag_name: str = "",
        annual_only: bool = True,
        min_duration_days: int = 330,                                      
        max_duration_days: int = 390,
    ) -> Dict[int, CleanMetricPoint]:
        units_dict = tag_data.get("units", {})
        target_unit_key = None

        for u in units_dict.keys():
            if self.validator.normalize_unit(u) == self.validator.normalize_unit(expected_unit):
                target_unit_key = u
                break

        if not target_unit_key:
            return {}

        items = units_dict[target_unit_key]
        cleaned_by_fy: Dict[int, CleanMetricPoint] = {}

        for item in items:
            form = item.get("form", "")
            fp = item.get("fp", "")
            fy = item.get("fy")
            val = item.get("val")
            filed = item.get("filed", "")
            start = item.get("start")
            end = item.get("end")

            if fy is None or val is None or not filed:
                continue

            try:
                fy = int(fy)
                val = float(val)
            except (ValueError, TypeError):
                continue

            if annual_only:
                if fp != "FY" or form not in ["10-K", "10-K/A", "20-F", "20-F/A"]:
                    continue

                if start and end:
                    try:
                        d_start = datetime.date.fromisoformat(start)
                        d_end = datetime.date.fromisoformat(end)
                        days = (d_end - d_start).days
                        if days < min_duration_days or days > max_duration_days:
                            continue
                    except ValueError:
                        pass

            if not self.validator.validate_sanity(metric_name, val):
                continue

            candidate = CleanMetricPoint(
                fy=fy,
                fp=fp,
                val=val,
                unit=self.validator.normalize_unit(target_unit_key),
                source_tag=tag_name,
                form=form,
                filed=filed,
                start=start,
                end=end,
                frame=item.get("frame"),
                accn=item.get("accn"),
            )

            if fy not in cleaned_by_fy:
                cleaned_by_fy[fy] = candidate
            else:
                existing = cleaned_by_fy[fy]
                cand_key = (
                    candidate.filed,
                    self.FORM_PRIORITY_WEIGHT.get(candidate.form, 0),
                )
                exist_key = (
                    existing.filed,
                    self.FORM_PRIORITY_WEIGHT.get(existing.form, 0),
                )

                if cand_key > exist_key:
                    cleaned_by_fy[fy] = candidate

        return cleaned_by_fy

    def build_metric_series(
        self,
        company_facts: Dict[str, Any],
        metric_name: str,
        annual_only: bool = True,
    ) -> List[CleanMetricPoint]:
        cfg = self.get_metric_config(metric_name)
        tags_priority: List[str] = cfg.get("tags_priority", [])
        expected_unit: str = cfg.get("expected_unit", "USD")

        gaap_facts = company_facts.get("facts", {}).get("us-gaap", {})
        if not gaap_facts:
            logger.warning("companyfacts JSON içerisinde 'facts.us-gaap' alanı bulunamadı!")
            return []

        merged_series: Dict[int, CleanMetricPoint] = {}

        for tag in tags_priority:
            if tag not in gaap_facts:
                continue

            tag_data = gaap_facts[tag]
            cleaned_tag_points = self.clean_single_tag(
                tag_data=tag_data,
                expected_unit=expected_unit,
                metric_name=metric_name,
                tag_name=tag,
                annual_only=annual_only,
            )

            for fy, point in cleaned_tag_points.items():
                if fy not in merged_series:
                    merged_series[fy] = point
                else:
                    pass

        sorted_points = [merged_series[k] for k in sorted(merged_series.keys())]
        return sorted_points

    @staticmethod
    def calculate_cagr(
        start_value: float,
        end_value: float,
        periods: int,
    ) -> float:
        if periods < 1:
            raise ValueError(f"CAGR periyot sayısı en az 1 olmalıdır! (verilen: {periods})")
        if start_value <= 0:
            raise ValueError(f"CAGR başlangıç değeri pozitif olmalıdır! (verilen: {start_value})")
        if end_value <= 0:
            raise ValueError(f"CAGR bitiş değeri pozitif olmalıdır! (verilen: {end_value})")

        cagr = ((end_value / start_value) ** (1.0 / periods) - 1.0) * 100.0
        return float(Decimal(str(cagr)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def calculate_margins_for_year(
        self,
        revenue_pt: Optional[CleanMetricPoint],
        gross_profit_pt: Optional[CleanMetricPoint] = None,
        operating_income_pt: Optional[CleanMetricPoint] = None,
        net_income_pt: Optional[CleanMetricPoint] = None,
    ) -> Dict[str, Optional[float]]:
        if not revenue_pt or revenue_pt.val <= 0:
            return {
                "gross_margin": None,
                "operating_margin": None,
                "net_margin": None,
            }

        rev = revenue_pt.val

        def _calc_ratio(num_pt: Optional[CleanMetricPoint]) -> Optional[float]:
            if not num_pt:
                return None
            ratio = (num_pt.val / rev) * 100.0
            return float(Decimal(str(ratio)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

        return {
            "gross_margin": _calc_ratio(gross_profit_pt),
            "operating_margin": _calc_ratio(operating_income_pt),
            "net_margin": _calc_ratio(net_income_pt),
        }

    def generate_comprehensive_summary(
        self,
        company_facts: Dict[str, Any],
        start_fy: Optional[int] = None,
        end_fy: Optional[int] = None,
    ) -> Dict[str, Any]:
        entity_name = company_facts.get("entityName", "Unknown")
        cik = company_facts.get("cik", "Unknown")

        rev_series = {p.fy: p for p in self.build_metric_series(company_facts, "revenue")}
        gp_series = {p.fy: p for p in self.build_metric_series(company_facts, "gross_profit")}
        op_series = {p.fy: p for p in self.build_metric_series(company_facts, "operating_income")}
        net_series = {p.fy: p for p in self.build_metric_series(company_facts, "net_income")}

        all_years = sorted(list(rev_series.keys()))
        if start_fy:
            all_years = [y for y in all_years if y >= start_fy]
        if end_fy:
            all_years = [y for y in all_years if y <= end_fy]

        yearly_results: List[Dict[str, Any]] = []
        for y in all_years:
            r = rev_series.get(y)
            gp = gp_series.get(y)
            op = op_series.get(y)
            net = net_series.get(y)

            margins = self.calculate_margins_for_year(r, gp, op, net)

            yearly_results.append({
                "fy": y,
                "revenue": r.val if r else None,
                "revenue_tag": r.source_tag if r else None,
                "gross_profit": gp.val if gp else None,
                "operating_income": op.val if op else None,
                "net_income": net.val if net else None,
                "gross_margin_pct": margins["gross_margin"],
                "operating_margin_pct": margins["operating_margin"],
                "net_margin_pct": margins["net_margin"],
                "filed": r.filed if r else None,
                "form": r.form if r else None,
            })

        cagr_val = None
        cagr_period_years = 0
        if len(yearly_results) >= 2:
            first_pt = yearly_results[0]
            last_pt = yearly_results[-1]
            if first_pt["revenue"] and last_pt["revenue"]:
                cagr_period_years = last_pt["fy"] - first_pt["fy"]
                if cagr_period_years >= 1:
                    cagr_val = self.calculate_cagr(
                        start_value=first_pt["revenue"],
                        end_value=last_pt["revenue"],
                        periods=cagr_period_years,
                    )

        return {
            "entity_name": entity_name,
            "cik": cik,
            "years_covered": all_years,
            "cagr_revenue_pct": cagr_val,
            "cagr_period": f"{all_years[0]}-{all_years[-1]} ({cagr_period_years} years)" if cagr_val else None,
            "yearly_financials": yearly_results,
        }

